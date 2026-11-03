"Project authoritative task state for all entry adapters."

from __future__ import annotations

from astroquery_ai.runtime.codec import loads
from astroquery_ai.science.evidence_views import review_evidence


def view(self, task_id, *, for_conversation=False):
    repo = self.repository
    with repo.read() as conn:
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
        pilot_scopes = repo.objects(conn, task_id, "pilot_scope")
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
        for stage, owners in [
            ("understand", {"M01"}),
            ("retrieval", {"M03", "M04", "M05"}),
            ("extraction", {"M06"}),
            ("quality_check", {"M07", "review"}),
            ("clean", {"M08", "M09"}),
            ("deliver", {"M10", "M13"}),
            ("insight", {"M11"}),
        ]:
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
        return {
            'review_actor':{'simulation':simulated_operator,
                'kind':'simulated_test_operator' if simulated_operator else 'local_user'},
            **task,
            "status": task["lifecycle"],
            "execution_context": {
                "mode": "isolated_live_pilot",
                "scientific_profile_validated": False,
                "formal_release_ready": False,
                "maximum_body_works": pilot_scopes[0]["maximum_body_works"],
                "maximum_core_pages_per_work": pilot_scopes[0]["maximum_core_pages_per_work"],
                "maximum_cost_micros": pilot_scopes[0]["maximum_cost_micros"],
            }
            if pilot_scopes
            else None,
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
            "delivery_ref": loads(task["delivery_ref"]) if task["delivery_ref"] else None,
            "insight_ref": loads(task["insight_ref"]) if task["insight_ref"] else None,
            "messages": repo.objects(conn, task_id, "message"),
        }
