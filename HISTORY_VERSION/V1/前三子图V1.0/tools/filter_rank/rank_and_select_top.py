"""
排序并选择Top N论文
"""

from typing import List
import logging
from models.paper_metadata import PaperMetadata
from configs.constants import OUTPUT_TOP_N

logger = logging.getLogger(__name__)


def rank_and_select_top(
    papers: List[PaperMetadata],
    top_n: int = OUTPUT_TOP_N
) -> List[PaperMetadata]:
    """
    排序并选择Top N论文

    Args:
        papers: 已计算score的论文列表
        top_n: 选择数量，None表示选择全部，默认从配置读取

    Returns:
        Top N论文（按score降序），如果top_n为None则返回所有论文
    """
    if not papers:
        logger.warning("Papers list is empty")
        return []

    # 按score降序排序
    sorted_papers = sorted(papers, key=lambda p: p.score if p.score else 0, reverse=True)

    # 选择Top N（如果top_n为None，则返回所有论文）
    if top_n is None:
        selected = sorted_papers
        logger.info(f"Selecting all {len(selected)} papers (OUTPUT_TOP_N=None)")
    else:
        selected = sorted_papers[:top_n]
        logger.debug(f"Selected top {len(selected)} papers from {len(papers)} total")

    return selected
