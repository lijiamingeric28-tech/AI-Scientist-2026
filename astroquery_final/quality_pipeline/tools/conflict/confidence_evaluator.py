"""
confidence_evaluator.py → V3.0: AnnotationConfidenceEvaluator (原 ConfidenceEvaluator)

V3.0 重写: 从"裁决置信度"改为"分类与标注置信度"。
  旧: 4维冲突裁决置信度 (source_agreement, statistical_clarity, domain_match, history)
  新: 3维差异分类置信度 (metadata_completeness, cause_consistency, domain_support)

评估差异原因分类是否可靠, 而非裁决是否可靠。
"""
from __future__ import annotations
from typing import Any
from ...utils.logger import get_logger
logger = get_logger(__name__)


def evaluate_confidence(
    variance: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    iteration_counter: int = 0,
) -> dict[str, Any]:
    """
    V3.0: 评估差异原因分类的置信度。

    3 个维度:
      1. Metadata Completeness (0.40) — V2 字段完整度
      2. Cause Consistency (0.35) — 规则推断 vs LLM vs 领域规则, 多方是否一致
      3. Domain Support (0.25) — 领域规则匹配度

    Args:
        variance: 方差条目 (含 source_stats, inferred_cause, classified_cause 等)
        evidence: (保留参数, 向后兼容)
        iteration_counter: 迭代计数 (用于动态阈值)

    Returns:
        {overall_confidence, components, meets_auto_threshold, confidence_level}
    """
    source_stats = variance.get("source_stats", {})
    inferred_cause = variance.get("inferred_cause", "unknown")
    classified_cause = variance.get("classified_cause", inferred_cause)
    cause_confidence = variance.get("cause_confidence_final", variance.get("cause_confidence", 0))

    # ── 1. Metadata Completeness (0.40) ──
    # 有多少 source 提供了 measurement_method / condition_tags
    total_sources = len(source_stats) if source_stats else 1
    sources_with_method = sum(
        1 for ss in source_stats.values()
        if ss.get("measurement_methods")
    )
    sources_with_tags = sum(
        1 for ss in source_stats.values()
        if ss.get("condition_tags")
    )
    sources_with_year = sum(
        1 for ss in source_stats.values()
        if ss.get("year") is not None
    )

    method_ratio = sources_with_method / max(total_sources, 1)
    tags_ratio = sources_with_tags / max(total_sources, 1)
    year_ratio = sources_with_year / max(total_sources, 1)

    metadata_score = 0.4 * method_ratio + 0.35 * tags_ratio + 0.25 * year_ratio

    # ── 2. Cause Consistency (0.35) ──
    # cause_confidence 来自分类器 (规则=高, LLM=中, fallback=低)
    classification_method = variance.get("classification_method", "rule")
    method_scores = {"rule": 0.90, "llm": 0.70, "fallback": 0.30}
    base_cause_score = method_scores.get(classification_method, 0.50)

    # 规则推断 vs LLM vs 领域规则的一致性
    consistency = base_cause_score

    # ── 3. Domain Support (0.25) ──
    domain_rules = (evidence or {}).get("domain_rules", {})
    has_guidance = domain_rules.get("has_domain_guidance", False)
    confidence_boost = domain_rules.get("confidence_boost", 0)

    domain_score = 0.60  # base
    if has_guidance:
        domain_score = 0.80 + confidence_boost
    domain_score = min(1.0, domain_score)

    # ── 综合 ──
    overall = (
        0.40 * metadata_score
        + 0.35 * consistency
        + 0.25 * domain_score
    )
    overall = round(overall, 4)

    # ── 动态阈值 ──
    thresholds = {0: 0.55, 1: 0.50, 2: 0.45}
    base_threshold = thresholds.get(iteration_counter, 0.45)
    meets_threshold = overall >= base_threshold

    if overall >= 0.70:
        level = "high"
    elif overall >= 0.50:
        level = "medium"
    else:
        level = "low"

    logger.info("[AnnotationConfidence V3.0] cls=%s, metadata=%.2f, consist=%.2f, domain=%.2f, overall=%.3f",
                classified_cause, metadata_score, consistency, domain_score, overall)

    return {
        "conflict_d": variance.get("conflict_d", variance.get("entity_name", "?")),
        "overall_confidence": overall,
        "components": {
            "metadata_completeness": round(metadata_score, 4),
            "cause_consistency": round(consistency, 4),
            "domain_support": round(domain_score, 4),
        },
        "meets_auto_threshold": meets_threshold,
        "confidence_level": level,
        "threshold_applied": base_threshold,
        "iteration_factor_applied": False,
    }
