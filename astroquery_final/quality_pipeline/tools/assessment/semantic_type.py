"""
semantic_type.py

SemanticTypeInferrer — 语义类型推断工具 (V2.2)

从 field_name + field_unit 推断物理量类型，判断数值是否在物理可行范围内。
V2.2: 规则从 quality_rules.yaml 动态加载，代码零领域强相关。
"""

from __future__ import annotations

from typing import Any

from ...configs import load_yaml, get_research_domain
from ...utils.logger import get_logger

logger = get_logger(__name__)

# 缓存: 从 config 加载的语义规则 (V3.1 fix: 按领域 key 缓存, 防止跨领域污染)
_SEMANTIC_RULES: dict[str, dict] | None = None
_SEMANTIC_RULES_DOMAIN: str = ""


def _load_semantic_rules() -> dict[str, dict]:
    """从 quality_rules.yaml 动态加载语义类型规则 (V3.1: 领域感知缓存)。"""
    global _SEMANTIC_RULES, _SEMANTIC_RULES_DOMAIN
    from ...configs import get_research_domain
    current_domain = get_research_domain() or "default"

    # 缓存仅在相同领域下复用; 领域切换时重新加载, 防止污染
    if _SEMANTIC_RULES is not None and _SEMANTIC_RULES_DOMAIN == current_domain:
        return _SEMANTIC_RULES
    try:
        from ...configs import load_domain_config
        raw = load_domain_config("semantic_types", "semantic_types")
        if raw:
            _SEMANTIC_RULES = dict(raw)
            _SEMANTIC_RULES_DOMAIN = current_domain
            logger.info("[SemanticType] Loaded %d semantic types (domain=%s)", len(_SEMANTIC_RULES), current_domain)
            return _SEMANTIC_RULES
    except Exception as e:
        logger.warning("[SemanticType] Failed to load from config: %s", e)

    logger.warning("[SemanticType] No semantic rules loaded — inference disabled")
    _SEMANTIC_RULES = {}
    _SEMANTIC_RULES_DOMAIN = current_domain
    return _SEMANTIC_RULES


def infer_semantic_type(
    field_name: str,
    field_unit: str | None = None,
    field_value: float | None = None,
) -> dict[str, Any]:
    """
    从 field_name + field_unit 推断语义类型，并验证物理可行性。

    Args:
        field_name: 字段名
        field_unit: 字段单位
        field_value: 字段值 (用于可行性校验)

    Returns:
        {
            "semantic_type": str | None,
            "confidence": float,
            "physically_plausible": bool | None,
            "feasible_range": [min, max] | None,
            "out_of_range": bool,
            "unit_recognized": bool,
            "matched_by": "keyword" | "unit" | "both" | "none",
        }
    """
    result: dict[str, Any] = {
        "semantic_type": None,
        "confidence": 0.0,
        "physically_plausible": None,
        "feasible_range": None,
        "out_of_range": False,
        "unit_recognized": False,
        "matched_by": "none",
    }

    fn_lower = field_name.lower()
    unit_str = (field_unit or "").strip()

    # V2.2: 从 config 动态加载规则
    rules_db = _load_semantic_rules()
    if not rules_db:
        return result

    # 按规则匹配
    best_match = None
    best_score = 0

    for type_name, rules in rules_db.items():
        score = 0
        matched_by = "none"

        # 关键词匹配
        # V4 fix: 单字母关键词 (如 luminosity 的 'L', stellar_mass 的 'M') 改整串相等 —
        # 此前子串匹配使 'database_catalog_properties' 被 'L'/'M'/'d'/'t' 误命中
        # (迭代序第一个 score=1 的类型胜出 → 误判为 luminosity)
        def _kw_hit(kw: str) -> bool:
            kw = kw.lower()
            return fn_lower == kw if len(kw) == 1 else kw in fn_lower
        keyword_hit = any(_kw_hit(kw) for kw in rules["keywords"])
        if keyword_hit:
            score += 1
            matched_by = "keyword"

        # 单位匹配
        # V4 fix: 空串单位不参与匹配 — redshift 规则 units 含 "" (无量纲),
        # 使所有无单位字段 (如 database_catalog_properties) 都被 unit 匹配为
        # redshift (score=1, dict 序在前优先)。空单位 = 无信号, 不构成证据。
        unit_hit = unit_str != "" and unit_str in rules["units"]
        if unit_hit:
            score += 1
            matched_by = "both" if keyword_hit else "unit"

        if score > best_score:
            best_score = score
            best_match = type_name
            result["matched_by"] = matched_by

    if best_match is None:
        return result

    rules = rules_db[best_match]
    result["semantic_type"] = best_match
    result["confidence"] = 0.5 + best_score * 0.25  # 0.75 for keyword+unit, 0.5 for one
    result["unit_recognized"] = unit_str in rules["units"]

    # 物理可行性校验 (V1.1: property_value 是 string, 需要 parse)
    from ...tools._parse_utils import parse_numeric
    nv = parse_numeric(field_value)
    if nv is not None:
        feasible_ranges = rules.get("feasible_ranges", {})
        feasible = feasible_ranges.get(unit_str)
        if feasible is None and unit_str:
            # try cleaned unit
            clean_unit = unit_str.replace("°", "").replace("℃", "C").strip()
            if clean_unit != unit_str:
                feasible = feasible_ranges.get(clean_unit)

        if feasible and len(feasible) == 2:
            # V4 fix: 强转 float — PyYAML 6.x 将 `1e10`/`1.0e10` 解析为字符串,
            # 此前 sci-notation 边界 (如 distance kpc 的 1e7) 触发 TypeError,
            # 被上层 except 吞掉后语义校验形同虚设
            try:
                lo, hi = float(feasible[0]), float(feasible[1])
            except (TypeError, ValueError):
                lo = hi = None
            if lo is not None:
                result["feasible_range"] = [lo, hi]
                result["physically_plausible"] = lo <= nv <= hi
                result["out_of_range"] = not result["physically_plausible"]
            else:
                result["physically_plausible"] = True
        else:
            result["physically_plausible"] = True  # 无规则时默认合理

    return result


def infer_all_fields(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    对所有 records 的 (entity_type, entity_name, field_name) 做语义类型推断。

    V2: 不同实体共享同一 field_name 时各自独立推断。
    Returns:
        {key: semantic_info}   key = "{entity_type}:{entity_name}/{field_name}" 或纯 field_name
    """
    result: dict[str, dict[str, Any]] = {}
    seen = set()

    for rec in records:
        fn = rec.get("field_name", "")
        et = rec.get("entity_type", "") or ""
        en = rec.get("entity_name", "") or ""

        # V2: entity-aware dedup key
        if et or en:
            ekey = f"{et}:{en}/{fn}" if (et and en) else (f"{en}/{fn}" if en else fn)
            dedup_key = (et, en, fn)
        else:
            ekey = fn
            dedup_key = fn

        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        result[ekey] = infer_semantic_type(
            fn,
            rec.get("field_unit"),
            rec.get("field_value"),
        )

    return result
