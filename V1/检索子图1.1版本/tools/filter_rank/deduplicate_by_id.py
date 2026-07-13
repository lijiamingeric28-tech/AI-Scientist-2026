"""
基于OpenAlex ID去重
"""

from typing import List
import logging
from models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def deduplicate_by_id(papers: List[PaperMetadata]) -> List[PaperMetadata]:
    """
    基于OpenAlex ID去重

    Args:
        papers: 可能包含重复的论文列表

    Returns:
        去重后的论文列表（保留第一次出现的）

    去重逻辑:
        使用OpenAlex ID（paper.id）作为唯一标识
        若遇到相同ID，保留第一次出现的记录
    """
    seen_ids = set()
    deduplicated = []

    for paper in papers:
        if paper.id not in seen_ids:
            seen_ids.add(paper.id)
            deduplicated.append(paper)

    duplicates_removed = len(papers) - len(deduplicated)
    logger.debug(f"Removed {duplicates_removed} duplicates, {len(deduplicated)} papers remain")

    return deduplicated
