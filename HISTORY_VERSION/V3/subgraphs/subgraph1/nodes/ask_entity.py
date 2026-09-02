"""追问天体名称节点"""

import logging
from datetime import datetime

from langgraph.types import interrupt

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def ask_entity(state: IntentClarificationState) -> IntentClarificationState:
    """
    追问天体名称节点
    当 target_entity 缺失时，主动追问用户想查询的天体名称

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    turns = state.get("clarification_turns", 0)
    logger.info(f"[ask_entity] 第 {turns + 1} 次追问天体名称")

    # 根据轮次调整追问文本
    if turns == 0:
        question = """
请告诉我您想查询哪个天体的信息？

您可以使用以下任何形式的名称：
- 梅西耶编号：M31, M87
- NGC 编号：NGC 224, NGC 4486
- 通俗名称：仙女座星系, 室女A星系
- 星表标识符：Gaia DR3 5854013331201520640
- 其他别名：Andromeda Galaxy

示例查询：
- "M31的距离"
- "仙女座星系的红移和金属丰度"
- "Gaia DR3 5854013331201520640"
"""
    elif turns == 1:
        question = """
抱歉，我还没有识别到天体名称。

请直接输入天体的名称或编号，例如：
- M31
- 仙女座星系
- NGC 224
- Gaia DR3 5854013331201520640
"""
    else:  # turns == 2
        question = """
请再试一次，直接输入天体名称：
（例如：M31 或 NGC 224）
"""

    # Phase 4c: input() → interrupt()（LangGraph HITL，前端可对接）
    # payload 携带完整渲染文本（text）与结构化字段，前端/CLI 自行渲染
    user_input = interrupt({
        "type": "ask_entity",
        "text": f"\n{config.ui['separator']}\n{question}\n{config.ui['separator']}\n\n您的输入：",
        "question": question,
        "turns": turns + 1,
    })
    if user_input is None:
        user_input = ""
    user_input = str(user_input).strip()
    logger.debug(f"[ask_entity] 用户输入: {user_input}")

    # 更新对话历史
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": question,
        "timestamp": datetime.now().isoformat()
    })
    chat_history.append({
        "role": "user",
        "content": user_input,
        "timestamp": datetime.now().isoformat()
    })

    state["chat_history"] = chat_history

    # 递增轮次
    state["clarification_turns"] = turns + 1

    logger.info(f"[ask_entity] 追问完成，当前轮次: {turns + 1}")
    return state
