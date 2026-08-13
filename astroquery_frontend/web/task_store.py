"""任务与事件持久化（sqlite，标准库）—— 契约 D8-3 事件落库 / D1-6 SqliteSaver 配套。

表结构：
- tasks:   task_id / query / title(LLM摘要) / status / created_at / output_dir
- events:  id(自增=seq) / task_id / payload(JSON) —— 历史回看 HTTP 批量拉取
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# M-08: 列表显式列裁剪（契约 D8-4；state_json/pdf_paths 走 get_task /state）
_LIST_COLUMNS = "task_id, query, title, status, created_at, completed_at"


class TaskStore:
    def __init__(self, db_path: str | Path):
        self._db = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                title TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                output_dir TEXT DEFAULT '',
                pdf_paths TEXT DEFAULT '[]',
                state_json TEXT DEFAULT '{}'
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                payload TEXT NOT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq)")

    # ── tasks ──
    def create_task(self, query: str, output_dir: str = "", pdf_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, query, status, created_at, output_dir, pdf_paths) VALUES (?,?,?,?,?,?)",
                (task_id, query, "queued", _now(), output_dir, json.dumps(pdf_paths or [])),
            )
        return {"task_id": task_id, "query": query, "status": "queued", "created_at": _now(), "pdf_paths": pdf_paths or []}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["pdf_paths"] = json.loads(d.get("pdf_paths") or "[]")
        except json.JSONDecodeError:
            d["pdf_paths"] = []
        return d

    def list_tasks(self, limit: int = 50, offset: int = 0, status: Optional[str] = None) -> Dict[str, Any]:
        # M-08: 契约 D8-4 显式列裁剪——不取 state_json/pdf_paths（单任务数百 KB，
        # 整行 SELECT 使 limit=50 列表响应膨胀 ~20-25MB；详情侧走 get_task /state）
        # H-01: 失败词表别名——status='error' 同时匹配旧词表 'failed'（存量记录归一）
        statuses = ["error", "failed"] if status == "error" else ([status] if status else [])
        marks = ",".join("?" * len(statuses))
        with self._conn() as conn:
            if statuses:
                rows = conn.execute(
                    f"SELECT {_LIST_COLUMNS} FROM tasks WHERE status IN ({marks}) "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (*statuses, limit, offset),
                ).fetchall()
                total = conn.execute(
                    f"SELECT COUNT(*) FROM tasks WHERE status IN ({marks})", statuses
                ).fetchone()[0]
            else:
                rows = conn.execute(
                    f"SELECT {_LIST_COLUMNS} FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        return {"items": [dict(r) for r in rows], "total": total}

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {cols} WHERE task_id=?", (*fields.values(), task_id))

    # ── events（seq = 自增主键，历史回看契约 D8-3）──
    def append_event(self, task_id: str, payload: Dict[str, Any]) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO events (task_id, payload) VALUES (?,?)",
                (task_id, json.dumps(payload, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def get_events(self, task_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT seq, payload FROM events WHERE task_id=? AND seq>? ORDER BY seq",
                (task_id, after_seq),
            ).fetchall()
        return [{"seq": r["seq"], **json.loads(r["payload"])} for r in rows]

    def last_seq(self, task_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(seq) AS m FROM events WHERE task_id=?", (task_id,)).fetchone()
        return row["m"] or 0
