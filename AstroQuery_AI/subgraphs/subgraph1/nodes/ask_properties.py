"""询问性质列表节点"""

import logging
from datetime import datetime

from langgraph.types import interrupt

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def ask_properties(state: IntentClarificationState) -> IntentClarificationState:
    """
    询问性质列表节点
    当天体名称已提取，但性质列表为空时，主动询问用户想查询哪些性质

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    target_entity = state.get("target_entity", "该天体")
    logger.info(f"[ask_properties] 询问 {target_entity} 的性质")

    question = f"""
您想查询 {target_entity} 的哪些物理性质？

您可以：
1. 输入具体性质名称（例如："距离和红移"）
2. 输入 "全部" 或 "所有" 查询所有可用性质
3. 直接按回车键跳过，我们将返回所有可用数据

请输入：
"""

    # Phase 4c: input() → interrupt()（LangGraph HITL）
    user_input = interrupt({
        "type": "ask_properties",
        "title": "选择查询性质",  # Web 结构化（契约 D3-2/D5-2）
        "text": f"\n{config.ui['separator']}\n{question}\n{config.ui['separator']}\n\n您的选择：",
        "question": question,
        "target_entity": target_entity,
    })
    if user_input is None:
        user_input = ""
    user_input = str(user_input).strip()
    logger.debug(f"[ask_properties] 用户输入: {user_input}")

    # 更新对话历史
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": question,
        "timestamp": datetime.now().isoformat()
    })
    chat_history.append({
        "role": "user",
        "content": user_input if user_input else "[直接回车]",
        "timestamp": datetime.now().isoformat()
    })

    state["chat_history"] = chat_history

    # 标记已询问过性质
    state["properties_asked"] = True

    logger.info("[ask_properties] 询问完成")
    return state
