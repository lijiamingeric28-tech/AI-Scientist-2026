"""寒暄处理节点"""

import logging
from datetime import datetime

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def greeting_handler(state: IntentClarificationState) -> IntentClarificationState:
    """
    寒暄处理节点
    响应用户寒暄，引导用户输入天文学查询

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    logger.info("[greeting_handler] 处理寒暄")

    greeting_response = """
你好！我是天文查询智能助手 AstroQuery AI。

我可以帮您查询天体的物理性质，例如：
- 恒星：温度、光度、金属丰度、视差等
- 星系：距离、红移、形态、质量等
- 星团：年龄、成员数量、空间分布等

请告诉我您想查询哪个天体的信息？
（例如：M31的距离和红移）
"""

    print("\n" + config.ui['separator'])
    print(greeting_response)
    print(config.ui['separator'])
    print("\n请输入您的查询：", end=" ")

    # 等待用户输入
    user_input = input().strip()
    logger.debug(f"[greeting_handler] 用户输入: {user_input}")

    # 更新对话历史
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": greeting_response,
        "timestamp": datetime.now().isoformat()
    })
    chat_history.append({
        "role": "user",
        "content": user_input,
        "timestamp": datetime.now().isoformat()
    })

    state["chat_history"] = chat_history

    logger.info("[greeting_handler] 寒暄处理完成")
    return state
