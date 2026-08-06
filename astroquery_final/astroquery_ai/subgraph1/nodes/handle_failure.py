"""失败处理节点"""

import logging
from datetime import datetime

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def handle_failure(state: IntentClarificationState) -> IntentClarificationState:
    """
    失败处理节点
    处理3轮追问后仍无法提取天体名称的情况

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    logger.info("[handle_failure] 处理澄清失败")

    failure_message = """
抱歉，经过多次尝试，我仍然无法识别您想查询的天体。

可能的原因：
1. 天体名称格式不标准或存在拼写错误
2. 该天体可能不在我们的数据库中
3. 输入的信息不够具体

建议：
- 使用标准天体编号（如 M31, NGC 224）
- 检查拼写是否正确
- 提供更多上下文信息

您可以稍后重新尝试查询。
"""

    print("\n" + config.ui['separator'])
    print(failure_message)
    print(config.ui['separator'])

    # 更新状态
    state["clarification_status"] = "failed"
    state["user_confirmed"] = False

    # 更新对话历史
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": failure_message,
        "timestamp": datetime.now().isoformat()
    })
    state["chat_history"] = chat_history

    logger.info("[handle_failure] 已标记为失败")
    return state
