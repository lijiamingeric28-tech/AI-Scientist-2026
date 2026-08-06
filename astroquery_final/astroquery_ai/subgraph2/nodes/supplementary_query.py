"""补充材料查询节点（P4）

从论文 bibcode 找到其 CDS/VizieR 关联表（J/ 表），提取其中关于
目标天体整体的物理性质数据，产出结构化 records。

流程（每篇下载成功的论文）：
1. 推导候选表号：bibcode 卷号页码 → J/{刊}/{卷}/{页}
   + Vizier.find_catalogs(bibcode) 补充
2. CDS 页面验证表号真实存在（Redirection error 判据）
3. LLM 读表元数据（列名+单位+描述）→ 表分类 + 物理性质列
4. 列名映射：LLM 把元数据列名映射到 PropertySpec（按表缓存）
5. 行级过滤：SIMBAD aliases 规范化匹配目标天体
6. 构建 records（与 database records 同构，provenance.source_kind="supplement"）

关键设计：
- LLM 只看元数据不看数据行（幻觉风险低、成本低）
- 判断结果按表号缓存（table_meta_cache.json）
- 列名映射按表号缓存（column_mapping_cache.json）
- 任何失败只跳过该表/该论文，绝不中断主流程
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests


from ..state import RetrievalState
from ..config import config
from ..utils.column_mapper import map_columns_to_properties
from ..utils.vizier_client import query_with_fallback

logger = logging.getLogger(__name__)

# 包内缓存目录（基于文件位置锚定，不依赖 CWD）
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "supplementary"
_CACHE_FILE = _CACHE_DIR / "table_meta_cache.json"

# CDS 页面验证的浏览器 UA
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36")
}

# 期刊缩写 → J/ 表前缀
_JOURNAL_PREFIX = {
    "MNRAS": "J/MNRAS",
    "A&A": "J/A+A",
    "AJ": "J/AJ",
    "ApJS": "J/ApJS",
    "ApJ": "J/ApJ",
}


def _parse_bibcode_parts(bibcode: str) -> Optional[tuple]:
    """
    从 bibcode 解析期刊/卷/页

    bibcode 是固定格式（期刊段、卷段、页段之间点号数量因期刊而异）：
    - A&A:   2018A&A...616A...1G
    - MNRAS: 2012MNRAS.427.1463Z
    - ApJ:   2014ApJ...780..128I
    - AJ:    2001AJ....121.2557D

    返回 (期刊段, 卷号, 页号) 或 None
    """
    m = re.match(r"^(\d{4})([A-Za-z&.]+?)[.]{1,4}(\d{1,4}[A-Z]?)[.]{1,4}(\d{1,4}[A-Za-z]?)$", bibcode)
    if not m:
        return None
    journal, vol, page = m.group(2), m.group(3), m.group(4)
    vol_num = re.sub(r"[A-Za-z]$", "", vol)
    page_num = re.sub(r"[A-Za-z]$", "", page)
    return journal, vol_num, page_num


def guess_j_tables(bibcode: str) -> List[str]:
    """从 bibcode 推导候选 J/ 表号"""
    parsed = _parse_bibcode_parts(bibcode)
    if not parsed:
        return []
    journal, vol, page = parsed
    for key, prefix in _JOURNAL_PREFIX.items():
        if key in journal:
            return [f"{prefix}/{vol}/{page}"]
    return []


def _catalog_real_exists(cat_id: str) -> bool:
    """
    CDS 页面验证表号真实性

    判据：页面含 "Redirection error" = 表不存在；含表标题 = 真实存在。
    astroquery get_catalogs 对不存在表不抛异常返回空，不可靠，必须用页面判据。
    """
    try:
        r = requests.get(
            f"https://cdsarc.cds.unistra.fr/viz-bin/cat/{cat_id}",
            headers=_HEADERS,
            timeout=25
        )
        return r.status_code == 200 and "Redirection error" not in r.text
    except Exception as e:
        logger.warning(f"[Supplementary] CDS 验证失败 {cat_id}: {e}")
        return False


def _load_llm_client():
    """复用 subgraph1 的 OpenAI 兼容客户端"""
    from ...subgraph1.utils.llm_utils import get_llm_client
    from ...subgraph1.config import config as s1_config
    return get_llm_client(), s1_config


def _llm_judge_table(metadata_text: str, target_entity: str) -> Dict:
    """
    LLM 读表元数据，判断表分类 + 物理性质列

    返回 {"table_class": ..., "entity_column": ..., "property_columns": [{"column": ..., "standard_name": ...}], "reasoning": ...}
    """
    client, s1_config = _load_llm_client()
    prompt = f"""你是天文数据表分类专家。根据一张 CDS 表的元数据（标题、描述、列名+单位+说明），判断这张表是否值得提取目标天体【{target_entity}】的数据。

## 表元数据
{metadata_text}

## 分类规则
- whole_entity: 表描述的是目标天体【{target_entity}】作为整体的物理性质（距离、金属丰度、总质量、速度弥散、整体光度等）
- sub_structure: 描述目标天体内部结构（成员恒星、球状星团、HII区、卫星星系如 M32/M110、局域群成员）
- other_entity: 表主体是其它天体（对比天体、校准源）
- irrelevant: 与目标天体无关

## 输出要求（严格 JSON）
{{
  "table_class": "whole_entity | sub_structure | other_entity | irrelevant",
  "entity_column": "表里标识天体名称的列名（如 Name/ID/objname），没有就填 null",
  "property_columns": [
    {{"column": "Size1", "standard_name": "size"}},
    {{"column": "Ipeak", "standard_name": "peak_intensity"}}
  ],
  "reasoning": "简要判断依据"
}}

property_columns 规则：
- 只列物理性质列，排除坐标列（RA/DE）、ID/标识列、观测标志列、误差列（如 e_DM）
- column 填表里的原始列名（如 Size1, Ipeak, z）
- standard_name 填该物理量的标准英文名（小写下划线，如 size, peak_intensity, redshift, flux, position_angle, spectral_index），不要写 column 的缩写形式"""

    try:
        response = client.chat.completions.create(
            model=s1_config.llm['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1000
        )
        text = response.choices[0].message.content
        # 提取 JSON
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"table_class": "irrelevant", "entity_column": None, "property_columns": []}
    except Exception as e:
        logger.warning(f"[Supplementary] LLM 判断失败: {e}")
        return {"table_class": "irrelevant", "entity_column": None, "property_columns": []}


def _load_table_meta(table_id: str) -> Optional[Dict]:
    """从 VizieR 拿表元数据（标题+描述+列名+单位+说明），供 LLM 判断"""
    try:
        cats = query_with_fallback(lambda v: v.get_catalogs(table_id), row_limit=1)
        if not cats:
            return None
        c = cats[0]
        meta = c.meta
        cols_desc = []
        for col in c.colnames:
            unit = meta.get(f"unit[{col}]", "") or meta.get(f"units[{col}]", "")
            desc = meta.get(f"description[{col}]", "") or meta.get(f"descr[{col}]", "")
            cols_desc.append(f"{col} [unit: {unit}] {desc}".strip())
        return {
            "title": str(meta.get("name", "") or meta.get("title", "")),
            "description": str(meta.get("description", "")),
            "columns": cols_desc,
        }
    except Exception as e:
        logger.warning(f"[Supplementary] 元数据获取失败 {table_id}: {e}")
        return None


def _normalize(s: str) -> str:
    """别名规范化：去空格、统一小写、忽略全半角"""
    return re.sub(r"\s+", "", s).lower().replace("（", "(").replace("）", ")").replace("，", ",")


def _row_matches_entity(row, entity_column, aliases: List[str]) -> bool:
    """行级过滤：该行的 entity_column 值是否命中任一别名（规范化后）"""
    if not entity_column:
        return False
    try:
        colnames = getattr(row, "colnames", None) or list(row.keys())
        if entity_column not in colnames:
            return False
        val = str(row[entity_column])
    except (KeyError, TypeError, AttributeError):
        return False
    if val in ("", "--", "nan", "None"):
        return False
    norm_val = _normalize(val)
    return any(_normalize(a) in norm_val or norm_val in _normalize(a) for a in aliases)


def supplementary_query(state: RetrievalState) -> RetrievalState:
    """
    补充材料查询节点

    对每篇下载成功的论文，尝试找 CDS J/ 表并提取目标天体数据。
    任何失败只跳过，绝不中断主流程。
    """
    papers = state.get("paper_sources", []) or []
    aliases = state.get("simbad_aliases", []) or []
    target_entity = state.get("target_entity", "")
    query_id = state.get("query_id", "")
    property_spec = state.get("property_spec", []) or []

    if not papers:
        logger.info("[Supplementary] 无论文，跳过")
        return {"supplementary_sources": [], "supplementary_records": []}

    logger.info(f"[Supplementary] 处理 {len(papers)} 篇论文 (query={query_id})")

    # 加载缓存
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = {}
    if _CACHE_FILE.exists():
        try:
            cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    supplementary_sources = []
    supplementary_records = []
    errors = []

    for paper in papers:
        bibcode = paper.get("source_id") or paper.get("bibcode")
        if not bibcode:
            continue

        # 1. 候选表号：推导 + find_catalogs 补充
        candidates = guess_j_tables(bibcode)
        try:
            fc = query_with_fallback(lambda v: v.find_catalogs(bibcode))
            for k, v in fc.items():
                n = str(getattr(v, "name", None) or k)
                if n.startswith("J/"):
                    candidates.append(n)
        except Exception as e:
            logger.debug(f"[Supplementary] find_catalogs 失败 {bibcode}: {e}")
        candidates = list(dict.fromkeys(candidates))  # 去重保序

        # 2. CDS 页面验证
        real_tables = [c for c in candidates if _catalog_real_exists(c)]
        if not real_tables:
            logger.debug(f"[Supplementary] {bibcode}: 无真实 J/ 表")
            continue

        for table_id in real_tables:
            # 3. LLM 判断（缓存优先）
            judgment = None
            if table_id in cache:
                judgment = cache[table_id]
            else:
                meta = _load_table_meta(table_id)
                if not meta:
                    continue
                meta_text = (
                    f"标题: {meta['title']}\n描述: {meta['description']}\n"
                    f"列:\n" + "\n".join(meta["columns"])
                )
                judgment = _llm_judge_table(meta_text, target_entity)
                cache[table_id] = judgment
                time.sleep(0.3)

            if not judgment or judgment.get("table_class") != "whole_entity":
                logger.debug(f"[Supplementary] {table_id}: 分类={judgment.get('table_class') if judgment else 'N/A'}，跳过")
                continue

            # 4. 取数据 + 列名映射
            try:
                cats = query_with_fallback(lambda v: v.get_catalogs(table_id), row_limit=10000)
                if not cats:
                    continue
                table = cats[0]
                entity_col = judgment.get("entity_column")
                prop_cols = judgment.get("property_columns", []) or []

                # 构造列元数据
                column_metadata = []
                for col_name in table.colnames:
                    unit = ""
                    try:
                        unit = str(table[col_name].unit) if table[col_name].unit else ""
                    except Exception:
                        pass
                    column_metadata.append({
                        "name": col_name,
                        "unit": unit,
                        "description": "",  # VizieR 元数据通常在 judgment 里，这里简化
                    })

                # 调用列名映射（按表 + PropertySpec 指纹缓存）
                # 返回 {列名: property_id字符串 | None}
                column_mapping = {}
                if property_spec:
                    column_mapping = map_columns_to_properties(
                        vizier_table=table_id,
                        columns_meta=column_metadata,
                        property_spec=property_spec,
                    )
                    # 过滤掉无匹配的列（值为 None）
                    column_mapping = {k: v for k, v in column_mapping.items() if v}
                    logger.debug(f"[Supplementary] {table_id}: 列名映射完成，{len(column_mapping)} 列有映射")

                # property_id → standard_unit 反查表
                spec_unit_map = {p["property_id"]: p.get("unit", "") for p in property_spec}

                # 行过滤：有 entity_column 按别名匹配；无则整表（单天体表）
                kept_rows = []
                discarded = 0
                if entity_col:
                    for row in table:
                        if _row_matches_entity(row, entity_col, aliases):
                            kept_rows.append(row)
                        else:
                            discarded += 1
                else:
                    kept_rows = list(table)

                # 5. 构建 records（只保留有映射的列）
                # 先构造 source_id（与下面的 source 对齐）
                source_id = f"SRC_SUPPL_{table_id.replace('/', '_')}"

                for row_index, row in enumerate(kept_rows):
                    for col_name, property_id in column_mapping.items():
                        if col_name not in table.colnames:
                            continue
                        val = row[col_name]
                        if val is None or (hasattr(val, "mask") and val.mask):
                            continue
                        field_value = str(val).strip()
                        if field_value in ("", "nan", "--"):
                            continue

                        # 标准单位（来自 PropertySpec）
                        standard_unit = spec_unit_map.get(property_id, "")

                        # 从表列取原始单位
                        raw_unit = ""
                        try:
                            raw_unit = str(table[col_name].unit) if table[col_name].unit else ""
                        except Exception:
                            pass

                        # 确定匹配到的 key_value（行级过滤的实际值）
                        key_value = target_entity
                        if entity_col and kept_rows:
                            try:
                                kv = str(kept_rows[0][entity_col])
                                if kv and kv.lower() not in ("nan", "--", ""):
                                    key_value = kv.strip()
                            except Exception:
                                pass

                        record = {
                            # 统一格式: REC_{source_id}_{bibcode_key}_{row_idx}_{property_id}
                            "record_id": (
                                f"REC_{source_id}_"
                                f"{bibcode.replace('/','_').replace(':','_')}_{row_index}_{property_id}"
                            ),
                            "source_id": source_id,
                            "entity_type": state.get("simbad_object_type") or "Unknown",
                            "entity_name": target_entity,
                            "field_name": property_id,
                            "field_value": field_value,
                            "field_unit": raw_unit,
                            "extraction_method": "database_query",       # 与下游 is_database_record 对齐
                            "provenance": {
                                "source_kind": "supplement",             # 唯一区分字段
                                "db_table": table_id,                    # ← 对齐 DB 四要素
                                "key_column": entity_col or "",
                                "key_value": key_value,
                                "raw_column": col_name,
                                "raw_unit": raw_unit,
                                "standard_unit": standard_unit,
                                "row_index": row_index,
                                "parent_bibcode": bibcode,
                                "matched_alias": "whole_table" if not entity_col else "alias_match",
                            },
                        }
                        supplementary_records.append(record)

                # 记录 source
                supplementary_sources.append({
                    "source_id": f"SRC_SUPPL_{table_id.replace('/', '_')}",
                    "source_type": "supplementary",
                    "cds_table_id": table_id,
                    "parent_bibcode": bibcode,
                    "title": paper.get("title", ""),
                })
                logger.info(
                    f"[Supplementary] {table_id}: 分类=whole_entity, "
                    f"保留 {len(kept_rows)} 行, 丢弃 {discarded} 行, "
                    f"产出 {len(column_mapping)} 列（有映射）× {len(kept_rows)} 行"
                )
            except Exception as e:
                errors.append({"node": "supplementary_query", "error": f"{table_id}: {e}",
                               "timestamp": datetime.now().isoformat()})
                logger.warning(f"[Supplementary] {table_id} 处理失败: {e}")

    # 保存缓存
    try:
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[Supplementary] 缓存保存失败: {e}")

    logger.info(f"[Supplementary] 完成: {len(supplementary_sources)} 张表, {len(supplementary_records)} 条 records")

    result = {
        "supplementary_sources": supplementary_sources,
        "supplementary_records": supplementary_records,
    }
    if errors:
        result["error_log"] = errors
    return result
