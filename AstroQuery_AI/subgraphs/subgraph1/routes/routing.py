"""路由函数模块"""

import logging
from typing import Literal

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def route_after_initial_parse(state: IntentClarificationState) -> Literal[
    "polite_reject", "greeting_handler", "exit",
    "ask_entity", "handle_failure", "ask_properties", "final_confirm"
]:
    """
    initial_parse 后的路由决策

    Args:
        state: 当前状态

    Returns:
        str: 下一个节点名称
    """
    query_type = state.get("query_type", "astronomical")
    target_entity = state.get("target_entity")
    turns = state.get("clarification_turns", 0)
    properties_asked = state.get("properties_asked", False)
    requested_properties = state.get("requested_properties", [])

    logger.debug(f"[route_after_initial_parse] query_type={query_type}, "
                 f"target_entity={target_entity}, turns={turns}, "
                 f"properties_asked={properties_asked}")

    # M7 fix: 非天文查询优先 — greeting/invalid 特例排在 final_confirm 捷径之前,
    # 否则用户在 ask_properties 回复"你好"会被误送去确认流程 (寒暄永不响应)
    # 1. 非天文查询
    if query_type == "invalid":
        logger.info("[route_after_initial_parse] 路由到 polite_reject")
        return "polite_reject"

    # 2. 寒暄
    if query_type == "greeting":
        logger.info("[route_after_initial_parse] 路由到 greeting_handler")
        return "greeting_handler"

    # 3. 退出意图
    if query_type == "exit":
        logger.info("[route_after_initial_parse] 路由到 exit")
        return "exit"

    # 特殊情况：如果已经询问过性质且有天体名称，直接进入确认
    # 这是为了处理用户在ask_properties中直接回车的情况 (仅天文查询时生效)
    if target_entity and properties_asked:
        logger.info("[route_after_initial_parse] 已有天体且已询问性质，路由到 final_confirm")
        return "final_confirm"

    # 4. 天文查询
    if query_type == "astronomical":
        # 4.1 缺少天体名称
        if not target_entity:
            if turns < config.clarification['max_turns']:
                logger.info(f"[route_after_initial_parse] 路由到 ask_entity (轮次 {turns})")
                return "ask_entity"
            else:
                logger.info("[route_after_initial_parse] 路由到 handle_failure (超过最大轮次)")
                return "handle_failure"

        # 4.2 天体名称存在，检查性质列表
        if not requested_properties and not properties_asked:
            logger.info("[route_after_initial_parse] 路由到 ask_properties")
            return "ask_properties"

        # 4.3 天体名称存在，性质列表已处理
        logger.info("[route_after_initial_parse] 路由到 final_confirm")
        return "final_confirm"

    # 默认
    logger.warning("[route_after_initial_parse] 默认路由到 ask_entity")
    return "ask_entity"


def route_after_ask_properties(state: IntentClarificationState) -> Literal[
    "confirm", "reask", "cancel"
]:
    """
    ask_properties 答复解读后的路由（2026-09-03 方向1：答复就地解读，
    不再回 initial_parse 全量重分类 —— 修复"全部"/回车被误判 invalid 杀死任务）。

    Args:
        state: 当前状态（ask_properties 已设置 properties_resolved /
               clarification_status）

    Returns:
        str: "confirm" → final_confirm | "reask" → ask_properties | "cancel" → END
    """
    # 澄清轮内显式取消（算了/不查了/取消…）→ 优雅终止
    if state.get("clarification_status") == "cancelled":
        logger.info("[route_after_ask_properties] 用户取消，路由到 END")
        return "cancel"

    if state.get("properties_resolved"):
        logger.info("[route_after_ask_properties] 性质已确定，路由到 final_confirm")
        return "confirm"

    turns = state.get("clarification_turns", 0)
    logger.info(f"[route_after_ask_properties] 答复未解析，重问性质 (轮次 {turns})")
    return "reask"


def route_after_final_confirm(state: IntentClarificationState) -> Literal[
    "success", "modify", "cancel"
]:
    """
    final_confirm 后的路由决策

    Args:
        state: 当前状态

    Returns:
        str: 下一个节点名称或结束状态
    """
    clarification_status = state.get("clarification_status", "confirmed")

    logger.debug(f"[route_after_final_confirm] clarification_status={clarification_status}")

    if clarification_status == "confirmed":
        logger.info("[route_after_final_confirm] 路由到 success (END)")
        return "success"
    elif clarification_status == "modified":
        logger.info("[route_after_final_confirm] 路由到 modify (initial_parse)")
        return "modify"
    else:  # "cancelled"
        logger.info("[route_after_final_confirm] 路由到 cancel (END)")
        return "cancel"
