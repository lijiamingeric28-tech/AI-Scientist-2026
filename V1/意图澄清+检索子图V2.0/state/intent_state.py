"""
意图澄清子图的State定义（兼容导入）
"""

from typing import TypedDict, Optional, NotRequired


class IntentClarificationState(TypedDict):
    """
    意图澄清子图的State定义

    职责：
    - 存储用户原始查询和上下文
    - 管理追问循环的状态（轮次、对话历史）
    - 存储意图解析的中间结果和最终输出
    - 控制子图内部的路由逻辑
    """

    # ========== 输入字段 ==========
    original_query: str
    """用户的原始自然语言查询，必填"""

    query_context: NotRequired[dict]
    """用户配置，可选"""

    # ========== 工作字段 ==========
    chat_history: NotRequired[list[dict]]
    """AI追问和用户回答的对话历史"""

    clarification_turns: NotRequired[int]
    """当前追问轮次计数器"""

    dynamic_task_schema: NotRequired[Optional[dict]]
    """Agent A动态生成的槽位检查清单"""

    extracted_parameters: NotRequired[dict]
    """已提取的结构化参数"""

    missing_slots: NotRequired[list[str]]
    """Agent A检测出的缺失槽位列表"""

    # ========== 控制字段 ==========
    is_clear: NotRequired[bool]
    """意图是否已完全澄清的标志位"""

    compromise_flag: NotRequired[bool]
    """是否包含AI强制推测的参数"""

    auto_confirm: NotRequired[bool]
    """是否启用自动确认模式（用于非交互式测试）"""

    # ========== 输出字段 ==========
    user_confirmed: NotRequired[bool]
    """用户是否确认最终参数"""

    clarified_intent: NotRequired[dict]
    """最终的澄清后的意图参数"""


# 兼容旧的导入名称
IntentState = IntentClarificationState
