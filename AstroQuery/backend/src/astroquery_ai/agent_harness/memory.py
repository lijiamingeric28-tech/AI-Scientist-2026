"""3-Tier 动态记忆管理器 (Hybrid Memory Manager 2.0)
1. Tier 1: 任务静态基底事实 (System Grounded Context)
2. Tier 2: 动态多轮滑动窗口 (Sliding Window Context)
3. Tier 3: SQLite 实体归档 (Persistence in agent_messages)
"""

from __future__ import annotations

from typing import Any, Dict, List
from .data_loader import TaskDataBundle
from .prompts import SYSTEM_PROMPT_TEMPLATE


class AgentMemory:
    """负责问答智能体的多层上下文装配与轮次管理。"""

    def __init__(self, bundle: TaskDataBundle, max_window_turns: int = 5):
        self.bundle = bundle
        self.max_window_turns = max_window_turns

    def build_system_message(self) -> Dict[str, str]:
        """构造携带当前任务全量事实基底的 System Message。"""
        grounded_context = self.bundle.get_grounded_summary()
        content = SYSTEM_PROMPT_TEMPLATE.format(task_grounded_context=grounded_context)
        return {"role": "system", "content": content}

    def assemble_messages(self, history: List[Dict[str, Any]], new_query: str) -> List[Dict[str, str]]:
        """装配送入大模型的最终消息列表（含滑动窗口控制）。"""
        messages = [self.build_system_message()]

        # 截取最近 N 轮 (一轮包括 user + assistant)
        recent_turns = history[-(self.max_window_turns * 2):] if history else []

        for m in recent_turns:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})

        # 追加当前最新提问
        messages.append({"role": "user", "content": new_query})
        return messages
