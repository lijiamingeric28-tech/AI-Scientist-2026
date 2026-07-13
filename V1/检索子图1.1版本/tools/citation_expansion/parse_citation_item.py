"""
解析OpenAlex API返回的引用论文记录
"""

from typing import Dict, Any, Optional
import logging
from models.paper_metadata import PaperMetadata
from tools.paper_search.parse_openalex_item import parse_openalex_item

logger = logging.getLogger(__name__)


def parse_citation_item(item: Dict[str, Any]) -> Optional[PaperMetadata]:
    """
    解析OpenAlex API返回的引用论文记录

    Args:
        item: OpenAlex API返回的单条JSON

    Returns:
        PaperMetadata对象，若解析失败返回None
    """
    try:
        # 复用Agent B的解析逻辑
        return parse_openalex_item(item)
    except Exception as e:
        logger.warning(f"Failed to parse citation item: {e}")
        return None
