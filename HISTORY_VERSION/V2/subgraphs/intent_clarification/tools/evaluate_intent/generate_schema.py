"""
工具：动态生成槽位检查清单
"""
from shared.utils.retry import retry_on_failure
from shared.utils.llm_client import call_llm_structured
from config.prompts import SCHEMA_GENERATION_PROMPT
from config.constants import LOW_TEMP, DEFAULT_TIMEOUT
import logging

logger = logging.getLogger(__name__)


@retry_on_failure(max_retries=1, delay_seconds=0.5, backoff_factor=1.0)
def generate_schema(query: str, domain: str = "general") -> dict:
    """
    基于用户查询动态生成槽位检查清单

    Args:
        query: 用户原始查询
        domain: 领域（如"materials_science"）

    Returns:
        槽位检查清单
        格式：{"entities": {...}, "properties": {...}, "conditions": {...}}

    Raises:
        TimeoutError: 调用超时
        ValueError: LLM返回格式错误

    Fallback:
        如果连续2次失败，调用方应使用DEFAULT_SCHEMA
    """
    logger.info(f"Generating schema for domain={domain}")

    # 构建Prompt
    prompt = SCHEMA_GENERATION_PROMPT.format(
        query=query,
        domain=domain
    )

    # 调用LLM（带自动重试）
    result = call_llm_structured(
        prompt=prompt,
        system_prompt="你是科学数据查询的意图分析专家。",
        temperature=LOW_TEMP,  # 低温度确保稳定输出
        timeout=DEFAULT_TIMEOUT
    )

    # 验证返回格式
    required_keys = ["entities", "properties", "conditions"]
    for key in required_keys:
        if key not in result:
            raise ValueError(f"Missing required key in schema: {key}")

    logger.info(f"Schema generated successfully with {len(result)} slots")

    return result
