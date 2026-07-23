"""
意图确认节点 - Agent C

职责：
    展示参数确认表单，支持确认/修改/拒绝，更新参数后放行

处理流程：
    Node 1: Prepare Display - 格式化参数为Markdown表单
    Node 2: Interrupt & Wait - 打印表单并等待用户操作
    Node 3: Parse & Update State - 解析确认/修改/拒绝指令

输入State字段：
    - extracted_parameters: 已提取的结构化参数
    - compromise_flag: 是否包含AI推测
    - original_query: 用户原始查询
    - _dynamic_task_schema: 槽位检查清单（可选）
    - _auto_confirm: 自动确认模式（可选）

输出State字段：
    - extracted_parameters: 可能被用户修改的参数
    - user_confirmed: 用户是否确认最终参数
    - clarified_intent: 最终的澄清后的意图参数
"""

from typing import Dict, Any
import logging

from subgraphs.intent_clarification.state import IntentState
from subgraphs.intent_clarification.tools.confirm_intent import (
    format_confirmation_display,
    parse_user_modifications,
    parse_user_modifications_fallback
)
from config.ui_messages import (
    SEPARATOR_LINE,
    CONFIRM_INPUT_PROMPT
)

logger = logging.getLogger(__name__)


def confirm_intent_node(state: IntentState) -> Dict[str, Any]:
    """
    意图确认节点（Agent C）

    职责：
        展示参数确认表单，支持确认/修改/拒绝，更新参数后放行

    Args:
        state: 当前State

    Returns:
        需要更新的State字段字典
    """
    # ===== Node 1: Prepare Display =====
    logger.info("[Node 1] Preparing confirmation display")

    extracted_parameters = state["extracted_parameters"]
    compromise_flag = state.get("compromise_flag", False)
    original_query = state["original_query"]
    dynamic_task_schema = state.get("_dynamic_task_schema")

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
    auto_confirm = state.get("_auto_confirm", False)

    if auto_confirm:
        logger.info("Auto-confirm mode enabled, skipping user input")
        user_input = "确认"
    else:
        # 终端模式：打印展示内容并接收用户输入
        print("\n" + SEPARATOR_LINE)
        print(display_text)
        print(SEPARATOR_LINE)

        logger.info("Waiting for user confirmation...")
        print(f"\n{CONFIRM_INPUT_PROMPT} ", end="")

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
        final_params = extracted_parameters  # 保持原参数
        user_confirmed = True
        # 设置最终的clarified_intent
        clarified_intent = extracted_parameters

    elif action == "modify":
        logger.info(f"User modified parameters: {updated_params}")
        final_params = updated_params
        user_confirmed = True
        # 设置最终的clarified_intent
        clarified_intent = updated_params

    elif action == "reject":
        logger.warning("User rejected the query")
        final_params = extracted_parameters  # 保持原参数用于记录
        user_confirmed = False
        # 拒绝时设置空的clarified_intent
        clarified_intent = {
            "entities": [],
            "properties": [],
            "conditions": {}
        }

    else:
        logger.error(f"Unknown action: {action}, treating as confirm")
        final_params = extracted_parameters
        user_confirmed = True
        clarified_intent = extracted_parameters

    logger.info(f"[Agent C] Setting clarified_intent: {clarified_intent}")
    logger.info("[Agent C] Confirm intent completed, exiting intent clarification sub-graph")

    # 返回更新
    return {
        "extracted_parameters": final_params,
        "user_confirmed": user_confirmed,
        "clarified_intent": clarified_intent
    }
