"Select and serialize the same sealed delivery; no alternative result store."

from __future__ import annotations

import csv

import io

import zipfile

from astroquery_ai.runtime.codec import canonical, digest, decimal_literal

from astroquery_ai.runtime.errors import DomainError


def csv_display(value):
    """Neutralize formula-like text; exact originals stay in structured JSON."""
    if not isinstance(value, str):
        return (value, False)
    stripped = value.lstrip(" \t\r\n")
    if stripped[:1] not in {"=", "+", "-", "@"}:
        return (value, False)
    try:
        decimal_literal(value)
        return (value, False)
    except ValueError:
        return ("'" + value, True)


def export(self, task_id: str, request: dict, *, origin: str | None = None) -> dict:
    allowed = {
        "operation_id",
        "task_id",
        "delivery_id",
        "expected_delivery_revision",
        "selection",
        "format",
        "export_schema_version",
    }
    if (
        set(request) != allowed
        or request["task_id"] != task_id
        or type(request["export_schema_version"]) is not int
        or request["export_schema_version"] not in {1, 2}
    ):
        raise DomainError("INVALID_EXPORT_REQUEST", "导出请求协议无效", 422)
    with self.repository.transaction() as conn:
        old = self.repository.replay_operation(conn, task_id, request["operation_id"], request)
        if old is not None:
            return old
        delivery = self.get(conn, task_id, request["delivery_id"])
        if request["expected_delivery_revision"] != delivery["revision"]:
            raise DomainError("DELIVERY_CHANGED", "交付版本已变化")
        selection = request["selection"]
        if set(selection) != {"mode", "measurement_ids"} or selection["mode"] not in {"all", "ids"}:
            raise DomainError("INVALID_EXPORT_SELECTION", "导出选择无效", 422)
        ids = selection["measurement_ids"]
        if (
            not isinstance(ids, list)
            or any((not isinstance(mid, str) for mid in ids))
            or len(ids) != len(set(ids))
        ):
            raise DomainError("INVALID_EXPORT_SELECTION", "导出ID不得重复或缺失", 422)
        if selection["mode"] == "all" and ids or (selection["mode"] == "ids" and (not ids)):
            raise DomainError("EMPTY_EXPORT_SELECTION", "未勾选任何记录", 422)
        available = {m["measurement_id"] for m in delivery["measurements"]}
        if set(ids) - available:
            raise DomainError("EXPORT_ID_NOT_IN_DELIVERY", "选择含其他版本或任务的记录", 422)
        selected = available if selection["mode"] == "all" else set(ids)
        body = {
            **delivery,
            "post_delivery_validation": self.repository.objects(
                conn, delivery["task_id"], "post_delivery_validation"
            ),
            "measurements": [
                m for m in delivery["measurements"] if m["measurement_id"] in selected
            ],
            "derived": [d for d in delivery["derived"] if d["measurement_id"] in selected],
            "contexts": [c for c in delivery["contexts"] if c["measurement_ref"]["id"] in selected],
            "resolved_contexts": [
                c
                for c in delivery.get("resolved_contexts", [])
                if c["measurement_ref"]["id"] in selected
            ],
            "export_selection": {
                "selected_ids": sorted(selected),
                "original_report_scope": delivery["snapshot_ref"],
            },
        }
        version = request['export_schema_version']
        if version == 2:
            body['export_metadata'] = {'origin': (origin or '').rstrip('/'), 'resource_task_id': task_id}
        if delivery.get("result_comparisons") is not None:
            from astroquery_ai.science.differences import select_result_comparisons

            body["result_comparisons"] = select_result_comparisons(
                delivery["result_comparisons"], selected
            )
        export_id = "export-" + digest(
            {
                "delivery": request["delivery_id"],
                "selection": sorted(selected),
                "format": request["format"],
                "generator": 'research-export/2' if version == 2 else 7 if body.get('insight_report',{}).get('schema_version')=='InsightReport/3' else 6 if body.get('workflow_contract')=='backend-consolidation/1' else 5,
                **({'export_schema_version': version, 'delivery_revision': delivery['revision'],
                    'export_metadata': body['export_metadata']} if version == 2 else {}),
                **({'delivery_revision':delivery['revision'],'insight_ref':delivery['insight']['report_ref'],
                    'quality_ref':delivery['quality']['report_ref']} if body.get('insight_report',{}).get('schema_version')=='InsightReport/3' else {}),
                "validation_annotations": body["post_delivery_validation"],
            }
        )
    data, media_type = self._serialize(body, request["format"],
        **({'export_schema_version': version} if version == 2 else {}))
    artifact = self.artifacts.write(data, media_type)
    with self.repository.transaction() as conn:
        old = self.repository.replay_operation(conn, task_id, request["operation_id"], request)
        if old is not None:
            return old
        current=self.get(conn, task_id, request["delivery_id"])
        if current['revision']!=delivery['revision']:
            raise DomainError('DELIVERY_CHANGED','导出期间报告修订已变化，请刷新后重试')
        self.artifacts.register(conn, task_id, export_id, artifact)
        manifest = {
            "schema_version": "ExportManifest/2" if version == 2 else "ExportManifest/1",
            "export_id": export_id,
            "task_id": task_id,
            "delivery_id": request["delivery_id"],
            **({'delivery_revision':delivery['revision'],'insight_ref':delivery['insight']['report_ref']}
               if body.get('insight_report',{}).get('schema_version')=='InsightReport/3' else {}),
            "snapshot_ref": delivery["snapshot_ref"],
            "selection": body["export_selection"],
            "format": request["format"],
            "status": "ready",
            "artifacts": [artifact],
            "selected_count": len(selected),
            **({'export_schema_version': version, 'delivery_revision': delivery['revision'],
                'insight_ref': delivery.get('insight', {}).get('report_ref')} if version == 2 else {}),
        }
        self.repository.put_object(conn, task_id, "export", export_id, 1, manifest)
        self.repository.event(
            conn, task_id, "export_updated", {"export_id": export_id, "status": "ready"}
        )
        self.repository.save_operation(conn, task_id, request["operation_id"], request, manifest)
        return manifest


def _serialize(body, format, *, _csv_long=None, export_schema_version=1):
    if export_schema_version == 2:
        from .research_export import serialize
        return serialize(body, format)
    if export_schema_version != 1:
        raise DomainError('INVALID_EXPORT_VERSION', '不支持此导出版本', 422)
    if format == "json":
        return (canonical(body), "application/json")
    outputs = {d["measurement_id"]: d for d in body["derived"]}
    reported_references = body.get("provenance_bundle", {}).get("reported_references", [])
    cited_works = {c['cited_work_id']:c for c in body.get('provenance_bundle',{}).get('cited_works',[])}
    aliases = {(m.get('original_measurement_ref') or {}).get('id'):m['measurement_id']
               for m in body.get('provenance_bundle',{}).get('source_mentions',[])}
    context_map = {c["measurement_ref"]["id"]: c for c in body["contexts"]}
    resolved_map = {c["measurement_ref"]["id"]: c for c in body.get("resolved_contexts", [])}
    statements = body.get("provenance_bundle", {}).get("source_statements", [])
    meta = {
        'evidence_views_json':body.get('evidence_views',[]),
        "snapshot_ref_json": body.get("snapshot_ref"),
        "registry_ref_json": body.get("registry_ref"),
        "property_bindings_json": body.get("definitions", []),
        "quality_json": body.get("quality"),
        "difference_json": body.get("difference"),
        "science_condition_checks_json": body.get("provenance_bundle", {}).get(
            "science_condition_checks", []
        ),
        "resolved_contexts_json": body.get("resolved_contexts", []),
        "result_relationships_json": [
            r
            for r in body.get("provenance_bundle", {}).get("result_relationships", [])
            if {m["measurement_id"] for m in body["measurements"]}.intersection(
                r["measurement_ids"]
            )
        ],
        "source_mentions_json": [
            r
            for r in body.get("provenance_bundle", {}).get("source_mentions", [])
            if r["measurement_id"] in {m["measurement_id"] for m in body["measurements"]}
        ],
        "export_selection_json": body.get("export_selection"),
    }
    # Preserve the resolved one-level bibliography even for entries without an
    # abstract. Per-record links below determine relevance; this background
    # never grants a new measurement or source-reading permission.
    for field in ('cited_works', 'citation_lookups'):
        if field in body.get('provenance_bundle', {}):
            meta[field + '_json'] = body['provenance_bundle'][field]
    if body.get('workflow_contract')=='backend-consolidation/1':
        meta.update(archive_groups_json=body.get('archive_groups',[]),task_score_json=body.get('task_score'))
    if body.get('insight_report',{}).get('schema_version')=='InsightReport/3':
        meta.update(insight_report_json=body['insight_report'],delivery_revision=body['revision'],
            insight_ref_json=body['insight']['report_ref'])
    if body.get("result_comparisons") is not None:
        meta["result_comparisons_json"] = {
            **body["result_comparisons"],
            "groups": [
                {
                    **{k: v for k, v in group.items() if k != "rows"},
                    "rows": [
                        {
                            k: row[k]
                            for k in (
                                "measurement_id",
                                "source_measurement_ref",
                                "context_ref",
                                "numeric_relation_state",
                                "numeric_relation_reason",
                            )
                        }
                        for row in group["rows"]
                    ],
                }
                for group in body["result_comparisons"]["groups"]
            ],
        }

    def statements_for(record):
        ids = {
            ref["id"]
            for ref in context_map.get(record["measurement_id"], {}).get("source_statements", [])
        }
        return [item for item in statements if item["statement_id"] in ids]

    def references_for(record):
        ids = {reference["id"] for reference in record.get("lineage_refs", [])}
        return [{**reference,'cited_work':cited_works.get(reference.get('cited_work_id'))}
            for reference in reported_references if reference['reference_id'] in ids
            or reference['measurement_id'] == record['measurement_id']
            or aliases.get(reference['measurement_id']) == record['measurement_id']]

    if format in {"json_wide", "csv_wide"}:
        wide = {}
        for record in body["measurements"]:
            wide.setdefault(record["property_ref"]["id"], []).append(
                {
                    "source": record,
                    "derived": outputs.get(record["measurement_id"]),
                    "reported_references": references_for(record),
                    "context": context_map.get(record["measurement_id"]),
                    "resolved_context": resolved_map.get(record["measurement_id"]),
                    "source_statements": statements_for(record),
                }
            )
        if format == "json_wide":
            return (
                canonical({"delivery_id": body["delivery_id"], "values": wide, "metadata": body}),
                "application/json",
            )
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            [
                "delivery_id",
                "post_delivery_validation_json",
                *meta,
                *[csv_display(key)[0] for key in wide],
            ]
        )
        writer.writerow(
            [
                body["delivery_id"],
                canonical(body.get("post_delivery_validation", [])).decode(),
                *[canonical(value).decode() for value in meta.values()],
                *[canonical(value).decode("utf-8") for value in wide.values()],
            ]
        )
        return (stream.getvalue().encode("utf-8-sig"), "text/csv")
    if format == "csv_long":
        stream = io.StringIO(newline="")
        fields = [
            "measurement_id",
            "property_id",
            "raw_value",
            "source_unit",
            "source_unit_declaration_json",
            "source_representation",
            "normalization_status",
            "uncertainty_source_json",
            "uncertainty_normalized_json",
            "source_measurement_json",
            "derived_json",
            "context_json",
            "resolved_context_json",
            "source_references_json",
            "source_statements_json",
            "post_delivery_validation_json",
            "delivery_id",
            "csv_text_escapes_json",
            *meta,
        ]
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        contexts = {c["measurement_ref"]["id"]: c for c in body["contexts"]}
        # Immutable task metadata is identical in every row. Encode it once,
        # keeping the existing CSV columns and their exact contents intact.
        encoded_meta = {key: canonical(value).decode() for key, value in meta.items()}
        annotations = canonical(body.get("post_delivery_validation", [])).decode()
        for record in body["measurements"]:
            mid = record["measurement_id"]
            derived = outputs.get(mid)
            display = {
                key: csv_display(value)
                for key, value in {
                    "raw_value": record["raw_value"],
                    "source_unit": record["unit"],
                    "source_representation": record["representation"],
                }.items()
            }
            writer.writerow(
                {
                    "measurement_id": mid,
                    "property_id": record["property_ref"]["id"],
                    **{key: value for key, (value, _) in display.items()},
                    "csv_text_escapes_json": canonical(
                        {
                            "policy": "apostrophe-prefix-1",
                            "escaped_fields": [
                                key for key, (_, escaped) in display.items() if escaped
                            ],
                            "original_values_in": "source_measurement_json",
                        }
                    ).decode(),
                    "normalization_status": derived["status"] if derived else "not_run",
                    "source_unit_declaration_json": canonical(
                        record.get("unit_declaration")
                    ).decode(),
                    "uncertainty_source_json": canonical(record["uncertainty"]).decode(),
                    "uncertainty_normalized_json": canonical(
                        derived["uncertainty_typed"] if derived else None
                    ).decode(),
                    "source_measurement_json": canonical(record).decode(),
                    "derived_json": canonical(derived).decode(),
                    "context_json": canonical(contexts.get(mid)).decode(),
                    "resolved_context_json": canonical(resolved_map.get(mid)).decode(),
                    "source_references_json": canonical(references_for(record)).decode(),
                    "source_statements_json": canonical(statements_for(record)).decode(),
                    "post_delivery_validation_json": annotations,
                    "delivery_id": body["delivery_id"],
                    **encoded_meta,
                }
            )
        return (stream.getvalue().encode("utf-8-sig"), "text/csv")
    if format == "package":
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("delivery.json", canonical(body))
            csv_bytes = _csv_long
            if csv_bytes is None:
                csv_bytes, _ = _serialize(body, "csv_long")
            archive.writestr("measurements.csv", csv_bytes)
            archive.writestr(
                "manifest.json",
                canonical(
                    {
                        "delivery_id": body["delivery_id"],
                        "files": {
                            "delivery.json": digest(body),
                            "measurements.csv": __import__("hashlib").sha256(csv_bytes).hexdigest(),
                        },
                    }
                ),
            )
        return (stream.getvalue(), "application/zip")
    raise DomainError("UNSUPPORTED_EXPORT_FORMAT", "不支持此导出格式", 422)
