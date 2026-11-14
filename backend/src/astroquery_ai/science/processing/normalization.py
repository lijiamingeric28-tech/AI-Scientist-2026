"science: processing: normalization.py operations; existing transactions and decisions retained."

from __future__ import annotations

from astroquery_ai.registry.models import Representation

from astroquery_ai.runtime.codec import canonical, content_hash, digest

from astroquery_ai.runtime.errors import DomainError

from astroquery_ai.runtime.models import SourceMeasurement

from astroquery_ai.runtime.representations import commit_current_representation

from astroquery_ai.science.normalization import (
    SameQuantityTransform,
    normalize_checked,
    verify_model_numbers,
)

from astroquery_ai.science.conversion_policy import conversion_permission, not_run_representation

from astroquery_ai.science.normalization_prompt import normalization_prompt

from astroquery_ai.science.unit_declarations import execution_unit, unit_record_text


async def normalize(self, job):
    tid, mid = (job["task_id"], job["payload"]["measurement_id"])
    model_check = None
    with self.repo.read() as conn:
        spec = self.spec(conn, tid)
        record = self.repo.object(conn, tid, "measurement", mid)
        interpretation = self.repo.object(
            conn, tid, "interpretation", record["interpretation_ref"]["id"]
        )
        binding = next(
            (b for b in spec["properties"] if b["property_id"] == record["property_ref"]["id"])
        )
        bases = {b["basis_id"]: b["value"] for b in self.repo.objects(conn, tid, "error_basis")}
        component_units = {
            u["unit_id"]: unit_record_text(u)
            for u in self.repo.objects(conn, tid, "unit")
            if "unit_text" in u
        }
    if record["content_sha256"] != job["payload"]["source_hash"]:
        raise DomainError("NORMALIZATION_SOURCE_CHANGED", "标准化输入版本已变化")
    output = binding["output_profile"]
    release = self.app.registry.load(spec["registry_release"]["id"])
    policy_ref = output["conversion_policy_ref"]
    policy=next((p for p in release['data']['conversion-policies'] if p['policy_id']==policy_ref['id']
                 and str(p['version'])==str(policy_ref['version']) and p['content_sha256']==policy_ref['content_sha256']),None)
    if (
        not policy
        or policy["content_sha256"] != policy_ref["content_sha256"]
        or str(policy["version"]) != str(policy_ref["version"])
    ):
        raise DomainError("CONVERSION_POLICY_UNAVAILABLE", "冻结输出配置的转换策略不可核验")
    numeric = record["value"]["kind"] in {"real", "integer", "interval"}
    source_parameters = interpretation["proposal"].get("representation_parameters")
    source_parameters = source_parameters or (
        {"kind": "linear"} if record["representation"] == "linear" else None
    )
    if source_parameters is None:
        from astroquery_ai.science.unit_declarations import catalog_representation_declaration
        with self.repo.read() as conn:
            source = self.repo.object(conn, tid, 'source', record['source_ref']['id'], record['source_ref']['version'])
        declaration = catalog_representation_declaration(source, record, interpretation)
        if declaration:
            source_parameters = declaration['parameters']
            with self.repo.transaction() as conn:
                self.repo.validate_lease(conn, job)
                self.repo.put_object(conn, tid, 'representation_declaration', 'representation-' + digest(declaration), 1, declaration)
    native_parameters_unknown=(source_parameters is None or source_parameters.get('native_coordinate_only') is True
        and source_parameters.get('reference_value') is None and source_parameters.get('reference_unit') is None
        and source_parameters.get('scale','1')=='1' and source_parameters.get('offset','0')=='0')
    user_declared = bool(binding.get('user_execution_ref'))
    if not user_declared and native_parameters_unknown and (output['representation'].get('native_coordinate_only')
            or record['source_kind']=='paper' and output['representation']['kind'] in {'log10','ln'}
            and (interpretation.get('paper_verification') or {}).get('state')=='passed'):
        from astroquery_ai.science.unit_declarations import output_coordinate_unit
        from astroquery_ai.science.units import native_coordinate_unit_equal
        coefficient_label=(record['representation']=='log10' and execution_unit(record)=='dex')
        if record['representation'] == output['representation']['kind'] and (coefficient_label or native_coordinate_unit_equal(execution_unit(record), output_coordinate_unit(output), record['representation'])):
            # A candidate identity of the independently checked native
            # coordinate, NOT an inferred new logarithm or a permission.
            # Scientific checks below must establish the actual source basis,
            # scale/zero point and exact quantity before this can execute.
            source_parameters = output['representation']
    if user_declared:
        from astroquery_ai.science.user_execution import user_permission
        declared_permission = user_permission(self, spec, binding, record, policy, source_parameters)
        scientific, semantics = None, None
    else:
        scientific, semantics = await self.scientific_permission(
            job, spec, binding, record, interpretation, release, source_parameters
        )
    requested_components = (
        [
            c["component_id"]
            for c in record["uncertainty"]["components"]
            if (
                c["interpretation_state"] == "unresolved"
                or semantics["uncertainty"].get(c["component_id"], {}).get("interpretation_needed")
                is True
            )
            and semantics["uncertainty"].get(c["component_id"], {}).get("disposition")
            in {"eligible", "needs_review"}
        ]
        if scientific
        else []
    )
    if scientific and scientific["allowed"] and requested_components:
        with self.repo.transaction() as conn:
            self.repo.validate_lease(conn, job)
            if self.defer_error_interpretation(
                conn, tid, record, interpretation, component_ids=requested_components
            ):
                self.repo.finish_job(conn, job)
                return
    permission = conversion_permission(
        policy,
        record,
        output,
        Representation.model_validate(source_parameters) if source_parameters else None,
        scientific_permission=scientific,
    )
    if user_declared:
        permission = declared_permission
    if not permission["allowed"]:
        result = not_run_representation(record, output, permission["reason"])
    elif not numeric or (output['representation'].get('native_coordinate_only') and source_parameters == output['representation']):
        result = {
            "schema_version": "DerivedRepresentation/2",
            "derived_id": "identity-"
            + digest(
                {
                    "source": record["content_sha256"],
                    "profile": output["content_sha256"],
                    "execution": "nonnumeric-identity-1",
                }
            ),
            "measurement_id": mid,
            "source_representation_hash": record["content_sha256"],
            "output_profile_ref": {
                "id": output["profile_id"],
                "version": output["version"],
                "content_sha256": output["content_sha256"],
            },
            "status": "ready",
            "main_state": "ready",
            "value_typed": record["value"],
            "limit": record["limit"],
            "uncertainty_typed": {
                "state": record["uncertainty"]["state"],
                "components": [
                    {
                        "source_component_id": c["component_id"],
                        "status": "source_preserved",
                        "output_component": c,
                        "method": "target_identical",
                    }
                    for c in record["uncertainty"]["components"]
                ],
            },
            "method": "target_identical",
        }
    else:
        if source_parameters is None:
            if record["representation"] != "linear":
                raise DomainError("SOURCE_REPRESENTATION_UNRESOLVED", "来源对数/星等基准尚未明确")
            source_parameters = {"kind": "linear"}
        from astroquery_ai.science.unit_declarations import arithmetic_coordinate_units

        native_unit,target_unit = arithmetic_coordinate_units(record,output)
        math_component_units=component_units
        if native_unit!=execution_unit(record):
            math_component_units={k:('1' if v in {'ct','count','counts','1','dimensionless'} else v) for k,v in component_units.items()}
        conversion = SameQuantityTransform(
            Representation.model_validate(source_parameters),
            Representation.model_validate(output["representation"]),
            native_unit,
            target_unit,
            source_quantity_key=binding["definition"]["quantity_key"],
            target_quantity_key=binding["definition"]["quantity_key"],
        )
        profile_ref = {
            "id": output["profile_id"],
            "version": output["version"],
            "content_sha256": output["content_sha256"],
        }
        result = normalize_checked(
            SourceMeasurement.model_validate(record),
            conversion,
            profile_ref,
            target_unit_ref=profile_ref,
            target_representation_ref=profile_ref,
            basis_values=bases,
            component_units=math_component_units,
        )
        if native_unit!=execution_unit(record):
            result['coordinate_units']['semantic_basis']='reviewed_count_coordinate; raw unit and component records retained'
            result['coordinate_units']['native_literal']=execution_unit(record)
        identity = execution_unit(record) == target_unit and Representation.model_validate(
            source_parameters
        ) == Representation.model_validate(output["representation"])
        if not identity and (not conversion.affine) and (result["main_state"] == "ready"):
            with self.repo.read() as conn:
                context = self.repo.object(
                    conn,
                    tid,
                    "context",
                    record["context_ref"]["id"],
                    record["context_ref"]["version"],
                )
                statements = [
                    self.repo.object(conn, tid, "source_statement", ref["id"], ref["version"])
                    for ref in context.get("source_statements", [])
                ]
            prompt = normalization_prompt(
                record,
                source_parameters,
                output,
                binding["definition"],
                source_quote=interpretation["proposal"]["source_quote"],
                context=context,
                statements=statements,
                basis_values=bases,
                component_units=component_units,
            )
            from ..normalization_prompt import normalization_wire
            from ..model_bindings import map_fields
            prompt,wire_binding=normalization_wire(prompt,record)
            proposed, receipt = await self.steps.model(
                job,
                task_id=tid,
                owner="M08",
                root_id=mid,
                messages=[{"role": "user", "content": canonical(prompt).decode()}],
                bindings=wire_binding,
                profile=self.model_profile(
                    "M08", version="same-quantity-proposal-3", max_output_tokens=8192
                ),
                job=job,
                purpose="verification"
                if scientific
                and scientific.get("software_eligibility", {}).get("mode")
                == "bounded_fixed_input_verification"
                else "production",
                root_limit=3,
            )
            proposed=map_fields(proposed,{'source_component_id':wire_binding['groups']['U']},expand=True,strict=False)
            checked = {
                "value_typed": result["value_typed"],
                "components": [
                    {
                        "source_component_id": c["source_component_id"],
                        "output_values": c["output_component"]["values"]
                        if c.get("output_component")
                        else None,
                    }
                    for c in result["uncertainty_typed"]["components"]
                ],
            }
            model_check = {
                "schema_version": "NormalizationProposalCheck/1",
                "job_id": job["job_id"],
                "measurement_id": mid,
                "source_hash": record["content_sha256"],
                "output_profile_ref": profile_ref,
                "attempt_id": receipt["attempt_id"],
                "expected_values_sha256": digest(checked),
                "proposed_values_sha256": digest(proposed),
                "status": "agreed",
                "model_numbers_adopted": False,
                "delivered_values_origin": "independent_math",
            }
            try:
                verify_model_numbers(proposed, checked)
            except DomainError as exc:
                if exc.code != "MODEL_NUMERIC_CHECK_FAILED":
                    raise
                model_check.update(status="numeric_recomputed", reason=exc.code)
    if user_declared:
        result['user_execution_ref'] = binding['user_execution_ref']
        result['authorization_origin'] = 'user_declared_local_publication'
        result['scientific_review_granted'] = False
        for issue in result.get('issues', []):
            issue.setdefault('message', '来源对数或星等的参考值、单位或体系未明确，原始数据已保留' if issue['code'] == 'user_source_representation_reference_unresolved' else '当前来源无法按已验证配置转换，原始值、单位和不确定度已保留')
    if scientific is not None:
        result["scientific_condition_ref"] = {
            "id": semantics["check_id"],
            "version": 1,
            "content_sha256": semantics["content_sha256"],
        }
        result["scientific_operation"] = {
            k: v for k, v in scientific.items() if k != "operation_data"
        }
        result["derived_id"] += "-" + semantics["content_sha256"][:16]
        if semantics.get("source_only_limitation") and result["main_state"] != "ready":
            result["source_only_limitation"] = semantics["source_only_limitation"]
        if result["main_state"] == "ready" and numeric:
            from astroquery_ai.science.scientific_conditions import restrict_components
            from astroquery_ai.registry.science_conditions import bound_condition_records
            selected_science=next(s for s in bound_condition_records(release,binding)
                                  if s['content_sha256']==semantics['science_record_hash'])

            restrict_components(
                result,
                record,
                selected_science,
                scientific,
                semantics,
            )
    with self.repo.transaction() as conn:
        self.repo.validate_lease(conn, job)
        current = self.repo.object(conn, tid, "measurement", mid)
        if current["content_sha256"] != record["content_sha256"]:
            raise DomainError("NORMALIZATION_SOURCE_CHANGED", "标准化响应不能覆盖更新后的来源解释")
        for component in (result.get("uncertainty_typed") or {}).get("components", []):
            if component.get("unit_definition"):
                definition = component["unit_definition"]
                self.repo.put_object(conn, tid, "unit", definition["unit_id"], 1, definition)
            if component.get("validation_receipt"):
                receipt = component["validation_receipt"]
                self.repo.put_object(
                    conn, tid, "validation_receipt", receipt["receipt_id"], 1, receipt
                )
        if result.get("validation_receipt"):
            receipt = result["validation_receipt"]
            self.repo.put_object(conn, tid, "validation_receipt", receipt["receipt_id"], 1, receipt)
        if model_check:
            model_check["check_id"] = "normalization-proposal-check-" + digest(model_check)
            self.repo.put_object(
                conn, tid, "normalization_proposal_check", model_check["check_id"], 1, model_check
            )
        error_receipt = self._error_receipt(conn, tid, record)
        if (
            error_receipt
            and error_receipt["status"] == "applied"
            and (error_receipt.get("output_hash") == record["content_sha256"])
        ):
            result["interpretation_receipt_ref"] = {
                "id": error_receipt["receipt_id"],
                "version": 1,
                "content_sha256": content_hash(error_receipt),
            }
        commit_current_representation(self.repo, conn, tid, record, result, job=job)
        self.repo.finish_job(conn, job)
