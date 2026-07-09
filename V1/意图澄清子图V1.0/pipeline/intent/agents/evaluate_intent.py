"""
Agent A: Evaluate_Intent_Agent

职责：动态生成槽位检查清单，提取参数，判断完整性，决策路由
"""
from typing import Optional
from state.intent_state import IntentClarificationState
from tools.evaluate_intent import (
    generate_schema,
    extract_parameters,
    check_completeness,
    force_fill_missing_slots
)
from configs.constants import DEFAULT_SCHEMA
import logging

logger = logging.getLogger(__name__)


def evaluate_intent_agent(state: IntentClarificationState) -> IntentClarificationState:
    """
    Agent A: Evaluate_Intent_Agent

    职责：动态生成槽位检查清单，提取参数，判断完整性，决策路由

    Args:
        state: 意图澄清State

    Returns:
        更新后的State
    """
    # 读取输入
    original_query = state["original_query"]
    query_context = state.get("query_context", {})
    chat_history = state.get("chat_history", [])
    clarification_turns = state.get("clarification_turns", 0)
    dynamic_task_schema = state.get("dynamic_task_schema")
    extracted_parameters = state.get("extracted_parameters", {})

    # ===== Node 1: Schema Planning =====
    logger.info("[Node 1] Starting Schema Planning")

    if dynamic_task_schema is None:
        try:
            domain = query_context.get("domain", "general")
            dynamic_task_schema = generate_schema(
                query=original_query,
                domain=domain
            )
            logger.info(f"Generated schema: {dynamic_task_schema}")
        except Exception as e:
            logger.error(f"Schema generation failed: {e}")
            dynamic_task_schema = DEFAULT_SCHEMA
            logger.warning("Using default schema as fallback")

    # ===== Node 2: Parameter Extraction =====
    logger.info("[Node 2] Starting Parameter Extraction")

    try:
        extracted_parameters = extract_parameters(
            query=original_query,
            chat_history=chat_history,
            schema=dynamic_task_schema,
            current_params=extracted_parameters
        )
        logger.info(f"Extracted parameters: {extracted_parameters}")
    except Exception as e:
        logger.error(f"Parameter extraction failed: {e}")
        # 保持原有参数不变

    # ===== Node 3: Slot Completeness Verification =====
    logger.info("[Node 3] Starting Completeness Check")

    is_complete, missing_slots = check_completeness(
        schema=dynamic_task_schema,
        params=extracted_parameters
    )
    logger.info(f"Completeness check: is_complete={is_complete}, missing={missing_slots}")

    # ===== Node 4: Decision Routing =====
    logger.info("[Node 4] Starting Decision Routing")

    if is_complete:
        # 全部填满 -> 放行
        state["is_clear"] = True
        state["compromise_flag"] = False
        logger.info("Intent is clear, routing to Agent C")

    elif clarification_turns >= 3:
        # 未填满但已达最大轮次 -> 强制填充
        try:
            extracted_parameters = force_fill_missing_slots(
                query=original_query,
                schema=dynamic_task_schema,
                current_params=extracted_parameters,
                missing_slots=missing_slots
            )
            logger.warning(f"Force filled parameters: {extracted_parameters}")
        except Exception as e:
            logger.error(f"Force fill failed: {e}, using defaults")
            # 使用空值或默认值填充
            for slot in missing_slots:
                if slot not in extracted_parameters:
                    extracted_parameters[slot] = []

        state["is_clear"] = True
        state["compromise_flag"] = True
        logger.info("Forced completion with compromise flag")

    else:
        # 未填满且未达最大轮次 -> 路由到Agent B
        state["missing_slots"] = missing_slots
        state["is_clear"] = False
        logger.info(f"Missing slots: {missing_slots}, routing to Agent B")

    # 写入输出
    state["dynamic_task_schema"] = dynamic_task_schema
    state["extracted_parameters"] = extracted_parameters

    return state
