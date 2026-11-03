"science: processing: assessment.py operations; existing transactions and decisions retained."

from __future__ import annotations

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads


def scientific_candidate_question(candidate, definition, spec):
    """Only source-grounded, actionable scientific ambiguity reaches a human."""
    assembly = candidate.get('assembly_context', {})
    source = assembly.get('source', {})
    verification = assembly.get('paper_verification') or {}
    issue = verification.get('review_issue') if verification.get('reason') == 'scientific_ambiguity' else None
    if assembly.get('owner') == 'M03':
        issue = candidate['proposal'].get('catalog_review_issue')
        if issue:
            fields = {c['name']: c for c in source.get('metadata', {}).get('columns', [])}
            keys = [*issue['scope_columns'], *issue['support_columns'], *issue['counter_columns']]
            actions = [c['action'] for c in issue['choices']]
            if (any(k not in fields or not fields[k].get('description') for k in keys)
                    or 'unable' not in actions or len(actions) != len(set(actions))
                    or (issue['issue_kind'] == 'unit_semantics' and 'confirm' in actions)):
                return None
            issue = {**issue, 'column_evidence': {k: fields[k] for k in keys}}
    if not issue:
        return None
    cid = candidate['candidate_id']
    ref = {'id': cid, 'version': 1, 'content_sha256': content_hash(candidate)}
    shared_scope = issue.get('scope_evidence', issue.get('scope_columns'))
    if assembly.get('owner')=='M03':
        shared_scope={'columns':shared_scope,'row':candidate['proposal'].get('row')
                      if issue.get('scope_kind','matched_row')=='matched_row' else None}
    return {
        'origin': assembly['owner'], 'owner': assembly['owner'],
        'issue_kind': issue['issue_kind'], 'issue_key': issue['issue_key'],
        'group_key': digest({'source': content_hash(source), 'property': candidate['proposal']['property_id'],
                             'kind': issue['issue_kind'], 'scope': shared_scope,
                             'issue_key': issue['issue_key'], 'fact': issue['undecided_fact']}),
        'question': definition['name_cn'] + '：' + issue['question'],
        'scientific_issue': issue, 'choices': issue['choices'],
        'approved_conditions': definition['measurement_conditions_schema'],
        'impact': '仅对列出的候选和待决事实生效；原始值、误差和其他已核结论保持可追溯。',
        'scope': {'candidate_ids': [cid]},
        'basis': {'candidate_ref': ref, 'candidate_refs': {cid: ref}, 'spec_hash': spec['spec_hash'],
                  'current_measurement_ref': candidate.get('current_measurement_ref'),
                  'current_measurement_refs': {cid: candidate.get('current_measurement_ref')}},
        'evidence_refs': [candidate['evidence_ref']],
        'allowed_actions': [c['action'] for c in issue['choices']], 'correction_types': issue.get('correction_types', []),
        'current_interpretation': candidate['proposal'],
    }


def scientific_measurement_question(record, interpretation, verification, source, definition, spec):
    pseudo = {'candidate_id': record['measurement_id'], 'proposal': interpretation['proposal'],
              'assembly_context': {'owner': interpretation['producer'], 'source': source,
                                   'paper_verification': verification},
              'evidence_ref': record['evidence_refs'][0]}
    item = scientific_candidate_question(pseudo, definition, spec)
    if item:
        ref = {'id': record['measurement_id'], 'version': record['revision'],
               'content_sha256': record['content_sha256']}
        item['scope'] = {'measurement_ids': [record['measurement_id']], 'main_semantics': True}
        item['basis'] = {'measurement_ref': ref, 'measurement_refs': {record['measurement_id']: ref},
                         'spec_hash': spec['spec_hash']}
        item['evidence_refs'] = record['evidence_refs']
    return item


async def review_source_gap(self, job):
    """Legacy queued technical gaps remain gaps, never user questions."""
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        self.repo.put_object(
            conn,
            job["task_id"],
            "source_review_gap_application",
            job["job_id"],
            1,
            {
                "gap_id": job["payload"]["gap_id"],
                "measurement_ids": [],
                "reason": "owner_technical_failure_not_scientific_ambiguity",
                "new_model_calls": 0,
            },
        )
        self.repo.finish_job(conn, job)


async def apply_source_recheck(self, job):
    tid = job["task_id"]
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        ref = job["payload"]["recheck_ref"]
        report = self.repo.object(conn, tid, "source_recheck", ref["id"], ref["version"])
        spec = self.spec(conn, tid)
        protected = set()
        human_dispositions = [
            d for d in self.repo.objects(conn, tid, "admission_disposition") if d.get("answer_ref")
        ]
        for record in self.repo.objects(conn, tid, "measurement"):
            interpretation = self.repo.object(
                conn,
                tid,
                "interpretation",
                record["interpretation_ref"]["id"],
                record["interpretation_ref"]["version"],
            )
            if interpretation.get("human_answer_ref"):
                protected.add(record["measurement_id"])
            for disposition in human_dispositions:
                reference = disposition.get("measurement_ref") or {}
                if (
                    disposition.get("answer_ref")
                    and reference.get("id") == record["measurement_id"]
                    and (reference.get("version") == record["revision"])
                    and (reference.get("content_sha256") == record["content_sha256"])
                ):
                    protected.add(record["measurement_id"])
        for row in conn.execute(
            "SELECT payload FROM reviews WHERE task_id=? AND status IN ('pending','accepted')",
            (tid,),
        ):
            question = loads(row[0])
            protected.update(question["scope"].get("measurement_ids", []))
            for cid in question["scope"].get("candidate_ids", []):
                candidate = self.repo.object(conn, tid, "candidate", cid)
                if candidate.get("current_measurement_ref"):
                    protected.add(candidate["current_measurement_ref"]["id"])
        for outcome in report["outcomes"]:
            item_ref = outcome["item_ref"]
            if item_ref["kind"] == "measurement" and outcome.get("source_check"):
                current = self.repo.object(conn, tid, "measurement", item_ref["id"])
                if current["content_sha256"] == item_ref["content_sha256"]:
                    check = outcome["source_check"]
                    self.repo.put_object(conn, tid, "source_check", check["check_id"], 1, check)
            if item_ref["kind"] != "measurement" or item_ref["id"] in protected:
                continue
            record = self.repo.object(conn, tid, "measurement", item_ref["id"])
            if (
                record["content_sha256"] != item_ref["content_sha256"]
                or outcome["state"] == "not_verified"
            ):
                continue
            public_ref = {key: item_ref[key] for key in ("id", "version", "content_sha256")}
            if outcome["state"] == "passed":
                withdrawals = self.repo.objects(conn, tid, "source_review_technical_withdrawal")
                old = self.repo.objects(conn, tid, "admission_disposition")
                resolves = []
                for withdrawal in withdrawals:
                    row = conn.execute(
                        "SELECT status,answer FROM reviews WHERE task_id=? AND review_id=?",
                        (tid, withdrawal["review_id"]),
                    ).fetchone()
                    if (
                        withdrawal["measurement_ref"] != public_ref
                        or not row
                        or row["status"] != "closed_unanswered"
                        or (row["answer"] is not None)
                    ):
                        continue
                    resolves.extend(
                        (
                            {
                                "id": d["disposition_id"],
                                "version": 1,
                                "content_sha256": content_hash(d),
                            }
                            for d in old
                            if d["status"] == "unresolved_main"
                            and (not d.get("answer_ref"))
                            and (d.get("measurement_ref") == public_ref)
                            and (d.get("source_recheck_ref") == withdrawal["source_recheck_ref"])
                        )
                    )
                if resolves:
                    resolution = {
                        "measurement_id": record["measurement_id"],
                        "measurement_ref": public_ref,
                        "status": "owner_rechecked_eligible",
                        "resolves_disposition_refs": resolves,
                        "source_recheck_ref": ref,
                        "reason": "exact_failed_machine_check_repaired_and_owner_verified",
                        "human_answer_applied": False,
                    }
                    resolution["disposition_id"] = "disposition-" + digest(resolution)
                    self.repo.put_object(
                        conn,
                        tid,
                        "admission_disposition",
                        resolution["disposition_id"],
                        1,
                        resolution,
                    )
                continue
            interpretation = self.repo.object(
                conn,
                tid,
                "interpretation",
                record["interpretation_ref"]["id"],
                record["interpretation_ref"]["version"],
            )
            status = (
                "not_supported"
                if outcome["state"] == "rejected" and (not interpretation.get("human_answer_ref"))
                else "unresolved_main"
            )
            disposition = {
                "disposition_id": "disposition-"
                + digest({"record": public_ref, "review": ref, "status": status}),
                "measurement_id": record["measurement_id"],
                "measurement_ref": public_ref,
                "status": status,
                "reason": outcome["verification"]["reason"],
                "source_recheck_ref": ref,
            }
            self.repo.put_object(
                conn, tid, "admission_disposition", disposition["disposition_id"], 1, disposition
            )
            if status == "unresolved_main":
                binding = next(
                    (
                        b
                        for b in spec["properties"]
                        if b["property_id"] == record["property_ref"]["id"]
                    )
                )
                source = self.repo.object(conn, tid, 'source', record['source_ref']['id'], record['source_ref']['version'])
                question = scientific_measurement_question(record, interpretation, outcome['verification'], source, binding['definition'], spec)
                if question:
                    question['basis']['source_recheck_ref'] = ref
                    self.app.reviews.register(conn, tid, question)
                else:
                    self.repo.put_object(conn, tid, 'coverage', 'source-unresolved-' + digest(disposition), 1, {
                        'owner': 'M06', 'state': 'partial', 'reason': outcome['verification']['reason'],
                        'measurement_id': record['measurement_id'], 'source_recheck_ref': ref,
                        'human_question': False, 'original_measurement_retained': True})
        for group in report["same_results"]:
            if (
                not {"canonical_ref", "member_refs", "reason", "discriminator", "source_quotes"}
                <= group.keys()
            ):
                continue
            canonical_ref = group["canonical_ref"]
            prior_aliases = self.repo.objects(conn, tid, "admission_disposition")
            if any(
                (
                    d["status"] == "same_source_mention"
                    and d.get("measurement_ref") in group["member_refs"]
                    and (d["canonical_ref"] != canonical_ref)
                    for d in prior_aliases
                )
            ):
                continue
            canonical_record = self.repo.object(conn, tid, "measurement", canonical_ref["id"])
            if canonical_record["content_sha256"] != canonical_ref["content_sha256"]:
                continue
            for member in group["member_refs"]:
                if member["id"] == canonical_ref["id"]:
                    continue
                record = self.repo.object(conn, tid, "measurement", member["id"])
                if record["content_sha256"] != member["content_sha256"]:
                    continue
                disposition = {
                    "disposition_id": "disposition-"
                    + digest({"member": member, "canonical": canonical_ref, "review": ref}),
                    "measurement_id": member["id"],
                    "measurement_ref": member,
                    "status": "same_source_mention",
                    "canonical_ref": canonical_ref,
                    "source_recheck_ref": ref,
                    "reason": group["reason"],
                }
                if member["id"] not in protected:
                    self.repo.put_object(
                        conn,
                        tid,
                        "admission_disposition",
                        disposition["disposition_id"],
                        1,
                        disposition,
                    )
                mention = {
                    "measurement_id": canonical_ref["id"],
                    "current_measurement_hash": canonical_ref["content_sha256"],
                    "original_measurement_ref": member,
                    "relation": "same_author_reported_result",
                    "evidence_refs": record["evidence_refs"],
                    "source_recheck_ref": ref,
                    "discriminator": group["discriminator"],
                    "source_quotes": group["source_quotes"],
                }
                self.repo.put_object(
                    conn, tid, "source_mention", "mention-" + digest(mention), 1, mention
                )
        self.repo.put_object(
            conn,
            tid,
            "source_review_application",
            job["job_id"],
            1,
            {
                "recheck_ref": ref,
                "owner": "M07",
                "values_and_errors_overwritten": False,
                "existing_manual_reviews_unchanged": True,
                "protected_measurement_ids": sorted(protected),
            },
        )
        for outcome in report["outcomes"]:
            item = outcome["item_ref"]
            if item["kind"] == "measurement" and outcome["state"] == "passed":
                current = self.repo.object(conn, tid, "measurement", item["id"])
                if current["content_sha256"] == item["content_sha256"]:
                    self.repo.enqueue(
                        conn,
                        tid,
                        "M08",
                        "normalize",
                        {
                            "measurement_id": item["id"],
                            "source_hash": current["content_sha256"],
                            "source_context_check_ref": ref,
                        },
                    )
        self.repo.finish_job(conn, job)


async def assess_batch(self, job):
    tid = job["task_id"]
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        spec = self.spec(conn, tid)
        from astroquery_ai.runtime.run_policy import consolidated
        unified=consolidated(spec)
        for mid in job["payload"]["measurement_ids"]:
            record = self.repo.object(conn, tid, "measurement", mid)
            if unified:
                # Admission/semantic evidence was already checked in the one
                # quality pass. M08 consumes it and requests only missing
                # operation-specific facts, not another full original review.
                self.repo.enqueue(conn,tid,'M08','normalize',{'measurement_id':mid,'source_hash':record['content_sha256']})
                continue
            from astroquery_ai.science.quality import check_native_dimension

            binding = next(
                (b for b in spec["properties"] if b["property_id"] == record["property_ref"]["id"])
            )
            if not check_native_dimension(self.repo, conn, tid, record, binding):
                continue
            unresolved = [
                component
                for component in record["uncertainty"]["components"]
                if component["interpretation_state"] == "unresolved"
            ]
            interpretation = self.repo.object(
                conn,
                tid,
                "interpretation",
                record["interpretation_ref"]["id"],
                record["interpretation_ref"]["version"],
            )
            scoped_science = any(
                (
                    b["property_id"] == record["property_ref"]["id"] and b.get("science_ref")
                    for b in spec["properties"]
                )
            )
            missing_details = (
                self.source_error_details_missing(conn, tid, record, interpretation)
                if scoped_science
                else []
            )
            if (
                scoped_science
                and (not interpretation.get("human_answer_ref"))
                and missing_details
                and self.defer_error_interpretation(
                    conn, tid, record, interpretation, component_ids=missing_details
                )
            ):
                continue
            if (
                unresolved
                and (not scoped_science)
                and (not interpretation.get("human_answer_ref"))
                and self.defer_error_interpretation(conn, tid, record, interpretation)
            ):
                continue
            self.repo.enqueue(
                conn,
                tid,
                "M08",
                "normalize",
                {"measurement_id": mid, "source_hash": record["content_sha256"]},
            )
            reviewed_error_attempt = self._error_receipt(conn, tid, record)
            if (
                unresolved
                and (not scoped_science or reviewed_error_attempt is not None)
                and (not interpretation.get("human_answer_ref"))
                and self.error_needs_review(conn, tid, record)
            ):
                unresolved, detail = self.error_review_details(conn, tid, record, unresolved)
                if not unresolved:
                    continue
                owner = interpretation["producer"]
                binding = next(
                    (
                        item
                        for item in spec["properties"]
                        if item["property_id"] == record["property_ref"]["id"]
                    )
                )
                self.app.reviews.register(
                    conn,
                    tid,
                    {
                        "origin": owner,
                        "owner": owner,
                        "issue_kind": "uncertainty_semantics",
                        "issue_key": "uncertainty-" + record["content_sha256"],
                        "question": binding["definition"]["name_cn"]
                        + "：原文误差已经保存，但其形式或含义尚未解释清楚。请依据现有证据修正，或选择无法判断。"
                        + detail,
                        "impact": "仅影响这条测量的不确定度解释；已核验主值予以保留。",
                        "scope": {
                            "measurement_ids": [mid],
                            "component_ids": [item["component_id"] for item in unresolved],
                        },
                        "basis": {
                            "measurement_ref": {
                                "id": mid,
                                "version": record["revision"],
                                "content_sha256": record["content_sha256"],
                            },
                            "spec_hash": spec["spec_hash"],
                        },
                        "evidence_refs": record["evidence_refs"],
                        "allowed_actions": ["correct", "unable"],
                        "correction_types": ["correct_uncertainty"],
                        "current_interpretation": interpretation["proposal"],
                        "approved_conditions": binding["definition"][
                            "measurement_conditions_schema"
                        ],
                    },
                )
        for cid in job["payload"]["candidate_ids"]:
            if unified:
                continue  # The source/property quality planner owns these.
            candidate = self.repo.object(conn, tid, "candidate", cid)
            if candidate["state"] != "review_candidate" or not candidate.get("evidence_ref"):
                continue
            assembly = candidate.get("assembly_context", {})
            origin_job = conn.execute(
                "SELECT kind FROM jobs WHERE task_id=? AND job_id=?",
                (tid, assembly.get("batch_id")),
            ).fetchone()
            declared = next(
                (
                    p
                    for p in self.repo.objects(conn, tid, "candidate_pre_review_pending")
                    if p["candidate_id"] == cid
                    and p["candidate_ref"]["content_sha256"] == content_hash(candidate)
                ),
                None,
            )
            if (
                assembly.get("owner") == "M06"
                and (declared or (origin_job and origin_job["kind"] == "paper_batch"))
                and (not candidate.get("current_measurement_ref"))
            ):
                pending = {
                    "candidate_id": cid,
                    "candidate_ref": {
                        "id": cid,
                        "version": 1,
                        "content_sha256": content_hash(candidate),
                    },
                    "owner": "M06",
                    "source_id": assembly["source"]["source_id"],
                    "reason": "whole_source_owner_check_before_human",
                }
                self.repo.put_object(conn, tid, "candidate_pre_review_pending", cid, 1, pending)
                continue
            definition = next(
                (
                    binding["definition"]
                    for binding in spec["properties"]
                    if binding["property_id"] == candidate["proposal"]["property_id"]
                )
            )
            binding = next(
                (
                    b
                    for b in spec["properties"]
                    if b["property_id"] == candidate["proposal"]["property_id"]
                )
            )
            source = candidate.get("assembly_context", {}).get("source", {})
            from astroquery_ai.science.native_dimensions import contradiction

            field = next(
                (
                    c
                    for c in source.get("metadata", {}).get("columns", [])
                    if c["name"] == candidate["proposal"].get("column")
                ),
                None,
            )
            conflict = contradiction(
                field, binding["output_profile"], candidate["proposal"]["representation"]
            )
            if conflict and source.get("kind") in {"catalog", "official_attachment"}:
                evidence = {
                    "candidate_id": cid,
                    "reason": conflict["reason"],
                    "proof": conflict,
                    "source_ref": {
                        "id": source["source_id"],
                        "version": 1,
                        "content_sha256": content_hash(source),
                    },
                    "evidence_refs": [candidate["evidence_ref"]],
                    "owner": "M07",
                    "state": "not_supported",
                }
                self.repo.put_object(
                    conn, tid, "rejection", "native-candidate-" + digest(evidence), 1, evidence
                )
                version = conn.execute(
                    "SELECT max(version)+1 FROM objects WHERE task_id=? AND kind='candidate' AND object_id=?",
                    (tid, cid),
                ).fetchone()[0]
                self.repo.put_object(
                    conn,
                    tid,
                    "candidate",
                    cid,
                    version,
                    {**candidate, "state": "rejected", "rejection": evidence},
                )
                for row in conn.execute(
                    "SELECT review_id,payload FROM reviews WHERE task_id=? AND status='pending' AND answer IS NULL",
                    (tid,),
                ):
                    question = loads(row["payload"])
                    if question.get("basis", {}).get("candidate_ref", {}).get(
                        "content_sha256"
                    ) == content_hash(candidate):
                        conn.execute(
                            "UPDATE reviews SET status='closed_unanswered',application=? WHERE review_id=?",
                            (
                                canonical(
                                    {
                                        "status": "rejected_by_owner",
                                        "reason": conflict["reason"],
                                        "human_answer_applied": False,
                                    }
                                ),
                                row["review_id"],
                            ),
                        )
                        self.repo.event(
                            conn,
                            tid,
                            "review_withdrawn",
                            {
                                "review_id": row["review_id"],
                                "reason": conflict["reason"],
                                "human_answer_applied": False,
                            },
                        )
                continue
            question = scientific_candidate_question(candidate, definition, spec)
            if question:
                self.app.reviews.register(conn, tid, question)
            else:
                self.repo.put_object(conn, tid, 'candidate_processing_limit', cid, 1, {
                    'candidate_id': cid, 'candidate_ref': {'id': cid, 'version': 1,
                        'content_sha256': content_hash(candidate)},
                    'state': 'unresolved_not_admitted', 'reason': candidate['reason'],
                    'owner': assembly.get('owner'), 'evidence_refs': [candidate['evidence_ref']],
                    'human_question': False, 'original_candidate_retained': True,
                })
                self.repo.put_object(conn, tid, 'coverage', 'candidate-limit-' + cid, 1, {
                    'owner': assembly.get('owner'), 'state': 'partial', 'reason': candidate['reason'],
                    'candidate_id': cid, 'evidence_refs': [candidate['evidence_ref']],
                    'human_question': False, 'original_candidate_retained': True})
        self.repo.finish_job(conn, job)
