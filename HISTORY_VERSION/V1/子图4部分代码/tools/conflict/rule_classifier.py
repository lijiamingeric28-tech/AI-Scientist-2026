"""
rule_classifier.py → V3.0: VarianceCauseClassifier (原 RuleBasedClassifier)

V3.0 重写: 分类多源差异原因, 替代旧的冲突类型分类。
  - 旧: cross_source_value_conflict / type_inconsistency / unit_inconsistency / ...
  - 新: methodological_variance / condition_variance / temporal_variation
       / measurement_uncertainty / duplicate_observation

利用 V2 Record 字段: measurement_method, condition_tags, year, extraction_confidence
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

# ── V3.0: 差异原因常量 ──
CAUSE_METHODOLOGICAL = "methodological_variance"
CAUSE_CONDITION = "condition_variance"
CAUSE_TEMPORAL = "temporal_variation"
CAUSE_UNCERTAINTY = "measurement_uncertainty"
CAUSE_DUPLICATE = "duplicate_observation"
CAUSE_UNKNOWN = "unknown"

# 时间差异阈值 (年)
_TEMPORAL_GAP_THRESHOLD = 5

# 条件类语义类型 (不同条件下自然有不同值)
_CONDITION_SEMANTIC_TYPES = {
    "temperature", "strain_rate", "pressure", "humidity",
    "exposure_time", "wavelength", "frequency", "resolution",
    "magnetic_field", "electric_field", "ph", "flux",
}


def classify_variance_cause(
    variance: dict[str, Any],
    semantic_types: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    V3.0: 分类多源差异原因 (规则确定性)。

    优先级:
      1. 值完全相同 + 不同source → duplicate_observation
      2. measurement_method 不同 → methodological_variance
      3. condition_tags 不同 → condition_variance
      4. year 差距 > 5 年 → temporal_variation
      5. 以上相同 + Cohen's d < 0.5 → measurement_uncertainty
      6. 以上相同 + Cohen's d >= 2.0 → statistical_outlier (潜在异常)
      7. 其他 → unknown

    Args:
        variance: 方差条目, 含 source_stats (per-source 详情)
        semantic_types: profile.semantic_types (可选)

    Returns:
        {cause, confidence, reason, method}
    """
    source_stats = variance.get("source_stats", {})
    source_ids = list(source_stats.keys())

    if len(source_ids) < 2:
        return {"cause": CAUSE_UNKNOWN, "confidence": 0.3,
                "reason": "Only one source", "method": "rule"}

    # 收集 per-source 特征
    methods_by_source: dict[str, set] = {}
    tags_by_source: dict[str, set] = {}
    years_by_source: dict[str, int | None] = {}
    means_by_source: dict[str, float] = {}

    for sid, ss in source_stats.items():
        methods_by_source[sid] = set(ss.get("measurement_methods", []))
        tags_by_source[sid] = set(ss.get("condition_tags", []))
        years_by_source[sid] = ss.get("year")
        means_by_source[sid] = ss.get("mean", 0)

    # ── Rule 1: Duplicate observation (值完全相同) ──
    unique_means = set(round(m, 6) for m in means_by_source.values())
    if len(unique_means) == 1 and len(source_ids) > 1:
        return {"cause": CAUSE_DUPLICATE, "confidence": 0.95,
                "reason": f"Identical value ({list(unique_means)[0]}) from {len(source_ids)} sources",
                "method": "rule"}

    # ── Rule 2: Methodological variance (方法不同) ──
    all_methods = set().union(*methods_by_source.values())
    if len(all_methods) > 0:
        methods_differ = any(
            methods_by_source[sia] != methods_by_source[sib]
            for i, sia in enumerate(source_ids)
            for sib in source_ids[i + 1:]
        )
        if methods_differ:
            conf = 0.85 if all(len(m) > 0 for m in methods_by_source.values()) else 0.70
            return {"cause": CAUSE_METHODOLOGICAL, "confidence": conf,
                    "reason": f"Different methods: {', '.join(sorted(all_methods))}",
                    "method": "rule"}

    # ── Rule 3: Condition variance (条件不同) ──
    all_tags = set().union(*tags_by_source.values())
    if len(all_tags) > 0:
        tags_differ = any(
            tags_by_source[sia] != tags_by_source[sib]
            for i, sia in enumerate(source_ids)
            for sib in source_ids[i + 1:]
        )
        if tags_differ:
            conf = 0.85 if all(len(t) > 0 for t in tags_by_source.values()) else 0.70
            return {"cause": CAUSE_CONDITION, "confidence": conf,
                    "reason": f"Different conditions: {', '.join(sorted(all_tags))}",
                    "method": "rule"}

    # ── Rule 4: Temporal variation (时间差异 > 5 年) ──
    valid_years = [y for y in years_by_source.values() if y is not None]
    if len(valid_years) >= 2:
        year_span = max(valid_years) - min(valid_years)
        if year_span > _TEMPORAL_GAP_THRESHOLD:
            return {"cause": CAUSE_TEMPORAL, "confidence": 0.75,
                    "reason": f"Time span: {year_span} years ({min(valid_years)}–{max(valid_years)})",
                    "method": "rule"}

    # ── Rule 5: Measurement uncertainty (小差异) ──
    cohens_d = variance.get("max_cohens_d", 0)
    if cohens_d < 0.5:
        return {"cause": CAUSE_UNCERTAINTY, "confidence": 0.80,
                "reason": f"Small effect (d={cohens_d:.2f}), within measurement uncertainty",
                "method": "rule"}

    # ── Rule 6: 无法确定 → LLM 补充 ──
    return {"cause": CAUSE_UNKNOWN, "confidence": 0.40,
            "reason": "Could not determine cause from available metadata",
            "method": "rule"}


# ── 向后兼容: 旧 API ──
def classify_conflict_rule(
    conflict: dict[str, Any],
    semantic_types: dict[str, Any] | None = None,
    field_criticality: str = "important",
) -> dict[str, Any]:
    """
    向后兼容的旧 API — 内部转调 V3.0 classify_variance_cause()。

    旧返回格式: {conflict_id, type, subtype, severity, rule_confidence}
    """
    result = classify_variance_cause(conflict, semantic_types)

    # 映射 V3.0 cause → 旧 subtype
    cause_subtype_map = {
        CAUSE_METHODOLOGICAL: "methodological_variance",
        CAUSE_CONDITION: "condition_variance",
        CAUSE_TEMPORAL: "temporal_variation",
        CAUSE_UNCERTAINTY: "measurement_uncertainty",
        CAUSE_DUPLICATE: "duplicate_observation",
        CAUSE_UNKNOWN: "undetermined",
    }

    return {
        "conflict_id": conflict.get("conflict_id"),
        "type": "multi_source_variance",
        "subtype": cause_subtype_map.get(result["cause"], "undetermined"),
        "severity": "info",  # V3.0: 方差不是错误, 是信息
        "rule_confidence": result["confidence"],
    }
