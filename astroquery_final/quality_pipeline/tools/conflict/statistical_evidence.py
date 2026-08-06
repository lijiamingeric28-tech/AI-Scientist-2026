"""
statistical_evidence.py — Tool 6: StatisticalEvidenceAnalyzer

分析冲突的统计证据：统计显著性、样本量充分性、效应量解释。
"""
from __future__ import annotations
import math
from typing import Any
from ...utils.logger import get_logger
logger = get_logger(__name__)


def analyze_statistical_evidence(conflict: dict[str, Any]) -> dict[str, Any]:
    """
    分析冲突的统计证据。

    Args:
        conflict: 冲突记录 (含 cohens_d, ci_95, n_a, n_b 等)

    Returns:
        {statistically_significant, small_sample_warning, effect_size_interpretation, recommendation}
    """
    cohens_d = conflict.get("cohens_d", 0)
    ci_95 = conflict.get("ci_95", [0, 0])
    n_a = conflict.get("n_a", 1)
    n_b = conflict.get("n_b", 1)

    # 1. 统计显著性判定
    ci_low, ci_high = ci_95[0], ci_95[1]
    if ci_low > 0.5:
        stat_sig = True  # CI 下界仍超 medium, 稳定
    elif ci_high < 0.2:
        stat_sig = False  # CI 上界不足 small, 可忽略
    else:
        stat_sig = "borderline"

    # 2. 样本量充分性
    small_sample = n_a < 3 or n_b < 3

    # 3. 效应量解释
    if cohens_d >= 2.0:
        interpretation = "Massive difference — almost certainly genuine, not measurement noise"
    elif cohens_d >= 1.0:
        interpretation = "Very large difference — likely genuine, strong evidence of real discrepancy"
    elif cohens_d >= 0.5:
        interpretation = "Medium difference — may be genuine or due to methodological differences"
    elif cohens_d >= 0.2:
        interpretation = "Small difference — possibly measurement noise or minor condition variations"
    else:
        interpretation = "Negligible difference — within expected measurement error"

    # 4. 推荐
    if stat_sig is True and not small_sample:
        recommendation = "strong_evidence"
    elif stat_sig is True and small_sample:
        recommendation = "moderate_evidence"
    elif stat_sig == "borderline":
        recommendation = "moderate_evidence"
    else:
        recommendation = "weak_evidence"

    logger.info("[StatisticalEvidence] %s: d=%.3f, sig=%s, small_sample=%s, rec=%s",
                conflict.get("conflict_id", "?"), cohens_d, stat_sig, small_sample, recommendation)

    return {
        "statistically_significant": stat_sig,
        "small_sample_warning": small_sample,
        "effect_size_interpretation": interpretation,
        "n_a": n_a,
        "n_b": n_b,
        "cohens_d": round(cohens_d, 4),
        "ci_95": ci_95,
        "recommendation": recommendation,
    }
