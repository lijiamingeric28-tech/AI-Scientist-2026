"""
semantic_type.py

SemanticTypeInferrer — 语义类型推断工具 (V2.2)

从 field_name + field_unit 推断物理量类型，判断数值是否在物理可行范围内。
V2.2: 规则从 quality_rules.yaml 动态加载，代码零领域强相关。
"""

from __future__ import annotations

from typing import Any

from subgraphs.quality.configs import load_yaml, get_research_domain
from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)

# 缓存: 从 config 加载的语义规则
_SEMANTIC_RULES: dict[str, dict] | None = None


def _load_semantic_rules() -> dict[str, dict]:
    """从 quality_rules.yaml 动态加载语义类型规则 (V3.0: 自动领域切换)。"""
    global _SEMANTIC_RULES
    if _SEMANTIC_RULES is not None:
        return _SEMANTIC_RULES
    try:
        from subgraphs.quality.configs import load_domain_config
        raw = load_domain_config("semantic_types", "semantic_types")
        if raw:
            _SEMANTIC_RULES = dict(raw)
            domain = get_research_domain() or "default"
            logger.info("[SemanticType] Loaded %d semantic types (domain=%s)", len(_SEMANTIC_RULES), domain)
            return _SEMANTIC_RULES
    except Exception as e:
        logger.warning("[SemanticType] Failed to load from config: %s", e)

    logger.warning("[SemanticType] No semantic rules loaded — inference disabled")
    _SEMANTIC_RULES = {}
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
        keyword_hit = any(kw.lower() in fn_lower for kw in rules["keywords"])
        if keyword_hit:
            score += 1
            matched_by = "keyword"

        # 单位匹配
        unit_hit = unit_str in rules["units"]
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
    from subgraphs.quality.tools._parse_utils import parse_numeric
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
            result["feasible_range"] = feasible
            result["physically_plausible"] = feasible[0] <= nv <= feasible[1]
            result["out_of_range"] = not result["physically_plausible"]
        else:
            result["physically_plausible"] = True  # 无规则时默认合理

    return result


def infer_all_fields(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    对所有 records 的 field_name 做语义类型推断。

    Returns:
        {field_name: semantic_info}
    """
    result: dict[str, dict[str, Any]] = {}
    seen = set()

    for rec in records:
        fn = rec.get("field_name", "")
        if fn in seen:
            continue
        seen.add(fn)
        result[fn] = infer_semantic_type(
            fn,
            rec.get("field_unit"),
            rec.get("field_value"),
        )

    return result
