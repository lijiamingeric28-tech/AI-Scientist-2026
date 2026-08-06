"""
contextual_evidence.py → V3.0: VarianceCauseEvidence (原 ContextualEvidenceCollector)

V3.0 修改: 上下文证据从"冲突裁决辅助"改为"差异原因证据汇总"。
  输出差异原因标签 + 置信度, 而非 conflict resolution evidence。
"""
from __future__ import annotations
from typing import Any
from ...utils.logger import get_logger
logger = get_logger(__name__)


def collect_contextual_evidence(
    conflict: dict[str, Any],
    current_data: dict[str, Any],
) -> dict[str, Any]:
    """
    V3.0: 收集差异原因证据 (替代旧冲突上下文证据)。

    Args:
        conflict: 带上下文的差异条目
        current_data: data_state.current_data

    Returns:
        {variance_cause_evidence, source_consistency, temporal_evidence, annotation_suggestions}
    """
    ctx = conflict.get("context", {})

    # V3.0: 直接读取 V2 字段差异
    methods_differ = ctx.get("methods_differ", False)
    tags_differ = ctx.get("tags_differ", False)
    all_methods = ctx.get("all_measurement_methods", [])
    all_tags = ctx.get("all_condition_tags", [])
    temporal_gap = ctx.get("temporal_gap_years")
    value_range = ctx.get("value_range")
    source_meta = ctx.get("source_meta", {})

    # ── 差异原因证据 ──
    cause_hints = []
    if methods_differ and all_methods:
        cause_hints.append({
            "cause": "methodological_variance",
            "confidence": 0.80,
            "evidence": f"Different measurement methods: {all_methods}",
        })
    if tags_differ and all_tags:
        cause_hints.append({
            "cause": "condition_variance",
            "confidence": 0.80,
            "evidence": f"Different observation conditions: {all_tags}",
        })
    if temporal_gap is not None and temporal_gap > 5:
        cause_hints.append({
            "cause": "temporal_variation",
            "confidence": 0.70,
            "evidence": f"Time span: {temporal_gap} years",
        })

    # ── 来源一致性 ──
    years = [
        m.get("year") for m in source_meta.values()
        if m.get("year") is not None
    ]
    journals = [
        m.get("journal", "") for m in source_meta.values()
        if m.get("journal")
    ]

    source_consistency = {
        "source_count": len(source_meta),
        "year_span": f"{min(years)}–{max(years)}" if len(years) >= 2 else "single year",
        "journals": list(set(journals)),
    }

    # ── 时间证据 ──
    temporal_evidence = {
        "temporal_gap_years": temporal_gap,
        "is_significant_temporal_gap": temporal_gap is not None and temporal_gap > 5,
        "note": (
            f"{temporal_gap}yr gap — likely temporal variation" if (temporal_gap and temporal_gap > 5)
            else "Same period — temporal factor unlikely"
        ),
    }

    # ── V3.0: 标注建议 ──
    annotation_suggestions = []
    if methods_differ:
        annotation_suggestions.append(
            f"Mark as methodological_variance: {', '.join(sorted(all_methods))}"
        )
    if tags_differ:
        annotation_suggestions.append(
            f"Mark as condition_variance: {', '.join(sorted(all_tags))}"
        )
    if value_range:
        annotation_suggestions.append(
            f"Value range: [{value_range[0]}, {value_range[1]}] — preserve all as range"
        )
    if not annotation_suggestions:
        annotation_suggestions.append(
            "Preserve all values with measurement_uncertainty annotation"
        )

    logger.info("[VarianceCauseEvidence V3.0] %s: methods_differ=%s, tags_differ=%s, gap=%s",
                conflict.get("conflict_id", "?"), methods_differ, tags_differ, temporal_gap)

    return {
        "variance_cause_evidence": cause_hints,
        "source_consistency": source_consistency,
        "temporal_evidence": temporal_evidence,
        "annotation_suggestions": annotation_suggestions,
    }
