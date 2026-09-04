"""意图澄清子图主模块"""

import logging
from langgraph.graph import StateGraph, END

from .state import IntentClarificationState
from .nodes import (
    initial_parse,
    polite_reject,
    greeting_handler,
    ask_entity,
    handle_failure,
    ask_properties,
    final_confirm
)
from .routes import (
    route_after_initial_parse,
    route_after_ask_properties,
    route_after_final_confirm,
)
from .config import config

logger = logging.getLogger(__name__)


def create_intent_clarification_subgraph(checkpointer=None) -> StateGraph:
    """
    创建意图澄清子图（极简版）

    Phase 4c: checkpointer 可选 —— HITL（interrupt）需要 checkpointer，
    主图经 config 传入共享实例（thread_id 隔离会话）。

    Returns:
        StateGraph: 编译后的图对象
    """
    logger.info("[create_intent_clarification_subgraph] 开始创建子图")

    # 1. 创建 StateGraph
    graph = StateGraph(IntentClarificationState)

    # 2. 添加所有节点
    graph.add_node("initial_parse", initial_parse)
    graph.add_node("polite_reject", polite_reject)
    graph.add_node("greeting_handler", greeting_handler)
    graph.add_node("ask_entity", ask_entity)
    graph.add_node("handle_failure", handle_failure)
    graph.add_node("ask_properties", ask_properties)
    graph.add_node("final_confirm", final_confirm)

    logger.debug("[create_intent_clarification_subgraph] 已添加所有节点")

    # 3. 设置入口点
    graph.set_entry_point("initial_parse")

    # 4. 添加条件边

    # 路由 1: initial_parse 后的多路分支
    graph.add_conditional_edges(
        "initial_parse",
        route_after_initial_parse,
        {
            "polite_reject": "polite_reject",
            "greeting_handler": "greeting_handler",
            "exit": END,
            "ask_entity": "ask_entity",
            "handle_failure": "handle_failure",
            "ask_properties": "ask_properties",
            "final_confirm": "final_confirm"
        }
    )

    # 路由 2: final_confirm 后的分支
    graph.add_conditional_edges(
        "final_confirm",
        route_after_final_confirm,
        {
            "success": END,
            "modify": "initial_parse",
            "cancel": END
        }
    )

    logger.debug("[create_intent_clarification_subgraph] 已添加条件边")

    # 5. 添加固定边
    graph.add_edge("polite_reject", END)
    graph.add_edge("greeting_handler", "initial_parse")
    graph.add_edge("ask_entity", "initial_parse")
    graph.add_edge("handle_failure", END)

    # 路由 3: ask_properties 答复就地解读后的分支（2026-09-03 方向1：
    # 不再固定回 initial_parse 全量重分类 —— "全部"/回车等澄清答复
    # 曾被 classify_query_type 误判 invalid 导致整次查询 polite_reject 失败）
    graph.add_conditional_edges(
        "ask_properties",
        route_after_ask_properties,
        {
            "confirm": "final_confirm",
            "reask": "ask_properties",
            "cancel": END,
        }
    )

    logger.debug("[create_intent_clarification_subgraph] 已添加固定边")

    # 6. 编译图
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info("[create_intent_clarification_subgraph] 子图创建完成")
    return compiled_graph
