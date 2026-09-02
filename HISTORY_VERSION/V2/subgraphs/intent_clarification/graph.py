"""
意图澄清子图 - Graph定义

职责：
    组装意图澄清子图的所有节点和边，定义拓扑结构和路由逻辑

拓扑结构：
    START → evaluate_intent → [条件路由] → ask_user_guided ⇄ evaluate_intent
                                        └→ confirm_intent → END

节点说明：
    - evaluate_intent (Agent A): 动态生成schema、提取参数、判断完整性
    - ask_user_guided (Agent B): 生成追问、等待用户回答、更新对话历史
    - confirm_intent (Agent C): 展示确认表单、解析用户操作、设置最终输出

路由逻辑：
    - evaluate_intent之后：
      - 如果_is_clear=True → 路由到confirm_intent
      - 如果_is_clear=False → 路由到ask_user_guided
    - ask_user_guided之后：固定路由回evaluate_intent（形成追问循环）
    - confirm_intent之后：固定路由到END（退出子图）

循环控制：
    - 最大追问轮次：3次（由MAX_CLARIFICATION_TURNS控制）
    - 熔断机制：在evaluate_intent内部，当turns >= 3时强制设置_is_clear=True
"""

from langgraph.graph import StateGraph, END
import logging

from subgraphs.intent_clarification.state import IntentState
from subgraphs.intent_clarification.nodes import (
    evaluate_intent_node,
    ask_user_node,
    confirm_intent_node
)

logger = logging.getLogger(__name__)


def route_after_evaluate(state: IntentState) -> str:
    """
    Agent A（evaluate_intent）执行后的路由决策

    决策逻辑：
        1. 如果_is_clear=True → 流向confirm_intent（Agent C）
        2. 如果_is_clear=False → 流向ask_user_guided（Agent B）

    注意：
        - 熔断逻辑在Agent A内部处理（turns >= 3时强制设置_is_clear=True）
        - 此路由函数仅读取_is_clear标志位，不做额外判断

    Args:
        state: 当前State

    Returns:
        "ask" 或 "confirm"
    """
    is_clear = state.get("_is_clear", False)

    if is_clear:
        logger.info("Routing to confirm_intent (Agent C)")
        return "confirm"
    else:
        logger.info("Routing to ask_user_guided (Agent B)")
        return "ask"


def create_intent_clarification_graph() -> StateGraph:
    """
    创建意图澄清子图

    拓扑结构：
        START
          ↓
        evaluate_intent (Agent A)
          ↓
        [条件路由]
          ├─→ _is_clear=False → ask_user_guided (Agent B) → 回到 evaluate_intent
          └─→ _is_clear=True → confirm_intent (Agent C) → END

    循环控制：
        - A ⇄ B 形成追问循环
        - 最大循环次数：3次（由_clarification_turns控制）
        - 熔断机制：turns >= 3时，Agent A强制设置_is_clear=True

    Returns:
        未编译的StateGraph对象
    """
    logger.info("Creating intent clarification graph")

    # 初始化StateGraph
    graph = StateGraph(IntentState)

    # 添加节点（3个Agent）
    graph.add_node("evaluate_intent", evaluate_intent_node)
    graph.add_node("ask_user_guided", ask_user_node)
    graph.add_node("confirm_intent", confirm_intent_node)

    # 设置入口
    graph.set_entry_point("evaluate_intent")

    # 添加条件边：evaluate_intent的路由逻辑
    graph.add_conditional_edges(
        "evaluate_intent",
        route_after_evaluate,
        {
            "ask": "ask_user_guided",      # _is_clear=False → 追问
            "confirm": "confirm_intent"    # _is_clear=True → 确认
        }
    )

    # 添加固定边：ask_user_guided → evaluate_intent（形成循环）
    graph.add_edge("ask_user_guided", "evaluate_intent")

    # 添加固定边：confirm_intent → END（退出子图）
    graph.add_edge("confirm_intent", END)

    logger.info("Intent clarification graph created successfully")

    return graph


def compile_intent_clarification_graph():
    """
    编译意图澄清子图

    Returns:
        编译后的可执行Graph对象
    """
    logger.info("Compiling intent clarification graph")
    compiled_graph = create_intent_clarification_graph().compile()
    logger.info("Intent clarification graph compiled successfully")
    return compiled_graph


# 兼容旧的函数名
create_intent_graph = create_intent_clarification_graph
compile_intent_graph = compile_intent_clarification_graph
