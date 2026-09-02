"""
意图澄清子图的State定义
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

    # ========== 输入字段（从上游或用户传入） ==========
    original_query: str
    """用户的原始自然语言查询，必填"""

    query_context: NotRequired[dict]
    """
    用户配置，可选
    示例：{"mode": "precision", "domain": "materials_science"}
    默认：{}
    """

    # ========== 工作字段（子图内部使用） ==========
    chat_history: NotRequired[list[dict]]
    """
    AI追问和用户回答的对话历史
    格式：[{"role": "user"|"assistant", "content": "..."}]
    默认：[]
    """

    clarification_turns: NotRequired[int]
    """
    当前追问轮次计数器，用于触发熔断机制
    范围：0 <= turns <= 3
    默认：0
    """

    dynamic_task_schema: NotRequired[Optional[dict]]
    """
    Agent A动态生成的槽位检查清单
    格式：{"entities": {...}, "properties": {...}, "conditions": {...}}
    默认：None（首轮生成）
    """

    extracted_parameters: NotRequired[dict]
    """
    已提取的结构化参数（累积更新）
    格式：{"entities": [...], "properties": [...], "conditions": {...}}
    默认：{}
    """

    missing_slots: NotRequired[list[str]]
    """
    Agent A检测出的缺失槽位列表，传递给Agent B
    示例：["properties", "conditions"]
    默认：[]
    """

    # ========== 控制字段（用于路由决策） ==========
    is_clear: NotRequired[bool]
    """
    意图是否已完全澄清的标志位
    - True: 流向Agent C（Confirm_Intent）
    - False: 流向Agent B（Ask_User_Guided）
    默认：False
    """

    compromise_flag: NotRequired[bool]
    """
    是否包含AI强制推测的参数（兜底标记）
    - True: 提示用户部分参数为AI推测
    - False: 所有参数均为用户明确提供或从查询中提取
    默认：False
    """

    # ========== 输出字段（传递给下游子图） ==========
    user_confirmed: NotRequired[bool]
    """
    用户是否确认最终参数（Agent C设置）
    - True: 用户确认或修改后接受
    - False: 用户拒绝，下游应终止流程
    默认：False
    """
