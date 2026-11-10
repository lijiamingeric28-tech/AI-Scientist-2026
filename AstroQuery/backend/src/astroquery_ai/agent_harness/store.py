"""科研问答智能体多轮历史存储持久化 (Agent Store)
在 runtime.sqlite3 中持久化 agent_messages 表，与任务生命周期深度绑定。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from astroquery_ai.runtime.codec import utcnow

logger = logging.getLogger("agent_harness.store")


class AgentStore:
    """管理特定 Repository 下的智能体多轮会话持久化。"""

    def __init__(self, repository):
        self.repository = repository
        self._ensure_table()

    def _ensure_table(self) -> None:
        """安全创建 agent_messages 实体表与索引。"""
        with self.repository.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    thought_steps TEXT DEFAULT '[]',
                    citations TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_messages_task_created 
                ON agent_messages(task_id, created_at)
                """
            )

    def get_messages(self, task_id: str) -> List[Dict[str, Any]]:
        """获取指定任务的全部问答历史。"""
        with self.repository.read() as conn:
            rows = conn.execute(
                """
                SELECT id, task_id, role, content, thought_steps, citations, created_at 
                FROM agent_messages 
                WHERE task_id=? 
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()

        messages = []
        for r in rows:
            d = dict(r)
            try:
                d["thought_steps"] = json.loads(d.get("thought_steps") or "[]")
            except Exception:
                d["thought_steps"] = []
            try:
                d["citations"] = json.loads(d.get("citations") or "[]")
            except Exception:
                d["citations"] = []
            messages.append(d)
        return messages

    def add_message(
        self,
        task_id: str,
        role: str,
        content: str,
        thought_steps: Optional[List[Dict[str, Any]]] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """追加一条问答消息。"""
        msg_id = f"agent-msg-{uuid.uuid4().hex[:12]}"
        created_at = utcnow()
        steps_json = json.dumps(thought_steps or [], ensure_ascii=False)
        citations_json = json.dumps(citations or [], ensure_ascii=False)

        with self.repository.transaction() as conn:
            conn.execute(
                """
                INSERT INTO agent_messages (id, task_id, role, content, thought_steps, citations, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, task_id, role, content, steps_json, citations_json, created_at),
            )

        return {
            "id": msg_id,
            "task_id": task_id,
            "role": role,
            "content": content,
            "thought_steps": thought_steps or [],
            "citations": citations or [],
            "created_at": created_at,
        }

    def delete_messages(self, task_id: str) -> int:
        """重置/清空指定任务的历史交互。"""
        with self.repository.transaction() as conn:
            cur = conn.execute("DELETE FROM agent_messages WHERE task_id=?", (task_id,))
            return int(cur.rowcount)
