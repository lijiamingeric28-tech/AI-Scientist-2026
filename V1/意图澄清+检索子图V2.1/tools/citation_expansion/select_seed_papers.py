"""
选择Top N高引用论文作为种子
"""

from typing import List
import logging
from models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def select_seed_papers(papers: List[PaperMetadata], top_n: int = 5) -> List[PaperMetadata]:
    """
    选择Top N高引用论文作为种子

    Args:
        papers: 已排序的论文列表（按cited_by_count降序）
        top_n: 选择数量，默认5

    Returns:
        前N篇论文作为种子列表

    注意:
        - papers必须已经排序（由Agent B保证）
        - 若papers数量<top_n，返回全部papers
    """
    if not papers:
        logger.warning("Papers list is empty")
        return []

    selected = papers[:top_n]
    logger.info(f"Selected {len(selected)} seed papers from {len(papers)} total papers")

    return selected
