"""
source_checker.py

Stage 2d：Source Reliability Assessment — 评估数据来源的
完整性、可信度及可追溯性。
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def check_source_reliability(data: dict[str, Any]) -> dict[str, Any]:
    """
    评估数据来源可信度。

    V1 纯文献场景下主要依赖：
    - DOI 是否有值
    - 元数据完整性（title, authors, year, journal）
    - retrieval_priority 评分

    Args:
        data: grounded_data JSON。

    Returns:
        来源可信度评估结果：
        {
            "score": float,
            "source_scores": dict[str, float],
            "issues": list[str],
            "summary": str,
        }
    """
    logger.info("开始来源可信度评估...")

    sources = data.get("sources", [])
    if not sources:
        return {
            "score": 0.0,
            "source_scores": {},
            "issues": ["无来源文献。"],
            "summary": "无来源文献。",
        }

    source_scores: dict[str, float] = {}
    issues: list[str] = []

    for source in sources:
        source_id = source.get("source_id", "unknown")
        score = _evaluate_single_source(source)
        source_scores[source_id] = score

        if score < 0.5:
            issues.append(f"来源 '{source_id}' 可信度较低 ({score:.2f})")

    # 整体评分：各来源评分加权平均（按 retrieval_priority 加权）
    total_weight = 0.0
    weighted_sum = 0.0
    for source in sources:
        source_id = source.get("source_id", "unknown")
        priority = source.get("retrieval_priority", 0.5)
        weighted_sum += source_scores.get(source_id, 0.0) * priority
        total_weight += priority

    overall_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    result = {
        "score": round(overall_score, 4),
        "source_scores": source_scores,
        "issues": issues,
        "summary": f"来源可信度整体{'良好' if overall_score >= 0.7 else '一般' if overall_score >= 0.5 else '较低'}。"
        if issues else "所有来源可信度良好。",
    }

    logger.info("来源可信度评估完成: score=%.2f, %d 个问题。", overall_score, len(issues))
    return result


def _evaluate_single_source(source: dict[str, Any]) -> float:
    """评估单个来源的可信度，返回 0-1 分数。"""
    score = 0.0
    checks = 0

    # DOI 存在性
    checks += 1
    if source.get("doi") is not None and source.get("doi") != "":
        score += 1.0

    # 标题
    checks += 1
    if source.get("title") and len(source.get("title", "")) > 5:
        score += 1.0

    # 作者
    checks += 1
    authors = source.get("authors", [])
    if authors and len(authors) > 0:
        score += 1.0

    # 年份
    checks += 1
    year = source.get("year")
    if year is not None and isinstance(year, int) and 1900 <= year <= 2030:
        score += 1.0

    # 期刊
    checks += 1
    if source.get("journal") is not None and source.get("journal", "") != "":
        score += 0.5

    # 检索优先级
    checks += 1
    priority = source.get("retrieval_priority", 0.0)
    score += priority

    return score / checks if checks > 0 else 0.0
