"""Persistent follow-up messages, with atomic starts and completion."""

from __future__ import annotations

import json
import uuid

from astroquery_ai.runtime.codec import digest, utcnow
from astroquery_ai.runtime.errors import DomainError


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _message(row):
    result = dict(row)
    for name, fallback in (("thought_steps", []), ("citations", []), ("scope", None), ("answer", None), ("meta", {})):
        try:
            result[name] = json.loads(result[name]) if result[name] else fallback
        except ValueError:
            result[name] = fallback
    result.update(result.pop("meta"))
    return result


class AgentStore:
    def __init__(self, repository):
        self.repository = repository
        with repository.transaction() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    role TEXT NOT NULL, content TEXT NOT NULL, thought_steps TEXT DEFAULT '[]',
                    citations TEXT DEFAULT '[]', created_at TEXT NOT NULL
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_messages)")}
            for name, kind in {
                "scope": "TEXT", "request_id": "TEXT", "question_id": "TEXT", "answer": "TEXT",
                "status": "TEXT NOT NULL DEFAULT 'complete'", "meta": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE agent_messages ADD COLUMN {name} {kind}")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_agent_messages_task_created
                            ON agent_messages(task_id, created_at)""")
            conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_requests
                            ON agent_messages(task_id, request_id) WHERE request_id IS NOT NULL""")
            conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_active
                            ON agent_messages(task_id) WHERE status='generating'""")

    def get_messages(self, task_id, scope=None):
        with self.repository.read() as conn:
            return self._history(conn, task_id, scope)

    @staticmethod
    def _history(conn, task_id, scope):
        where = " AND (scope IS NULL OR scope=?)" if scope else ""
        args = (task_id, _json(scope)) if scope else (task_id,)
        return [_message(row) for row in conn.execute(
            f"SELECT * FROM agent_messages WHERE task_id=?{where} ORDER BY rowid", args
        )]

    def get_message(self, task_id, message_id):
        with self.repository.read() as conn:
            return self._get(conn, task_id, message_id)

    @staticmethod
    def _get(conn, task_id, message_id):
        row = conn.execute("SELECT * FROM agent_messages WHERE task_id=? AND id=?", (task_id, message_id)).fetchone()
        if row is None:
            raise DomainError("AGENT_MESSAGE_NOT_FOUND", "未找到这条回答", 404)
        return _message(row)

    def start(self, task_id, scope, content, request_id, context, retry_of=None, repair_block=None):
        operation = digest({"scope": scope, "content": content, "context": context,
                            "retry_of": retry_of, "repair_block": repair_block})
        with self.repository.transaction() as conn:
            existing = conn.execute("SELECT * FROM agent_messages WHERE task_id=? AND request_id=?",
                                    (task_id, request_id)).fetchone()
            if existing:
                message = _message(existing)
                if message.get("operation") != operation:
                    raise DomainError("AGENT_REQUEST_CHANGED", "同一请求已用于另一条追问")
                return message, None, [], None
            if conn.execute("SELECT 1 FROM agent_messages WHERE task_id=? AND status='generating'",
                            (task_id,)).fetchone():
                raise DomainError("AGENT_BUSY", "上一条回答仍在生成")
            history = self._history(conn, task_id, scope)
            previous = self._get(conn, task_id, retry_of) if retry_of else None
            if previous:
                if previous["role"] != "assistant" or previous["scope"] != scope or not previous["question_id"]:
                    raise DomainError("AGENT_RETRY_SCOPE", "这条回答不属于当前交付版本")
                qid = previous["question_id"]
                question = self._get(conn, task_id, qid)
                position = next(i for i, row in enumerate(history) if row["id"] == qid)
                earlier = {row["id"] for row in history[:position] if row["role"] == "user"}
                history = [row for index, row in enumerate(history) if index < position or row["question_id"] in earlier]
            else:
                question = self._insert(conn, task_id, "user", content, scope=scope)
                qid = question["id"]
            message = self._insert(
                conn, task_id, "assistant", "", scope=scope, request_id=request_id,
                question_id=qid, status="generating", meta={"operation": operation, "context": context},
            )
            return message, question, history, previous

    def _insert(self, conn, task_id, role, content, *, scope=None, request_id=None, question_id=None,
                status="complete", meta=None, thought_steps=None, citations=None):
        mid = "agent-msg-" + uuid.uuid4().hex
        conn.execute("""
            INSERT INTO agent_messages
            (id, task_id, role, content, thought_steps, citations, created_at, scope, request_id, question_id, status, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mid, task_id, role, content, _json(thought_steps or []), _json(citations or []),
              utcnow(), _json(scope) if scope else None, request_id, question_id, status, _json(meta or {})))
        return self._get(conn, task_id, mid)

    def add_message(self, task_id, role, content, thought_steps=None, citations=None):
        with self.repository.transaction() as conn:
            return self._insert(conn, task_id, role, content, thought_steps=thought_steps, citations=citations)

    def save(self, task_id, message_id, *, content, blocks, citations, trace, status="generating", **meta):
        with self.repository.transaction() as conn:
            current = self._get(conn, task_id, message_id)
            if current["status"] == "generating":
                conn.execute("""
                    UPDATE agent_messages SET content=?, answer=?, citations=?, thought_steps=?, status=?, meta=?
                    WHERE task_id=? AND id=?
                """, (content, _json({"version": 1, "blocks": blocks}), _json(citations), _json(trace), status,
                      _json({"operation": current.get("operation"), "context": current.get("context"), **meta}),
                      task_id, message_id))
            return self._get(conn, task_id, message_id)

    def recover(self):
        with self.repository.transaction() as conn:
            conn.execute("UPDATE agent_messages SET status='interrupted' WHERE status='generating'")

    def delete_messages(self, task_id):
        with self.repository.transaction() as conn:
            if conn.execute("SELECT 1 FROM agent_messages WHERE task_id=? AND status='generating'",
                            (task_id,)).fetchone():
                raise DomainError("AGENT_BUSY", "请先停止正在生成的回答")
            return conn.execute("DELETE FROM agent_messages WHERE task_id=?", (task_id,)).rowcount
