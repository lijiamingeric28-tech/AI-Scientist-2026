"""
工具：根据缺失槽位生成引导式追问
"""
import json
from shared.utils.retry import retry_on_failure
from shared.utils.llm_client import call_llm_structured
from config.prompts import CLARIFICATION_PROMPT
from config.constants import MID_TEMP, DEFAULT_TIMEOUT
import logging

logger = logging.getLogger(__name__)


@retry_on_failure(max_retries=1, delay_seconds=0.5, backoff_factor=1.0)
def generate_clarification_question(
    missing_slots: list[str],
    schema: dict,
    query: str,
    current_params: dict = None
) -> dict:
    """
    根据缺失槽位和上下文，生成引导式追问文本和选项

    Args:
        missing_slots: 缺失的槽位列表
        schema: 槽位检查清单
        query: 用户原始查询
        current_params: 当前已提取参数（可选）

    Returns:
        {"question": str, "options": list[str]}

    Raises:
        TimeoutError: 调用超时
        ValueError: LLM返回格式错误

    Fallback:
        如果失败，调用方应生成通用追问文本
    """
    logger.info(f"Generating clarification question for missing slots: {missing_slots}")

    if current_params is None:
        current_params = {}

    # 格式化数据
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    current_params_str = json.dumps(current_params, ensure_ascii=False, indent=2)
    missing_slots_str = ", ".join(missing_slots)

    # 构建Prompt
    prompt = CLARIFICATION_PROMPT.format(
        query=query,
        current_params=current_params_str,
        schema=schema_str,
        missing_slots=missing_slots_str
    )

    # 调用LLM（带自动重试）
    result = call_llm_structured(
        prompt=prompt,
        system_prompt="你是科学数据查询的交互助手。",
        temperature=MID_TEMP,
        timeout=DEFAULT_TIMEOUT
    )

    # 验证返回格式
    if "question" not in result:
        raise ValueError("Missing 'question' in response")
    if "options" not in result:
        result["options"] = []

    logger.info(f"Generated question: {result['question']}")
    logger.debug(f"Options: {result['options']}")

    return result
