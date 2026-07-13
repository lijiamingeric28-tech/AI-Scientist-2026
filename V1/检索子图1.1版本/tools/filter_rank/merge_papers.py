"""
合并两个论文列表
"""

from typing import List
import logging
from models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def merge_papers(
    papers: List[PaperMetadata],
    citation_papers: List[PaperMetadata]
) -> List[PaperMetadata]:
    """
    合并两个论文列表

    Args:
        papers: Agent B的搜索结果
        citation_papers: Agent D的引用扩展结果

    Returns:
        合并后的列表（可能包含重复）
    """
    merged = papers + citation_papers
    logger.debug(f"Merged {len(papers)} + {len(citation_papers)} = {len(merged)} papers")
    return merged
