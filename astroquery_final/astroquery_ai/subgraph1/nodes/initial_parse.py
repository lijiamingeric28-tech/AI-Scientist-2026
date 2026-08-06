"""初步解析节点"""

import logging
from datetime import datetime

from ..state import IntentClarificationState
from ..utils import (
    get_latest_user_input,
    classify_query_type,
    extract_entity_and_properties,
    update_chat_history
)

logger = logging.getLogger(__name__)


def initial_parse(state: IntentClarificationState) -> IntentClarificationState:
    """
    初步解析节点

    步骤：
    1. 获取最新用户输入（original_query 或 chat_history 的最后一条）
    2. 检测查询类型（天文/寒暄/退出/无效）
    3. 如果是天文查询，提取 target_entity 和 requested_properties
    4. 更新状态

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    logger.info("[initial_parse] 开始解析用户输入")

    try:
        # Step 1: 获取最新用户输入
        latest_input = get_latest_user_input(state)
        logger.debug(f"[initial_parse] 最新输入: {latest_input}")

        # Step 2: 查询类型分类
        query_type = classify_query_type(latest_input)
        state["query_type"] = query_type
        logger.info(f"[initial_parse] 查询类型: {query_type}")

        # Step 3: 如果是天文查询，提取实体和性质
        if query_type == "astronomical":
            # 调用 LLM 提取 target_entity
            extraction_result = extract_entity_and_properties(
                user_input=latest_input,
                chat_history=state.get("chat_history", [])
            )

            # 更新提取结果
            if extraction_result["target_entity"]:
                state["target_entity"] = extraction_result["target_entity"]
                logger.info(f"[initial_parse] 提取到天体: {extraction_result['target_entity']}")

            if extraction_result["requested_properties"]:
                state["requested_properties"] = extraction_result["requested_properties"]
                logger.info(f"[initial_parse] 提取到性质: {extraction_result['requested_properties']}")

            # 判断是否已澄清
            if state.get("target_entity"):
                state["is_clear"] = True
                logger.info("[initial_parse] 意图已澄清")
            else:
                state["is_clear"] = False
                logger.info("[initial_parse] 意图尚未澄清")

        # Step 4: 更新对话历史
        update_chat_history(state, latest_input)

        return state

    except Exception as e:
        logger.error(f"[initial_parse] 处理失败: {e}")
        # 直接报错退出
        raise
