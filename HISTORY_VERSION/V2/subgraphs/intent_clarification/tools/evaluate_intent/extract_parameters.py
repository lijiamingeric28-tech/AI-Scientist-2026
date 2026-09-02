"""
工具：从自然语言中提取结构化参数
"""
import json
from shared.utils.retry import retry_on_failure
from shared.utils.llm_client import call_llm_structured
from config.prompts import EXTRACTION_PROMPT
from config.constants import MID_TEMP, DEFAULT_TIMEOUT
import logging

logger = logging.getLogger(__name__)


@retry_on_failure(max_retries=1, delay_seconds=0.5, backoff_factor=1.0)
def extract_parameters(
    query: str,
    chat_history: list[dict],
    schema: dict,
    current_params: dict
) -> dict:
    """
    从自然语言中提取结构化参数，填充到槽位清单

    Args:
        query: 用户原始查询
        chat_history: 对话历史
        schema: 槽位清单
        current_params: 当前已提取参数

    Returns:
        更新后的extracted_parameters

    Raises:
        TimeoutError: 调用超时
        ValueError: LLM返回格式错误

    Fallback:
        如果连续2次失败，调用方应保持current_params不变
    """
    logger.info("Extracting parameters from query and chat history")

    # 格式化对话历史
    chat_history_str = json.dumps(chat_history, ensure_ascii=False, indent=2)
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    current_params_str = json.dumps(current_params, ensure_ascii=False, indent=2)

    # 构建Prompt
    prompt = EXTRACTION_PROMPT.format(
        query=query,
        chat_history=chat_history_str,
        schema=schema_str,
        current_params=current_params_str
    )

    # 调用LLM（带自动重试）
    result = call_llm_structured(
        prompt=prompt,
        system_prompt="你是科学数据查询的参数提取专家。",
        temperature=MID_TEMP,
        timeout=DEFAULT_TIMEOUT
    )

    logger.info(f"Extracted parameters: {result}")

    return result
