"Apply owner-specific failure outcomes within the scheduler transaction."

from __future__ import annotations

from astroquery_ai.runtime.errors import DomainError


class JobFailures:
    def __init__(self, application):
        self.application, self.repository = (application, application.repository)

    def handle(self, conn, job, task, code, error):
        repo, tid = (self.repository, job["task_id"])
        if job["kind"] == "normalize":
            current_record = repo.object(conn, tid, "measurement", job["payload"]["measurement_id"])
            if (
                code == "NORMALIZATION_SOURCE_CHANGED"
                or current_record["content_sha256"] != job["payload"]["source_hash"]
            ):
                conn.execute(
                    "UPDATE jobs SET status='not_run',reason='NORMALIZATION_SOURCE_CHANGED',lease_token=NULL,lease_until=NULL WHERE job_id=?",
                    (job["job_id"],),
                )
                repo.event(
                    conn,
                    tid,
                    "normalization_input_superseded",
                    {
                        "job_id": job["job_id"],
                        "input_source_hash": job["payload"]["source_hash"],
                        "current_source_hash": current_record["content_sha256"],
                        "current_representation_unchanged": True,
                    },
                )
                return
        if task["lifecycle"] == "pausing" and code in {
            "DISPATCH_FORBIDDEN",
            "HTTP_DISPATCH_FORBIDDEN",
        }:
            conn.execute(
                "UPDATE jobs SET status='ready',reason='user_pause',lease_token=NULL,lease_until=NULL WHERE job_id=?",
                (job["job_id"],),
            )
            repo.mutate_task(conn, tid, lifecycle="paused", resume_required=1)
            repo.event(
                conn, tid, "task_state_changed", {"lifecycle": "paused", "reason": "user_pause"}
            )
            return
        conn.execute(
            "UPDATE jobs SET status='failed',reason=?,lease_token=NULL WHERE job_id=?",
            (code, job["job_id"]),
        )
        if job["kind"] == "prepare":
            draft = self.application._draft(conn, tid)
            draft["last_error"] = {
                "code": code,
                "message": error.message
                if isinstance(error, DomainError)
                else "准备请求未完成，已保留草稿",
                "retryable": True,
            }
            draft["pause_reason"] = (
                "registry_unavailable"
                if code.startswith(("REGISTRY", "PROPERTY", "CORRUPT_RELEASE"))
                else "service_error"
            )
            self.application._save_draft(conn, draft, lifecycle="paused")
        elif code == "DEFINITION_INVALIDATED":
            from astroquery_ai.runtime.codec import loads, digest

            conn.execute(
                "UPDATE jobs SET status='not_run',reason=?,lease_token=NULL WHERE task_id=? AND status IN ('ready','running','waiting_dependency','awaiting_review')",
                (code, tid),
            )
            conn.execute(
                "UPDATE producers SET state='closed',close_reason=?,revision=revision+1 WHERE task_id=? AND state='open'",
                (code, tid),
            )
            conn.execute(
                "UPDATE reviews SET status=CASE WHEN status='accepted' THEN 'closed_unapplied' ELSE 'closed_unanswered' END WHERE task_id=? AND status IN ('pending','accepted')",
                (tid,),
            )
            if task["science_state"] == "open" and task["query_ref"]:
                query = repo.object(conn, tid, "confirmed_query", loads(task["query_ref"])["id"])
                revoked = list(
                    conn.execute(
                        "SELECT revision,dependency_id,reason FROM revocations WHERE release_id=?",
                        (query["registry_release"]["id"],),
                    )
                )
                impacted = {
                    binding["property_id"]
                    for binding in query["properties"]
                    if any(
                        (
                            row["dependency_id"] is None
                            or row["dependency_id"]
                            in {ref["id"] for ref in binding["dependency_refs"]}
                            for row in revoked
                        )
                    )
                }
                quarantined = []
                for record in repo.objects(conn, tid, "measurement"):
                    if record["property_ref"]["id"] not in impacted:
                        continue
                    receipt = {
                        "measurement_id": record["measurement_id"],
                        "status": "not_supported",
                        "reason": code,
                        "origin": "definition_eligibility",
                        "current_measurement_hash": record["content_sha256"],
                        "revocation_revisions": [row["revision"] for row in revoked],
                    }
                    repo.put_object(
                        conn,
                        tid,
                        "admission_disposition",
                        "invalidated-" + digest(receipt),
                        1,
                        receipt,
                    )
                    quarantined.append(record["measurement_id"])
                repo.put_object(
                    conn,
                    tid,
                    "coverage",
                    "definition-invalidation",
                    1,
                    {
                        "owner": "M13",
                        "state": "partial",
                        "reason": code,
                        "affected_property_ids": sorted(impacted),
                        "quarantined_measurement_ids": quarantined,
                        "original_evidence_retained": True,
                    },
                )
                conn.execute("SAVEPOINT invalidated_delivery")
                try:
                    self.application.delivery.seal(conn, tid, outcome="definition_invalidated")
                    conn.execute("RELEASE invalidated_delivery")
                except Exception:
                    conn.execute("ROLLBACK TO invalidated_delivery")
                    conn.execute("RELEASE invalidated_delivery")
                    repo.event(
                        conn,
                        tid,
                        "delivery_failed",
                        {"reason": "definition_invalidation_finalization_failed"},
                    )
            repo.mutate_task(
                conn,
                tid,
                lifecycle="definition_invalidated",
                terminal_reason=code,
                generation=task["generation"] + 1,
            )
        elif job["kind"] in {"catalog_discover", "catalog_extract"} and code in {
            "CATALOG_DISPATCH_CLOSED", "CATALOG_WINDOW_EXPIRED"
        }:
            from astroquery_ai.runtime.run_policy import stop_job
            stop_job(repo, conn, job, code)
        elif job["kind"] in {"paper_figures", "paper_figure_page"} and code not in {
            "CAMPAIGN_BUDGET_EXHAUSTED", "TASK_MODEL_LIMIT", "TASK_HTTP_LIMIT"
        }:
            repo.put_object(conn, tid, "figure_coverage", job["job_id"], 1,
                {"source_id": job["payload"]["work_id"],
                 "page": job["payload"].get("candidate", {}).get("page"),
                 "state": "failed", "reason": code,
                 "meaning": "图证未完成，不等于没有相关图；数值交付继续"})
        elif code in {"CAMPAIGN_BUDGET_EXHAUSTED", "TASK_MODEL_LIMIT", "TASK_HTTP_LIMIT"}:
            conn.execute(
                "UPDATE jobs SET status='not_run',reason=? WHERE task_id=? AND status IN ('ready','waiting_dependency','awaiting_review')",
                (code, tid),
            )
            conn.execute(
                "UPDATE producers SET state='closed',close_reason=?,revision=revision+1 WHERE task_id=? AND state='open'",
                (code, tid),
            )
            conn.execute(
                "UPDATE reviews SET status=CASE WHEN status='accepted' THEN 'closed_unapplied' ELSE 'closed_unanswered' END WHERE task_id=? AND status IN ('pending','accepted')",
                (tid,),
            )
            conn.execute("SAVEPOINT budget_delivery")
            try:
                self.application.delivery.seal(conn, tid, outcome="budget_exhausted")
                conn.execute("RELEASE budget_delivery")
            except Exception:
                conn.execute("ROLLBACK TO budget_delivery")
                conn.execute("RELEASE budget_delivery")
                repo.event(conn, tid, "delivery_failed", {"reason": "budget_finalization_failed"})
            repo.mutate_task(
                conn,
                tid,
                lifecycle="budget_exhausted",
                terminal_reason=code,
                generation=task["generation"] + 1,
            )
        elif code in {
            "MODULE_MODEL_LIMIT",
            "MODULE_HTTP_LIMIT",
            "MODULE_HTTP_BYTE_LIMIT",
            "MODULE_HTTP_TIME_LIMIT",
            "MODULE_READING_LIMIT",
        } and job["owner"] in {"M03", "M06", "M08"}:
            conn.execute(
                "UPDATE jobs SET status='not_run',reason=?,lease_token=NULL WHERE task_id=? AND owner=? AND status IN ('ready','waiting_dependency','awaiting_review')",
                (code, tid, job["owner"]),
            )
            repo.put_object(
                conn,
                tid,
                "branch_closure",
                job["owner"],
                1,
                {"owner": job["owner"], "reason": code, "state": "budget_exhausted"},
            )
            repo.put_object(
                conn,
                tid,
                "coverage",
                "branch-budget-" + job["owner"],
                1,
                {
                    "owner": job["owner"],
                    "state": "partial",
                    "reason": code,
                    "unprocessed_scope": "remaining_authorized_branch_jobs",
                },
            )
            if job["owner"] == "M03":
                for name in ("catalog_hints", "catalog_discovery", "catalog_measurements"):
                    row = conn.execute(
                        "SELECT state,watermark FROM producers WHERE task_id=? AND producer_id=?",
                        (tid, name),
                    ).fetchone()
                    if row and row["state"] == "open":
                        repo.producer(
                            conn, tid, name, close_reason=code, watermark=row["watermark"]
                        )
                repo.close_failed_metadata_dependencies(conn, tid, code)
        elif job["kind"] == "insights" and task["science_state"] == "sealed":
            from astroquery_ai.runtime.codec import canonical

            delivery = self.application.delivery.get(conn, tid)
            from astroquery_ai.runtime.codec import loads
            qref=loads(task['query_ref']);spec=repo.object(conn,tid,'confirmed_query',qref['id'],qref['version'])
            from astroquery_ai.science.author_release import enabled as author_enabled
            if author_enabled(spec):
                from astroquery_ai.science.property_insights import enabled as property_enabled
                if property_enabled(spec):
                    from astroquery_ai.science.property_insight_generation import unfinished_report
                    report=unfinished_report(repo,conn,tid,delivery,spec,code)
                    self.application.delivery.finish_insights(conn,tid,report)
                    repo.event(conn,tid,'job_state_changed',{'job_id':job['job_id'],'status':'failed','reason':code})
                    return
                from astroquery_ai.science.author_insights import final_report
                plans=repo.objects(conn,tid,'author_insight_plan')
                units=[u for p in plans if p['snapshot_ref']==delivery['snapshot_ref'] for u in p['units']]
                checkpoints={p['unit']['unit_id']:p['unit'] for p in repo.objects(conn,tid,'author_insight_checkpoint')}
                for u in units:
                    if u['unit_id'] in checkpoints:u.update(checkpoints[u['unit_id']])
                    else:u.update(status='not_completed',reason=code)
                materials=[{'property_id':b['property_id'],
                    'measurements':[r for u in units if u['property_id']==b['property_id'] for r in u['measurements']],
                    'claims':[r for u in units if u['property_id']==b['property_id'] for r in u['claims']]} for b in spec['properties']]
                count=conn.execute("SELECT count(*) FROM attempts WHERE task_id=? AND owner='M11' AND status<>'not_dispatched'",(tid,)).fetchone()[0]
                report=final_report(delivery,spec,spec.get('knowledge_release'),materials,units,count)
                report.update(status='partial',reason=code)
                self.application.delivery.finish_insights(conn,tid,report)
                repo.event(conn,tid,'job_state_changed',{'job_id':job['job_id'],'status':'failed','reason':code})
                return
            report = {
                "schema_version": "InsightReport/1",
                "report_id": "insight-failure-" + delivery["delivery_id"],
                "delivery_id": delivery["delivery_id"],
                "snapshot_ref": delivery["snapshot_ref"],
                "status": "partial",
                "reason": code,
                "facts": [
                    {
                        "measurement_id": r["measurement_id"],
                        "source_value": r["value"],
                        "uncertainty": r["uncertainty"],
                    }
                    for r in delivery["measurements"]
                ],
                "theory": [],
                "units": [],
                "knowledge_release_ref": None,
                "limitations": ["解释未完成；数据、证据及导出保持可用。"],
            }
            ref = repo.put_object(conn, tid, "insight", report["report_id"], 1, report)
            repo.mutate_task(
                conn,
                tid,
                insight_ref=canonical(ref).decode(),
                lifecycle="completed",
                phase="insight",
            )
            repo.event(
                conn,
                tid,
                "insight_updated",
                {"report_ref": ref, "status": "partial", "reason": code},
            )
        elif job["kind"] == "apply_review" and code in {
            "REVIEW_BASIS_CHANGED",
            "REVIEW_APPLICATION_STALE",
        }:
            from astroquery_ai.runtime.codec import canonical

            receipt = {
                "status": "not_applied",
                "reason": code,
                "postcheck": "not_checked",
                "answer_id": job["payload"]["answer_id"],
            }
            conn.execute(
                "UPDATE reviews SET status='stale',application=? WHERE task_id=? AND review_id=? AND status='accepted'",
                (canonical(receipt), tid, job["payload"]["review_id"]),
            )
            repo.event(
                conn,
                tid,
                "review_not_applied",
                {"review_id": job["payload"]["review_id"], "receipt": receipt},
            )
        elif job["kind"] == "material_prepare":
            # This coordinator owns the still-open material ledger. Marking it
            # terminal leaves no job capable of closing that ledger, so the
            # whole query waits forever. Keep the checkpoint resumable instead.
            conn.execute("UPDATE jobs SET status='ready',lease_token=NULL,lease_until=NULL WHERE job_id=?",
                         (job["job_id"],))
            if job["attempt_count"] < 3:
                repo.event(conn, tid, "job_retry_scheduled",
                           {"job_id": job["job_id"], "reason": code,
                            "attempt": job["attempt_count"], "limit": 3})
            else:
                repo.mutate_task(conn, tid, lifecycle="interrupted", resume_required=1)
                repo.event(conn, tid, "orchestration_interrupted",
                           {"job_id": job["job_id"], "reason": code,
                            "operation": "material_preparation"})
            return
        elif job["kind"] not in {"start_science", "finalize", "apply_review"} and code not in {
            "DEFINITION_INVALIDATED",
            "PROFILE_NOT_VALIDATED",
            "PROVIDER_NOT_CONFIGURED",
            "SMOKE_NOT_PASSED",
            "ADS_NOT_CONFIGURED",
            "DISPATCH_FORBIDDEN",
            "HTTP_DISPATCH_FORBIDDEN",
        }:
            permanent = code in {
                "ATTEMPT_LIMIT",
                "MODULE_HTTP_LIMIT",
                "TASK_HTTP_LIMIT",
                "MODULE_HTTP_BYTE_LIMIT",
                "MODULE_HTTP_TIME_LIMIT",
                "PROPERTY_NOT_SELECTED",
                "PROPERTY_VALUE_TYPE",
                "SOURCE_REPRESENTATION_UNRESOLVED",
                "UNIT_CONVERSION_UNSUPPORTED",
                "MODEL_NUMERIC_CHECK_FAILED",
            }
            permanent = permanent or (
                code == "PROVIDER_HTTP_ERROR"
                and isinstance(error, DomainError)
                and (error.details.get("provider_status") in {400, 401, 403, 404})
            )
            if not permanent and job["attempt_count"] < 3:
                conn.execute("UPDATE jobs SET status='ready' WHERE job_id=?", (job["job_id"],))
                repo.event(
                    conn,
                    tid,
                    "job_retry_scheduled",
                    {
                        "job_id": job["job_id"],
                        "reason": code,
                        "attempt": job["attempt_count"],
                        "limit": 3,
                    },
                )
                return
            from astroquery_ai.runtime.codec import digest, loads

            failure_id = 'failed-job-' + job['job_id']
            failure_version = conn.execute("SELECT coalesce(max(version),0)+1 FROM objects WHERE task_id=? AND kind='coverage' AND object_id=?",
                (tid, failure_id)).fetchone()[0]
            repo.put_object(
                conn,
                tid,
                "coverage",
                failure_id,
                failure_version,
                {
                    "owner": job["owner"],
                    "job_id": job["job_id"],
                    "state": "failed",
                    "reason": code,
                    "scope": job["payload"],
                },
            )
            if job["kind"] == "interpret_uncertainty":
                mid = job["payload"]["measurement_id"]
                exists = conn.execute(
                    "SELECT 1 FROM objects WHERE task_id=? AND kind='uncertainty_interpretation_receipt' AND object_id=?",
                    (tid, job["job_id"]),
                ).fetchone()
                if not exists:
                    attempts = [
                        {"attempt_id": r["attempt_id"], "status": r["status"]}
                        for r in conn.execute(
                            "SELECT attempt_id,status FROM attempts WHERE job_id=? ORDER BY created_at,attempt_id",
                            (job["job_id"],),
                        )
                    ]
                    repo.put_object(
                        conn,
                        tid,
                        "uncertainty_interpretation_receipt",
                        job["job_id"],
                        1,
                        {
                            "schema_version": "UncertaintyInterpretationReceipt/1",
                            "receipt_id": job["job_id"],
                            "measurement_id": mid,
                            "input_hash": job["payload"]["source_hash"],
                            "output_hash": None,
                            "status": "not_checked",
                            "reason": code,
                            "outcomes": [],
                            "actual_attempt_refs": attempts,
                            "raw_source_replaced": False,
                            "human_answer_created": False,
                        },
                    )
                repo.enqueue(
                    conn,
                    tid,
                    "M07",
                    "assess_batch",
                    {"measurement_ids": [mid], "candidate_ids": [], "batch_id": job["job_id"]},
                )
            if job["kind"] == "normalize":
                from astroquery_ai.runtime.representations import commit_current_representation

                mid = job["payload"]["measurement_id"]
                record = repo.object(conn, tid, "measurement", mid)
                query_ref = loads(task["query_ref"])
                spec = repo.object(
                    conn, tid, "confirmed_query", query_ref["id"], query_ref["version"]
                )
                output = next(
                    (
                        b["output_profile"]
                        for b in spec["properties"]
                        if b["property_id"] == record["property_ref"]["id"]
                    )
                )
                output_ref = {
                    "id": output["profile_id"],
                    "version": output["version"],
                    "content_sha256": output["content_sha256"],
                }
                known_failure = code in {
                    "MODEL_NUMERIC_CHECK_FAILED",
                    "MODEL_SEMANTIC_CHANGE",
                    "NONFINITE_TRANSFORM",
                    "UNSUPPORTED_TRANSFORM",
                }
                result = {
                    "schema_version": "DerivedRepresentation/2",
                    "derived_id": "failed-"
                    + digest(
                        {"source": record["content_sha256"], "profile": output_ref, "reason": code}
                    ),
                    "measurement_id": mid,
                    "source_representation_hash": record["content_sha256"],
                    "output_profile_ref": output_ref,
                    "status": "failed" if known_failure else "not_checked",
                    "main_state": "failed" if known_failure else "not_checked",
                    "value_typed": None,
                    "uncertainty_typed": None,
                    "limit": record["limit"],
                    "issues": [{"code": code}],
                    "method": "not_verified",
                }
                commit_current_representation(repo, conn, tid, record, result, job=job)
            if job["kind"] == "catalog_discover":
                for name in ("catalog_hints", "catalog_discovery"):
                    repo.producer(conn, tid, name, close_reason=code)
                repo.close_failed_metadata_dependencies(conn, tid, code)
            if job["kind"] in {"literature_discover", "acquire_window"}:
                for name in (
                    ("literature_candidates", "selections", "attachment_discovery")
                    if job["kind"] == "literature_discover"
                    else ("selections", "attachment_discovery")
                ):
                    state = conn.execute(
                        "SELECT state,watermark FROM producers WHERE task_id=? AND producer_id=?",
                        (tid, name),
                    ).fetchone()
                    if state and state["state"] == "open":
                        repo.producer(
                            conn, tid, name, close_reason=code, watermark=state["watermark"]
                        )
        else:
            conn.execute("UPDATE jobs SET status='ready' WHERE job_id=?", (job["job_id"],))
            repo.mutate_task(conn, tid, lifecycle="interrupted", resume_required=1)
        repo.event(
            conn,
            tid,
            "job_state_changed",
            {"job_id": job["job_id"], "status": "failed", "reason": code},
        )
