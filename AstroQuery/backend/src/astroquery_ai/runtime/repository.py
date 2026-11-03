"""One repository facade for short transactions, objects, tasks and events."""

from __future__ import annotations

import sqlite3

from contextlib import contextmanager

from pathlib import Path

from typing import Iterator

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads, new_id, utcnow

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import LIFECYCLES, TERMINAL

from astroquery_ai.runtime.persistence import schema as _schema, jobs as _jobs

from astroquery_ai.runtime.persistence.schema import SCHEMA, SCHEMA_VERSION


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
        finally:
            conn.rollback()
            conn.close()

    def backup(self, destination: Path):
        if destination.resolve() == self.path:
            raise ValueError("backup destination must differ from database")
        with self.read() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()

    @staticmethod
    def task(conn, task_id: str) -> dict:
        if conn.execute("SELECT 1 FROM task_tombstones WHERE task_id=?", (task_id,)).fetchone():
            raise DomainError("TASK_DELETED", "任务已删除", 410)
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", 404)
        return dict(row)

    def get_task(self, task_id: str) -> dict:
        with self.read() as conn:
            return self.task(conn, task_id)

    def list_tasks(self, limit=50, offset=0) -> list[dict]:
        with self.read() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM tasks WHERE kind<>'validation' AND task_id NOT IN (SELECT task_id FROM task_tombstones) ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (min(max(limit, 1), 500), max(offset, 0)),
                )
            ]

    def event(self, conn, task_id: str, kind: str, payload: dict | None = None) -> dict:
        task = self.task(conn, task_id)
        seq = task["last_event_seq"] + 1
        event = {
            "protocol_version": 1,
            "task_id": task_id,
            "seq": seq,
            "event_id": new_id(),
            "committed_at": utcnow(),
            "task_revision": task["revision"],
            "generation": task["generation"],
            "kind": kind,
            "payload": payload or {},
        }
        conn.execute(
            "INSERT INTO events VALUES(?,?,?,?)",
            (task_id, seq, event["event_id"], canonical(event)),
        )
        conn.execute(
            "INSERT INTO outbox(event_id,task_id,seq) VALUES(?,?,?)",
            (event["event_id"], task_id, seq),
        )
        conn.execute("UPDATE tasks SET last_event_seq=? WHERE task_id=?", (seq, task_id))
        return event

    def events(self, task_id: str, after_seq=0, limit=200) -> list[dict]:
        with self.read() as conn:
            task = self.task(conn, task_id)
            if after_seq < 0 or after_seq > task["last_event_seq"]:
                raise DomainError(
                    "RESYNC_REQUIRED",
                    "事件游标无效，请重新读取任务状态",
                    core_event_cursor=task["last_event_seq"],
                )
            return [
                loads(row[0])
                for row in conn.execute(
                    "SELECT payload FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (task_id, after_seq, min(max(limit, 1), 500)),
                )
            ]

    def put_object(
        self, conn, task_id: str, kind: str, object_id: str, version: int, payload: dict
    ) -> dict:
        self.task(conn, task_id)
        sha = content_hash(payload)
        if "content_sha256" in payload and payload["content_sha256"] != sha:
            raise DomainError(
                "OBJECT_HASH_MISMATCH", "对象内容哈希不匹配", 422, object_id=object_id
            )
        raw = canonical(payload)
        existing = conn.execute(
            "SELECT content_sha256,payload FROM objects WHERE task_id=? AND kind=? AND object_id=? AND version=?",
            (task_id, kind, object_id, version),
        ).fetchone()
        if existing:
            if bytes(existing["payload"]) != raw:
                raise DomainError(
                    "IMMUTABLE_OBJECT", "不可覆盖已保存版本", object_id=object_id, kind=kind
                )
        else:
            conn.execute(
                "INSERT INTO objects VALUES(?,?,?,?,?,?,?)",
                (task_id, kind, object_id, version, sha, raw, utcnow()),
            )
        return {"id": object_id, "version": version, "content_sha256": sha}

    @staticmethod
    def object(conn, task_id: str, kind: str, object_id: str, version: int | None = None) -> dict:
        query = "SELECT payload FROM objects WHERE task_id=? AND kind=? AND object_id=?"
        args: tuple = (task_id, kind, object_id)
        if version is not None:
            query += " AND version=?"
            args += (version,)
        row = conn.execute(query + " ORDER BY version DESC LIMIT 1", args).fetchone()
        if row is None:
            raise DomainError(
                "OBJECT_NOT_FOUND", "所需版本不存在", 404, object_id=object_id, kind=kind
            )
        return loads(row[0])

    def objects(self, conn, task_id: str, kind: str) -> list[dict]:
        return [
            loads(row[0])
            for row in conn.execute(
                "SELECT o.payload FROM objects o WHERE task_id=? AND kind=? AND version=(SELECT max(version) FROM objects i WHERE i.task_id=o.task_id AND i.kind=o.kind AND i.object_id=o.object_id) ORDER BY object_id",
                (task_id, kind),
            )
        ]

    def create_task(
        self, text: str, *, kind="live", task_id: str | None = None, initializer=None
    ) -> dict:
        if kind not in {"live", "legacy", "replay", "validation"} or not text.strip():
            raise DomainError("INVALID_TASK", "查询不能为空", 422)
        task_id = task_id or new_id()
        now = utcnow()
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT task_id FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if existing:
                messages = self.objects(conn, task_id, "message")
                originals = [message for message in messages if message.get("original")]
                if len(originals) != 1 or originals[0]["text"] != text:
                    raise DomainError("OPERATION_CONFLICT", "同一创建操作不能更改查询")
                return self.task(conn, task_id)
            conn.execute(
                "INSERT INTO tasks(task_id,revision,generation,lifecycle,phase,science_state,kind,title,created_at,updated_at) VALUES(?,1,1,'clarifying','prepare','not_started',?,?,?,?)",
                (task_id, kind, text[:120], now, now),
            )
            self.put_object(
                conn,
                task_id,
                "message",
                new_id(),
                1,
                {"role": "user", "text": text, "original": True, "created_at": now},
            )
            self.event(conn, task_id, "task_state_changed", {"lifecycle": "clarifying"})
            if initializer is not None:
                initializer(conn, self.task(conn, task_id))
            return self.task(conn, task_id)

    def mutate_task(self, conn, task_id: str, **changes) -> dict:
        allowed = {
            "lifecycle",
            "phase",
            "science_state",
            "query_ref",
            "delivery_ref",
            "insight_ref",
            "generation",
            "resume_required",
            "terminal_reason",
            "title",
        }
        if not changes or set(changes) - allowed:
            raise ValueError("invalid task mutation")
        current = self.task(conn, task_id)
        if "lifecycle" in changes and changes["lifecycle"] not in LIFECYCLES:
            raise ValueError("invalid lifecycle")
        if current["lifecycle"] in TERMINAL:
            raise DomainError("TERMINAL_TASK", "该任务已经结束，只能查看")
        if current["science_state"] == "sealed" and any(
            (key in changes for key in {"query_ref", "science_state"})
        ):
            raise DomainError("SCIENCE_SEALED", "科学数据已封口")
        conn.execute(
            "UPDATE tasks SET "
            + ",".join((f"{key}=?" for key in changes))
            + ",revision=revision+1,updated_at=? WHERE task_id=?",
            (*changes.values(), utcnow(), task_id),
        )
        return self.task(conn, task_id)

    @staticmethod
    def check_revision(task: dict, expected: int):
        if task["revision"] != expected:
            raise DomainError(
                "REVISION_CONFLICT", "任务已更新，请刷新", current_revision=task["revision"]
            )

    @staticmethod
    def replay_operation(conn, task_id: str, operation_id: str, request: dict) -> dict | None:
        row = conn.execute(
            "SELECT * FROM operations WHERE task_id=? AND operation_id=?", (task_id, operation_id)
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != digest(request):
            raise DomainError("OPERATION_CONFLICT", "同一操作编号不能用于不同请求")
        return loads(row["response_json"])

    @staticmethod
    def save_operation(conn, task_id: str, operation_id: str, request: dict, response: dict):
        conn.execute(
            "INSERT INTO operations VALUES(?,?,?,?)",
            (task_id, operation_id, digest(request), canonical(response).decode("utf-8")),
        )

    def control(
        self,
        task_id: str,
        action: str,
        operation_id: str,
        expected_revision: int,
        *,
        finalizer=None,
    ) -> dict:
        request = {"action": action, "expected_revision": expected_revision}
        with self.transaction() as conn:
            old = self.replay_operation(conn, task_id, operation_id, request)
            if old is not None:
                return old
            task = self.task(conn, task_id)
            self.check_revision(task, expected_revision)
            if task["kind"] != "live" or task["lifecycle"] in TERMINAL:
                raise DomainError("TERMINAL_TASK", "该任务只读，不能恢复执行")
            if action == "pause":
                if task["lifecycle"] not in {
                    "running",
                    "queued",
                    "waiting_review",
                    "waiting_input",
                    "clarifying",
                }:
                    raise DomainError("INVALID_TRANSITION", "当前状态不能暂停")
                inflight = conn.execute(
                    "SELECT 1 FROM jobs WHERE task_id=? AND status='running'", (task_id,)
                ).fetchone()
                self.mutate_task(conn, task_id, lifecycle="pausing" if inflight else "paused")
            elif action == "cancel":
                self.mutate_task(
                    conn, task_id, lifecycle="cancelling", generation=task["generation"] + 1
                )
                conn.execute(
                    "UPDATE jobs SET status='cancelled',reason='user_cancelled',lease_token=NULL WHERE task_id=? AND status IN ('ready','running','waiting_dependency','awaiting_review')",
                    (task_id,),
                )
                conn.execute(
                    "UPDATE reviews SET status=CASE WHEN status='accepted' THEN 'closed_unapplied' ELSE 'closed_unanswered' END WHERE task_id=? AND status IN ('pending','accepted')",
                    (task_id,),
                )
                conn.execute(
                    "UPDATE producers SET state='closed',close_reason='user_cancelled',revision=revision+1 WHERE task_id=? AND state='open'",
                    (task_id,),
                )
                if finalizer and task["query_ref"] and task["science_state"] in {'open','sealed'}:
                    conn.execute("SAVEPOINT cancelled_delivery")
                    try:
                        finalizer(conn, task_id, outcome="cancelled")
                        conn.execute("RELEASE cancelled_delivery")
                    except Exception as exc:
                        conn.execute("ROLLBACK TO cancelled_delivery")
                        conn.execute("RELEASE cancelled_delivery")
                        self.event(
                            conn,
                            task_id,
                            "delivery_failed",
                            {"reason": getattr(exc, "code", "LOCAL_FINALIZATION_FAILED")},
                        )
                self.mutate_task(
                    conn, task_id, lifecycle="cancelled", terminal_reason="user_cancelled"
                )
            elif action in {"continue", "retry"}:
                if task["lifecycle"] not in {"paused", "interrupted"}:
                    raise DomainError("INVALID_TRANSITION", "只有暂停或中断任务可以继续")
                from astroquery_ai.runtime.reviews import withdraw_paused_checks

                withdraw_paused_checks(self, conn, task_id)
                self.mutate_task(
                    conn,
                    task_id,
                    lifecycle="queued" if task["query_ref"] else "waiting_input",
                    resume_required=0,
                )
                if task["query_ref"] and task["science_state"] == "open":
                    self.enqueue(
                        conn, task_id, "M13", "reconcile", {"resume_operation_id": operation_id}
                    )
            else:
                raise DomainError("INVALID_ACTION", "未知控制动作", 422)
            from .run_policy import user_pause
            user_pause(self, conn, task_id, action)
            result = self.task(conn, task_id)
            self.event(conn, task_id, "task_state_changed", {"lifecycle": result["lifecycle"]})
            self.save_operation(conn, task_id, operation_id, request, result)
            return result

    def recover(self) -> int:
        """Called only after the process instance lock is acquired. Never dispatches."""
        with self.transaction() as conn:
            conn.execute("UPDATE attempts SET status='unknown' WHERE status='dispatched'")
            conn.execute(
                "UPDATE http_attempts SET status='unknown',error_code='process_interrupted' WHERE status='dispatched'"
            )
            conn.execute(
                "UPDATE attempts SET status='not_dispatched',actual_micros=0,settled_at=? WHERE status='reserved'",
                (utcnow(),),
            )
            tasks = conn.execute(
                "SELECT task_id FROM tasks WHERE lifecycle IN ('running','queued','clarifying','pausing','cancelling')"
            ).fetchall()
            for row in tasks:
                tid = row[0]
                task = self.task(conn, tid)
                if task["lifecycle"] == "cancelling":
                    conn.execute(
                        "UPDATE jobs SET status='cancelled',lease_token=NULL WHERE task_id=? AND status IN ('ready','running')",
                        (tid,),
                    )
                    conn.execute(
                        "UPDATE reviews SET status=CASE WHEN status='accepted' THEN 'closed_unapplied' ELSE 'closed_unanswered' END WHERE task_id=? AND status IN ('pending','accepted')",
                        (tid,),
                    )
                    self.mutate_task(
                        conn, tid, lifecycle="cancelled", terminal_reason="user_cancelled"
                    )
                    self.event(conn, tid, "task_state_changed", {"lifecycle": "cancelled"})
                    continue
                conn.execute(
                    "UPDATE jobs SET status='ready',lease_token=NULL,lease_until=NULL WHERE task_id=? AND status='running'",
                    (tid,),
                )
                if not task["query_ref"]:
                    current = conn.execute(
                        "SELECT payload FROM objects WHERE task_id=? AND kind='draft' ORDER BY version DESC LIMIT 1",
                        (tid,),
                    ).fetchone()
                    if current:
                        draft = loads(current[0])
                        draft.update(
                            revision=draft["revision"] + 1,
                            status="paused",
                            pause_reason="process_interrupted",
                            pending_question=None,
                        )
                        self.put_object(conn, tid, "draft", tid, draft["revision"], draft)
                        conn.execute(
                            "UPDATE jobs SET status='not_run',reason='preparation_interrupted' WHERE task_id=? AND status='ready'",
                            (tid,),
                        )
                self.mutate_task(conn, tid, lifecycle="interrupted", resume_required=1)
                self.event(
                    conn,
                    tid,
                    "task_state_changed",
                    {"lifecycle": "interrupted", "reason": "process_interrupted"},
                )
            return len(tasks)

    _migrate = _schema._migrate
    enqueue = _jobs.enqueue
    close_failed_metadata_dependencies = _jobs.close_failed_metadata_dependencies
    dispatch_delay = _jobs.dispatch_delay
    claim_job = _jobs.claim_job
    validate_lease = _jobs.validate_lease
    guard_definitions = _jobs.guard_definitions
    renew = _jobs.renew
    finish_job = _jobs.finish_job
    producer = _jobs.producer
