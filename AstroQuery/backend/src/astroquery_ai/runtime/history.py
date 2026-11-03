"""Immutable read-only replay. No jobs, questions, model calls or answer routes."""

from .codec import canonical, digest, loads, utcnow
from .errors import DomainError
from .models import TERMINAL


class History:
    def __init__(self, application):
        self.app, self.repo = application, application.repository

    def source(self, conn, tid):
        task = self.repo.task(conn, tid)
        if task["kind"] != "replay":
            return tid
        row = conn.execute("SELECT * FROM replay_sources WHERE replay_id=?", (tid,)).fetchone()
        if not row:
            raise DomainError("REPLAY_SOURCE_UNAVAILABLE", "回放源引用不可用", 410)
        self.repo.task(conn, row["source_task_id"])
        return row["source_task_id"]

    def replay(self, source_id, speed, operation_id):
        if type(speed) not in {int, float} or not 0.25 <= speed <= 100:
            raise DomainError("REPLAY_SPEED", "回放速度须在0.25至100倍之间", 422)
        source_view = self.app.view(source_id)
        if (
            source_view["kind"] not in {"live", "legacy"}
            or source_view["lifecycle"] not in TERMINAL
        ):
            raise DomainError("REPLAY_SOURCE_NOT_CLOSED", "仅可回放已结束的真实历史任务")
        with self.repo.read() as conn:
            request = {"source_task_id": source_id, "speed": speed}
            previous = self.repo.replay_operation(conn, source_id, operation_id, request)
            if previous:
                return previous
            timeline = []
            if source_view["kind"] == "legacy":
                archive = self.app.legacy.get(conn, source_id)
                timeline.extend(
                    {
                        "at": archive["original_created_at"],
                        "kind": "event",
                        "title": "历史原始事件",
                        "body": item,
                    }
                    for item in archive["events"]
                )
            for row in conn.execute(
                "SELECT payload,created_at FROM objects WHERE task_id=? AND kind='draft' ORDER BY version",
                (source_id,),
            ):
                question = loads(row["payload"]).get("pending_question")
                if question:
                    timeline.append(
                        {
                            "at": row["created_at"],
                            "kind": "question",
                            "title": question.get("title", "当时的问题"),
                            "body": question,
                        }
                    )
            for review in source_view["reviews"]:
                timeline.append(
                    {
                        "at": review["created_at"],
                        "kind": "question",
                        "title": review["question"],
                        "stage_id": "quality_check",
                        "body": {"review_id": review["review_id"], "impact": review["impact"], "evidence": review["evidence_bundle"]},
                    }
                )
                answer = review.get("answer")
                timeline.append(
                    {
                        "at": answer["received_at"] if answer else review["created_at"],
                        "kind": "answer",
                        "stage_id": "quality_check",
                        "review_id": review["review_id"],
                        "title": "原回答" if answer else "历史未保存回答",
                        "body": answer,
                    }
                )
            for message in source_view["messages"]:
                timeline.append(
                    {
                        "at": message.get("created_at", source_view["created_at"]),
                        "kind": "message",
                        "title": "原始输入",
                        "body": {"text": message["text"], "role": message["role"]},
                    }
                )
            for row in conn.execute(
                "SELECT payload FROM events WHERE task_id=? ORDER BY seq", (source_id,)
            ):
                event = loads(row[0])
                if event["kind"] in {
                    "query_confirmed",
                    "batch_committed",
                    "delivery_ready",
                    "science_sealed",
                    "insight_updated",
                    "task_state_changed",
                    "job_state_changed",
                    "execution_stage_changed",
                    "review_withdrawn",
                }:
                    timeline.append(
                        {
                            "at": event["committed_at"],
                            "kind": "event",
                            "title": event["kind"],
                            "body": {**event["payload"], "event_kind": event["kind"]},
                        }
                    )
            timeline.sort(key=lambda item: item["at"])
            from uuid import UUID

            try:
                UUID(operation_id)
            except (ValueError, TypeError) as exc:
                raise DomainError("INVALID_OPERATION_ID", "回放操作须使用UUID", 422) from exc
            rid = operation_id
            captured = {
                "schema_version": "ReplaySnapshot/1",
                "source_task_id": source_id,
                "source_revision": source_view["revision"],
                "source_delivery_ref": source_view["delivery_ref"],
                "source_view": source_view,
                "timeline": timeline,
                "speed": speed,
                "created_at": utcnow(),
                "scientific_execution": False,
            }
            result = {"task_id": rid, "source_task_id": source_id}

        def initialize(conn, task):
            current = self.repo.task(conn, source_id)
            if current["revision"] != source_view["revision"]:
                raise DomainError("REPLAY_SOURCE_CHANGED", "回放源在创建时已变化，请重试")
            self.repo.put_object(conn, rid, "replay_snapshot", rid, 1, captured)
            self.repo.put_object(
                conn,
                rid,
                "task_origin",
                rid,
                1,
                {
                    "source": source_view.get("source", "user"),
                    "legacy_version": source_view.get("legacy_version"),
                    "replay_of": source_id,
                },
            )
            conn.execute(
                "INSERT INTO replay_sources VALUES(?,?,?)",
                (rid, source_id, canonical({"snapshot_hash": digest(captured)})),
            )
            conn.execute(
                "UPDATE tasks SET lifecycle='completed',science_state='sealed',phase='replay' WHERE task_id=?",
                (rid,),
            )
            self.repo.event(
                conn,
                rid,
                "replay_created",
                {"source_task_id": source_id, "snapshot_hash": digest(captured)},
            )
            self.repo.save_operation(conn, source_id, operation_id, request, result)

        self.repo.create_task(
            "只读回放：" + source_view["title"], kind="replay", task_id=rid, initializer=initialize
        )
        with self.repo.read() as conn:
            return self.repo.replay_operation(conn, source_id, operation_id, request)

    def view(self, conn, task):
        captured = self.repo.object(conn, task["task_id"], "replay_snapshot", task["task_id"])
        source = captured["source_view"]
        return {
            **source,
            **task,
            "status": "completed",
            "protocol_version": 2,
            "source": "user",
            "pending": None,
            "reviews": [],
            "jobs": source["jobs"],
            "core_event_cursor": task["last_event_seq"],
            "delivery_ref": source["delivery_ref"],
            "insight_ref": source["insight_ref"],
            "replay": {**{k: v for k, v in captured.items() if k != "source_view"},
                       "saved_reviews": source.get("reviews", [])},
            "messages": [],
            "stages": source["stages"],
            "replay_of": captured["source_task_id"],
        }
