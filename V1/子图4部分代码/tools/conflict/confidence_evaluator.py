"""
confidence_evaluator.py — Tool 8: ConfidenceEvaluator

4 维置信度评估 + 动态阈值调整:
  1. Source Agreement (来源可靠性共识)
  2. Statistical Clarity (统计清晰度)
  3. Domain Rule Match (领域规则匹配)
  4. Historical Corroboration (历史一致性)
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def evaluate_confidence(
    reasoning_result: dict[str, Any],
    evidence: dict[str, Any],
    iteration_counter: int = 0,
) -> dict[str, Any]:
    """
    对冲突推理结果进行置信度评估。

    Args:
        reasoning_result: Node 4 推理结果 (含 strategy, resolved_value 等)
        evidence: Node 3 证据集合 (source_reliability, domain_rules, statistical, contextual)
        iteration_counter: B⇄C 循环次数

    Returns:
        {overall_confidence, components, meets_auto_threshold, confidence_level}
    """
    src_rel = evidence.get("source_reliability", {})
    stat_ev = evidence.get("statistical_evidence", {})
    domain = evidence.get("domain_rules", {})
    contextual = evidence.get("contextual_evidence", {})

    # ── 1. Source Agreement (0.30) ──
    # reliability gap 越大 → 选择越明确
    gap = src_rel.get("reliability_gap", 0)
    source_agreement = min(1.0, gap / 0.30)  # gap=0.15 → 0.50, gap=0.30 → 1.0
    source_agreement = max(0.20, source_agreement)

    # ── 2. Statistical Clarity (0.30) ──
    cohens_d = stat_ev.get("cohens_d", 0)
    ci_95 = stat_ev.get("ci_95", [0, 0])
    ci_low = ci_95[0] if ci_95 else 0
    small_sample = stat_ev.get("small_sample_warning", False)

    if ci_low >= 0.8:
        clarity = 1.0
    elif ci_low >= 0.5:
        clarity = 0.85
    elif ci_low >= 0.2:
        clarity = 0.60
    else:
        clarity = 0.30

    if small_sample:
        clarity *= 0.70  # 小样本惩罚

    # ── 3. Domain Rule Match (0.20) ──
    has_guidance = domain.get("has_domain_guidance", False)
    matched_count = len(domain.get("matched_rules", []))
    if matched_count >= 2:
        domain_match = 0.90
    elif matched_count == 1:
        domain_match = 0.80
    elif has_guidance:
        domain_match = 0.65
    else:
        domain_match = 0.40

    # ── 4. Historical Corroboration (0.20) ──
    # V1.0: 无历史库 → 使用 heuristic
    # 基于 contextual evidence 的一致性
    hist = 0.70  # base
    if contextual.get("same_material", True):
        hist += 0.05
    if contextual.get("same_condition", True):
        hist += 0.05
    if contextual.get("same_measurement_method") is True:
        hist += 0.05
    # 语义类型置信度
    hist = min(1.0, hist)

    # ── 综合 ──
    overall = (
        0.30 * source_agreement
        + 0.30 * clarity
        + 0.20 * domain_match
        + 0.20 * hist
    )
    overall = round(overall, 4)

    # ── 动态阈值 ──
    thresholds = {0: 0.75, 1: 0.70, 2: 0.65}
    base_threshold = thresholds.get(iteration_counter, 0.65)

    # 迭代激进因子: 第3轮 (iteration_counter >= 2) 降低要求
    if iteration_counter >= 2:
        overall = round(overall * 0.85, 4)

    meets_threshold = overall >= base_threshold

    if overall >= 0.75:
        level = "high"
    elif overall >= 0.50:
        level = "medium"
    else:
        level = "low"

    logger.info("[ConfidenceEvaluator] %s: overall=%.3f, threshold=%.2f, meets=%s, level=%s",
                reasoning_result.get("conflict_id", "?"), overall, base_threshold, meets_threshold, level)

    return {
        "conflict_id": reasoning_result.get("conflict_id"),
        "overall_confidence": overall,
        "components": {
            "source_agreement": round(source_agreement, 4),
            "statistical_clarity": round(clarity, 4),
            "domain_rule_match": round(domain_match, 4),
            "historical_corroboration": round(hist, 4),
        },
        "meets_auto_threshold": meets_threshold,
        "confidence_level": level,
        "threshold_applied": base_threshold,
        "iteration_factor_applied": iteration_counter >= 2,
    }
