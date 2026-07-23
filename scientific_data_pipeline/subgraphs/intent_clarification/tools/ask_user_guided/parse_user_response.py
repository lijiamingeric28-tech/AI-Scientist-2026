"""
工具：解析用户的纯文本回答，规范化为结构化信息
"""
from shared.utils.retry import retry_on_failure
from shared.utils.llm_client import call_llm
from config.prompts import PARSE_RESPONSE_PROMPT
from config.constants import LOW_TEMP, DEFAULT_TIMEOUT
import logging

logger = logging.getLogger(__name__)


def parse_user_response(
    user_input: str,
    question: str,
    options: list[str],
    missing_slot: str
) -> str:
    """
    解析用户的纯文本回答，规范化为结构化信息

    策略：LLM解析 + 规则兜底

    Args:
        user_input: 用户原始输入
        question: 之前的追问
        options: 之前提供的选项
        missing_slot: 当前追问针对的槽位

    Returns:
        规范化后的回答
    """
    logger.info(f"Parsing user response: {user_input[:50]}...")

    # 尝试LLM解析
    try:
        result = _parse_with_llm(user_input, question, options, missing_slot)
        logger.info(f"LLM parsing succeeded: {result}")
        return result

    except Exception as e:
        logger.warning(f"LLM parsing failed: {e}, using fallback")

        # 兜底：简单规则匹配
        result = _parse_with_rules(user_input, options)
        logger.info(f"Fallback parsing result: {result}")
        return result


@retry_on_failure(max_retries=1, delay_seconds=0.5, backoff_factor=1.0)
def _parse_with_llm(
    user_input: str,
    question: str,
    options: list[str],
    missing_slot: str
) -> str:
    """LLM解析（内部函数，带重试）"""
    # 格式化选项
    options_str = "\n".join(f"- {opt}" for opt in options) if options else "无"

    prompt = PARSE_RESPONSE_PROMPT.format(
        question=question,
        options=options_str,
        user_input=user_input
    )

    # 返回纯文本（不需要JSON）
    result = call_llm(
        prompt=prompt,
        system_prompt="你是对话理解助手。",
        temperature=LOW_TEMP,
        timeout=DEFAULT_TIMEOUT
    )

    return result.strip()


def _parse_with_rules(user_input: str, options: list[str]) -> str:
    """规则兜底（内部函数，纯Python）"""
    user_input = user_input.strip()

    # 尝试数字索引
    if user_input.isdigit() and options:
        idx = int(user_input) - 1
        if 0 <= idx < len(options):
            return options[idx]

    # 保持原文本
    return user_input
