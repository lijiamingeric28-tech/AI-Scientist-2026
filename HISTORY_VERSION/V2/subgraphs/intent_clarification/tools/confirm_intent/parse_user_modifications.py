"""
工具：解析用户的确认/修改/拒绝指令
"""
import json
from shared.utils.retry import retry_on_failure
from shared.utils.llm_client import call_llm_structured
from config.prompts import MODIFICATION_PROMPT
from config.constants import LOW_TEMP, DEFAULT_TIMEOUT
import logging

logger = logging.getLogger(__name__)


def parse_user_modifications(
    user_input: str,
    current_params: dict,
    schema: dict = None
) -> dict:
    """
    解析用户的确认/修改/拒绝指令，更新extracted_parameters

    策略：LLM解析 + 规则兜底

    Args:
        user_input: 用户输入
        current_params: 当前参数
        schema: 槽位清单（可选）

    Returns:
        {"action": str, "updated_params": dict}
        action可为: "confirm", "modify", "reject"
    """
    logger.info(f"Parsing user modifications: {user_input[:50]}...")

    # 尝试LLM解析
    try:
        result = _parse_with_llm(user_input, current_params)
        logger.info(f"LLM parsing succeeded: action={result['action']}")
        return result

    except Exception as e:
        logger.warning(f"LLM parsing failed: {e}, using fallback")

        # 兜底：简单规则匹配
        result = parse_user_modifications_fallback(user_input, current_params)
        logger.info(f"Fallback parsing result: action={result['action']}")
        return result


@retry_on_failure(max_retries=1, delay_seconds=0.5, backoff_factor=1.0)
def _parse_with_llm(user_input: str, current_params: dict) -> dict:
    """LLM解析（内部函数，带重试）"""
    current_params_str = json.dumps(current_params, ensure_ascii=False, indent=2)

    prompt = MODIFICATION_PROMPT.format(
        current_params=current_params_str,
        user_input=user_input
    )

    result = call_llm_structured(
        prompt=prompt,
        system_prompt="你是参数修改助手。",
        temperature=LOW_TEMP,
        timeout=DEFAULT_TIMEOUT
    )

    # 验证返回格式
    if "action" not in result or "updated_params" not in result:
        raise ValueError("Missing required keys in response")

    return result


def parse_user_modifications_fallback(user_input: str, current_params: dict) -> dict:
    """
    LLM失败时的简单兜底逻辑
    """
    user_input_lower = user_input.strip().lower()

    # 确认关键词
    if any(kw in user_input_lower for kw in ["确认", "ok", "没问题", "可以", "继续", "yes"]):
        return {"action": "confirm", "updated_params": current_params}

    # 拒绝关键词
    if any(kw in user_input_lower for kw in ["拒绝", "重新", "不对", "取消", "no"]):
        return {"action": "reject", "updated_params": {}}

    # 默认视为修改（但无法解析具体内容，保持原参数）
    logger.warning("Unable to parse modification, treating as confirm")
    return {"action": "modify", "updated_params": current_params}
