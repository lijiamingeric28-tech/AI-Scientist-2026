"""
rule_classifier.py — Tool 3: RuleBasedClassifier

确定性冲突分类：Type / Subtype / Severity。
LLM 仅对 subtype=="undetermined" 的分类进行补充。
"""
from __future__ import annotations
from typing import Any
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

# 条件类语义类型 (不同实验/观测条件下可有不同值)
# V2.2: 从语义类型推断，不再硬编码字段名
_CONDITION_SEMANTIC_TYPES = {
    "temperature", "strain_rate", "pressure", "humidity",
    "exposure_time", "wavelength", "resolution",
    "magnetic_field", "electric_field", "ph",
}


def _is_condition_field(field_name: str, semantic_types: dict[str, Any] | None) -> bool:
    """从 semantic_type 推断是否为条件字段 (V2.2: 泛化)。"""
    fn_lower = field_name.lower()
    # 通过字段名关键词
    generic_keywords = ("temperature", "temp", "strain_rate", "strain rate",
                        "pressure", "humidity", "exposure", "wavelength",
                        "resolution", "magnetic", "electric", "ph")
    if any(k in fn_lower for k in generic_keywords):
        return True
    # 通过语义类型
    if semantic_types:
        st_info = semantic_types.get(field_name, {})
        st = st_info.get("semantic_type", "") if isinstance(st_info, dict) else str(st_info)
        if st in _CONDITION_SEMANTIC_TYPES:
            return True
    return False


def classify_conflict_rule(
    conflict: dict[str, Any],
    semantic_types: dict[str, Any] | None = None,
    field_criticality: str = "important",
) -> dict[str, Any]:
    """
    确定性规则分类 (V2.2: 条件字段判断泛化)。

    Args:
        conflict: 含上下文信息的单个冲突
        semantic_types: profile.semantic_types
        field_criticality: 字段关键性 (critical/important/auxiliary)

    Returns:
        {conflict_id, type, subtype, severity, rule_confidence}
    """
    ctype = conflict.get("type", "unknown")
    ctx = conflict.get("context", {})
    cohens_d = conflict.get("cohens_d", 0)
    same_material = ctx.get("same_material", True)
    same_condition = ctx.get("same_condition", True)
    temporal_gap = ctx.get("temporal_gap_years")
    fn = conflict.get("field_name", "")
    is_condition_field = _is_condition_field(fn, semantic_types)

    # ── Step 1: Type 分类 ──
    if ctype in ("cross_source_value_conflict", "statistical_conflict"):
        resolved_type = "cross_source_value_conflict"
    elif ctype in ("type_conflict", "type_inconsistency"):
        resolved_type = "type_inconsistency"
    elif ctype in ("unit_conflict", "unit_inconsistency"):
        resolved_type = "unit_inconsistency"
    else:
        resolved_type = ctype

    # ── Step 2: Subtype 分类 ──
    subtype = "undetermined"
    rule_confidence = 0.5

    if resolved_type == "cross_source_value_conflict":
        if not same_material:
            subtype = "material_difference"
            rule_confidence = 0.85
        elif not same_condition and is_condition_field:
            subtype = "condition_difference"
            rule_confidence = 0.80
        elif cohens_d >= 0.8 and same_material and same_condition:
            subtype = "systematic_bias"
            rule_confidence = 0.80
        elif cohens_d >= 0.5 and same_material:
            subtype = "measurement_discrepancy"
            rule_confidence = 0.70
        elif temporal_gap is not None and temporal_gap > 10:
            subtype = "temporal_drift"
            rule_confidence = 0.65
        else:
            subtype = "undetermined"

    elif resolved_type == "type_inconsistency":
        values_a = str(conflict.get("value_a", ""))
        values_b = str(conflict.get("value_b", ""))
        try:
            float(values_a.replace("~", "").replace("≈", "").strip())
            subtype = "numeric_vs_string"
            rule_confidence = 0.90
        except ValueError:
            subtype = resolved_type
            rule_confidence = 0.60

    elif resolved_type == "unit_inconsistency":
        subtype = "same_dimension"
        rule_confidence = 0.70

    elif resolved_type == "semantic_conflict":
        subtype = "undetermined"
        rule_confidence = 0.30

    elif resolved_type == "completeness_conflict":
        subtype = "undetermined"
        rule_confidence = 0.40

    # ── Step 3: Severity 分类 ──
    severity = "medium"
    if field_criticality == "critical" and cohens_d >= 0.8:
        severity = "critical"
    elif field_criticality == "critical" and cohens_d >= 0.5:
        severity = "high"
    elif field_criticality == "important":
        severity = "medium"
    elif field_criticality == "auxiliary":
        severity = "low"

    logger.debug("[RuleClassifier] %s → %s/%s/%s (confidence=%.2f)",
                 conflict.get("conflict_id", "?"), resolved_type, subtype, severity, rule_confidence)

    return {
        "conflict_id": conflict.get("conflict_id"),
        "type": resolved_type,
        "subtype": subtype,
        "severity": severity,
        "rule_confidence": rule_confidence,
    }
