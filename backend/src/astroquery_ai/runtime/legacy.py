"""Explicit read-only history import. Never imports graphs, grants or approvals."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .codec import canonical, digest, loads, utcnow
from .errors import DomainError


class LegacyHistory:
    def __init__(self, application):
        self.app, self.repo = application, application.repository

    def import_database(self, path: Path):
        path = path.resolve()
        if not path.is_file() or path == self.repo.path:
            raise DomainError("LEGACY_DATABASE_PATH", "请选择独立的旧任务数据库", 422)
        imported, gaps = [], []
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
            source.row_factory = sqlite3.Row
            source.execute("PRAGMA query_only=ON")
            source.execute("BEGIN")
            columns = {row["name"] for row in source.execute("PRAGMA table_info(tasks)")}
            if not {"task_id", "query", "state_json", "created_at", "status"} <= columns:
                raise DomainError("LEGACY_DATABASE_SCHEMA", "不是受支持的旧任务数据库", 422)
            if source.execute("SELECT count(*) FROM tasks").fetchone()[0] > 10000:
                raise DomainError("LEGACY_DATABASE_LIMIT", "单次历史导入最多10000个任务", 422)
            has_events = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            for row in source.execute("SELECT * FROM tasks ORDER BY created_at,task_id"):
                old = dict(row)
                raw = old["state_json"].encode("utf-8")
                if len(raw) > 32 * 1024**2:
                    gaps.append({"task_id": old["task_id"], "reason": "legacy_state_too_large"})
                    continue
                try:
                    state = loads(raw)
                    if not isinstance(state, dict):
                        raise ValueError("object required")
                except (ValueError, UnicodeError):
                    gaps.append({"task_id": old["task_id"], "reason": "legacy_state_invalid_json"})
                    continue
                events = []
                if has_events:
                    for event in source.execute(
                        "SELECT seq,payload FROM events WHERE task_id=? ORDER BY seq LIMIT 100001",
                        (old["task_id"],),
                    ):
                        if len(events) == 100000:
                            gaps.append({"task_id": old["task_id"], "reason": "legacy_event_limit"})
                            break
                        try:
                            events.append(
                                {"original_seq": event["seq"], "payload": loads(event["payload"])}
                            )
                        except ValueError:
                            events.append(
                                {
                                    "original_seq": event["seq"],
                                    "unavailable": True,
                                    "reason": "invalid_original_event",
                                }
                            )
                identity = {
                    "source_database": str(path),
                    "original_task_id": old["task_id"],
                    "state_sha256": hashlib.sha256(raw).hexdigest(),
                    "events_sha256": digest(events),
                    "metadata_sha256": digest({k: v for k, v in old.items() if k != "state_json"}),
                }
                tid = str(uuid5(NAMESPACE_URL, "astroquery-legacy:" + digest(identity)))
                artifact = self.app.artifacts.write(raw, "application/json")
                result_id = "legacy-" + digest(identity)
                metadata = {
                    "schema_version": "LegacyArchive/1",
                    "legacy_version": 1,
                    **identity,
                    "result_id": result_id,
                    "query": old["query"],
                    "title": old.get("title") or old["query"],
                    "original_status": old["status"],
                    "source": old.get("source", "user"),
                    "original_created_at": old["created_at"],
                    "state_artifact": artifact,
                    "events": events,
                    "imported_at": utcnow(),
                    "original_metadata": {k: v for k, v in old.items() if k != "state_json"},
                    "limitations": [
                        "旧结果只读；未按新科学规则复检。",
                        "不能恢复旧执行器或补答历史问题。",
                        "未重新核验旧报告中的评分、原件路径与科学结论。",
                    ],
                }

                def initialize(conn, task):
                    self.app.artifacts.register(conn, tid, result_id, artifact)
                    reference = self.repo.put_object(conn, tid, "legacy_archive", tid, 1, metadata)
                    self.repo.put_object(
                        conn,
                        tid,
                        "task_origin",
                        tid,
                        1,
                        {"source": metadata["source"], "legacy_version": 1},
                    )
                    lifecycle = (
                        "completed"
                        if old["status"] == "completed"
                        else "cancelled"
                        if old["status"] == "cancelled"
                        else "error"
                    )
                    conn.execute(
                        "UPDATE tasks SET lifecycle=?,science_state='sealed',phase='legacy',delivery_ref=? WHERE task_id=?",
                        (
                            lifecycle,
                            canonical(
                                {
                                    "id": result_id,
                                    "version": 1,
                                    "content_sha256": reference["content_sha256"],
                                }
                            ).decode(),
                            tid,
                        ),
                    )
                    self.repo.event(
                        conn,
                        tid,
                        "legacy_imported",
                        {
                            "result_id": result_id,
                            "original_task_id": old["task_id"],
                            "scientific_validation": False,
                        },
                    )

                self.repo.create_task(
                    "历史：" + str(metadata["title"])[:200],
                    kind="legacy",
                    task_id=tid,
                    initializer=initialize,
                )
                imported.append(tid)
        return {
            "imported_task_ids": imported,
            "count": len(imported),
            "gaps": gaps,
            "scientific_validation": False,
        }

    def get(self, conn, tid):
        source = self.app.history.source(conn, tid)
        task = self.repo.task(conn, source)
        return (
            self.repo.object(conn, source, "legacy_archive", source)
            if task["kind"] == "legacy"
            else None
        )

    def view(self, conn, task):
        archive = self.repo.object(conn, task["task_id"], "legacy_archive", task["task_id"])
        return {
            **task,
            "status": task["lifecycle"],
            "protocol_version": 2,
            "legacy_version": 1,
            "read_only": True,
            "source": archive["source"],
            "delivery_ref": loads(task["delivery_ref"]),
            "insight_ref": None,
            "draft": {"target": None, "last_error": None},
            "pending": None,
            "reviews": [],
            "jobs": [],
            "stages": [],
            "core_event_cursor": task["last_event_seq"],
            "messages": [
                {"role": "user", "text": archive["query"]},
                {"role": "assistant", "text": "\n".join(archive["limitations"])},
            ],
            "legacy": {
                k: archive[k]
                for k in (
                    "legacy_version",
                    "original_task_id",
                    "original_status",
                    "original_created_at",
                    "state_sha256",
                    "events_sha256",
                    "limitations",
                )
            },
            "legacy_archive_artifact_id": archive["state_artifact"]["artifact_id"],
        }

    def resource(self, conn, tid, result_id, name):
        archive = self.get(conn, tid)
        if archive is None or result_id != archive["result_id"]:
            raise DomainError("LEGACY_RESULT_MISMATCH", "历史结果身份不一致", 409)
        source_task = self.app.history.source(conn, tid)
        _, path = self.app.artifacts.read_owned(
            source_task, archive["state_artifact"]["artifact_id"]
        )
        state = loads(path.read_bytes())
        final = state.get("final_output") or {}
        quality = final.get("quality_report") or {}
        structured = quality.get("output_state", {}).get("structured_data", {}).get("json", {})
        if name in {"records", "sources"}:
            # An explicitly saved empty final list is authoritative, never fallback.
            result = structured[name] if name in structured else final.get(name, [])
            if not isinstance(result, list):
                raise DomainError(
                    "LEGACY_RESOURCE_SCHEMA", "旧结果集合结构不受支持；原始归档仍可下载"
                )
            return [
                {**row, "protocol_version": 1, "legacy_version": 1}
                for row in result
                if isinstance(row, dict)
            ]
        if name == "quality":
            return {
                "protocol_version": 1,
                "legacy_version": 1,
                "quality_report": quality,
                "report_state": quality.get("report_state", {}),
            }
        if name == "figures":
            return []  # Old absolute paths do not authorize serving arbitrary files.
        if name == "insights":
            return [
                {
                    "delivery_id": result_id,
                    "legacy_report": final.get("insights")
                    or quality.get("report_state", {}).get("insights")
                    or {},
                }
            ]
        if name == "differences":
            return {
                "legacy_version": 1,
                "available": False,
                "reason": "not_reinterpreted_under_new_comparison_rules",
            }
        if name == "coverage":
            return [
                {
                    "legacy_version": 1,
                    "state": "not_revalidated",
                    "limitations": archive["limitations"],
                }
            ]
        raise DomainError("LEGACY_RESOURCE_UNAVAILABLE", "此历史资源未保存或不支持", 404)
