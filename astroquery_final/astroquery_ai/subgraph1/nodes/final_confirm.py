"""最终确认节点"""

import logging
from datetime import datetime

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def final_confirm(state: IntentClarificationState) -> IntentClarificationState:
    """
    最终确认节点
    展示提取的天体名称和性质列表，让用户确认、修改或取消

    Args:
        state: 当前状态

    Returns:
        IntentClarificationState: 更新后的状态
    """
    target_entity = state.get("target_entity", "未知天体")
    requested_properties = state.get("requested_properties", [])

    logger.info(f"[final_confirm] 确认查询: {target_entity}, {requested_properties}")

    # 格式化展示
    if requested_properties:
        properties_display = ", ".join(requested_properties)
    else:
        properties_display = "所有可用性质"

    confirmation_message = f"""
请确认您的查询信息：

╔════════════════════════════════════════════════╗
║  天体名称：{target_entity:<40} ║
║  查询性质：{properties_display:<40} ║
╚════════════════════════════════════════════════╝

请选择：
  [y] 确认，开始检索
  [m] 修改查询信息
  [n] 取消查询

您的选择：
"""

    print("\n" + config.ui['separator'])
    print(confirmation_message)
    print(config.ui['separator'])
    print("\n请输入 (y/m/n)：", end=" ")

    # 等待用户输入
    user_choice = input().strip().lower()
    logger.debug(f"[final_confirm] 用户选择: {user_choice}")

    # 更新对话历史
    chat_history = state.get("chat_history", [])
    chat_history.append({
        "role": "assistant",
        "content": confirmation_message,
        "timestamp": datetime.now().isoformat()
    })
    chat_history.append({
        "role": "user",
        "content": user_choice,
        "timestamp": datetime.now().isoformat()
    })

    state["chat_history"] = chat_history

    # 处理用户选择
    if user_choice in ["y", "yes", "确认", "是"]:
        state["user_confirmed"] = True
        state["clarification_status"] = "confirmed"
        print("\n✓ 查询信息已确认，正在启动检索流程...\n")
        logger.info("[final_confirm] 用户确认查询")

    elif user_choice in ["m", "modify", "修改"]:
        state["user_confirmed"] = False
        state["clarification_status"] = "modified"
        # 清空状态，重新开始
        state["target_entity"] = None
        state["requested_properties"] = []
        state["clarification_turns"] = 0
        state["properties_asked"] = False
        print("\n↻ 已清空信息，请重新输入查询...\n")
        print("请输入新的查询：", end=" ")

        # 获取用户新的输入
        new_query = input().strip()
        logger.debug(f"[final_confirm] 用户输入新查询: {new_query}")

        # 将新查询添加到对话历史
        chat_history.append({
            "role": "user",
            "content": new_query,
            "timestamp": datetime.now().isoformat()
        })

        logger.info("[final_confirm] 用户选择修改")

    else:  # 取消或其他输入
        state["user_confirmed"] = False
        state["clarification_status"] = "cancelled"
        print("\n✗ 查询已取消。\n")
        logger.info("[final_confirm] 用户取消查询")

    # 复制对话历史到输出字段
    state["conversation_history"] = chat_history.copy()

    return state
