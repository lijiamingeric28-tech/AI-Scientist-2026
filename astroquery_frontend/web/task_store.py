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
# replay_of: 回放任务指向源任务（事件级重放，2026-08-27；前端徽标/防重用）
# 2026-09-01: 列表轻量统计列 record_count/source_count（侧边栏「N 条记录 · M 个来源」）
# ——完成任务落库时在 update_task 解析一次写入，列表纯列 SELECT（不触碰大 state_json）；
# 取数与 /records、/sources 端点同源优先链（quality structured_data 优先）。
# 2026-09-02: source 列（'user'|'sample'）——内嵌演示样例与用户真实查询隔离；
# 列表/回放任务按归属过滤（side：我的查询/演示样例切换）。
_LIST_COLUMNS = "task_id, query, title, status, created_at, completed_at, replay_of, record_count, source_count, source"


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    """幂等迁移：PRAGMA 检查后 ALTER 加列（老库升级用；新库建表 DDL 已带列，走不到）。"""
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


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
                state_json TEXT DEFAULT '{}',
                replay_of TEXT DEFAULT NULL,
                record_count INTEGER DEFAULT 0,
                source_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'user'
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                ts REAL DEFAULT NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq)")
            # 老库幂等升级（建表 DDL 已带列时 PRAGMA 命中，ALTER 不执行）
            _ensure_column(conn, "tasks", "replay_of", "replay_of TEXT DEFAULT NULL")
            _ensure_column(conn, "tasks", "record_count", "record_count INTEGER DEFAULT 0")
            _ensure_column(conn, "tasks", "source_count", "source_count INTEGER DEFAULT 0")
            _ensure_column(conn, "tasks", "source", "source TEXT DEFAULT 'user'")
            _ensure_column(conn, "events", "ts", "ts REAL DEFAULT NULL")

    # ── tasks ──
    def create_task(self, query: str, output_dir: str = "", pdf_paths: Optional[List[str]] = None,
                    replay_of: Optional[str] = None, source: str = "user") -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, query, status, created_at, output_dir, pdf_paths, replay_of, source) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, query, "queued", _now(), output_dir, json.dumps(pdf_paths or []), replay_of, source),
            )
        return {"task_id": task_id, "query": query, "status": "queued", "created_at": _now(),
                "pdf_paths": pdf_paths or [], "replay_of": replay_of, "source": source}

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

    def list_tasks(self, limit: int = 50, offset: int = 0, status: Optional[str] = None,
                   source: Optional[str] = None) -> Dict[str, Any]:
        # M-08: 契约 D8-4 显式列裁剪——不取 state_json/pdf_paths（单任务数百 KB，
        # 整行 SELECT 使 limit=50 列表响应膨胀 ~20-25MB；详情侧走 get_task /state）
        # H-01: 失败词表别名——status='error' 同时匹配旧词表 'failed'（存量记录归一）
        # 2026-09-02: source 归属过滤（我的查询=user / 演示样例=sample；None=不筛）
        statuses = ["error", "failed"] if status == "error" else ([status] if status else [])
        clauses: List[str] = []
        args: List[Any] = []
        if statuses:
            marks = ",".join("?" * len(statuses))
            clauses.append(f"status IN ({marks})")
            args.extend(statuses)
        if source in ("user", "sample"):
            clauses.append("source=?")
            args.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_LIST_COLUMNS} FROM tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
            total = conn.execute(f"SELECT COUNT(*) FROM tasks {where}", args).fetchone()[0]
        return {"items": [dict(r) for r in rows], "total": total}

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        # 2026-09-01: state_json 落库时顺带解析轻量计数（列表「N 条记录 · M 个来源」）——
        # 免去列表接口读大字段；取数与 /records、/sources 端点同源（质量输出优先）。
        # 解析失败不阻塞落库（计数置 0，仅影响统计展示）。
        if "state_json" in fields:
            rec_count = src_count = 0
            try:
                st = json.loads(fields["state_json"] or "{}")
                fo = st.get("final_output") or {}
                sd = (fo.get("quality_report") or {}).get("output_state", {}).get("structured_data", {})
                rec_count = sd.get("row_count") if sd else None
                if rec_count is None:
                    rec_count = len(fo.get("records") or [])
                srcs = (sd or {}).get("json", {}).get("sources")
                if srcs is None:
                    srcs = fo.get("sources")
                src_count = len(srcs) if isinstance(srcs, (list, dict)) else (int(srcs or 0) if isinstance(srcs, (int, float)) else 0)
                rec_count = int(rec_count or 0)
            except Exception:  # noqa: BLE001
                rec_count = src_count = 0
            fields = {**fields, "record_count": rec_count, "source_count": src_count}
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {cols} WHERE task_id=?", (*fields.values(), task_id))

    # ── events（seq = 自增主键，历史回看契约 D8-3）──
    def append_event(self, task_id: str, payload: Dict[str, Any], ts: Optional[float] = None) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO events (task_id, payload, ts) VALUES (?,?,?)",
                (task_id, json.dumps(payload, ensure_ascii=False), ts),
            )
            return int(cur.lastrowid)

    def get_events(self, task_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT seq, ts, payload FROM events WHERE task_id=? AND seq>? ORDER BY seq",
                (task_id, after_seq),
            ).fetchall()
        return [{"seq": r["seq"], "ts": r["ts"], **json.loads(r["payload"])} for r in rows]

    def last_seq(self, task_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(seq) AS m FROM events WHERE task_id=?", (task_id,)).fetchone()
        return row["m"] or 0

    # ── 回放（2026-08-27：事件级重放；replay_of 指向源任务）──
    def active_replay_exists(self, source_id: str) -> bool:
        """源任务是否存在活跃（queued/running）回放——防重复重放排队。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE replay_of=? AND status IN ('queued','running')",
                (source_id,),
            ).fetchone()
        return bool(row and row[0] > 0)

    def replay_ids_of(self, source_id: str) -> List[str]:
        """源任务的全部回放任务 id（删除源时级联用）。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT task_id FROM tasks WHERE replay_of=?", (source_id,)).fetchall()
        return [r["task_id"] for r in rows]

    # ── 样例包恢复（2026-09-02：演示样例启动导入专用，幂等由调用方保证）──
    def restore_task(self, task_id: str, query: str, *, title: str = "",
                     status: str = "completed", created_at: Optional[str] = None,
                     completed_at: Optional[str] = None, output_dir: str = "",
                     pdf_paths: Optional[List[str]] = None, state_json: str = "{}",
                     replay_of: Optional[str] = None, record_count: int = 0,
                     source_count: int = 0, source: str = "sample") -> None:
        """整行恢复（样例包任务）：全字段插入，task_id 冲突时抛错（调用方先查重）。"""
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, query, title, status, created_at, completed_at, "
                "output_dir, pdf_paths, state_json, replay_of, record_count, source_count, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, query, title, status, created_at or _now(), completed_at, output_dir,
                 json.dumps(pdf_paths or [], ensure_ascii=False), state_json, replay_of,
                 int(record_count or 0), int(source_count or 0), source),
            )

    def restore_events(self, task_id: str, events: List[Any]) -> int:
        """批量恢复事件（样例包）：[(ts 或 None, payload JSON 文本), ...]，返回恢复条数。"""
        if not events:
            return 0
        with self._lock, self._conn() as conn:
            conn.executemany(
                "INSERT INTO events (task_id, payload, ts) VALUES (?,?,?)",
                [(task_id, payload, ts) for ts, payload in events],
            )
        return len(events)

    # ── 删除（2026-08-24：任务清理功能）──
    def delete_events(self, task_id: str) -> int:
        """删除任务的全部事件记录，返回删除行数。"""
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM events WHERE task_id=?", (task_id,))
            return int(cur.rowcount)

    def delete_task(self, task_id: str) -> int:
        """删除任务行（events 不级联，调用方按需先删），返回删除行数。"""
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
            return int(cur.rowcount)

    def update_orphan_status(self) -> int:
        """启动纠偏：running/queued 任务重启后已成孤儿（队列为内存态），
        统一标记为 cancelled，返回受影响行数。"""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status='cancelled' "
                "WHERE status IN ('running','queued')"
            )
            return int(cur.rowcount)
