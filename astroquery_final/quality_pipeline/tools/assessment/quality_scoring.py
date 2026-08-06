"""
quality_scoring.py

Stage 3：Quality Scoring — 综合各项评估结果，
计算 Overall Quality Score、确定 Quality Level。
"""

from __future__ import annotations

from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)

# 默认权重
_DEFAULT_WEIGHTS = {
    "completeness": 0.25,
    "consistency": 0.30,
    "format": 0.10,
    "source_reliability": 0.15,
    "conflict_risk": 0.20,
}

# 质量等级阈值
_LEVELS = {
    "excellent": 0.90,
    "good": 0.75,
    "fair": 0.60,
    "poor": 0.40,
}


def compute_quality_score(
    metrics: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    综合各项评估指标计算 Overall Quality Score。

    Args:
        metrics: 各评估维度的结果字典。
            需包含键：completeness, consistency, format, source_reliability, conflict_risk
            每个子字典需含 "score" 字段。
        weights: 各维度权重。None 则使用默认权重。

    Returns:
        质量评分结果：
        {
            "overall_score": float,
            "quality_level": str,
            "dimension_scores": dict[str, float],
            "dimension_weights": dict[str, float],
            "confidence": float,
            "summary": str,
        }
    """
    logger.info("开始综合质量评分...")

    w = weights or _DEFAULT_WEIGHTS

    dimension_scores: dict[str, float] = {}
    weighted_sum = 0.0
    total_weight = 0.0

    for dim, weight in w.items():
        dim_data = metrics.get(dim, {})
        if isinstance(dim_data, dict):
            score = dim_data.get("score", 0.0)
        else:
            score = 0.0
        dimension_scores[dim] = round(score, 4)
        weighted_sum += score * weight
        total_weight += weight

    # 归一化
    overall_score = weighted_sum / total_weight if total_weight > 0 else 0.0
    overall_score = round(max(0.0, min(1.0, overall_score)), 4)

    # 确定质量等级
    quality_level = "poor"
    for level, threshold in sorted(_LEVELS.items(), key=lambda x: -x[1]):
        if overall_score >= threshold:
            quality_level = level
            break

    # 评估置信度：基于各维度评分的一致性
    scores_list = list(dimension_scores.values())
    if len(scores_list) >= 2:
        import statistics
        try:
            stdev = statistics.stdev(scores_list)
        except statistics.StatisticsError:
            stdev = 0.0
        # 标准差越小，置信度越高
        confidence = round(1.0 - min(1.0, stdev), 4)
    else:
        confidence = 0.5

    # 生成摘要
    weak_dims = [d for d, s in dimension_scores.items() if s < 0.6]
    summary_parts = [f"Overall: {overall_score:.2f} ({quality_level})"]
    if weak_dims:
        summary_parts.append(f"薄弱维度: {', '.join(weak_dims)}")

    result = {
        "overall_score": overall_score,
        "quality_level": quality_level,
        "dimension_scores": dimension_scores,
        "dimension_weights": w,
        "confidence": confidence,
        "summary": " | ".join(summary_parts),
    }

    logger.info("质量评分完成: overall=%.2f, level=%s。", overall_score, quality_level)
    return result
