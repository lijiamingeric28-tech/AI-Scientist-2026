"science: processing: review_application.py operations; existing transactions and decisions retained."

from __future__ import annotations

from pydantic import ValidationError

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.science.measurements.contracts import MeasurementProposal

from astroquery_ai.runtime.reviews import corrected_proposal


async def apply_review(self, job):
    try:
        await self.apply_review_once(job)
    except (DomainError, ValidationError) as exc:
        code = getattr(exc, "code", "REVIEW_CORRECTION_SCHEMA")
        if code not in {
            "SOURCE_VALUE_TRANSCRIPTION_MISMATCH",
            "PROPERTY_VALUE_TYPE",
            "REVIEW_POSTCHECK_FAILED",
            "REVIEW_CORRECTION_SCHEMA",
        }:
            raise
        self.reopen_invalid_answer(job, code, getattr(exc, "details", {}))


def reopen_invalid_answer(self, job, code, details):
    tid = job["task_id"]
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        row = conn.execute(
            "SELECT * FROM reviews WHERE task_id=? AND review_id=?",
            (tid, job["payload"]["review_id"]),
        ).fetchone()
        if not row or row["status"] != "accepted":
            raise DomainError("REVIEW_APPLICATION_STALE", "审核状态已变化")
        item, answer = (loads(row["payload"]), loads(row["answer"]))
        item["revision"] += 1
        item["invalid_answer_count"] = item.get("invalid_answer_count", 0) + 1
        item["rejected_answer"] = answer
        item["validation_feedback"] = {
            "code": code,
            "reason": details.get("reason"),
            "message": "这次输入未通过原责任模块复检，尚未应用。请按保存的原件修正，或选择无法判断。",
        }
        if answer["action"] == "correct":
            item["current_interpretation"] = corrected_proposal(
                item["current_interpretation"], answer["correction"]
            )
        receipt = {
            "schema_version": "ReviewApplicationReceipt/1",
            "answer_id": answer["answer_id"],
            "status": "not_applied",
            "postcheck": "failed",
            "reason": code,
            "input_retained": True,
            "review_revision": item["revision"],
            "owner": item["owner"],
        }
        self.repo.put_object(conn, tid, "review_application", answer["answer_id"], 1, receipt)
        conn.execute(
            "UPDATE reviews SET revision=?,status='pending',payload=?,application=? WHERE task_id=? AND review_id=?",
            (item["revision"], canonical(item), canonical(receipt), tid, item["review_id"]),
        )
        self.repo.event(
            conn,
            tid,
            "review_validation_failed",
            {
                "review_id": item["review_id"],
                "review_revision": item["revision"],
                "reason": code,
                "input_retained": True,
            },
        )
        self.repo.finish_job(conn, job)
        if item["invalid_answer_count"] >= 3:
            inflight = conn.execute(
                "SELECT 1 FROM jobs WHERE task_id=? AND status='running'", (tid,)
            ).fetchone()
            self.repo.mutate_task(conn, tid, lifecycle="pausing" if inflight else "paused")
            self.repo.event(
                conn,
                tid,
                "review_correction_paused",
                {
                    "review_id": item["review_id"],
                    "reason": "three_invalid_answers",
                    "draft_retained": True,
                },
            )


async def apply_review_once(self, job):
    tid = job["task_id"]
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        row = conn.execute(
            "SELECT * FROM reviews WHERE review_id=? AND task_id=?",
            (job["payload"]["review_id"], tid),
        ).fetchone()
        if not row or row["status"] != "accepted":
            raise DomainError("REVIEW_APPLICATION_STALE", "审核答案已不再可应用")
        item, answer = (loads(row["payload"]), loads(row["answer"]))
        scope = item["scope"]
        human_context_keys = (
            [c["key"] for c in answer.get("correction", {}).get("conditions", [])]
            if answer.get("correction") and answer["correction"]["type"] == "correct_context"
            else scope.get("condition_keys", [])
            if item.get("issue_kind") == "condition_semantics"
            else []
        )
        results = []
        for cid in scope.get("candidate_ids", []):
            candidate = self.repo.object(conn, tid, "candidate", cid)
            basis = item['basis'].get('candidate_refs', {}).get(cid) or item["basis"]["candidate_ref"]
            if basis['id'] != cid:
                raise DomainError('REVIEW_BASIS_CHANGED', '审核未绑定此候选')
            if content_hash(candidate) != basis["content_sha256"]:
                raise DomainError("REVIEW_BASIS_CHANGED", "相关证据版本已变化")
            current = item['basis'].get('current_measurement_refs', {}).get(cid) if 'current_measurement_refs' in item['basis'] else item['basis'].get('current_measurement_ref')
            if current:
                existing = self.repo.object(conn, tid, "measurement", current["id"])
                if existing["content_sha256"] != current["content_sha256"]:
                    raise DomainError(
                        "REVIEW_BASIS_CHANGED", "相关测量解释已经变化，不能覆盖当前版本"
                    )
            if answer["action"] in {"confirm", "correct"}:
                proposal = (
                    corrected_proposal(candidate["proposal"], answer["correction"])
                    if answer["action"] == "correct"
                    else dict(candidate["proposal"])
                )
                proposal["ambiguity"] = None
                if not candidate.get("assembly_context"):
                    results.append(
                        {
                            "candidate_id": cid,
                            "status": "not_applied",
                            "reason": "assembly_binding_missing",
                        }
                    )
                else:
                    from copy import deepcopy
                    assembly = deepcopy(candidate['assembly_context'])
                    verification = assembly.get('paper_verification')
                    if verification and item.get('scientific_issue'):
                        verification['review_resolution'] = {
                            'answer_ref': answer['answer_ref'], 'action': answer['action'],
                            'issue_key': item['scientific_issue']['issue_key'],
                            'candidate_ref': basis,
                        }
                    assembled = self.extractor.assemble(
                        proposal=MeasurementProposal.model_validate(proposal),
                        human_answer_ref=answer["answer_ref"],
                        human_context_keys=human_context_keys,
                        **assembly,
                    )
                    if assembled["state"] != "admitted":
                        raise DomainError(
                            "REVIEW_POSTCHECK_FAILED",
                            "人工输入后准入条件仍未满足",
                            reason=assembled.get("reason"),
                        )
                    self.commit_candidates(conn, tid, [assembled], job["job_id"])
                    results.append({"candidate_id": cid, "status": assembled["state"]})
            else:
                results.append(
                    {
                        "candidate_id": cid,
                        "status": "unresolved_not_admitted"
                        if answer["action"] == "unable"
                        else "not_supported",
                    }
                )
        for mid in scope.get("measurement_ids", []):
            record = self.repo.object(conn, tid, "measurement", mid)
            basis = item['basis'].get('measurement_refs', {}).get(mid) or item['basis']['measurement_ref']
            if basis['id'] != mid:
                raise DomainError('REVIEW_BASIS_CHANGED', '审核未绑定此测量')
            if (
                content_hash(record) != basis["content_sha256"]
                or record["revision"] != basis["version"]
            ):
                raise DomainError("REVIEW_BASIS_CHANGED", "测量解释已变化，不能应用旧答案")
            if item.get('issue_kind')=='comparison_contradiction' and (
                    answer['action']!='correct' or answer.get('correction_measurement_id')!=mid):
                results.append({'measurement_id':mid,'status':'comparison_unresolved_preserved' if answer['action']=='unable' else 'comparison_checked_preserved',
                    **({'comparison_outcome': answer['comparison_outcome']} if answer.get('comparison_outcome') else {})})
                continue
            if answer["action"] == "not_supported":
                disposition = {
                    "disposition_id": "disposition-"
                    + digest({"measurement": mid, "answer": answer["answer_id"]}),
                    "measurement_id": mid,
                    "measurement_ref": basis,
                    "status": "not_supported",
                    "reason": answer["reason"],
                    "answer_ref": answer["answer_ref"],
                }
                self.repo.put_object(
                    conn,
                    tid,
                    "admission_disposition",
                    disposition["disposition_id"],
                    1,
                    disposition,
                )
                results.append({"measurement_id": mid, "status": "not_supported"})
            elif answer["action"] == "unable":
                results.append({"measurement_id": mid, "status": "unresolved_source_preserved"})
            else:
                spec = self.spec(conn, tid)
                interpretation = self.repo.object(
                    conn,
                    tid,
                    "interpretation",
                    record["interpretation_ref"]["id"],
                    record["interpretation_ref"]["version"],
                )
                proposal = (
                    corrected_proposal(interpretation["proposal"], answer["correction"])
                    if answer["action"] == "correct"
                    else dict(interpretation["proposal"])
                )
                proposal["ambiguity"] = None
                source = self.repo.object(
                    conn, tid, "source", record["source_ref"]["id"], record["source_ref"]["version"]
                )
                evidence = self.repo.object(conn, tid, "evidence", record["evidence_refs"][0]["id"])
                artifact = self.app.artifacts.read_owned(tid, evidence["artifact_ref"]["id"])[0]
                from copy import deepcopy
                verification = deepcopy(interpretation.get('paper_verification'))
                recheck_ref = item['basis'].get('source_recheck_ref')
                if recheck_ref and item.get('scientific_issue'):
                    recheck = self.repo.object(conn, tid, 'source_recheck', recheck_ref['id'], recheck_ref['version'])
                    if content_hash(recheck) != recheck_ref['content_sha256']:
                        raise DomainError('REVIEW_BASIS_CHANGED', '来源复核版本已变化')
                    outcome = next((o for o in recheck['outcomes'] if o['item_ref']['id'] == mid), None)
                    if not outcome or outcome['item_ref']['content_sha256'] != basis['content_sha256']:
                        raise DomainError('REVIEW_BASIS_CHANGED', '来源复核未绑定当前测量')
                    verification = deepcopy(outcome['verification'])
                    verification['review_resolution'] = {'answer_ref': answer['answer_ref'], 'action': answer['action'],
                        'issue_key': item['scientific_issue']['issue_key'], 'measurement_ref': basis}
                assembled = self.extractor.assemble(
                    spec=spec,
                    source=source,
                    artifact=artifact,
                    proposal=MeasurementProposal.model_validate(proposal),
                    owner=item["owner"],
                    batch_id=job["job_id"],
                    allowed_pages=[proposal["page"]],
                    matched_rows=[proposal["row"]],
                    revision=record["revision"] + 1,
                    human_answer_ref=answer["answer_ref"],
                    human_context_keys=human_context_keys,
                    measurement_id_override=mid,
                    paper_verification=verification,
                    object_binding_ref=evidence.get("object_binding_ref"),
                )
                if assembled["state"] != "admitted":
                    raise DomainError(
                        "REVIEW_POSTCHECK_FAILED",
                        "人工输入后准入条件仍未满足",
                        reason=assembled.get("reason"),
                    )
                self.commit_candidates(conn, tid, [assembled], job["job_id"])
                retained = bool(scope.get("component_ids")) and any(
                    (
                        component["interpretation_state"] == "unresolved"
                        for component in assembled["measurement"]["uncertainty"]["components"]
                    )
                )
                results.append(
                    {
                        "measurement_id": mid,
                        "status": "retained_unresolved" if retained else assembled["state"],
                    }
                )
        receipt = {
            "schema_version": "ReviewApplicationReceipt/1",
            "answer_id": answer["answer_id"],
            "status": "applied"
            if all((r["status"] != "not_applied" for r in results))
            else "not_applied",
            "owner": item["owner"],
            "results": results,
            "human_interpretation": True,
            **({'comparison_outcome': answer['comparison_outcome']} if answer.get('comparison_outcome') else {}),
        }
        receipt["postcheck"] = (
            "passed"
            if results and all((r["status"] in {"admitted", "not_supported",'comparison_checked_preserved'} for r in results))
            else "unresolved"
        )
        state = (
            "unable"
            if answer["action"] == "unable"
            else "resolved"
            if receipt["postcheck"] == "passed"
            else "retained_unresolved"
            if any((result["status"] == "retained_unresolved" for result in results))
            else "application_failed"
        )
        self.repo.put_object(conn, tid, "review_application", answer["answer_id"], 1, receipt)
        conn.execute(
            "UPDATE reviews SET status=?,application=? WHERE review_id=?",
            (state, canonical(receipt), item["review_id"]),
        )
        self.repo.event(
            conn, tid, "review_applied", {"review_id": item["review_id"], "receipt": receipt}
        )
        self.repo.finish_job(conn, job)
