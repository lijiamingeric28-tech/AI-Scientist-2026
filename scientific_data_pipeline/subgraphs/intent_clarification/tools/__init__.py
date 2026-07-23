"""
意图澄清子图的工具函数模块

包含三个Agent的所有工具函数：
- evaluate_intent: Agent A的工具（schema生成、参数提取、完整性检查、强制填充）
- ask_user_guided: Agent B的工具（追问生成、格式化、回答解析）
- confirm_intent: Agent C的工具（确认表单、修改解析）
"""

# Agent A工具
from subgraphs.intent_clarification.tools.evaluate_intent import (
    generate_schema,
    extract_parameters,
    check_completeness,
    force_fill_missing_slots
)

# Agent B工具
from subgraphs.intent_clarification.tools.ask_user_guided import (
    generate_clarification_question,
    format_question_for_display,
    parse_user_response
)

# Agent C工具
from subgraphs.intent_clarification.tools.confirm_intent import (
    format_confirmation_display,
    parse_user_modifications,
    parse_user_modifications_fallback
)

__all__ = [
    # Agent A
    "generate_schema",
    "extract_parameters",
    "check_completeness",
    "force_fill_missing_slots",
    # Agent B
    "generate_clarification_question",
    "format_question_for_display",
    "parse_user_response",
    # Agent C
    "format_confirmation_display",
    "parse_user_modifications",
    "parse_user_modifications_fallback",
]
