"""Existing tasks HTTP routes; business services retain authority."""

from __future__ import annotations

from fastapi import Request

from astroquery_ai.runtime.codec import loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.reviews import ReviewAnswer


def register(app, application, scheduler):

    @app.post("/api/tasks")
    async def create(request: Request):
        body = await request.json()
        if not isinstance(body, dict) or not {"query", "operation_id"} <= set(body) or set(body) - {"query", "operation_id", "retrieval_preferences"}:
            raise DomainError("INVALID_CREATE_REQUEST", "创建查询协议无效", 422)
        result = application.create(body["query"], body["operation_id"], body.get("retrieval_preferences"))
        scheduler.wake.set()
        return result

    @app.get("/api/tasks")
    def listing(
        limit: int = 50, offset: int = 0, status: str | None = None, source: str | None = None,
        category: str | None = None, include_replays: bool = True
    ):
        conditions, arguments = (
            [
                "tasks.kind<>'validation'",
                "tasks.task_id NOT IN (SELECT task_id FROM task_tombstones)",
            ],
            [],
        )
        if source not in {None, "user", "sample"}:
            raise DomainError("TASK_SOURCE_FILTER", "任务来源筛选无效", 422)
        if source:
            conditions.append(
                "coalesce(json_extract(CAST(origin.payload AS TEXT),'$.source'),'user')=?"
            )
            arguments.append(source)
        if status:
            conditions.append("tasks.lifecycle=?")
            arguments.append(status)
        if not include_replays:
            conditions.append("tasks.kind<>'replay'")
        categories={
            'active':('queued','running','pausing','cancelling','clarifying'),
            'attention':('waiting_input','waiting_review','paused','interrupted'),
            'error':('failed','error','budget_exhausted','definition_invalidated'),
            'ended':('completed','cancelled','failed','error','budget_exhausted','definition_invalidated')}
        if category:
            if category not in categories:raise DomainError('TASK_CATEGORY_INVALID','任务分类无效',422)
            values=categories[category]
            conditions.append('tasks.lifecycle IN ('+','.join('?' for _ in values)+')')
            arguments.extend(values)
        where = " AND ".join(conditions)
        with application.repository.read() as conn:
            tables = "tasks LEFT JOIN objects origin ON origin.task_id=tasks.task_id AND origin.kind='task_origin' AND origin.object_id=tasks.task_id AND origin.version=1"
            total = conn.execute(
                "SELECT count(*) FROM " + tables + " WHERE " + where, arguments
            ).fetchone()[0]
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT tasks.*,origin.payload AS origin_json FROM "
                    + tables
                    + " WHERE "
                    + where
                    + " ORDER BY tasks.created_at DESC LIMIT ? OFFSET ?",
                    (*arguments, min(max(1, limit), 500), max(0, offset)),
                )
            ]
            for row in rows:
                ref = loads(row['query_ref']) if row.get('query_ref') else None
                if not isinstance(ref, dict):
                    continue
                saved = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='confirmed_query' "
                    "AND object_id=? AND version=?", (row['task_id'], ref.get('id'), ref.get('version'))).fetchone()
                if saved:
                    query = loads(saved[0])
                    target = query.get('target') or {}
                    row['display_identity'] = {'target': next(iter(target.get('user_mentions') or []), None) or target.get('main_id'),
                        'properties': ' · '.join(b['definition']['name_cn'] for b in query.get('properties', []) if (b.get('definition') or {}).get('name_cn')),
                        'question': query.get('original_query')}
        for row in rows:
            origin = loads(row.pop("origin_json") or "{}")
            row.update(
                status=row["lifecycle"],
                protocol_version=2,
                source=origin.get("source", "user"),
                legacy_version=origin.get("legacy_version"),
                replay_of=origin.get("replay_of"),
            )
        return {"items": rows, "total": total}

    @app.put("/api/tasks/{task_id}/title")
    async def rename(task_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"title"}:
            raise DomainError("INVALID_TITLE", "任务名请求无效", 422)
        return application.maintenance.rename(task_id, body["title"])

    @app.post("/api/tasks/{task_id}/replay")
    async def replay(task_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"speed", "operation_id"}:
            raise DomainError("INVALID_REPLAY", "回放请求无效", 422)
        return application.history.replay(task_id, body["speed"], body["operation_id"])

    @app.delete("/api/tasks/{task_id}")
    def remove_task(task_id: str, operation_id: str):
        return application.maintenance.cleanup(task_id, operation_id=operation_id, whole=True)

    @app.delete("/api/tasks/{task_id}/data")
    async def clean_task(task_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"operation_id", "parts"}:
            raise DomainError("INVALID_CLEANUP", "清理请求无效", 422)
        return application.maintenance.cleanup(
            task_id, operation_id=body["operation_id"], parts=body["parts"]
        )

    @app.post("/api/tasks/batch-delete")
    async def remove_many(request: Request):
        body = await request.json()
        if (
            not isinstance(body, dict)
            or set(body) != {"operation_id", "task_ids"}
            or (not isinstance(body["task_ids"], list))
            or (len(body["task_ids"]) > 100)
            or any((not isinstance(tid, str) for tid in body["task_ids"]))
        ):
            raise DomainError("INVALID_CLEANUP", "批量清理须提供不超过100个任务", 422)
        results = []
        for tid in dict.fromkeys(body["task_ids"]):
            try:
                results.append(
                    application.maintenance.cleanup(
                        tid, operation_id=body["operation_id"], whole=True
                    )
                )
            except DomainError as exc:
                results.append({"task_id": tid, "deleted": False, "error": exc.as_dict()})
        return {"results": results}

    @app.get("/api/tasks/{task_id}")
    @app.get("/api/tasks/{task_id}/state")
    def state(task_id: str, view: str | None = None):
        if view == 'workspace':
            return application.view(task_id, for_workspace=True)
        if view == 'conversation':
            return application.view(task_id, for_conversation=True)
        return application.view(task_id)

    @app.get('/api/tasks/{task_id}/presentation')
    def presentation(task_id: str, at_seq: int | None = None, include_chat_activity: bool = False, activity_limit: int = 5):
        from astroquery_ai.application.presentation import presentation as project
        return project(application,task_id,at_seq,include_chat_activity,activity_limit)

    @app.get('/api/tasks/{task_id}/replay-clock')
    def replay_clock(task_id: str):
        from astroquery_ai.application.presentation import replay_clock as clock
        return clock(application,task_id)

    @app.get('/api/tasks/{task_id}/execution')
    def execution(task_id: str, at_seq: int | None = None, stage_id: str | None = None,
                  category: str | None = None, offset: int = 0, limit: int = 100,
                  section: str | None = None, focus_seq: int | None = None,
                  job_id: str | None = None, status: str | None = None, search: str | None = None,
                  start: str | None = None, end: str | None = None, sort: str = 'time'):
        if section is None:
            from astroquery_ai.application.presentation import execution as project
            return project(application,task_id,at_seq,stage_id,category,offset,limit)
        from astroquery_ai.application.execution_view import read
        return read(application,task_id,at_seq,section,stage_id,category,offset,limit,
                    focus_seq,job_id,status,search,start,end,sort)

    @app.get('/api/tasks/{task_id}/execution/report')
    def execution_report(task_id: str, at_seq: int | None = None, format: str = 'json'):
        from fastapi.responses import Response
        from astroquery_ai.application.execution_report import report, json_bytes, pdf_bytes
        if format not in {'json', 'pdf'}:
            raise DomainError('EXECUTION_REPORT_FORMAT', '请选择PDF或JSON运行报告', 422)
        body = report(application,task_id,at_seq)
        raw = pdf_bytes(body) if format == 'pdf' else json_bytes(body)
        return Response(raw,media_type='application/pdf' if format == 'pdf' else 'application/json',
            headers={'Content-Disposition': f'attachment; filename="execution-{task_id}-{body["cursor"]}.{format}"'})

    @app.get("/api/tasks/{task_id}/property-catalog")
    def property_catalog(task_id: str, question_id: str):
        from astroquery_ai.query.drafts import catalog_context
        with application.repository.read() as conn:
            task = application.repository.task(conn, task_id)
            draft = application._draft(conn, task_id)
            question = draft.get("pending_question") or {}
            if (task["query_ref"] or draft["status"] != "waiting_input" or
                question.get("question_id") != question_id or not question.get("full_property_catalog")):
                raise DomainError("PROPERTY_CATALOG_CHANGED", "当前查询的适用性质已变化", 409)
            return {"catalog_context_hash": catalog_context(draft), "question_id": question_id,
                    "bindings": draft["property_support"]["bindings"]}

    @app.post("/api/tasks/{task_id}/draft-actions")
    async def draft_action(task_id: str, request: Request):
        result = application.draft_action(task_id, await request.json())
        scheduler.wake.set()
        return result

    @app.post("/api/tasks/{task_id}/review-answers")
    def answer(task_id: str, body: ReviewAnswer):
        if body.task_id != task_id:
            raise DomainError("TASK_MISMATCH", "审核答案所属任务不匹配", 422)
        result = application.reviews.answer(body)
        scheduler.wake.set()
        return result

    async def control(task_id: str, action: str, request: Request):
        if action not in {"pause", "continue", "cancel", "retry"}:
            raise DomainError("ACTION_REMOVED", "请使用具体的草稿、审核或任务控制接口", 410)
        body = await request.json()
        if set(body) != {"operation_id", "expected_revision"}:
            raise DomainError("INVALID_CONTROL_REQUEST", "任务控制协议无效", 422)
        result = application.repository.control(
            task_id,
            action,
            body["operation_id"],
            body["expected_revision"],
            finalizer=application.delivery.seal,
        )
        scheduler.wake.set()
        return result

    return control
