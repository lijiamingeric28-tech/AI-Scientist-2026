"""ADS 论文检索节点"""

import re
import time
import logging
from datetime import datetime

try:
    import ads
except ImportError:
    ads = None
    logging.warning("ads library not installed. Paper search will be disabled.")

from ..state import RetrievalState
from ..config import config
from ..utils import calculate_retrieval_priority, extract_paper_metadata
from events import emit_progress  # Web 事件埋点（离线 no-op）

logger = logging.getLogger(__name__)


def _llm_build_group_query(
    target_entity: str,
    group_name: str,
    props: list,
    error_msg: str = "",
) -> str:
    """
    为单个性质族构造 ADS 查询串（每族一次 LLM 调用）。

    查询词只基于族名与族内性质的名称（property_id + 中文名的常见英文表达），
    不自行扩展族外关键词；字段限定 title:/abs: 提升相关性。
    2026-08-11: error_msg 非空时把上次 ADS 拒绝的报错反馈给 LLM 精准修正
    （只重建失败族，其他族结果不受影响）。

    Returns:
        查询串（校验通过）或 ""
    """
    props_desc = "\n".join(
        f"- {p['property_id']} | {p.get('name_cn', '')}" for p in props
    )

    error_section = ""
    if error_msg:
        error_section = f"""
上次构造的查询串被 ADS 服务器拒绝（报错截断）:
{error_msg[:600]}
请针对报错修正（通常是保留符号未加引号或语法问题）。"""

    prompt = f"""你是天文数据检索专家。为 NASA ADS 构造检索查询字符串。

目标天体: {target_entity}
性质族: {group_name}
族内标准性质（property_id | 中文名）:
{props_desc}
{error_section}
要求：
1. 构造 1 个查询字符串，检索词**只基于族名和族内性质的名称**（标准名 +
   中文名的常见英文表达）生成，**不得添加族外或未提供的其他关键词**
2. 字段限定：天体名用 title:/abs: 限定，性质检索词用 abs: 限定，
   格式: (title:"天体名" OR abs:"天体名") AND (abs:词1 OR abs:词2 ...)
3. **特殊字符必须加引号**：含方括号 []、括号 ()、冒号 :、斜杠 /、问号 ?、
   星号 *、连字符 - 等 ADS 保留符号的词，即使无空格也必须加引号
   （如 abs:"[Fe/H]"）——否则会被解析为范围/函数语法报 500 错误
4. 约束：检索词 ≤ 8 个；查询串总长 ≤ 300 字符；不使用下划线 snake_case 词
5. 只输出 JSON，不要任何解释：
{{"query": "(title:\\"{target_entity}\\" OR abs:\\"{target_entity}\\") AND (abs:词1 OR abs:词2)"}}

示例（天体 M31，性质 parallax 与 distance_sun）:
{{"query": "(title:\\"M31\\" OR abs:\\"M31\\") AND (abs:parallax OR abs:distance)"}}"""

    try:
        from subgraphs.subgraph1.utils.llm_utils import get_llm_client
        from subgraphs.subgraph1.config import config as s1_config

        client = get_llm_client()
        resp = client.chat.completions.create(
            model=s1_config.llm['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
            timeout=60,
        )
        content = (resp.choices[0].message.content or "").strip()
        content = re.sub(r"^```\w*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        import json as _json
        data = _json.loads(content)
        q = (data.get("query") or "").strip() if isinstance(data, dict) else ""
        # 校验：含字段限定 + 引号成对 + 长度
        if (
            q
            and f'"{target_entity}"' in q
            and q.count('"') % 2 == 0
            and len(q) <= 300
        ):
            return q
        logger.warning(f"[ADS QueryBuilder] 组[{group_name}] 查询串不合法: {q[:80]!r}")
        return ""
    except Exception as e:
        logger.warning(f"[ADS QueryBuilder] 组[{group_name}] 查询串构造失败: {e}")
        return ""


def _llm_build_query_groups(target_entity: str, property_spec: list) -> list:
    """
    按 P1 已分好的语义族构造 ADS 查询串（2026-08-11 重写）：
      分组在 P1 性质选择阶段完成（property_spec 每项带 group），这里不做二次
      分组，直接按 group 聚合，每族分别调用一次 LLM 构造查询串。

    Returns:
        [{"group": str, "properties": [pid...], "query": str}, ...]
        property_spec 为空返回 []
    """
    if not property_spec:
        logger.info("[ADS QueryBuilder] 无 PropertySpec，跳过 LLM 查询构造")
        return []

    # 按 P1 的 group 字段聚合（保序：按首次出现顺序）
    groups: list = []
    seen_groups: dict = {}
    for p in property_spec[:15]:
        g = p.get("group") or p.get("name_cn", "") or p["property_id"]
        if g not in seen_groups:
            seen_groups[g] = len(groups)
            groups.append({"group": g, "properties": []})
        groups[seen_groups[g]]["properties"].append(p)

    # 每族分别构造查询串
    results = []
    for g in groups:
        props = g["properties"]
        q = _llm_build_group_query(target_entity, g["group"], props)
        if q:
            results.append({
                "group": g["group"],
                "properties": [p["property_id"] for p in props],
                "query": q,
            })
            logger.info(f"[ADS QueryBuilder] 组[{g['group']}] 查询串: {q[:120]}...")
        else:
            # 该族构造失败 → 规则回退（引号转义 property_id 单词）
            fallback = (
                f'(title:"{target_entity}" OR abs:"{target_entity}") '
                f"AND (abs:{_quote_ads_term(props[0]['property_id'])})"
            )
            results.append({
                "group": g["group"],
                "properties": [p["property_id"] for p in props],
                "query": fallback,
            })
            logger.warning(
                f"[ADS QueryBuilder] 组[{g['group']}] 规则回退: {fallback[:100]}"
            )

    return results


# 每个性质单独检索的返回篇数（2026-08-11: 按性质分开检索, 每性质 20 篇,
# 多性质时总量 = 性质数 × 20, 按 bibcode 去重合并）
PER_PROPERTY_ROWS = 20

# 2026-08-11: _llm_rebuild_query 已并入 _llm_build_group_query 的 error_msg 参数
# （报错精准回传该族的构造 LLM，其他族不受影响）


_ADS_SAFE_TERM = re.compile(r"[A-Za-z0-9_.,+\-]+")


def _quote_ads_term(term: str) -> str:
    """ADS/SOLR 查询 term 转义 — 含特殊字符的 term 用双引号包裹 (R1-E10)。

    ADS 查询语法中空格/括号/冒号/引号等是保留符号, 未转义会改变查询语义
    或直接报错。规则:
      - 空串 → 空引号对 (不产生裸语法)
      - 已带引号 → 原样返回
      - 仅含安全字符 (字母/数字/下划线/点/逗号/加号/连字符) → 原样返回
      - 其余 (含空格/括号等) → 双引号包裹, 内部引号转义
    """
    term = (term or "").strip()
    if not term:
        return '""'
    if term.startswith('"') and term.endswith('"'):
        return term
    if _ADS_SAFE_TERM.fullmatch(term):
        return term
    escaped = term.replace('"', '\\"')
    return f'"{escaped}"'


def build_ads_query(state: RetrievalState) -> RetrievalState:
    """
    LLM 按语义族分组构造 ADS 查询串节点（qwen3.7-flash）。

    ads_query_strings = 每组的查询串；ads_query_properties = 二维列表
    （每组对应的性质列表，论文级子集标记用）；ads_query_string 保留第一个
    （兼容日志与 search_metadata）。property_spec 为空时返回 {}，
    由 ads_search 回退到仅天体名单查询。
    """
    target_entity = state["target_entity"]
    property_spec = state.get("property_spec", []) or []

    groups = _llm_build_query_groups(target_entity, property_spec)
    if groups:
        # Web 埋点：查询串构建完成（前端卡 2 论文①，X/N + 族名，契约 D6-6）
        emit_progress(
            state.get("query_id", ""), "retrieval", "paper/build", "completed",
            data={"groups": [g["group"] for g in groups], "total": len(groups)},
        )
        return {
            "ads_query_strings": [g["query"] for g in groups],
            "ads_query_string": groups[0]["query"],
            # 二维：每查询串对应的性质列表（同组性质一起标记，
            # VLM/supplement 按组性质子集提取）
            "ads_query_properties": [g["properties"] for g in groups],
            # 每查询串对应的族名（报错重建时精准回传对应族的 LLM）
            "ads_query_groups": [g["group"] for g in groups],
        }
    return {}


def ads_search(state: RetrievalState) -> RetrievalState:
    """
    ADS 论文检索节点

    步骤：
    1. 构建 ADS 查询字符串
    2. 执行查询（带重试和错误分类）
    3. 提取论文元数据
    4. 计算 retrieval_priority
    5. 更新状态

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    if ads is None:
        logger.error("[ADS Search] ads library not installed")
        # 只返回本节点更新的字段：error_log 是 Annotated[list, add]，
        # 返回整个 state 会把已累积的条目重复累加一次。
        return {
            "ads_search_status": "failed",
            "ads_total_found": 0,
            "ads_papers_metadata": [],
            "error_log": [{
                "node": "ads_search",
                "error": "ads library not installed",
                "timestamp": datetime.now().isoformat()
            }]
        }

    target_entity = state["target_entity"]
    requested_properties = state.get("requested_properties", [])
    property_spec = state.get("property_spec", []) or []
    query_id = state["query_id"]

    logger.info(f"[ADS Search] Query ID: {query_id}")
    logger.info(f"[ADS Search] Target: {target_entity}")
    logger.info(f"[ADS Search] Properties: {requested_properties}")

    state["ads_search_status"] = "running"

    # 设置 ADS API token
    ads_token = config.api['ads']['token']
    if ads_token:
        ads.config.token = ads_token
    else:
        logger.warning("[ADS Search] ADS_API_TOKEN not configured")

    # Step 1: 查询串列表（逐性质分开 —— build_ads_query 节点 LLM 产出；
    # 缺失时回退 property_id OR 拼接 / 仅天体名）
    queries = state.get("ads_query_strings") or []
    if not queries:
        if property_spec:
            # R1-E10: property_id 含特殊字符时加引号转义, 防止 ADS 语法解析错误
            properties_str = " OR ".join(
                _quote_ads_term(p.get("property_id", "")) for p in property_spec
            )
            queries = [f'"{target_entity}" AND ({properties_str})']
        else:
            queries = [f'"{target_entity}"']

    state["ads_query_string"] = queries[0]
    logger.info(f"[ADS Search] Queries ({len(queries)}): {queries}")

    # Step 2: 逐性质查询（每性质 PER_PROPERTY_ROWS 篇）+ 按 bibcode 合并去重
    max_retries = config.api['ads']['max_retries']
    retry_backoff = config.api['ads']['retry_backoff']
    papers_metadata: Dict[str, dict] = {}  # bibcode → metadata
    prop_list: Dict[str, list] = {}        # bibcode → 命中的性质列表（论文级子集标记）
    # 查询串 ↔ 性质组对应（build_ads_query 按语义族分组输出，二维；
    # 回退时每查询对应一个性质）
    query_properties: list = state.get("ads_query_properties") or [
        [p.get("property_id", "")] for p in property_spec
    ]
    # 长度对齐：回退单查询（无性质标记）时全部查询串无对应性质组 → 空组
    if len(query_properties) != len(queries):
        query_properties = [[] for _ in queries]
    total_found = 0
    papers_config = config.retrieval['papers']
    global_rank = 0
    query_errors: list = []

    # 逐查询独立重试（2026-08-11）：此前所有查询包在同一 attempt 循环里，
    # 任一查询失败 → 整批重试 → 前序成功结果被丢弃（部分成功全丢）。
    # 现在每个查询独立重试，失败只丢该查询；3 次失败后把报错精准回传
    # 该族的构造 LLM 重建（其他族不重生成、不重检索）。
    query_groups: list = state.get("ads_query_groups") or [""] * len(queries)
    if len(query_groups) != len(queries):
        query_groups = [""] * len(queries)
    prop_by_id = {p["property_id"]: p for p in property_spec}
    per_query_hits: list = []  # Web 埋点：每查询串命中数

    for q, group_props, group_name in zip(queries, query_properties, query_groups):
        for attempt in range(1, max_retries + 1):
            try:
                search_query = ads.SearchQuery(
                    q=q,
                    fl=[
                        'bibcode', 'doi', 'title', 'author', 'year', 'pub',
                        'abstract', 'keyword', 'citation_count',
                        'score',  # R2-2: 请求真实相关性分（sort=score desc 时返回）
                        'identifier', 'esources'  # 用于 arXiv 直链下载（P0）
                    ],
                    rows=PER_PROPERTY_ROWS,
                    sort=papers_config['ads_sort']
                )

                results = list(search_query)
                total_found += len(results)
                per_query_hits.append(len(results))
                logger.info(f"[ADS Search] Query '{q[:60]}...' found {len(results)} papers")

                for idx, paper in enumerate(results, 1):
                    global_rank += 1
                    try:
                        metadata = extract_paper_metadata(paper, global_rank, q)
                    except Exception as e:
                        logger.warning(
                            f"[ADS Search] Failed to extract metadata for paper {global_rank}: {e}"
                        )
                        continue
                    bibcode = metadata.get("bibcode", "")
                    if bibcode in papers_metadata:
                        # 同一论文命中多组性质 → 合并去重
                        prop_list[bibcode] = list(
                            dict.fromkeys(prop_list[bibcode] + group_props)
                        )
                        continue
                    papers_metadata[bibcode] = metadata
                    prop_list[bibcode] = list(group_props)
                break  # 该查询成功

            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "rate limit" in error_msg.lower():
                    # 限流：跳过该查询（不整体失败）
                    logger.error(f"[ADS Search] 限流，跳过查询 '{q[:60]}...'")
                    query_errors.append({
                        "node": "ads_search",
                        "error": f"rate limit: {q[:80]}",
                        "timestamp": datetime.now().isoformat(),
                    })
                    break

                if attempt < max_retries:
                    wait_time = attempt * retry_backoff
                    logger.warning(
                        f"[ADS Search] 查询失败 (attempt {attempt}/{max_retries}): {error_msg[:150]}"
                    )
                    logger.info(f"[ADS Search] Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                else:
                    # 3 次失败：把 ADS 报错精准回传该族的构造 LLM 重建
                    # （修正转义等语法问题；其他族不重生成、不重检索）
                    rebuild_props = [
                        prop_by_id[pid] for pid in group_props if pid in prop_by_id
                    ]
                    rebuilt = ""
                    if rebuild_props:
                        rebuilt = _llm_build_group_query(
                            target_entity, group_name, rebuild_props, error_msg=error_msg
                        )
                    if rebuilt:
                        logger.info(
                            f"[ADS Search] 组[{group_name}] LLM 重建查询: {rebuilt[:120]}... "
                            f"(原: {q[:60]}...)"
                        )
                        q = rebuilt
                        attempt = 0  # 用新串重新开始重试
                        continue
                    logger.error(
                        f"[ADS Search] 组[{group_name}] 查询失败（LLM 重建也失败）: {error_msg[:200]}"
                    )
                    query_errors.append({
                        "node": "ads_search",
                        "error": f"query failed after {max_retries} attempts: {error_msg[:200]}",
                        "timestamp": datetime.now().isoformat(),
                    })
                    break

    if not papers_metadata:
        logger.warning("[ADS Search] 所有查询均无论文")
        if query_errors:
            # 全部查询失败：若均为限流 → skipped（历史语义），否则 failed
            all_rate_limited = all(
                "rate limit" in e.get("error", "") for e in query_errors
            )
            # M-15: 早退路径补发 paper/search 终止事件——前端子步骤②不再永久 waiting
            emit_progress(
                query_id, "retrieval", "paper/search",
                "skipped" if all_rate_limited else "failed",
                data={"per_query": [], "deduped": 0},
            )
            return {
                "ads_search_status": "skipped" if all_rate_limited else "failed",
                "ads_total_found": 0,
                "ads_papers_metadata": [],
                "error_log": query_errors,
            }
        # M-15: 零命中正常完成——补发 completed 终止事件（前端子步骤②不再永久 waiting）
        emit_progress(
            query_id, "retrieval", "paper/search", "completed",
            data={"per_query": [], "deduped": 0},
        )
        return {
            "ads_search_status": "completed",
            "ads_total_found": 0,
            "ads_papers_metadata": []
        }

    # Step 3: 按命中性质数降序 + score 降序排序 —— 覆盖性质多的论文优先
    # （其 PDF 下载/提取优先级更高）；论文级性质子集写入 metadata
    papers_metadata_list = sorted(
        papers_metadata.values(),
        key=lambda m: (
            -len(prop_list.get(m.get("bibcode", ""), [])),
            -(m.get("score") or 0),
        ),
    )
    for m in papers_metadata_list:
        # 论文级性质子集（VLM/supplement 单一性质提取的依据；
        # 空列表 = 未按性质标记 → 提取端全量兜底）
        m["property_ids"] = prop_list.get(m.get("bibcode", ""), [])

    # R2-2: 合并集批内 score 归一化 —— 跨查询 score 量纲不同不可直接比较，
    # 按合并集内最大值归一后重算 retrieval_priority。
    real_scores = [
        m["score"] for m in papers_metadata_list
        if m.get("score_source") == "ads" and m.get("score", 0) > 0
    ]
    if real_scores:
        batch_max_score = max(real_scores)
        for m in papers_metadata_list:
            if m.get("score_source") == "ads" and m.get("score", 0) > 0:
                m["retrieval_priority"] = calculate_retrieval_priority(
                    score=m["score"],
                    citation_count=m["citation_count"],
                    year=int(m["year"]) if m.get("year") else 2020,
                    max_score=batch_max_score,
                    max_citations=1000,
                )
        logger.info(
            f"[ADS Search] 合并集 score 批内归一化: "
            f"batch_max={batch_max_score:.4f}, 样本={len(real_scores)}"
        )
    else:
        logger.warning(
            "[ADS Search] 无真实 score（fl 未返回），retrieval_priority "
            "回退被引量权重（历史行为）"
        )

    # Web 埋点：检索与去重完成（前端卡 2 论文②：每串命中数 + 合并去重数）
    emit_progress(
        state.get("query_id", ""), "retrieval", "paper/search", "completed",
        data={
            "per_query": per_query_hits,
            "groups": query_groups,
            "deduped": len(papers_metadata_list),
        },
    )

    logger.info(
        f"[ADS Search] Successfully extracted {len(papers_metadata_list)} papers "
        f"(去重自 {total_found} 次命中)"
    )

    # Step 4: 更新状态
    state["ads_search_status"] = "completed"
    state["ads_papers_metadata"] = papers_metadata_list
    state["ads_total_found"] = len(papers_metadata_list)

    logger.info("[ADS Search] Completed!")
    logger.info(f"[ADS Search]   Papers found (deduped): {len(papers_metadata_list)}")

    # 只返回更新的字段
    return {
        "ads_search_status": state.get("ads_search_status"),
        "ads_query_string": state.get("ads_query_string"),
        "ads_query_strings": state.get("ads_query_strings", []),
        "ads_total_found": state.get("ads_total_found", 0),
        "ads_papers_metadata": state.get("ads_papers_metadata", [])
    }

