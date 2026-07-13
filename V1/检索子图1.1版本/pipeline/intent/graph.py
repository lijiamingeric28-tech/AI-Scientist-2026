"""
意图澄清子图的Graph组装
"""
from langgraph.graph import StateGraph, END
from state.intent_state import IntentClarificationState
from pipeline.intent.agents.evaluate_intent import evaluate_intent_agent
from pipeline.intent.agents.ask_user_guided import ask_user_guided
from pipeline.intent.agents.confirm_intent import confirm_intent
import logging

logger = logging.getLogger(__name__)


def route_after_evaluate(state: IntentClarificationState) -> str:
    """
    Agent A（evaluate_intent）执行后的路由决策

    决策逻辑：
    1. 如果is_clear=True → 流向confirm_intent（Agent C）
    2. 如果is_clear=False → 流向ask_user_guided（Agent B）

    注意：
    - 熔断逻辑在Agent A内部处理（turns >= 3时强制设置is_clear=True）
    - 此路由函数仅读取is_clear标志位，不做额外判断

    Args:
        state: 当前State

    Returns:
        "ask" 或 "confirm"
    """
    is_clear = state.get("is_clear", False)

    if is_clear:
        logger.info("Routing to confirm_intent (Agent C)")
        return "confirm"
    else:
        logger.info("Routing to ask_user_guided (Agent B)")
        return "ask"


def create_intent_clarification_graph():
    """
    创建意图澄清子图

    拓扑结构：
        START
          ↓
        evaluate_intent (Agent A)
          ↓
        [条件路由]
          ├─→ is_clear=False → ask_user_guided (Agent B) → 回到 evaluate_intent
          └─→ is_clear=True → confirm_intent (Agent C) → END

    循环控制：
        - A ⇄ B 形成追问循环
        - 最大循环次数：3次（由clarification_turns控制）
        - 熔断机制：turns >= 3时，Agent A强制设置is_clear=True

    Returns:
        编译后的StateGraph
    """
    logger.info("Creating intent clarification graph")

    # 初始化StateGraph
    graph = StateGraph(IntentClarificationState)

    # 添加节点（3个Agent）
    graph.add_node("evaluate_intent", evaluate_intent_agent)
    graph.add_node("ask_user_guided", ask_user_guided)
    graph.add_node("confirm_intent", confirm_intent)

    # 设置入口
    graph.set_entry_point("evaluate_intent")

    # 添加条件边：evaluate_intent的路由逻辑
    graph.add_conditional_edges(
        "evaluate_intent",
        route_after_evaluate,
        {
            "ask": "ask_user_guided",      # is_clear=False → 追问
            "confirm": "confirm_intent"    # is_clear=True → 确认
        }
    )

    # 添加固定边：ask_user_guided → evaluate_intent（形成循环）
    graph.add_edge("ask_user_guided", "evaluate_intent")

    # 添加固定边：confirm_intent → END（退出子图）
    graph.add_edge("confirm_intent", END)

    # 编译图
    compiled_graph = graph.compile()

    logger.info("Intent clarification graph created successfully")

    return compiled_graph
