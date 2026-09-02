"""
意图澄清子图 State定义

职责：
    定义意图澄清子图的State结构

用法：
    from subgraphs.intent_clarification.state import IntentState

State字段：
    - original_query: 用户输入
    - extracted_parameters: 提取的结构化参数
    - compromise_flag: 是否包含AI推测
    - clarified_intent: 最终澄清后的意图（输出给主图）
    - user_confirmed: 用户是否确认参数
"""

from typing import TypedDict, Optional, List, Dict, Any
from typing_extensions import Annotated


class IntentState(TypedDict, total=False):
    """
    意图澄清子图State

    Input Fields (从主图接收):
        original_query: 用户原始查询（必填）
        query_context: 查询上下文配置（可选）

    Output Fields (传递给主图):
        extracted_parameters: 结构化参数
        compromise_flag: 是否包含AI推测
        clarified_intent: 最终澄清后的意图参数
        user_confirmed: 用户是否确认最终参数

    Internal Fields (子图内部使用，下划线前缀):
        _chat_history: 追问历史
        _clarification_turns: 追问次数
        _dynamic_task_schema: 动态槽位检查清单
        _is_clear: 意图是否已完全澄清
        _missing_slots: 缺失的槽位列表
        _auto_confirm: 自动确认模式（测试用）
    """

    # === Input ===
    original_query: str
    query_context: Optional[Dict[str, Any]]

    # === Output ===
    extracted_parameters: Dict[str, Any]
    compromise_flag: bool
    clarified_intent: Dict[str, Any]
    user_confirmed: bool

    # === Internal ===
    _chat_history: List[Dict[str, str]]
    _clarification_turns: int
    _dynamic_task_schema: Optional[Dict[str, Any]]
    _is_clear: bool
    _missing_slots: List[str]
    _auto_confirm: bool


# 兼容旧的导入名称
IntentClarificationState = IntentState
