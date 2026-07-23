"""
意图评估节点 - Agent A

职责：
    动态生成槽位检查清单，提取参数，判断完整性，决策路由

处理流程：
    Node 1: Schema Planning - 动态生成槽位检查清单
    Node 2: Parameter Extraction - 从查询和对话历史提取参数
    Node 3: Slot Completeness Verification - 检查必填项是否完整
    Node 4: Decision Routing - 决定路由（放行/追问/熔断填充）

输入State字段：
    - original_query: 用户原始查询
    - query_context: 查询上下文配置（可选）
    - _chat_history: 对话历史
    - _clarification_turns: 当前追问轮次
    - _dynamic_task_schema: 动态槽位检查清单（可选）
    - extracted_parameters: 当前已提取参数（可选）

输出State字段：
    - _dynamic_task_schema: 动态槽位检查清单
    - extracted_parameters: 已提取的结构化参数
    - _is_clear: 意图是否已完全澄清
    - compromise_flag: 是否包含AI强制推测的参数
    - _missing_slots: 缺失的必填项列表
"""

from typing import Dict, Any
import logging

from subgraphs.intent_clarification.state import IntentState
from subgraphs.intent_clarification.tools.evaluate_intent import (
    generate_schema,
    extract_parameters,
    check_completeness,
    force_fill_missing_slots
)
from config.constants import DEFAULT_SCHEMA

logger = logging.getLogger(__name__)


def evaluate_intent_node(state: IntentState) -> Dict[str, Any]:
    """
    意图评估节点（Agent A）

    职责：
        动态生成schema、提取参数、判断完整性、决策路由

    Args:
        state: 当前State

    Returns:
        需要更新的State字段字典
    """
    # ===== 读取输入 =====
    original_query = state["original_query"]
    query_context = state.get("query_context", {})
    chat_history = state.get("_chat_history", [])
    clarification_turns = state.get("_clarification_turns", 0)
    dynamic_task_schema = state.get("_dynamic_task_schema")
    extracted_parameters = state.get("extracted_parameters", {})

    logger.info("=" * 70)
    logger.info("[Agent A] Starting intent evaluation")
    logger.info(f"Query: {original_query}")
    logger.info(f"Clarification turns: {clarification_turns}")

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
        is_clear = True
        compromise_flag = False
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

        is_clear = True
        compromise_flag = True
        logger.info("Forced completion with compromise flag")

    else:
        # 未填满且未达最大轮次 -> 路由到Agent B
        is_clear = False
        compromise_flag = False
        logger.info(f"Missing slots: {missing_slots}, routing to Agent B")

    # ===== 返回更新 =====
    result = {
        "_dynamic_task_schema": dynamic_task_schema,
        "extracted_parameters": extracted_parameters,
        "_is_clear": is_clear,
        "compromise_flag": compromise_flag,
        "_missing_slots": missing_slots
    }

    logger.info("[Agent A] Intent evaluation completed")
    logger.info(f"Result: is_clear={is_clear}, compromise={compromise_flag}")
    logger.info("=" * 70)

    return result
