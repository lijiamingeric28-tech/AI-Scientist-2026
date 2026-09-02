"""
工具：将问题和选项格式化为用户友好的展示文本
"""
import logging

logger = logging.getLogger(__name__)


def format_question_for_display(question: str, options: list[str]) -> str:
    """
    将问题和选项格式化为用户友好的展示文本

    Args:
        question: 问题文本
        options: 选项列表

    Returns:
        格式化后的完整文本

    Example:
        >>> format_question_for_display("您想查找哪种超新星？", ["Ia型", "II型"])
        "您想查找哪种超新星？\n\n选项：\n1. Ia型\n2. II型"
    """
    if not options:
        return question

    formatted = f"{question}\n\n选项："
    for i, option in enumerate(options, 1):
        formatted += f"\n{i}. {option}"

    logger.debug(f"Formatted question with {len(options)} options")

    return formatted
