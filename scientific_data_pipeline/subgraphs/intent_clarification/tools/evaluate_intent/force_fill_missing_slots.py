"""
工具：对缺失槽位进行AI最佳猜测填充（兜底机制）
"""
import json
from shared.utils.retry import retry_on_failure
from shared.utils.llm_client import call_llm_structured
from config.prompts import FORCE_FILL_PROMPT
from config.constants import MID_TEMP, DEFAULT_TIMEOUT
import logging

logger = logging.getLogger(__name__)


@retry_on_failure(max_retries=1, delay_seconds=0.5, backoff_factor=1.0)
def force_fill_missing_slots(
    query: str,
    schema: dict,
    current_params: dict,
    missing_slots: list[str]
) -> dict:
    """
    对缺失槽位进行AI最佳猜测填充（兜底机制）

    Args:
        query: 用户原始查询
        schema: 槽位清单
        current_params: 当前已提取参数
        missing_slots: 缺失的槽位列表

    Returns:
        补齐后的extracted_parameters

    Raises:
        TimeoutError: 调用超时
        ValueError: LLM返回格式错误

    Fallback:
        如果失败，调用方应使用空值或默认值填充
    """
    logger.warning(f"Force filling missing slots: {missing_slots}")

    # 格式化数据
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    current_params_str = json.dumps(current_params, ensure_ascii=False, indent=2)
    missing_slots_str = ", ".join(missing_slots)

    # 构建Prompt
    prompt = FORCE_FILL_PROMPT.format(
        query=query,
        schema=schema_str,
        current_params=current_params_str,
        missing_slots=missing_slots_str
    )

    # 调用LLM（带自动重试）
    result = call_llm_structured(
        prompt=prompt,
        system_prompt="你是科学数据查询的参数推测专家。",
        temperature=MID_TEMP,
        timeout=DEFAULT_TIMEOUT
    )

    logger.info(f"Force filled parameters: {result}")

    return result
