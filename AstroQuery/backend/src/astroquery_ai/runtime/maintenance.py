"""Explicit task cleanup with tombstones, live-reference checks and receipts."""

import time

from .codec import canonical, digest, loads, new_id, utcnow
from .errors import DomainError
from .models import TERMINAL


class Maintenance:
    def __init__(self, application):
        self.app, self.repo = application, application.repository

    def rename(self, tid, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise DomainError("INVALID_TITLE", "任务名须为1至200字符", 422)
        with self.repo.transaction() as conn:
            self.repo.task(conn, tid)
            conn.execute(
                "UPDATE tasks SET title=?,revision=revision+1,updated_at=? WHERE task_id=?",
                (title.strip(), utcnow(), tid),
            )
            self.repo.event(conn, tid, "task_title_updated", {"title": title.strip()})
        return {"task_id": tid, "title": title.strip()}

    def cleanup(self, tid, *, operation_id, whole=False, parts=None):
        parts = parts or []
        if (
            not isinstance(parts, list)
            or set(parts) - {"pdfs", "figures", "checkpoints", "events"}
            or not whole
            and not parts
        ):
            raise DomainError("INVALID_CLEANUP", "请选择具体清理内容", 422)
        request = {"whole": whole, "parts": sorted(set(parts))}
        with self.repo.transaction() as conn:
            old = conn.execute(
                "SELECT * FROM cleanups WHERE task_id=? AND operation_id=?", (tid, operation_id)
            ).fetchone()
            if old:
                if old["request_hash"] != digest(request):
                    raise DomainError("OPERATION_CONFLICT", "清理操作编号已用于不同请求")
                receipt = loads(old["payload"])
            else:
                task = self.repo.task(conn, tid)
                if task["lifecycle"] not in TERMINAL:
                    raise DomainError("TASK_RECOVERABLE", "任务仍可恢复，须先明确取消或等待完成")
                if (
                    conn.execute(
                        "SELECT 1 FROM jobs WHERE task_id=? AND status='running'", (tid,)
                    ).fetchone()
                    or conn.execute(
                        "SELECT 1 FROM attempts WHERE task_id=? AND status='dispatched'", (tid,)
                    ).fetchone()
                ):
                    raise DomainError("CLEANUP_IN_FLIGHT", "仍有在途请求，暂不能清理")
                if conn.execute(
                    "SELECT 1 FROM replay_sources r WHERE source_task_id=? AND replay_id NOT IN (SELECT task_id FROM task_tombstones)",
                    (tid,),
                ).fetchone():
                    raise DomainError(
                        "REPLAY_SOURCE_REFERENCED", "已有回放引用该任务，请先删除相应回放"
                    )
                artifacts = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT DISTINCT a.* FROM artifacts a JOIN artifact_refs r USING(artifact_id) WHERE r.task_id=?",
                        (tid,),
                    )
                ]
                selected = [
                    a
                    for a in artifacts
                    if whole
                    or a["media_type"].split(";")[0] == "application/pdf"
                    and "pdfs" in parts
                    or a["media_type"].startswith("image/")
                    and "figures" in parts
                ]
                if any(
                    conn.execute(
                        "SELECT 1 FROM artifact_leases WHERE artifact_id=? AND expires_at>?",
                        (a["artifact_id"], time.time()),
                    ).fetchone()
                    for a in selected
                ):
                    raise DomainError("RESOURCE_LEASE_ACTIVE", "原件正在被读取，请稍后清理")
                cleanup_id = new_id()
                receipt = {
                    "cleanup_id": cleanup_id,
                    "task_id": tid,
                    "whole": whole,
                    "request": request,
                    "status": "pending",
                    "items": [{**a, "status": "pending"} for a in selected],
                    "retained": [
                        "budget_ledger",
                        "core_events",
                        "scientific_objects",
                        "review_answers",
                        "confirmed_query",
                    ],
                }
                self.repo.event(
                    conn, tid, "cleanup_started", {"cleanup_id": cleanup_id, "whole": whole}
                )
                if whole:
                    conn.execute(
                        "INSERT INTO task_tombstones VALUES(?,?,?)", (tid, cleanup_id, utcnow())
                    )
                    conn.execute(
                        "UPDATE tasks SET generation=generation+1,revision=revision+1 WHERE task_id=?",
                        (tid,),
                    )
                    conn.execute("DELETE FROM replay_sources WHERE replay_id=?", (tid,))
                for a in selected:
                    conn.execute(
                        "DELETE FROM artifact_refs WHERE task_id=? AND artifact_id=?",
                        (tid, a["artifact_id"]),
                    )
                conn.execute(
                    "INSERT INTO cleanups VALUES(?,?,?,?,?,?)",
                    (cleanup_id, tid, operation_id, digest(request), "pending", canonical(receipt)),
                )
        # A crash between tombstone and file reclaim is recoverable by repeating
        # this same operation. Hash/path and shared references are checked again.
        for item in receipt["items"]:
            if item["status"] not in {"pending", "failed"}:
                continue
            with self.repo.transaction() as conn:
                if conn.execute(
                    "SELECT 1 FROM artifact_refs WHERE artifact_id=?", (item["artifact_id"],)
                ).fetchone():
                    item["status"] = "retained_shared"
                elif conn.execute(
                    "SELECT 1 FROM artifact_leases WHERE artifact_id=? AND expires_at>?",
                    (item["artifact_id"], time.time()),
                ).fetchone():
                    item["status"] = "failed"
                    item["reason"] = "resource_lease_active"
                else:
                    try:
                        path = self.app.artifacts.path(item["relative_path"])
                        existed = path.exists()
                        path.unlink(missing_ok=True)
                        item["status"] = "deleted" if existed else "already_missing"
                        conn.execute(
                            "UPDATE artifacts SET availability='missing' WHERE artifact_id=?",
                            (item["artifact_id"],),
                        )
                    except OSError as exc:
                        item.update(status="failed", reason=type(exc).__name__)
                conn.execute(
                    "UPDATE cleanups SET payload=? WHERE cleanup_id=?",
                    (canonical(receipt), receipt["cleanup_id"]),
                )
        receipt["status"] = (
            "partial" if any(i["status"] == "failed" for i in receipt["items"]) else "completed"
        )
        receipt["deleted"] = bool(whole)
        with self.repo.transaction() as conn:
            conn.execute(
                "UPDATE cleanups SET status=?,payload=? WHERE cleanup_id=?",
                (receipt["status"], canonical(receipt), receipt["cleanup_id"]),
            )
        return receipt
