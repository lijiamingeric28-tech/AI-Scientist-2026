"""礼貌拒绝节点"""

import logging
from datetime import datetime

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def polite_reject(state: IntentClarificationState) -> IntentClarificationState:
    """
    礼貌拒绝节点
    处理非天文学查询，礼貌拒绝并结束流程

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    logger.info("[polite_reject] 礼貌拒绝非天文查询")

    reject_message = """
抱歉，我只能回答天文学相关的问题。

我可以帮助您查询：
- 恒星、星团、星系、星系团等天体的物理性质
- 例如：距离、红移、金属丰度、光度、质量等

请尝试输入天文学相关的查询。
"""

    print("\n" + config.ui['separator'])
    print(reject_message)
    print(config.ui['separator'])

    # 更新状态
    state["clarification_status"] = "failed"
    state["user_confirmed"] = False

    # 更新对话历史
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": reject_message,
        "timestamp": datetime.now().isoformat()
    })
    state["chat_history"] = chat_history

    logger.info("[polite_reject] 已拒绝非天文查询")
    return state
