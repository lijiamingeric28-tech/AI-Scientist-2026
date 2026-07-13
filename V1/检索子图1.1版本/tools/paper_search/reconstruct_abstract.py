"""
从OpenAlex的倒排索引重建摘要
"""

from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:
    """
    从OpenAlex的倒排索引重建摘要

    Args:
        inverted_index: OpenAlex返回的倒排索引，如
            {
                "This": [0],
                "study": [1],
                "investigates": [2],
                "the": [3, 7],
                "mechanical": [4],
                ...
            }

    Returns:
        重建的摘要字符串，如"This study investigates the mechanical..."
        若输入为空，返回None
    """
    if not inverted_index:
        return None

    try:
        # 反转索引：位置 -> 单词
        position_to_word = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                position_to_word[pos] = word

        # 按位置排序并拼接
        sorted_positions = sorted(position_to_word.keys())
        words = [position_to_word[pos] for pos in sorted_positions]

        return " ".join(words)

    except Exception as e:
        logger.warning(f"Failed to reconstruct abstract: {e}")
        return None
