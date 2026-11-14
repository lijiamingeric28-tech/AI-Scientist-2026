"Assemble evidence-backed source measurements with unchanged producer rules."

from __future__ import annotations

from astroquery_ai.science.measurements.uncertainty_components import assemble_uncertainties

from astroquery_ai.runtime.codec import content_hash, digest

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import SourceMeasurement, ComparisonContext

from astroquery_ai.science.measurements.admission_contracts import matches_proposal_hash

from astroquery_ai.science.measurements.contracts import MeasurementProposal, evidence_ref


class EvidenceExtractor:
    def __init__(self, application):
        self.app = application

    def assemble(
        self,
        *,
        spec: dict,
        source: dict,
        artifact: dict,
        proposal: MeasurementProposal,
        owner: str,
        batch_id: str,
        allowed_pages: list[int],
        matched_rows: list[int] | None = None,
        revision: int = 1,
        human_answer_ref: dict | None = None,
        measurement_id_override: str | None = None,
        paper_verification: dict | None = None,
        quality_verification: dict | None = None,
        component_parent_ids: dict[str, str] | None = None,
        object_binding_ref: dict | None = None,
        human_context_keys: list[str] | None = None,
    ) -> dict:
        if owner == "M06":
            from astroquery_ai.science.paper_admission import preserve_parenthetical_errors

            proposal = preserve_parenthetical_errors(proposal)
        doc = proposal.model_dump(mode="json")
        # Independent admission hashes the exact proposal before the server's
        # recorded integer→real type decoding. Numeric bytes are unchanged.
        from copy import deepcopy
        verified_proposal=deepcopy(doc)
        if object_binding_ref is not None:
            with self.app.repository.read() as conn:
                identity = self.app.repository.object(
                    conn,
                    spec["task_id"],
                    "object_match",
                    object_binding_ref["id"],
                    object_binding_ref["version"],
                )
            if (
                content_hash(identity) != object_binding_ref["content_sha256"]
                or identity["target_id"] != spec["target"]["target_id"]
                or identity["target_content_sha256"] != content_hash(spec["target"])
                or (identity["table_id"] != source.get("table_id"))
                or (doc["row"] not in identity["source_rows"])
                or (identity["source_artifact_ref"]["content_sha256"] != artifact["sha256"])
            ):
                raise DomainError("OBJECT_BINDING_MISMATCH", "对象匹配凭据不属于此来源、目标或原行")
        bindings = {p["property_id"]: p for p in spec["properties"]}
        if doc["property_id"] not in bindings:
            raise DomainError("PROPERTY_NOT_SELECTED", "来源提案越过已选性质权限", 422)
        binding = bindings[doc["property_id"]]
        definition = binding["definition"]
        if owner == "M06" and (doc["page"] not in allowed_pages or doc["location_kind"] == "catalog_cell"):
            raise DomainError("EVIDENCE_OUTSIDE_BATCH", "提案页或位置不属于实际读取批次")
        if owner == "M03" and (doc["row"] not in (matched_rows or []) or doc["location_kind"] != "catalog_cell"):
            raise DomainError("OBJECT_ROW_NOT_MATCHED", "表行尚未核实属于目标")
        locator = (
            {"page": doc["page"], "location_label": doc["location_label"]}
            if owner == "M06"
            else {"table": source["table_id"], "row": doc["row"], "column": doc["column"]}
        )
        evidence_id = "evidence-" + digest(
            {
                "artifact": artifact["sha256"],
                "locator": locator,
                "quote": doc["source_quote"],
                "source": evidence_ref(source, "source_id"),
                "paper_verification": paper_verification,
                **({"object_binding_ref": object_binding_ref} if object_binding_ref else {}),
            }
        )
        evidence = {
            "evidence_id": evidence_id,
            "artifact_ref": {
                "id": artifact["artifact_id"],
                "version": 1,
                "content_sha256": artifact["sha256"],
            },
            "source_id": source["source_id"],
            "kind": source["kind"],
            "locator": locator,
            "raw_text": doc["source_quote"],
            "text_origin": "model_transcription" if owner == "M06" else "original_cells",
            "available": True,
            "scope": "measurement",
            "truncated": False,
        }
        if paper_verification:
            evidence["local_admission_check"] = paper_verification
        if object_binding_ref:
            evidence["object_binding_ref"] = object_binding_ref
        evref = evidence_ref(evidence, "evidence_id")

        def candidate(reason):
            return {
                "state": "review_candidate",
                "reason": reason,
                "proposal": doc,
                "evidence": evidence,
                "evidence_ref": evref,
                "assembly_context": {
                    "spec": spec,
                    "source": source,
                    "artifact": artifact,
                    "owner": owner,
                    "batch_id": batch_id,
                    "allowed_pages": allowed_pages,
                    "matched_rows": matched_rows,
                    "paper_verification": paper_verification,
                    "object_binding_ref": object_binding_ref,
                    **({'quality_verification':quality_verification} if quality_verification else {}),
                },
            }

        from astroquery_ai.runtime.run_policy import consolidated
        quality_checked=bool(quality_verification and quality_verification.get('state')=='supported'
            and quality_verification.get('candidate_ref',{}).get('content_sha256')
            and quality_verification.get('model_attempt_ref'))
        if consolidated(spec) and not quality_checked and human_answer_ref is None:
            return candidate('pending_unified_quality')

        if owner == "M06":
            from astroquery_ai.science.paper_admission import native_numeric_conflict

            conflict = native_numeric_conflict(proposal)
            if conflict:
                return {
                    "state": "rejected",
                    "reason": "model_computed_native_value",
                    "proposal": doc,
                    "native_coordinate_check": conflict,
                    "original_artifact_ref": artifact,
                    "no_target_value_computed": True,
                }
        if owner == "M03" and doc.get("quantity_match") == "different":
            fields = {c["name"]: c for c in source.get("metadata", {}).get("columns", [])}
            anchors = doc.get("catalog_quantity_evidence", [])
            column = fields.get(doc.get("column"))
            original_definition = (
                (source.get("metadata", {}).get("catalog_document") or {})
                .get("parsed", {})
                .get("fields", {})
                .get(doc.get("column"), [])
            )
            if (
                column
                and doc["column"] in anchors
                and (set(anchors) <= fields.keys())
                and (column.get("description") or original_definition)
            ):
                return {
                    "state": "rejected",
                    "reason": "different_source_measurand_evidenced",
                    "proposal": doc,
                    "source_id": source["source_id"],
                    "source_column_evidence": column,
                    "source_document_evidence": original_definition,
                    "original_artifact_ref": artifact,
                    "no_value_or_error_changed": True,
                }
        if (
            doc["subject_role"] not in {"target", "unresolved"}
            or doc["result_role"] in {"assumption", "calibration_constant", "rejected_solution"}
            or doc["location_kind"] == "plot"
        ):
            return {
                "state": "rejected",
                "reason": "wrong_subject_result_role_or_plot",
                "proposal": doc,
            }
        if doc["source_quality"] and doc["source_quality"]["state"] == "invalid":
            return {"state": "rejected", "reason": "source_explicitly_invalid", "proposal": doc}
        if owner == "M06" and (
            doc["page"] not in allowed_pages or doc["location_kind"] == "catalog_cell"
        ):
            raise DomainError("EVIDENCE_OUTSIDE_BATCH", "提案页或位置不属于实际读取批次")
        if owner == "M03" and (
            doc["row"] not in (matched_rows or []) or doc["location_kind"] != "catalog_cell"
        ):
            raise DomainError("OBJECT_ROW_NOT_MATCHED", "表行尚未核实属于目标")
        if owner == "M03" and human_answer_ref is not None:
            from decimal import Decimal, InvalidOperation
            from astroquery_ai.runtime.codec import loads

            try:
                saved = loads(doc["source_quote"])
            except ValueError:
                saved = None
            if (
                isinstance(saved, dict)
                and isinstance(saved.get("cells"), dict)
                and (doc["column"] in saved["cells"])
            ):
                cell = saved["cells"][doc["column"]]
                if doc["value"]["kind"] in {"real", "integer"}:
                    try:
                        original_number = Decimal(cell.strip())
                    except (InvalidOperation, AttributeError):
                        pass
                    else:
                        if (
                            not original_number.is_finite()
                            or original_number != Decimal(doc["value"]["value"])
                            or doc["raw_value"] != cell
                        ):
                            raise DomainError(
                                "SOURCE_VALUE_TRANSCRIPTION_MISMATCH",
                                "修改值与保存的原始数值单元格不一致",
                            )
        value_kind = doc["value"]["kind"]
        expected_kind = definition["value_schema"]["kind"]
        typed_decoding = None
        if value_kind == 'integer' and expected_kind == 'real':
            typed_decoding = {'operation': 'integer_literal_in_real_measurand', 'original_model_value': dict(doc['value']),
                              'raw_source_preserved': True}
            doc['value'] = {**doc['value'], 'kind': 'real'}
            value_kind = 'real'
        if value_kind not in {expected_kind, *(["interval"] if expected_kind == "real" else [])}:
            raise DomainError("PROPERTY_VALUE_TYPE", "值类型与已批准定义不符")
        if (
            value_kind == "category"
            and doc["value"]["code"] not in definition["value_schema"]["categories"]
        ):
            return {"state": "rejected", "reason": "unapproved_category_code", "proposal": doc}
        if value_kind == "relation" and any(
            (
                doc["value"][key] != definition["value_schema"][key]
                for key in ("predicate_id", "subject_role", "object_role")
            )
        ):
            return {"state": "rejected", "reason": "relation_definition_mismatch", "proposal": doc}
        if owner == 'M06' and paper_verification and paper_verification['state'] == 'rejected':
            return {'state': 'rejected', 'reason': paper_verification['reason'],
                    'proposal': doc, 'paper_verification': paper_verification}
        if owner == 'M06' and human_answer_ref and paper_verification and paper_verification.get('review_issue'):
            resolution = paper_verification.get('review_resolution') or {}
            if (resolution.get('answer_ref') != human_answer_ref
                    or resolution.get('issue_key') != paper_verification['review_issue']['issue_key']
                    or resolution.get('action') not in {'confirm', 'correct'}
                    or (paper_verification['review_issue']['issue_kind'] == 'unit_semantics'
                        and resolution.get('action') == 'confirm')):
                return candidate('scientific_ambiguity_not_resolved')
            if paper_verification['review_issue']['issue_kind'] == 'object_semantics':
                doc['subject_role'] = 'target'
            if paper_verification['review_issue']['issue_kind'] == 'quantity_semantics':
                doc['quantity_match'] = 'exact'
        if owner == "M06" and human_answer_ref is None:
            if (binding.get('output_profile',{}).get('representation',{}).get('native_coordinate_only')
                    and doc['representation'] != binding['output_profile']['representation']['kind']):
                return {'state':'rejected', 'reason':'requested_native_coordinate_not_reported',
                        'proposal':doc, 'original_artifact_ref':artifact, 'no_target_value_computed':True}
            if not paper_verification or not matches_proposal_hash(
                verified_proposal, paper_verification.get("proposal_hash")
            ):
                return candidate("local_subject_or_result_evidence_unresolved")
            if paper_verification["state"] == "rejected":
                return {
                    "state": "rejected",
                    "reason": paper_verification["reason"],
                    "proposal": doc,
                    "paper_verification": paper_verification,
                }
            if paper_verification["state"] != "passed":
                return candidate(paper_verification["reason"])
        if (
            owner == "M03"
            and human_answer_ref is None
            and (doc.get("quantity_match") == "unresolved")
        ):
            return candidate("source_quantity_semantics_unresolved")
        if doc["subject_role"] == "unresolved" or doc["result_role"] == "unresolved":
            if human_answer_ref is None:
                return candidate("local_subject_or_result_evidence_unresolved")
        from astroquery_ai.science.unit_declarations import catalog_unit_declaration

        unit_declaration = (
            catalog_unit_declaration(source, doc["column"], proposed_unit=doc["unit"])
            if owner == "M03" and doc["value"]["kind"] in {"real", "integer", "interval"}
            else None
        )
        if unit_declaration is None:
            from astroquery_ai.science.unit_declarations import dimensionless_coordinate_declaration
            unit_declaration=dimensionless_coordinate_declaration(doc,binding,paper_verification,
                {'id':artifact['artifact_id'],'version':1,'content_sha256':artifact['sha256']})
        if unit_declaration is None:
            from astroquery_ai.science.unit_declarations import count_unit_declaration
            unit_declaration=count_unit_declaration(source,doc,binding,paper_verification=paper_verification,
                artifact_ref={'id':artifact['artifact_id'],'version':1,'content_sha256':artifact['sha256']})
        if unit_declaration:
            doc["unit"] = None
        if (
            expected_kind in {"real", "integer"}
            and (not doc["unit"])
            and (unit_declaration is None)
        ):
            return candidate("source_unit_missing")
        if doc["ambiguity"]:
            return candidate(doc["ambiguity"])
        mid = measurement_id_override or "measurement-" + digest(
            {
                "task": spec["task_id"],
                "artifact": artifact["sha256"],
                "source": evidence_ref(source, "source_id"),
                "locator": locator,
                "property": binding["property_id"],
                "role": doc["result_role"],
                "quote": doc["source_quote"],
                "raw_value": doc["raw_value"],
                "conditions": doc["conditions"],
            }
        )
        interpretation = {
            "interpretation_id": "interpretation-"
            + digest(
                {
                    "measurement": mid,
                    "proposal": doc,
                    "human_answer_ref": human_answer_ref,
                    "batch_id": batch_id,
                }
            ),
            "revision": revision,
            "measurement_id": mid,
            "proposal": doc,
            "producer": owner,
            "evidence_refs": [evref],
            "batch_id": batch_id,
            "human_answer_ref": human_answer_ref,
            "paper_verification": paper_verification,
            **({'quality_verification':quality_verification} if quality_verification else {}),
            "interpretation_kind": "human_interpretation"
            if human_answer_ref
            else "model_interpretation",
        }
        if typed_decoding:
            interpretation['structural_decoding'] = typed_decoding
        ir = evidence_ref(interpretation, "interpretation_id")
        unit = {
            "unit_id": "unit-"
            + digest(
                {
                    "source": source["source_id"],
                    "unit": doc["unit"],
                    "representation": doc["representation"],
                    "parameters": doc["representation_parameters"],
                    "evidence": evref,
                    **({"declaration": unit_declaration} if revision > 1 and unit_declaration else {}),
                }
            ),
            "unit_text": doc["unit"],
            "representation": doc["representation"],
            "parameters": doc["representation_parameters"],
            "evidence_refs": [evref],
            **({"unit_declaration": unit_declaration} if unit_declaration else {}),
        }
        ur = evidence_ref(unit, "unit_id")
        components, component_units, bases, uncertainty_state = assemble_uncertainties(
            doc=doc,
            source=source,
            owner=owner,
            mid=mid,
            evref=evref,
            ur=ur,
            ir=ir,
            component_parent_ids=component_parent_ids,
            main_unit_declaration=unit_declaration,
        )
        context_id = "context-" + digest(mid)
        admission = {
            "receipt_id": "admission-" + digest({"mid": mid, "interpretation": ir}),
            "owner": owner,
            "status": "passed",
            "checks": [
                "frozen_property",
                "matched_subject",
                "reported_result_role",
                "actual_batch_locator",
                "typed_value",
            ],
            "evidence_refs": [evref],
        }
        admission_ref = evidence_ref(admission, "receipt_id")
        condition_schema = {c["key"]: c for c in definition["measurement_conditions_schema"]}
        for contract in binding.get("science_conditions", {}).get("contexts", []):
            condition_schema.setdefault(
                contract["key"],
                {
                    "key": contract["key"],
                    "value_type": "reference" if "object" in contract["value_type"] else "text",
                    "allowed_values": [],
                    "missing_policy": "retain_unknown",
                    "required_scope": contract["required_scope"],
                },
            )
        supplied = {c["key"]: c for c in doc["conditions"]}
        if len(supplied) != len(doc["conditions"]):
            return candidate("unapproved_or_duplicate_condition_requires_source_interpretation")
        auxiliary = [c for c in doc["conditions"] if c["key"] not in condition_schema]
        conditions = []
        for key in condition_schema:
            condition = supplied.get(
                key, {"state": "not_reported", "value": None, "raw_text": None}
            )
            known = (
                condition["state"] == "known"
                and condition["raw_text"]
                and (condition["value"] is not None)
            )
            if known:
                expected = condition_schema[key]["value_type"]
                val = condition["value"]
                if expected == "boolean":
                    known = type(val) is bool
                elif expected == "decimal":
                    from astroquery_ai.runtime.codec import decimal_literal

                    try:
                        decimal_literal(val)
                    except (ValueError, TypeError):
                        known = False
                elif expected == "integer":
                    known = type(val) is int or (
                        isinstance(val, str)
                        and val.lstrip("+-").isascii()
                        and val.lstrip("+-").isdigit()
                    )
                elif expected == "reference":
                    known = isinstance(val, (str, dict, list)) and bool(val)
                elif expected == "enum":
                    known = isinstance(val, str) and val in condition_schema[key]["allowed_values"]
            conditions.append(
                {
                    "key": key,
                    "state": "known"
                    if known
                    else "unresolved"
                    if condition["state"] == "known"
                    else condition["state"],
                    "value": condition["value"] if known else None,
                    "representation_ref": None,
                    "scope": "measurement",
                    "evidence_refs": [evref] if condition["raw_text"] else [],
                    "check_ref": admission_ref,
                    "reason": None if known else "source_condition_not_resolved",
                    **(
                        {"human_answer_ref": human_answer_ref}
                        if human_answer_ref and key in (human_context_keys or [])
                        else {}
                    ),
                }
            )
        if any(
            (
                condition_schema[c["key"]]["missing_policy"] == "block_admission"
                and c["state"] != "known"
                for c in conditions
            )
        ):
            return candidate("required_identity_condition_missing")
        uncertainty = {
            "contract_version": "UncertaintyBundle/1",
            "state": uncertainty_state,
            "components": components,
            "raw_refs": [evref],
            "reason": "reported_error_semantics_unresolved"
            if uncertainty_state == "unresolved"
            else None,
            "inspection_ref": admission_ref,
        }
        uncertainty_record = {
            "uncertainty_id": "uncertainty-" + digest(uncertainty),
            "bundle": uncertainty,
        }
        references = [
            {
                "reference_id": "reported-source-"
                + digest({"measurement": mid, "reference": reference,
                          **({"evidence": evref} if revision > 1 else {})}),
                "schema_version": "ReportedSourceReference/1",
                "measurement_id": mid,
                "raw_code": reference["raw_code"],
                "location": reference["location"],
                'role':reference.get('role','unknown'),
                'link_quote':reference.get('link_quote'), 'page':reference.get('page'),
                'block_ids':reference.get('block_ids', []),
                'revision':1,
                "state": "source_reported_unresolved",
                "transcription_state": "literal_in_saved_evidence"
                if reference["raw_code"] in doc["source_quote"]
                else "unverified_model_transcription",
                "resolved_work_ref": None,
                "source_ref": evidence_ref(source, "source_id"),
                "evidence_refs": [evref],
                "grants_reading": False,
                "same_observation_established": False,
            }
            for reference in doc["source_references"]
        ]
        reference_refs = [evidence_ref(reference, "reference_id") for reference in references]
        statements = [
            {
                "statement_id": "statement-"
                + digest(
                    {
                        "measurement": mid,
                        "revision": revision,
                        "context": item,
                        "verification": paper_verification.get("attempt_id"),
                    }
                ),
                "schema_version": "ReportedContextStatement/1",
                "measurement_id": mid,
                "kind": item["kind"],
                "text": item["text"],
                "raw_quote": item["anchor"]["quote"],
                "page": item["anchor"]["page"],
                "source_ref": evidence_ref(source, "source_id"),
                "artifact_ref": evidence["artifact_ref"],
                "verification_attempt_id": paper_verification.get("attempt_id"),
                "origin": "independent_model_source_interpretation",
                "subject_scope": item.get("subject_scope"),
                "property_scope": item.get("property_scope"),
                "grants_retrieval": False,
            }
            for item in (paper_verification or {}).get("context", [])
        ]
        statements.extend(
            (
                {
                    "statement_id": "statement-"
                    + digest({"measurement": mid, "revision": revision, "auxiliary": item}),
                    "schema_version": "ReportedContextStatement/1",
                    "measurement_id": mid,
                    "kind": "reported_auxiliary_context",
                    "text": item["key"] + ": " + str(item["value"]),
                    "raw_quote": item["raw_text"],
                    "page": doc["page"],
                    "source_ref": evidence_ref(source, "source_id"),
                    "artifact_ref": evidence["artifact_ref"],
                    "origin": "model_proposed_auxiliary_context",
                    "transcription_state": "not_independently_verified",
                    "eligible_for_comparison": False,
                    "grants_retrieval": False,
                }
                for item in auxiliary
            )
        )
        if owner == "M03":
            from astroquery_ai.science.catalog_transcription import reported_uncertainty_context

            for item in reported_uncertainty_context(source, doc, evidence, evref):
                statements.append(
                    {
                        **item,
                        "schema_version": "ReportedContextStatement/1",
                        "statement_id": "statement-"
                        + digest({"measurement": mid, "revision": revision, "table_context": item}),
                        "measurement_id": mid,
                        "source_ref": evidence_ref(source, "source_id"),
                    }
                )
        context = {
            "contract_version": "ComparisonContext/1",
            "context_id": context_id,
            "revision": revision,
            "measurement_ref": {"id": mid, "version": revision},
            "source_ref": evidence_ref(source, "source_id"),
            "snapshot_binding": {
                "query": {
                    "id": spec["spec_id"],
                    "version": 1,
                    "content_sha256": content_hash(spec),
                },
                "artifact": evidence["artifact_ref"],
                "source_qualification": source["qualification_ref"],
                "property": {
                    "id": definition["property_id"],
                    "version": definition["definition_version"],
                    "content_sha256": definition["content_sha256"],
                },
            },
            "source_background_ref": source.get("background_ref"),
            "conditions": conditions,
            "excerpt_refs": [evref],
            "source_statements": [evidence_ref(item, "statement_id") for item in statements],
            "lineage_refs": reference_refs,
            "uncertainty_ref": evidence_ref(uncertainty_record, "uncertainty_id"),
            "collection_receipt": admission_ref,
        }
        context["content_sha256"] = content_hash(context)
        ComparisonContext.model_validate(context)
        target_ref = {
            "id": spec["target"]["target_id"],
            "version": 1,
            "content_sha256": digest(spec["target"]),
        }
        record = {
            "schema_version": "SourceMeasurement/2",
            "measurement_id": mid,
            "revision": revision,
            "task_id": spec["task_id"],
            "query_ref": {
                "id": spec["spec_id"],
                "version": 1,
                "content_sha256": content_hash(spec),
            },
            "target_ref": target_ref,
            "property_ref": {
                "id": definition["property_id"],
                "version": definition["definition_version"],
                "content_sha256": definition["content_sha256"],
            },
            "source_ref": evidence_ref(source, "source_id"),
            "interpretation_ref": ir,
            "source_kind": source["kind"],
            "value": doc["value"],
            "raw_value": doc["raw_value"],
            "unit": doc["unit"],
            **({"unit_declaration": unit_declaration} if unit_declaration else {}),
            "representation": doc["representation"],
            "limit": doc["limit"],
            "uncertainty": uncertainty,
            "context_ref": evidence_ref(context, "context_id"),
            "evidence_refs": [evref],
            "admission_receipt_ref": admission_ref,
            "source_qualification_ref": source["qualification_ref"],
            "lineage_refs": reference_refs,
            'citation_state':doc.get('citation_state','unknown'),
        }
        record["content_sha256"] = content_hash(record)
        SourceMeasurement.model_validate(record)
        from astroquery_ai.science.source_restrictions import checked_source_information

        texts = {"saved_quote": evidence["raw_text"]}
        if owner == "M06":
            texts.update(
                {
                    b["block_id"]: b["text"]
                    for b in (paper_verification or {}).get("source_information_blocks", [])
                }
            )
            check = (paper_verification or {}).get("check") or {}
            anchors = [
                a
                for k in ("subject_evidence", "role_evidence", "quantity_evidence")
                for a in check.get(k, [])
            ]
            anchors += [
                c["anchor"]
                for c in (paper_verification or {}).get("context", [])
                if c.get("anchor")
            ]
            for a in anchors:
                if a.get("quote"):
                    texts["anchor:" + digest(a)] = a["quote"]
                    for block_id in a.get("block_ids", []):
                        texts[block_id] = a["quote"]
        if owner == "M03":
            from astroquery_ai.runtime.codec import canonical
            from astroquery_ai.science.source_restrictions import catalog_source_materials

            metadata = source.get("metadata", {})
            texts.update(catalog_source_materials(source))
            texts.update(
                {"column:" + c["name"]: canonical(c).decode() for c in metadata.get("columns", [])}
            )

            def strings(value):
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for v in value.values():
                        yield from strings(v)
                elif isinstance(value, list):
                    for v in value:
                        yield from strings(v)

            texts.update({"metadata:" + str(i): t for i, t in enumerate(strings(metadata))})
        quality_check = checked_source_information(
            doc["source_quality"],
            texts,
            measurement_id=mid,
            measurement_version=revision,
            evidence_refs=[evref],
            interpretation_ref=ir,
            check_basis={"producer": owner, "scope": "supplied_material_only"},
        )
        return {
            "state": "admitted",
            "measurement": record,
            "context": context,
            "evidence": evidence,
            "interpretation": interpretation,
            "source_unit": unit,
            "component_units": component_units,
            "uncertainty_record": uncertainty_record,
            "error_bases": bases,
            "admission": admission,
            "source_check": quality_check,
            "reported_references": references,
            "source_statements": statements,
            "assembly_context": {
                "spec": spec,
                "source": source,
                "artifact": artifact,
                "owner": owner,
                "batch_id": batch_id,
                "allowed_pages": allowed_pages,
                "matched_rows": matched_rows,
                "paper_verification": paper_verification,
                "object_binding_ref": object_binding_ref,
            },
        }
