"""
Agent B: Ask_User_Guided

职责：生成引导式追问，挂起等待用户回答，更新对话历史
"""
from typing import Optional
from state.intent_state import IntentClarificationState
from tools.ask_user_guided import (
    generate_clarification_question,
    format_question_for_display,
    parse_user_response
)
import logging

logger = logging.getLogger(__name__)


def ask_user_guided(state: IntentClarificationState) -> IntentClarificationState:
    """
    Agent B: Ask_User_Guided

    职责：生成引导式追问，挂起等待用户回答，更新对话历史

    Args:
        state: 意图澄清State

    Returns:
        更新后的State
    """
    # ===== Node 1: Read Context =====
    logger.info("[Node 1] Reading context for clarification")

    missing_slots = state.get("missing_slots", [])
    dynamic_task_schema = state["dynamic_task_schema"]
    original_query = state["original_query"]
    extracted_parameters = state.get("extracted_parameters", {})
    chat_history = state.get("chat_history", [])
    clarification_turns = state.get("clarification_turns", 0)

    logger.debug(f"Missing slots: {missing_slots}")
    logger.debug(f"Current turn: {clarification_turns}")

    # ===== Node 2: Generate Clarification Question =====
    logger.info("[Node 2] Generating clarification question")

    clarification_data = None
    try:
        clarification_data = generate_clarification_question(
            missing_slots=missing_slots,
            schema=dynamic_task_schema,
            query=original_query,
            current_params=extracted_parameters
        )
        logger.info(f"Generated question: {clarification_data['question']}")
        logger.debug(f"Options: {clarification_data['options']}")

    except Exception as e:
        logger.warning(f"Clarification generation failed: {e}, using fallback")
        # 使用通用追问文本作为兜底
        clarification_data = {
            "question": f"请补充以下信息：{', '.join(missing_slots)}",
            "options": []
        }

    question = clarification_data["question"]
    options = clarification_data["options"]

    # ===== Node 3: Format and Interrupt =====
    logger.info("[Node 3] Formatting question for display and interrupting")

    # 格式化展示文本
    display_text = format_question_for_display(question, options)
    logger.debug(f"Display text:\n{display_text}")

    # 终端模式：打印展示内容并接收用户输入
    print("\n" + "="*60)
    print(display_text)
    print("="*60)

    logger.info("Waiting for user response...")
    print("\n>>> 请输入您的回答：", end=" ")

    # 使用input()直接接收用户输入（终端模式）
    user_input = input()
    user_input = user_input.strip()
    logger.info(f"User input received: {user_input}")

    # ===== Node 4: Parse and Update State =====
    logger.info("[Node 4] Parsing user response and updating state")

    # 解析用户回答
    parsed_response = user_input  # 默认保持原文本
    try:
        parsed_response = parse_user_response(
            user_input=user_input,
            question=question,
            options=options,
            missing_slot=missing_slots[0] if missing_slots else "unknown"
        )
        logger.info(f"Parsed response: {parsed_response}")
    except Exception as e:
        logger.warning(f"Response parsing failed: {e}, using original input")
        # 失败时使用兜底逻辑
        if user_input.isdigit() and options:
            idx = int(user_input) - 1
            if 0 <= idx < len(options):
                parsed_response = options[idx]

    # 更新chat_history（追加AI追问和用户回答）
    chat_history.append({
        "role": "assistant",
        "content": display_text
    })
    chat_history.append({
        "role": "user",
        "content": parsed_response
    })
    logger.debug(f"Updated chat_history, total messages: {len(chat_history)}")

    # 递增追问轮次
    clarification_turns += 1
    logger.info(f"Clarification turns incremented to: {clarification_turns}")

    # 写入State
    state["chat_history"] = chat_history
    state["clarification_turns"] = clarification_turns

    logger.info("Agent B completed, routing back to Agent A")
    return state
