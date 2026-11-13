"Build and seal the single scientific snapshot and final assessment."

from __future__ import annotations

from astroquery_ai.runtime.codec import canonical, content_hash, digest, loads

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import SourceMeasurement

from astroquery_ai.science.quality import assess

from astroquery_ai.science.differences import compare


def _unfinished_insights(repo,conn,tid,delivery,spec,reason):
    from ..property_insights import enabled
    if enabled(spec):
        from ..property_insight_generation import unfinished_report
    else:
        from ..author_insights import unfinished_report
    return unfinished_report(repo,conn,tid,delivery,spec,reason)


def current_delivery_measurements(records, dispositions):
    """Apply only version-bound source findings; preserve every original record."""
    current = {record["measurement_id"]: record for record in records}

    def matches(reference):
        record = current.get((reference or {}).get("id"))
        return (
            record is not None
            and record["revision"] == reference["version"]
            and (record["content_sha256"] == reference["content_sha256"])
        )

    def applies(disposition):
        if disposition.get("measurement_ref"):
            return matches(disposition["measurement_ref"])
        record = current.get(disposition["measurement_id"])
        return record is not None and record["content_sha256"] == disposition.get(
            "current_measurement_hash"
        )

    cleared = {
        (ref["id"], ref["content_sha256"])
        for d in dispositions
        if d["status"] == "owner_rechecked_eligible" and applies(d)
        for ref in d.get("resolves_disposition_refs", [])
    }
    excluded = {
        d["measurement_id"]
        for d in dispositions
        if d["status"] in {"not_supported", "unresolved_main"}
        and applies(d)
        and (
            not (
                d["status"] == "unresolved_main"
                and (not d.get("answer_ref"))
                and ((d.get("disposition_id"), content_hash(d)) in cleared)
            )
        )
    }
    mentions = {
        d["measurement_id"]
        for d in dispositions
        if d["status"] == "same_source_mention"
        and matches(d.get("measurement_ref"))
        and matches(d.get("canonical_ref"))
        and (d["canonical_ref"]["id"] not in excluded)
    }
    return [record for record in records if record["measurement_id"] not in excluded | mentions]


def current_derived_representations(records, bindings, history, selections):
    """Use the committed pointer, never incidental object ordering or best score."""
    outputs = {b["property_id"]: b["output_profile"] for b in bindings}
    pointers = {p["measurement_id"]: p for p in selections}
    current = []
    for record in records:
        output = outputs[record["property_ref"]["id"]]
        profile = {
            "id": output["profile_id"],
            "version": output["version"],
            "content_sha256": output["content_sha256"],
        }
        candidates = [
            d
            for d in history
            if d["measurement_id"] == record["measurement_id"]
            and d.get("source_representation_hash") == record["content_sha256"]
            and (d.get("output_profile_ref") == profile)
        ]
        pointer = pointers.get(record["measurement_id"])
        if pointer:
            if (
                pointer["source_hash"] != record["content_sha256"]
                or pointer["output_profile_ref"] != profile
            ):
                continue
            candidates = [
                d
                for d in candidates
                if d["derived_id"] == pointer["derived_ref"]["id"]
                and content_hash(d) == pointer["derived_ref"]["content_sha256"]
            ]
            if len(candidates) != 1:
                raise DomainError("DERIVED_REFERENCE_MISMATCH", "当前标准化结果的引用无法核验")
        elif len(candidates) > 1:
            raise DomainError(
                "DERIVED_CURRENT_UNRESOLVED", "历史标准化结果缺少唯一的当前引用，需要重新处理该项"
            )
        current.extend(candidates)
    return current


def preview(self, conn, task_id, *, offset=0, limit=100, expected_preview_id=None):
    """Read one transaction's provisional evidence; never publish or adjudicate."""
    repo = self.repository
    task = repo.task(conn, task_id)
    if (
        task["kind"] in {"legacy", "replay"}
        or task["science_state"] == "sealed"
        or (not task["query_ref"])
    ):
        raise DomainError("PREVIEW_UNAVAILABLE", "当前任务不提供临时科学数据预览", 409)
    query_ref = loads(task["query_ref"])
    spec = repo.object(conn, task_id, "confirmed_query", query_ref["id"], query_ref["version"])
    bindings = {b["property_id"]: b for b in spec["properties"]}
    records = repo.objects(conn, task_id, "measurement")
    dispositions = repo.objects(conn, task_id, "admission_disposition")
    eligible = {r["measurement_id"] for r in current_delivery_measurements(records, dispositions)}
    reviews = [
        dict(r)
        for r in conn.execute(
            "SELECT review_id,status,payload FROM reviews WHERE task_id=? AND status IN ('pending','accepted')",
            (task_id,),
        )
    ]
    pending_by_mid = {}
    for row in reviews:
        question = loads(row["payload"])
        mids = set(question["scope"].get("measurement_ids", []))
        for cid in question["scope"].get("candidate_ids", []):
            candidate = repo.object(conn, task_id, "candidate", cid)
            if candidate.get("current_measurement_ref"):
                mids.add(candidate["current_measurement_ref"]["id"])
        for mid in mids:
            pending_by_mid.setdefault(mid, []).append(row["review_id"])

    def linked(kind, reference):
        actual = repo.object(conn, task_id, kind, reference["id"], reference["version"])
        if content_hash(actual) != reference["content_sha256"]:
            raise DomainError("PREVIEW_REFERENCE_MISMATCH", "临时数据引用与原件版本不一致")
        return actual

    rows = []
    for record in records:
        context = linked("context", record["context_ref"])
        rows.append(
            {
                "source": record,
                "property_binding": bindings[record["property_ref"]["id"]],
                "target": spec["target"],
                "context": context,
                "source_document": linked("source", record["source_ref"]),
                "evidence": [linked("evidence", ref) for ref in record["evidence_refs"]],
                "source_statements": [
                    linked("source_statement", ref) for ref in context.get("source_statements", [])
                ],
                "review_ids": pending_by_mid.get(record["measurement_id"], []),
                "provisional_state": "under_review"
                if record["measurement_id"] in pending_by_mid
                else "collected"
                if record["measurement_id"] in eligible
                else "withheld_or_linked_mention",
            }
        )
    counts = {
        "source_records": len(records),
        "pending_questions": sum((r["status"] == "pending" for r in reviews)),
        "accepted_answers_awaiting_application": sum((r["status"] == "accepted" for r in reviews)),
        "unresolved_candidates": sum(
            (c["state"] == "review_candidate" for c in repo.objects(conn, task_id, "candidate"))
        ),
    }
    basis = {
        "task_id": task_id,
        "task_revision": task["revision"],
        "event_cursor": task["last_event_seq"],
        "query_ref": query_ref,
        "items": rows,
        "counts": counts,
    }
    preview_id = "preview-" + digest(basis)
    if expected_preview_id is not None and expected_preview_id != preview_id:
        raise DomainError("PREVIEW_CHANGED", "临时数据已有更新，请重新读取", 409)
    return {
        "schema_version": "ProvisionalSciencePreview/1",
        "task_id": task_id,
        "preview_id": preview_id,
        "task_revision": task["revision"],
        "event_cursor": task["last_event_seq"],
        "status": "provisional_read_only",
        "final_quality_available": False,
        "exportable": False,
        "counts": counts,
        "items": rows[max(0, offset) : max(0, offset) + min(max(1, limit), 500)],
        "total": len(rows),
    }


def delivery_provenance(snapshot):
    """Project existing snapshot evidence; citation background grants no measurements."""
    result = {
        key: snapshot[key]
        for key in [
            "interpretations",
            "derived_history",
            "derived_selections",
            "uncertainties",
            "unit_records",
            "error_bases",
            "admission_receipts",
            "source_checks",
            "qualifications",
            "human_answers",
            "reported_references",
            "cited_works",
            "citation_lookups",
            "source_statements",
            "source_mentions",
            "result_relationships",
            "source_rechecks",
            "source_review_applications",
            "reading_repairs",
            "source_measurements",
            "source_measurement_history",
            "review_applications",
            "validation_receipts",
            "processing_receipts",
            "normalization_changes",
            "normalization_proposal_checks",
            "uncertainty_interpretations",
            "science_condition_checks",
            "native_cell_inspections",
            "verification_scopes",
            "catalog_column_plans",
            "catalog_schemas",
            "catalog_documents",
            "catalog_document_observations",
            "catalog_identity_queries",
            "catalog_identity_limits",
            "target_astrometries",
            "object_matches",
            "pilot_scope",
        ]
    }
    for key in ('attachment_quality_scopes', 'attachment_quality_summaries', 'attachment_role_exclusions'):
        if key in snapshot:
            result[key] = snapshot[key]
    return result


def seal(self, conn, task_id: str, *, outcome="completed") -> dict:
    task = self.repository.task(conn, task_id)
    if task["science_state"] == "sealed":
        if task["delivery_ref"]:
            ref = loads(task["delivery_ref"])
            existing=self.repository.object(conn, task_id, "delivery", ref["id"], ref["version"])
            if outcome=='cancelled' and existing.get('report_state')=='pending_insights':
                qref=loads(task['query_ref']);spec=self.repository.object(conn,task_id,'confirmed_query',qref['id'],qref['version'])
                return finish_insights(self,conn,task_id,_unfinished_insights(self.repository,conn,task_id,existing,spec,'user_cancelled'),complete_task=False)
            return existing
        raise DomainError("INCOMPLETE_PUBLICATION", "已封口数据尚未完成交付")
    if not task["query_ref"]:
        raise DomainError("QUERY_NOT_CONFIRMED", "没有冻结规格，不能发布科学结果")
    active = conn.execute(
        "SELECT 1 FROM jobs WHERE task_id=? AND status IN ('ready','running','waiting_dependency','awaiting_review') AND kind<>'finalize' LIMIT 1",
        (task_id,),
    ).fetchone()
    producers = conn.execute("SELECT state FROM producers WHERE task_id=?", (task_id,)).fetchall()
    reviews = conn.execute("SELECT status FROM reviews WHERE task_id=?", (task_id,)).fetchall()
    if (
        active
        or not producers
        or any((p[0] != "closed" for p in producers))
        or any((r[0] in {"pending", "accepted"} for r in reviews))
    ):
        raise DomainError("SCIENCE_NOT_CLOSED", "生产、处理或审核事项尚未闭合")
    from astroquery_ai.runtime.stages import current_stage, set_stage

    staged = current_stage(conn, task_id) is not None
    if staged:
        set_stage(self.repository, conn, task_id, "postcheck")
    query = self.repository.object(conn, task_id, "confirmed_query", loads(task["query_ref"])["id"])
    from astroquery_ai.runtime.run_policy import consolidated
    unified=consolidated(query)
    source_records = self.repository.objects(conn, task_id, "measurement")
    from astroquery_ai.science.quality import check_native_dimension

    bindings = {b["property_id"]: b for b in query["properties"]}
    for record in source_records:
        check_native_dimension(
            self.repository, conn, task_id, record, bindings[record["property_ref"]["id"]]
        )
    dispositions = self.repository.objects(conn, task_id, "admission_disposition")
    records = current_delivery_measurements(source_records,
        [d for d in dispositions if d['status']!='same_source_mention'] if unified else dispositions)
    for record in records:
        SourceMeasurement.model_validate(record)
        for field, kind in [
            ("source_ref", "source"),
            ("interpretation_ref", "interpretation"),
            ("context_ref", "context"),
            ("admission_receipt_ref", "admission"),
            ("source_qualification_ref", "qualification"),
        ]:
            reference = record[field]
            actual = self.repository.object(
                conn, task_id, kind, reference["id"], reference["version"]
            )
            if content_hash(actual) != reference["content_sha256"]:
                raise DomainError(
                    "SNAPSHOT_REFERENCE_MISMATCH",
                    "科学快照的引用版本或哈希不一致",
                    field=field,
                    measurement_id=record["measurement_id"],
                )
        context = self.repository.object(
            conn, task_id, "context", record["context_ref"]["id"], record["context_ref"]["version"]
        )
        if context["measurement_ref"] != {
            "id": record["measurement_id"],
            "version": record["revision"],
        }:
            raise DomainError("CONTEXT_MEASUREMENT_MISMATCH", "上下文未绑定当前测量版本")
        for reference in context.get("source_statements", []):
            statement = self.repository.object(
                conn, task_id, "source_statement", reference["id"], reference["version"]
            )
            if (
                content_hash(statement) != reference["content_sha256"]
                or statement["measurement_id"] != record["measurement_id"]
                or statement["source_ref"] != record["source_ref"]
            ):
                raise DomainError("SNAPSHOT_CONTEXT_MISMATCH", "来源上下文与当前测量不一致")
        for reference in record.get("lineage_refs", []):
            if not reference["id"].startswith("reported-source-"):
                continue
            actual = self.repository.object(
                conn, task_id, "reported_source_ref", reference["id"], reference["version"]
            )
            if (
                content_hash(actual) != reference["content_sha256"]
                or actual["measurement_id"] != record["measurement_id"]
                or actual["source_ref"] != record["source_ref"]
                or (reference not in context["lineage_refs"])
            ):
                raise DomainError(
                    "SNAPSHOT_REFERENCE_MISMATCH", "原报参考代码未绑定当前测量、来源和上下文"
                )
    source_ids = {r["source_ref"]["id"] for r in records}
    sources = self.repository.objects(conn, task_id, "source")
    if source_ids - {s["source_id"] for s in sources}:
        raise DomainError("SOURCE_LINK_MISSING", "测量引用的来源不完整")
    context_refs = {r["context_ref"]["id"]: r["context_ref"]["version"] for r in records}
    contexts = [
        self.repository.object(conn, task_id, "context", cid, version)
        for cid, version in sorted(context_refs.items())
    ]
    derived_history = self.repository.objects(conn, task_id, "derived")
    derived_selections = self.repository.objects(conn, task_id, "derived_current")
    derived = current_derived_representations(
        records, query["properties"], derived_history, derived_selections
    )
    closure = {
        "reviews": [
            dict(r)
            for r in conn.execute(
                "SELECT review_id,status FROM reviews WHERE task_id=?", (task_id,)
            )
        ],
        "producers": [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM producers WHERE task_id=? ORDER BY producer_id", (task_id,)
            )
        ],
    }
    from astroquery_ai.science.evidence_views import build_views
    evidence=self.repository.objects(conn,task_id,'evidence')
    evidence_views=build_views(self.repository,conn,task_id,evidence,sources)
    snapshot = {
        "schema_version": "ScienceSnapshot/1",
        "query": query,
        "measurements": records,
        "derived": derived,
        "contexts": contexts,
        "sources": sources,
        "evidence": evidence,
        "evidence_views":evidence_views,
        "coverage": self.repository.objects(conn, task_id, "coverage"),
        "rejections": self.repository.objects(conn, task_id, "rejection"),
        "processing_receipts": self.repository.objects(conn, task_id, "processing_receipt"),
        "review_closure": closure,
        "admission_dispositions": dispositions,
        "source_measurements": source_records,
        "source_measurement_history": [
            loads(row[0])
            for row in conn.execute(
                "SELECT payload FROM objects WHERE task_id=? AND kind='measurement' ORDER BY object_id,version",
                (task_id,),
            )
        ],
        "outcome": outcome,
    }
    for field, kind in [
        ("interpretations", "interpretation"),
        ("derived_history", "derived"),
        ("derived_selections", "derived_current"),
        ("uncertainties", "uncertainty"),
        ("unit_records", "unit"),
        ("error_bases", "error_basis"),
        ("admission_receipts", "admission"),
        ("source_checks", "source_check"),
        ("qualifications", "qualification"),
        ("human_answers", "review_answer"),
        ("reported_references", "reported_source_ref"),
        ('cited_works','cited_work'),
        ('citation_lookups','citation_lookup'),
        ('reading_batch_states','reading_batch_state'),
        ("source_statements", "source_statement"),
        ("source_mentions", "source_mention"),
        ("source_rechecks", "source_recheck"),
        ("source_review_applications", "source_review_application"),
        ("reading_repairs", "reading_repair"),
        ("review_applications", "review_application"),
        ("validation_receipts", "validation_receipt"),
        ("normalization_changes", "change_event"),
        ("normalization_proposal_checks", "normalization_proposal_check"),
        ("uncertainty_interpretations", "uncertainty_interpretation_receipt"),
        ("science_condition_checks", "science_condition_check"),
        ("native_cell_inspections", "native_cell_inspection"),
        ("verification_scopes", "validation_scope"),
        ("catalog_column_plans", "catalog_column_plan"),
        ("catalog_schemas", "catalog_schema"),
        ("catalog_documents", "catalog_document"),
        ("catalog_document_observations", "catalog_document_observation"),
        ("catalog_identity_queries", "catalog_identity_query"),
        ("catalog_identity_limits", "catalog_identity_limitation"),
        ("target_astrometries", "target_astrometry"),
        ("object_matches", "object_match"),
        ("pilot_scope", "pilot_scope"),
    ]:
        snapshot[field] = self.repository.objects(conn, task_id, kind)
    if unified:
        from ..archive_comparison import current_reports
        snapshot['archive_comparisons']=current_reports(self.repository,conn,task_id,records)
        snapshot['archive_groups']=[g for r in snapshot['archive_comparisons'] for g in r['duplicates']]
        for kind in ('quality_candidate_root','quality_candidate_link','quality_decision','quality_reextraction_action',
                     'quality_reextraction_result','quality_batch_receipt','candidate','completion_scope'):
            snapshot[kind]=self.repository.objects(conn,task_id,kind)
        scope_refs = {ref['id']: ref for decision in snapshot['quality_decision']
                      if (ref := decision.get('shared_table_check_ref'))}
        if scope_refs:
            scopes = []
            for ref in scope_refs.values():
                scope = self.repository.object(conn, task_id, 'attachment_quality_scope', ref['id'], ref['version'])
                if content_hash(scope) != ref['content_sha256']:
                    raise DomainError('SNAPSHOT_REFERENCE_MISMATCH', '附表共享核验引用不一致')
                scopes.append({'reference': ref, 'scope': scope})
            snapshot['attachment_quality_scopes'] = scopes
        attachment_summaries = self.repository.objects(conn, task_id, 'attachment_quality_summary')
        if attachment_summaries:
            snapshot['attachment_quality_summaries'] = attachment_summaries
        exclusions = self.repository.objects(conn, task_id, 'attachment_role_exclusion')
        if exclusions:
            snapshot['attachment_role_exclusions'] = exclusions
    # Figures are evidence-only: they never enter numeric coverage, assessment
    # or comparisons. Their immutable payload is bound to this delivery.
    figures = self.repository.objects(conn, task_id, "figure")
    figure_coverage = self.repository.objects(conn, task_id, "figure_coverage")
    if figures or figure_coverage:
        snapshot["figures"] = figures
        snapshot["figure_coverage"] = figure_coverage
    from astroquery_ai.science.source_relationships import relationships

    snapshot["result_relationships"] = [] if unified else relationships(
        records,
        snapshot["source_mentions"],
        snapshot["reported_references"],
        snapshot["interpretations"],
    )
    snapshot_id = "science-" + digest(snapshot)
    snapshot_ref = self.repository.put_object(
        conn, task_id, "science_snapshot", snapshot_id, 1, snapshot
    )
    difference = {'schema_version':'ArchiveDifference/1','report_id':'difference-'+snapshot_id,
        'snapshot_ref':snapshot_ref,'archive_groups':snapshot['archive_groups'],
        'checks':snapshot['archive_comparisons'],
        'suspicions':[g for r in snapshot['archive_comparisons'] for g in r['suspicions']],
        'review_closure':closure['reviews'],'groups':[],
        'result_comparisons':{'schema_version':'ResultComparisons/1','groups':[]},
        'scope':'有据重复归档与明显疑似矛盾；不做统计/来源图/原因推断'} if unified else compare(
        records,
        derived,
        contexts,
        query["properties"],
        snapshot_ref,
        source_statements=snapshot["source_statements"],
        science_checks=snapshot["science_condition_checks"],
    )
    difference["result_relationships"] = snapshot["result_relationships"]
    difference_ref = self.repository.put_object(
        conn, task_id, "difference", difference["report_id"], 1, difference
    )
    groups = {
        s["source_id"]: s.get("known_source_group_id")
        or (
            "catalog-table-" + digest(s["table_id"])
            if s["kind"] == "catalog" and s.get("table_id")
            else s["source_id"]
        )
        for s in sources
    }
    checks = {
        c["measurement_id"]: c
        for c in [
            loads(row[0])
            for row in conn.execute(
                "SELECT payload FROM objects WHERE task_id=? AND kind='source_check' ORDER BY created_at,version",
                (task_id,),
            )
        ]
        if c.get("measurement_version")
        == next(
            (r["revision"] for r in records if r["measurement_id"] == c["measurement_id"]), None
        )
    }
    quality = {} if unified else assess(
        records,
        derived,
        [b["property_id"] for b in query["properties"]],
        snapshot_ref=snapshot_ref,
        source_groups=groups,
        source_cautions={mid: c.get("cautions", []) for mid, c in checks.items()},
        source_checks=checks,
    )
    quality["difference_ref"] = difference_ref
    quality["review_closure_ref"] = {
        "id": snapshot_id,
        "version": 1,
        "content_sha256": digest(closure),
    }
    quality_ref = None if unified else self.repository.put_object(
        conn, task_id, "quality", quality["report_id"], 1, quality
    )
    if staged:
        set_stage(self.repository, conn, task_id, "delivery")
    delivery = {
        "schema_version": "delivery/1",
        "task_id": task_id,
        "revision": 1,
        "snapshot_ref": snapshot_ref,
        "target": query["target"],
        "query_ref": loads(task["query_ref"]),
        "registry_ref": query["registry_release"],
        "status": "ready" if outcome == "completed" else "partial",
        "run_outcome": outcome,
        "measurements": records,
        "derived": derived,
        "contexts": contexts,
        "sources": sources,
        "definitions": query["properties"],
        "evidence_index": snapshot["evidence"],
        "evidence_views":snapshot['evidence_views'],
        "coverage": snapshot["coverage"],
        "dispositions": snapshot["rejections"],
        "quality": {"state": "available", "report_ref": quality_ref},
        "difference": {"state": "available", "report_ref": difference_ref},
        "result_comparisons": difference["result_comparisons"],
        "counts": {"accepted": len(records)},
    }
    if "figures" in snapshot:
        delivery["figures"] = snapshot["figures"]
        delivery["figure_coverage"] = snapshot["figure_coverage"]
    delivery["provenance_bundle"] = delivery_provenance(snapshot)
    from astroquery_ai.science.context_views import delivery_contexts

    delivery["resolved_contexts"] = delivery_contexts(delivery)
    delivery["current_source_check_refs"] = {
        mid: {"id": c["check_id"], "version": 1, "content_sha256": content_hash(c)}
        for mid, c in checks.items()
    }
    delivery_id = ('delivery-'+digest({'task_id':task_id,'snapshot_ref':snapshot_ref,'contract':'backend-consolidation/1'})) if unified else "delivery-" + digest(delivery)
    delivery["delivery_id"] = delivery_id
    if unified:
        from .export_validation import verify_formats
        from .task_score import calculate
        from ..author_knowledge import disabled_report
        delivery['archive_groups']=snapshot['archive_groups']
        delivery['comparison_checks']=snapshot['archive_comparisons']
        delivery['workflow_contract']='backend-consolidation/1'
        delivery['provenance_bundle'].update({k:snapshot[k] for k in (
            'quality_candidate_root','quality_candidate_link','quality_decision','quality_reextraction_action',
            'quality_reextraction_result','quality_batch_receipt','candidate','completion_scope')})
        # Publication is one atomic transaction. The delivery score is
        # conditional on the mandatory verification below succeeding; a
        # mismatch rolls back the score, snapshot and delivery together.
        # Serializing the pre-score body as well doubled sealing work and
        # could expire the job lease before the final commit.
        quality=calculate(self.repository,conn,task_id,query,snapshot,delivery_verified=True)
        quality.update(snapshot_ref=snapshot_ref,difference_ref=difference_ref,
            archive_groups=snapshot['archive_groups'],comparison_checks=snapshot['archive_comparisons'])
        quality_ref=self.repository.put_object(conn,task_id,'quality',quality['report_id'],1,quality)
        delivery['quality']={'state':'available','report_ref':quality_ref}
        delivery['task_score']=quality
        from ..author_release import enabled as author_enabled
        if author_enabled(query):
            from ..property_insights import enabled as property_enabled
            if property_enabled(query):
                from ..property_insights import pending_report
                delivery['export_schema_version']=2
            else:
                from ..author_insights import pending_report
            insight=pending_report(delivery,query.get('knowledge_release'))
        else:insight=disabled_report(delivery)
        insight_ref=self.repository.put_object(conn,task_id,'insight',insight['report_id'],1,insight)
        delivery['insight']={'state':insight['status'],'report_ref':insight_ref}
        if author_enabled(query):
            delivery['insight_report']=insight
            delivery['report_state']='pending_insights'
        verification=verify_formats(delivery)
        if verification['state'] != 'passed':
            raise DomainError('EXPORT_CONTENT_MISMATCH', '交付五格式核验未通过，不能发布快照或任务评分')
        self.repository.put_object(conn,task_id,'delivery_serialization_check',delivery_id,1,verification)
    ref = self.repository.put_object(conn, task_id, "delivery", delivery_id, 1, delivery)
    self.repository.mutate_task(
        conn, task_id, science_state="sealed", delivery_ref=canonical(ref).decode(), phase="insight",
        **({'insight_ref':canonical(insight_ref).decode()} if unified and author_enabled(query) else {})
    )
    self.repository.event(conn, task_id, "science_sealed", {"snapshot_ref": snapshot_ref})
    self.repository.event(
        conn, task_id, "delivery_ready", {"delivery_ref": ref, "counts": delivery["counts"]}
    )
    if unified and author_enabled(query) and outcome=='cancelled':
        return finish_insights(self,conn,task_id,_unfinished_insights(self.repository,conn,task_id,delivery,query,'user_cancelled'),complete_task=False)
    return delivery


def finish_insights(self,conn,task_id,report,*,complete_task=True):
    """Revise reports on the SAME immutable science snapshot, atomically."""
    from copy import deepcopy
    from ..author_release import enabled
    from .task_score import calculate
    from .export_validation import verify_formats
    task=self.repository.task(conn,task_id);delivery=self.get(conn,task_id)
    qref=loads(task['query_ref']);spec=self.repository.object(conn,task_id,'confirmed_query',qref['id'],qref['version'])
    from ..property_insights import enabled as property_enabled
    research=property_enabled(spec)
    expected_schema='InsightReport/4' if research else 'InsightReport/3'
    if not enabled(spec) or report['schema_version']!=expected_schema or report['status']=='pending' or task['science_state']!='sealed':
        raise DomainError('INSIGHT_PUBLICATION_MODE','新洞察不能改写旧任务或未封口数据')
    if report['snapshot_ref']!=delivery['snapshot_ref'] or report['delivery_id']!=delivery['delivery_id']:
        raise DomainError('INSIGHT_SNAPSHOT_CHANGED','解释与科学快照不一致')
    if delivery.get('report_state')=='final':
        if delivery['insight_report']==report:return delivery
        raise DomainError('INSIGHT_ALREADY_FINAL','已完成解释不可重复生成或覆盖')
    updated=deepcopy(delivery);revision=delivery['revision']+1
    if research:
        records={r['measurement_id']:r for r in delivery['measurements']}
        additions=[]
        for disposition in report.get('owner_rechecks',[]):
            record=records.get(disposition.get('measurement_id'))
            expected={'id':record['measurement_id'],'version':record['revision'],'content_sha256':record['content_sha256']} if record else None
            if (not record or disposition.get('measurement_ref')!=expected
                    or disposition.get('snapshot_ref')!=delivery['snapshot_ref']):
                raise DomainError('INSIGHT_RECHECK_SCOPE','责任复检不属于当前冻结记录')
            reference=disposition.get('source_recheck_ref')
            if reference:
                source_check=self.repository.object(conn,task_id,'source_recheck',reference['id'],reference['version'])
                if content_hash(source_check)!=reference['content_sha256']:
                    raise DomainError('INSIGHT_RECHECK_SCOPE','责任复检引用不一致')
                outcome=next((o for o in source_check['outcomes'] if o['item_ref']['id']==record['measurement_id']
                    and o['item_ref']['version']==record['revision'] and o['item_ref']['content_sha256']==record['content_sha256']),None)
                if not outcome:raise DomainError('INSIGHT_RECHECK_SCOPE','责任复检未覆盖该原记录')
                if disposition['status']=='not_supported':
                    attempt=conn.execute('SELECT owner,status FROM attempts WHERE task_id=? AND attempt_id=?',
                        (task_id,outcome.get('attempt_id'))).fetchone()
                    if (outcome['state']!='rejected' or outcome['verification']['state']!='rejected'
                            or not attempt or attempt['owner']!='M06' or attempt['status']!='settled'
                            or disposition.get('actual_attempt_ref')!=outcome['attempt_id']):
                        raise DomainError('INSIGHT_RECHECK_UNPROVEN','目标示例排除需要实际责任核验及原文反证')
            elif disposition['status']=='not_supported':
                raise DomainError('INSIGHT_RECHECK_UNPROVEN','没有责任复检引用不能排除目标示例')
            additions.append(disposition)
        existing={d.get('disposition_id'):d for d in updated.get('dispositions',[]) if d.get('disposition_id')}
        existing.update({d['disposition_id']:d for d in additions if d.get('disposition_id')})
        updated.update(dispositions=list(existing.values()),export_schema_version=2)
    insight_ref=self.repository.put_object(conn,task_id,'insight',report['report_id'],revision,report)
    snapref=delivery['snapshot_ref'];snapshot=self.repository.object(conn,task_id,'science_snapshot',snapref['id'],snapref['version'])
    score=calculate(self.repository,conn,task_id,spec,snapshot,delivery_verified=True,insight_report=report)
    score.update(snapshot_ref=snapref,difference_ref=delivery['difference']['report_ref'],
        archive_groups=delivery['archive_groups'],comparison_checks=delivery['comparison_checks'])
    quality_ref=self.repository.put_object(conn,task_id,'quality',score['report_id'],revision,score)
    updated.update(revision=revision,insight={'state':report['status'],'report_ref':insight_ref},
        insight_report=report,quality={'state':'available','report_ref':quality_ref},task_score=score,report_state='final')
    verification=verify_formats(updated)
    if verification['state']!='passed':raise DomainError('INSIGHT_EXPORT_INCONSISTENT','新洞察交付五格式不一致')
    self.repository.put_object(conn,task_id,'delivery_serialization_check',delivery['delivery_id'],revision,verification)
    ref=self.repository.put_object(conn,task_id,'delivery',delivery['delivery_id'],revision,updated)
    self.repository.mutate_task(conn,task_id,delivery_ref=canonical(ref).decode(),insight_ref=canonical(insight_ref).decode(),
        **({'lifecycle':'completed'} if complete_task else {}),phase='insight')
    self.repository.event(conn,task_id,'delivery_ready',{'delivery_ref':ref,'counts':updated['counts']})
    self.repository.event(conn,task_id,'insight_updated',{'report_ref':insight_ref,'status':report['status'],'delivery_ref':ref})
    if complete_task:self.repository.event(conn,task_id,'task_state_changed',{'lifecycle':'completed'})
    return updated


def delivery_reference(self, conn, task_id: str, delivery_id: str | None = None):
    task = self.repository.task(conn, task_id)
    if task["kind"] == "replay":
        row = conn.execute(
            "SELECT source_task_id FROM replay_sources WHERE replay_id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise DomainError("REPLAY_SOURCE_UNAVAILABLE", "回放源不可用", 410)
        captured = self.repository.object(conn, task_id, "replay_snapshot", task_id)
        reference = captured["source_delivery_ref"]
        if reference is None:
            raise DomainError("RESULT_NOT_READY", "原历史未保存交付结果", 410)
        if delivery_id is not None and reference["id"] != delivery_id:
            raise DomainError("DELIVERY_CHANGED", "回放绑定的交付版本不匹配")
        self.repository.task(conn, row[0])
        return row[0], reference
    if not task["delivery_ref"]:
        raise DomainError("RESULT_NOT_READY", "最终结果尚未就绪")
    ref = loads(task["delivery_ref"])
    if delivery_id is not None and delivery_id != ref["id"]:
        raise DomainError("DELIVERY_CHANGED", "结果版本已变化，请重新选择")
    return task_id, ref


def get(self, conn, task_id: str, delivery_id: str | None = None):
    source_task, ref = delivery_reference(self, conn, task_id, delivery_id)
    return self.repository.object(conn, source_task, "delivery", ref["id"], ref["version"])
