"""
根据条件过滤论文
"""

from typing import List, Dict, Optional, Tuple
import logging
from models.paper_metadata import PaperMetadata
from configs.constants import (
    FILTER_MIN_CITATION_COUNT,
    FILTER_YEAR_RELAXATION,
    FILTER_OA_HIGH_CITATION_THRESHOLD
)

logger = logging.getLogger(__name__)


def filter_papers(
    papers: List[PaperMetadata],
    conditions: Dict[str, str]
) -> List[PaperMetadata]:
    """
    根据条件过滤论文

    Args:
        papers: 去重后的论文列表
        conditions: 过滤条件，如{"year": "2015-2025"}

    Returns:
        过滤后的论文列表

    过滤规则:
        1. 年份：放宽±2年（如原始2015-2025，实际2013-2025）
        2. 引用数：>=3
        3. OA状态：OA优先，但保留高引用(>50)的非OA论文
    """
    filtered = []

    # 解析年份范围（放宽±2年）
    year_range = _parse_year_range_relaxed(conditions.get("year"))

    for paper in papers:
        # 年份过滤
        if year_range and (paper.year < year_range[0] or paper.year > year_range[1]):
            continue

        # 引用数过滤
        if paper.citation_count < FILTER_MIN_CITATION_COUNT:
            continue

        # OA过滤（OA优先，但高引用非OA也保留）
        if not paper.is_oa and paper.citation_count < FILTER_OA_HIGH_CITATION_THRESHOLD:
            continue

        filtered.append(paper)

    logger.debug(f"Filtered {len(papers)} -> {len(filtered)} papers")

    return filtered


def _parse_year_range_relaxed(year_str: Optional[str]) -> Optional[Tuple[int, int]]:
    """
    解析年份范围并放宽±2年

    Args:
        year_str: "2015-2025"

    Returns:
        (2013, 2025) - 起始年份-2，结束年份不变
    """
    if not year_str:
        return None

    try:
        start, end = year_str.split("-")
        start_year = int(start) - FILTER_YEAR_RELAXATION
        end_year = int(end)
        logger.debug(f"Year range: {start_year}-{end_year} (relaxed from {year_str})")
        return (start_year, end_year)
    except:
        logger.warning(f"Failed to parse year range: {year_str}")
        return None
