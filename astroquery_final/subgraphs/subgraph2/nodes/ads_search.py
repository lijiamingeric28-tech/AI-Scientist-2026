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

logger = logging.getLogger(__name__)


def _llm_build_query_string(target_entity: str, property_spec: list) -> str:
    """
    用 LLM（qwen3.7-flash）构造 ADS 查询字符串。

    property_id 是 snake_case（如 gas_phase_metallicity），ADS 全文检索
    匹配效果一般；LLM 负责扩展成 ADS 友好的同义词/自然表达。
    失败时返回空串，由调用方回退到原逻辑。
    """
    # property_spec 为空时不做 LLM 扩展（避免生成"所有性质"的超长查询），
    # 由 ads_search 回退到只按天体名检索。
    if not property_spec:
        logger.info("[ADS QueryBuilder] 无 PropertySpec，跳过 LLM 查询构造")
        return ""

    try:
        from subgraphs.subgraph1.utils.llm_utils import get_llm_client
        from subgraphs.subgraph1.config import config as s1_config

        props = [p["property_id"] for p in property_spec][:10]  # 最多 10 个性质
        props_desc = ", ".join(props)

        prompt = f"""你是天文学文献检索专家。为 NASA ADS 查询构造检索字符串。

目标天体: {target_entity}
需要检索的物理性质: {props_desc}

要求：
1. 返回一个 ADS 查询字符串，格式: "{target_entity}" AND (term1 OR term2 OR ...)
2. 每个性质最多 2 个 term（标准名 + 1 个常见同义词），总 term 数不超过 15 个
3. 使用英文天文学常见词，不用下划线 snake_case 词
4. 所有带空格的短语必须用引号包裹且引号成对闭合
5. 只输出查询字符串本身，不要任何解释

示例输入: M31, [distance, gas_phase_metallicity]
示例输出: "M31" AND (distance OR "distance modulus" OR metallicity OR "metal abundance")"""

        client = get_llm_client()
        resp = client.chat.completions.create(
            model=s1_config.llm['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
        )
        q = (resp.choices[0].message.content or "").strip()
        # 校验：以 "天体名" 开头 + 引号成对 + 长度限制（ADS 拒绝超长查询）
        if (
            q and f'"{target_entity}"' in q
            and q.count('"') % 2 == 0
            and len(q) < 500
        ):
            logger.info(f"[ADS QueryBuilder] LLM 构造查询: {q[:150]}...")
            return q
        logger.warning(f"[ADS QueryBuilder] LLM 输出不合法，回退: {q[:80]}")
        return ""

    except Exception as e:
        logger.warning(f"[ADS QueryBuilder] LLM 失败，回退: {e}")
        return ""


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
    LLM 构造 ADS 查询字符串节点（qwen3.7-flash）。

    失败时回退到原 property_id OR 拼接逻辑（由 ads_search 完成）。
    """
    target_entity = state["target_entity"]
    property_spec = state.get("property_spec", []) or []

    q = _llm_build_query_string(target_entity, property_spec)
    if q:
        return {"ads_query_string": q}
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

    # Step 1: 构建查询字符串
    # 优先复用 build_ads_query 节点的 LLM 查询串；失败/缺失时回退到
    # property_id OR 拼接（RAG 标准性质名，ADS 可匹配，不使用用户原文）。
    query_string = state.get("ads_query_string", "")
    if not query_string:
        if property_spec:
            # R1-E10: property_id 含特殊字符时加引号转义, 防止 ADS 语法解析错误
            properties_str = " OR ".join(
                _quote_ads_term(p.get("property_id", "")) for p in property_spec
            )
            query_string = f'"{target_entity}" AND ({properties_str})'
        else:
            query_string = f'"{target_entity}"'

    state["ads_query_string"] = query_string
    logger.info(f"[ADS Search] Query: {query_string}")

    # Step 2: 执行查询（带重试）
    max_retries = config.api['ads']['max_retries']
    retry_backoff = config.api['ads']['retry_backoff']
    papers_metadata = []

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[ADS Search] Attempt {attempt}/{max_retries}")

            # 查询前 50 篇论文
            papers_config = config.retrieval['papers']
            search_query = ads.SearchQuery(
                q=query_string,
                fl=[
                    'bibcode', 'doi', 'title', 'author', 'year', 'pub',
                    'abstract', 'keyword', 'citation_count',
                    'score',  # R2-2: 请求真实相关性分（sort=score desc 时返回）
                    'identifier', 'esources'  # 用于 arXiv 直链下载（P0）
                ],
                rows=papers_config['ads_max_papers'],
                sort=papers_config['ads_sort']
            )

            results = list(search_query)

            if not results:
                logger.warning(f"[ADS Search] No papers found for query: {query_string}")
                return {
                    "ads_search_status": "completed",
                    "ads_total_found": 0,
                    "ads_papers_metadata": []
                }

            logger.info(f"[ADS Search] Found {len(results)} papers")
            state["ads_total_found"] = len(results)

            # Step 3: 提取元数据
            for idx, paper in enumerate(results, 1):
                try:
                    metadata = extract_paper_metadata(paper, idx, query_string)
                    papers_metadata.append(metadata)
                except Exception as e:
                    logger.warning(f"[ADS Search] Failed to extract metadata for paper {idx}: {e}")

            # R2-2: 真实 ADS score 的批内相对归一化 —— score 量纲不定，
            # 按批内最大值归一后重算 retrieval_priority，避免 max_score=1000
            # 把真实相关性分压成 ~0（被引量实际权重 0.8 的根因）。
            real_scores = [
                m["score"] for m in papers_metadata
                if m.get("score_source") == "ads" and m.get("score", 0) > 0
            ]
            if real_scores:
                batch_max_score = max(real_scores)
                for m in papers_metadata:
                    if m.get("score_source") == "ads" and m.get("score", 0) > 0:
                        m["retrieval_priority"] = calculate_retrieval_priority(
                            score=m["score"],
                            citation_count=m["citation_count"],
                            year=int(m["year"]) if m.get("year") else 2020,
                            max_score=batch_max_score,
                            max_citations=1000,
                        )
                logger.info(
                    f"[ADS Search] 真实 score 批内归一化: "
                    f"batch_max={batch_max_score:.4f}, 样本={len(real_scores)}"
                )
            else:
                logger.warning(
                    "[ADS Search] 无真实 score（fl 未返回），retrieval_priority "
                    "回退被引量权重（历史行为）"
                )

            logger.info(f"[ADS Search] Successfully extracted {len(papers_metadata)} papers")
            break  # 查询成功，跳出重试循环

        except Exception as e:
            error_msg = str(e)

            # 判断错误类型
            if "429" in error_msg or "rate limit" in error_msg.lower():
                # 限额用完，直接跳过
                logger.error("[ADS Search] Rate limit reached, skipping paper search")
                return {
                    "ads_search_status": "skipped",
                    "ads_total_found": 0,
                    "ads_papers_metadata": [],
                    "error_log": [{
                        "node": "ads_search",
                        "error": "ADS API rate limit reached",
                        "timestamp": datetime.now().isoformat()
                    }]
                }

            elif attempt < max_retries:
                # 其他错误（网络问题等），等待后重试
                wait_time = attempt * retry_backoff
                logger.warning(f"[ADS Search] Error: {error_msg}")
                logger.info(f"[ADS Search] Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                # 3次重试全部失败
                logger.error(f"[ADS Search] All {max_retries} attempts failed: {error_msg}")
                return {
                    "ads_search_status": "failed",
                    "ads_total_found": 0,
                    "ads_papers_metadata": [],
                    "error_log": [{
                        "node": "ads_search",
                        "error": f"ADS query failed after {max_retries} attempts: {error_msg}",
                        "timestamp": datetime.now().isoformat()
                    }]
                }

    # Step 4: 更新状态
    state["ads_search_status"] = "completed"
    state["ads_papers_metadata"] = papers_metadata

    logger.info("[ADS Search] Completed!")
    logger.info(f"[ADS Search]   Papers found: {len(papers_metadata)}")

    # 只返回更新的字段
    return {
        "ads_search_status": state.get("ads_search_status"),
        "ads_query_string": state.get("ads_query_string"),
        "ads_total_found": state.get("ads_total_found", 0),
        "ads_papers_metadata": state.get("ads_papers_metadata", [])
    }
