"""
合并多个论文列表
"""

from typing import List
import logging
from shared.models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def merge_papers(
    papers: list[PaperMetadata],
    citation_papers: list[PaperMetadata],
    pubmed_papers: list[PaperMetadata] = None
) -> list[PaperMetadata]:
    """
    合并多个论文列表

    Args:
        papers: Agent B的OpenAlex搜索结果
        citation_papers: Agent D的引用扩展结果
        pubmed_papers: Agent B2的PubMed搜索结果（可选）

    Returns:
        合并后的列表（可能包含重复）
    """
    merged = papers + citation_papers

    if pubmed_papers:
        merged += pubmed_papers
        logger.debug(f"Merged {len(papers)} + {len(citation_papers)} + {len(pubmed_papers)} = {len(merged)} papers")
    else:
        logger.debug(f"Merged {len(papers)} + {len(citation_papers)} = {len(merged)} papers")

    return merged
