"Project authoritative task state for all entry adapters."

from __future__ import annotations

from astroquery_ai.runtime.codec import loads
from astroquery_ai.science.evidence_views import review_evidence
from astroquery_ai.science.results.preview_revision import preview_revision


def _execution_context(repo, conn, task_id):
    scopes = repo.objects(conn, task_id, 'pilot_scope')
    if not scopes:
        return None
    return {
        'mode': 'isolated_live_pilot',
        'scientific_profile_validated': False,
        'formal_release_ready': False,
        **{key: scopes[0][key] for key in ('maximum_body_works', 'maximum_core_pages_per_work', 'maximum_cost_micros')},
    }


def view(self, task_id, *, for_conversation=False, for_workspace=False, for_chat=False):
    with self.repository.read() as conn:
        return view_in_snapshot(self, conn, task_id, for_conversation=for_conversation or for_chat,
                                for_workspace=for_workspace, for_chat=for_chat)


def view_in_snapshot(self, conn, task_id, *, for_conversation=False, for_workspace=False, for_chat=False):
    repo = self.repository
    task = repo.task(conn, task_id)
    if task["kind"] == "replay":
        return self.history.view(conn, task)
    if task["kind"] == "legacy":
        return self.legacy.view(conn, task)
    # Fixed-input and imported histories can have a confirmed request and
    # reviews without ever passing through the interactive draft editor.
    row = conn.execute("SELECT payload FROM objects WHERE task_id=? AND kind='draft' AND object_id=? "
                       "ORDER BY version DESC LIMIT 1", (task_id,task_id)).fetchone()
    draft = loads(row[0]) if row else None
    if for_workspace:
        return _workspace_view(self, conn, task, draft)
    omission_context = self.omission_hash(draft) if draft is not None else None
    if for_conversation and draft is not None and task['query_ref'] and not draft.get('pending_question'):
        draft = {k: draft.get(k) for k in ('target', 'original_query', 'revision', 'status', 'last_error',
                                           'pause_reason', 'selected_property_ids', 'pending_question')}
    job_fields = ("json_extract(CAST(payload AS TEXT),'$.table_id') AS table_id,"
                  "json_extract(CAST(payload AS TEXT),'$.work_id') AS work_id") if for_conversation else "payload"
    jobs = [
        dict(row)
        for row in conn.execute(
            f"SELECT job_id,owner,kind,status,reason,{job_fields} FROM jobs WHERE task_id=? ORDER BY created_at",
            (task_id,),
        )
    ]
    for job in jobs:
        if for_conversation:
            job['payload'] = {k: v for k in ('table_id','work_id') if (v := job.pop(k)) is not None}
        else:
            job["payload"] = loads(job["payload"])
    from astroquery_ai.runtime.stages import JOB_STAGE, PRESENTATION_STAGE, current_stage

    execution_stage = current_stage(conn, task_id)
    if execution_stage:
        for job in jobs:
            job["execution_stage"] = JOB_STAGE.get(job["kind"])
        members = [j for j in jobs if j["execution_stage"] == execution_stage["stage_id"]]
        execution_stage = {
            **execution_stage,
            "completed": sum((j["status"] == "succeeded" for j in members)),
            "running": sum((j["status"] == "running" for j in members)),
            "pending": sum(
                (
                    j["status"] in {"ready", "waiting_dependency", "awaiting_review"}
                    for j in members
                )
            ),
            "waiting_resource": sum(
                (j["status"] == "ready" and j["reason"] == "waiting_resource" for j in members)
            ),
        }
    simulated_operator=any(s.get('schema_version')=='NormalQueryAcceptance/1'
        and s.get('task_id')==task_id and s.get('simulation_authorized') is True
        and s.get('operator_mode')=='simulation'
        for s in repo.objects(conn,task_id,'query_acceptance_run'))
    reviews = self.reviews.list(conn, task_id)
    for review in reviews:
        review["evidence_bundle"] = [
            review_evidence(repo, conn, task_id, ref)
            for ref in review["evidence_refs"]
        ]
    stages = []
    for stage, owners in ([] if for_chat else [
        ("understand", {"M01"}),
        ("retrieval", {"M03", "M04", "M05"}),
        ("extraction", {"M06"}),
        ("quality_check", {"M07", "review"}),
        ("clean", {"M08", "M09"}),
        ("deliver", {"M10", "M13"}),
        ("insight", {"M11"}),
    ]):
        items = [
            j
            for j in jobs
            if (
                PRESENTATION_STAGE[JOB_STAGE[j["kind"]]] == stage
                if execution_stage and j["kind"] in JOB_STAGE
                else j["owner"] in owners
            )
            and (not (j["owner"] == "M13" and j["kind"] != "finalize"))
        ]
        if stage == "retrieval":
            items += [j for j in jobs if j["kind"] == "start_science"]
        status = (
            "pending"
            if not items
            else "running"
            if any((j["status"] == "running" for j in items))
            else "failed"
            if any((j["status"] == "failed" for j in items))
            else "completed"
            if all((j["status"] == "succeeded" for j in items))
            else "waiting"
        )
        if (
            stage == "understand"
            and (not task["query_ref"])
            and draft is not None and (draft["status"] in {"waiting_input", "paused"})
        ):
            status = "waiting"
        if stage == "understand" and task["query_ref"]:
            status = "completed"
        if stage == "quality_check" and any(
            (r["status"] in {"pending", "accepted"} for r in reviews)
        ):
            status = "waiting"
        disabled_insights=False
        if stage=='insight' and task['insight_ref']:
            ref=loads(task['insight_ref']);report=repo.object(conn,task_id,'insight',ref['id'],ref['version'])
            disabled_insights=report.get('status')=='disabled_pending_content'
            if disabled_insights:status='not_run'
        stages.append(
            {
                "id": stage,
                "status": status,
                "jobs": items,
                "completed": sum((j["status"] == "succeeded" for j in items)),
                "total": len(items),
                **({'scope':'disabled_pending_content','reason':'新洞察待知识内容接入，本轮未启用'} if disabled_insights else {}),
            }
        )
    result = {
        'review_actor':{'simulation':simulated_operator,
            'kind':'simulated_test_operator' if simulated_operator else 'local_user'},
        **task,
        "status": task["lifecycle"],
        'execution_context': _execution_context(repo, conn, task_id),
        "protocol_version": 2,
        "source": "user",
        "draft": draft,
        "pending": draft.get("pending_question") if draft is not None else None,
        "reviews": reviews,
        "validation_alerts": repo.objects(conn, task_id, "post_delivery_validation"),
        "jobs": jobs,
        "stages": stages,
        "execution_stage": execution_stage,
        "omission_context_hash": omission_context,
        "core_event_cursor": task["last_event_seq"],
        "preview_revision": preview_revision(conn, task),
        "delivery_ref": loads(task["delivery_ref"]) if task["delivery_ref"] else None,
        "insight_ref": loads(task["insight_ref"]) if task["insight_ref"] else None,
        **({} if for_chat else {"messages": repo.objects(conn, task_id, "message")}),
    }

    if for_chat:
        from .presentation import presentation_in_snapshot
        result['presentation'] = presentation_in_snapshot(
            self, conn, task_id, include_chat_activity=True, reviews_data=reviews)
        for key in ('jobs', 'stages'):
            result.pop(key)
    return result


def _workspace_view(self, conn, task, draft):
    """Open results and execution without constructing the conversation."""
    from astroquery_ai.application.presentation import EXECUTION
    from astroquery_ai.runtime.stages import current_stage

    task_id = task['task_id']
    draft = draft or {}
    query_ref = loads(task['query_ref']) if task['query_ref'] else None
    delivery_ref = loads(task['delivery_ref']) if task['delivery_ref'] else None
    spec = (self.repository.object(conn, task_id, 'confirmed_query', query_ref['id'], query_ref['version'])
            if query_ref else {})
    bindings = spec.get('properties') or [binding for binding in (draft.get('property_support') or {}).get('bindings', [])
                                         if binding['property_id'] in draft.get('selected_property_ids', [])]
    stage = current_stage(conn, task_id)
    cursor = task['last_event_seq']
    pending = draft.get('pending_question')
    reviews = [{'review_id': review['review_id'], 'status': review['status']}
               for review in self.reviews.list(conn, task_id)] if task['lifecycle'] == 'waiting_review' else []
    return {
        'workspace_only': True,
        **{key: task[key] for key in ('task_id', 'kind', 'title', 'lifecycle', 'revision', 'science_state')},
        'status': task['lifecycle'], 'query_ref': task['query_ref'], 'delivery_ref': delivery_ref,
        'pending': {'title': pending.get('title')} if pending else None,
        'reviews': reviews, 'core_event_cursor': cursor,
        'preview_revision': preview_revision(conn, task),
        'execution_context': _execution_context(self.repository, conn, task_id),
        'validation_alerts': self.repository.objects(conn, task_id, 'post_delivery_validation'),
        'presentation': {
            'task_id': task_id, 'cursor': cursor, 'latest_cursor': cursor, 'historical': False,
            'lifecycle': task['lifecycle'], 'delivery_ref': delivery_ref,
            'target': spec.get('target') or draft.get('target'),
            'properties': [{'property_id': binding['property_id'], 'name': binding['definition']['name_cn']}
                           for binding in bindings],
            'active_stage': EXECUTION.get(stage['stage_id'], 'understand') if stage else 'understand',
            'request': {'original_query': draft.get('original_query') or spec.get('original_query'),
                        'confirmed': bool(spec)},
        },
    }
