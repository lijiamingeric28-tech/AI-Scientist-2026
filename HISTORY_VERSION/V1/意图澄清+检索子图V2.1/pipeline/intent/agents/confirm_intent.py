"""
Agent C: Confirm_Intent

职责：展示参数确认表单，支持确认/修改/拒绝，更新参数后放行
"""
from typing import Optional
from state.intent_state import IntentClarificationState
from tools.confirm_intent import (
    format_confirmation_display,
    parse_user_modifications,
    parse_user_modifications_fallback
)
import logging

logger = logging.getLogger(__name__)


def confirm_intent(state: IntentClarificationState) -> IntentClarificationState:
    """
    Agent C: Confirm_Intent

    职责：展示参数确认表单，支持确认/修改/拒绝，更新参数后放行

    Args:
        state: 意图澄清State

    Returns:
        更新后的State
    """
    # ===== Node 1: Prepare Display =====
    logger.info("[Node 1] Preparing confirmation display")

    extracted_parameters = state["extracted_parameters"]
    compromise_flag = state.get("compromise_flag", False)
    original_query = state["original_query"]
    dynamic_task_schema = state.get("dynamic_task_schema")

    # 格式化展示文本
    display_text = format_confirmation_display(
        params=extracted_parameters,
        compromise_flag=compromise_flag,
        original_query=original_query,
        schema=dynamic_task_schema
    )
    logger.debug(f"Display text generated:\n{display_text}")

    # ===== Node 2: Interrupt & Wait =====
    logger.info("[Node 2] Interrupting for user confirmation")

    # 检查是否为自动确认模式（非交互式测试）
    auto_confirm = state.get("auto_confirm", False)

    if auto_confirm:
        logger.info("Auto-confirm mode enabled, skipping user input")
        user_input = "确认"
    else:
        # 终端模式：打印展示内容并接收用户输入
        print("\n" + "="*60)
        print(display_text)
        print("="*60)

        logger.info("Waiting for user confirmation...")
        print("\n>>> 请输入您的操作（确认/修改/拒绝）：", end=" ")

        user_input = input()
        user_input = user_input.strip()
        logger.info(f"User input received: {user_input}")

    # ===== Node 3: Parse & Update State =====
    logger.info("[Node 3] Parsing user modifications")

    # 解析用户输入
    result = None
    try:
        result = parse_user_modifications(
            user_input=user_input,
            current_params=extracted_parameters,
            schema=dynamic_task_schema
        )
        logger.info(f"Parsed result: action={result['action']}")
    except Exception as e:
        logger.warning(f"Parse failed: {e}, using fallback")
        result = parse_user_modifications_fallback(user_input, extracted_parameters)

    action = result["action"]
    updated_params = result["updated_params"]

    # 根据action更新State
    if action == "confirm":
        logger.info("User confirmed parameters without modification")
        state["extracted_parameters"] = extracted_parameters  # 保持原参数
        state["user_confirmed"] = True
        # 设置最终的clarified_intent
        state["clarified_intent"] = extracted_parameters

    elif action == "modify":
        logger.info(f"User modified parameters: {updated_params}")
        state["extracted_parameters"] = updated_params
        state["user_confirmed"] = True
        # 设置最终的clarified_intent
        state["clarified_intent"] = updated_params

    elif action == "reject":
        logger.warning("User rejected the query")
        state["user_confirmed"] = False
        # 拒绝时也设置空的clarified_intent
        state["clarified_intent"] = {
            "entities": [],
            "properties": [],
            "conditions": {}
        }

    else:
        logger.error(f"Unknown action: {action}, treating as confirm")
        state["user_confirmed"] = True
        state["clarified_intent"] = extracted_parameters

    logger.info(f"[Agent C] Setting clarified_intent: {state.get('clarified_intent')}")
    logger.info("Agent C completed, exiting intent clarification sub-graph")
    return state
