"""Scientific qualifications are bound to model, operation and frozen definitions."""

from .codec import content_hash, digest, loads
from .errors import DomainError
from .provider import compatible


class ProfileAuthority:
    def __init__(self, application):
        self.app = application

    def load(self, conn, owner, *, check_connection=True):
        try:
            return self._load(conn, owner, check_connection=check_connection)
        except DomainError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainError("PROFILE_QUALIFICATION_SCHEMA", "科学资格记录结构不可核验") from exc

    def _load(self, conn, owner, *, check_connection=True):
        row = conn.execute(
            "SELECT payload FROM settings WHERE key=?", ("profile:" + owner,)
        ).fetchone()
        if not row:
            raise DomainError("PROFILE_NOT_VALIDATED", "此模块没有科学运行资格")
        setting = loads(row[0])
        if (
            setting.get("synthetic")
            and not self.app.registry.allow_synthetic
            or setting.get("state") != "validated"
            or check_connection and not compatible(setting, self.app.configuration.runtime.get("dashscope_base_url", ""))
        ):
            raise DomainError("PROFILE_NOT_VALIDATED", "运行资格未批准或端点已变化")
        ref = setting.get("validation_ref")
        if not isinstance(ref, dict) or not {"task_id", "id", "version", "content_sha256"} <= set(
            ref
        ):
            raise DomainError("PROFILE_NOT_VALIDATED", "缺少固定的科学校准回执")
        report = self.app.repository.object(
            conn, ref["task_id"], "profile_validation", ref["id"], ref["version"]
        )
        if not isinstance(report, dict):
            raise DomainError("PROFILE_QUALIFICATION_SCHEMA", "科学资格回执不是对象")
        if report.get("synthetic") and not self.app.registry.allow_synthetic:
            raise DomainError("PROFILE_NOT_VALIDATED", "合成资格仅用于离线软件验证")
        if (
            content_hash(report) != ref["content_sha256"]
            or report.get("schema_version") not in {"ScientificProfileQualification/1", "ScientificProfileQualification/2"}
            or report.get("scientific_profile_validated") is not True
            or report.get("owner") != owner
            or report.get("state") != "qualified"
            or not report.get("validation_evidence_refs")
        ):
            raise DomainError("PROFILE_NOT_VALIDATED", "科学资格回执未覆盖当前模块或缺少验证依据")
        if not isinstance(report["validation_evidence_refs"], list):
            raise DomainError("PROFILE_EVIDENCE_UNAVAILABLE", "科学资格的验证依据必须为引用数组")
        for evidence_ref in report["validation_evidence_refs"]:
            if (
                not isinstance(evidence_ref, dict)
                or evidence_ref.get("kind")
                not in {"validation", "validation_manifest", "validation_corpus"}
                or not {"task_id", "id", "version", "content_sha256"} <= evidence_ref.keys()
            ):
                raise DomainError("PROFILE_EVIDENCE_UNAVAILABLE", "科学资格的验证依据引用不完整")
            evidence = self.app.repository.object(
                conn,
                evidence_ref["task_id"],
                evidence_ref["kind"],
                evidence_ref["id"],
                evidence_ref["version"],
            )
            if (
                content_hash(evidence) != evidence_ref["content_sha256"]
                or self.app.repository.task(conn, evidence_ref["task_id"])["kind"] != "validation"
            ):
                raise DomainError("PROFILE_EVIDENCE_UNAVAILABLE", "科学资格引用的验证数据不可核验")
        return report, ref

    def authorize(self, task_id, owner, profile, input_bound):
        user_bindings, user_refs = set(), []
        with self.app.repository.read() as conn:
            report, reference = self.load(conn, owner)
            def string_list(value):
                return (
                    isinstance(value, list)
                    and bool(value)
                    and all(isinstance(item, str) and item for item in value)
                )

            multiple = report['schema_version'] == 'ScientificProfileQualification/2'
            executions = report.get('execution_profiles') if multiple else [report.get('execution', {})]
            if (not isinstance(executions, list) or not executions or not all(isinstance(e, dict) for e in executions)
                    or multiple and 'execution' in report):
                raise DomainError('PROFILE_QUALIFICATION_SCHEMA', '科学资格必须给出明确且无歧义的执行配置集合')
            matches = [execution for execution in executions
                if string_list(execution.get('operations'))
                and profile.operation in execution['operations']
                and all(execution.get(key) == getattr(profile, key)
                        for key in ('model', 'version', 'thinking', 'high_resolution_images'))
                and (not multiple or string_list(execution.get('source_formats'))
                     and profile.source_format in execution['source_formats'])]
            if not matches:
                raise DomainError(
                    "PROFILE_CONFIGURATION_CHANGED", "模型、模式、版本或操作不在已校准范围内"
                )
            if len(matches) != 1:
                raise DomainError('PROFILE_EXECUTION_AMBIGUOUS', '同一次调用匹配多个执行配置，不能择宽限额放行')
            execution = matches[0]
            bounds = {
                "input_tokens": input_bound,
                "output_tokens": profile.max_output_tokens,
                "images": profile.max_images,
                "wall_seconds": profile.wall_seconds,
                "inactivity_seconds": profile.inactivity_seconds,
            }
            import math

            if any(
                type(execution.get("maximum_" + key)) not in {int, float}
                or not math.isfinite(execution["maximum_" + key])
                or execution["maximum_" + key] < (0 if key == "images" else 1)
                or value > execution["maximum_" + key]
                for key, value in bounds.items()
            ):
                raise DomainError(
                    "PROFILE_CAPABILITY_EXCEEDED", "调用超过已验证的输入、输出或时间范围"
                )
            task = self.app.repository.task(conn, task_id)
            scope = report.get("scope", {})
            if not isinstance(scope, dict):
                raise DomainError("PROFILE_SCOPE_UNAVAILABLE", "科学资格缺少适用范围")
            if (
                not string_list(scope.get("source_formats"))
                or profile.source_format not in scope["source_formats"]
            ):
                raise DomainError(
                    "PROFILE_SOURCE_FORMAT_NOT_VALIDATED", "当前输入格式未被科学校准覆盖"
                )
            if owner == "M01":
                if scope.get("kind") != "request_parser" or not isinstance(
                    scope.get("maximum_query_characters"), int
                ):
                    raise DomainError("PROFILE_SCOPE_UNAVAILABLE", "请求解析资格缺少适用范围")
                draft = self.app._draft(conn, task_id)
                if len(draft["original_query"]) > scope["maximum_query_characters"]:
                    raise DomainError("PROFILE_SCOPE_EXCEEDED", "请求文本超过已验证范围")
            else:
                if not task["query_ref"] or scope.get("kind") != "frozen_properties":
                    raise DomainError("PROFILE_SCOPE_UNAVAILABLE", "科学调用缺少冻结性质范围")
                spec_ref = loads(task["query_ref"])
                spec = self.app.repository.object(
                    conn, task_id, "confirmed_query", spec_ref["id"], spec_ref["version"]
                )
                if any(b.get('user_execution_ref') for b in spec['properties']):
                    from astroquery_ai.registry.user_execution import verified_user_bindings
                    user_bindings = verified_user_bindings(self.app, spec)
                    user_refs = [b['user_execution_ref'] for b in spec['properties'] if b.get('user_execution_ref') and b.get('property_id') in user_bindings]
                registry_refs = scope.get('registry_release_refs', [scope.get('registry_release_ref')])
                if (not isinstance(registry_refs, list) or not registry_refs
                        or 'registry_release_refs' in scope and any(r is None for r in registry_refs)
                        or any(not isinstance(r, dict) for r in registry_refs if r is not None)):
                    raise DomainError('PROFILE_SCOPE_UNAVAILABLE', '科学基线资格范围格式无效')
                if None not in registry_refs and spec['registry_release'] not in registry_refs and len(user_bindings) != len(spec['properties']):
                    from astroquery_ai.query.registry_context import qualification_reference
                    base_ref = qualification_reference(self.app, spec)
                    if base_ref is None or base_ref not in registry_refs:
                        raise DomainError('PROFILE_REGISTRY_NOT_VALIDATED', '当前科学基线不在运行资格范围内')
                primary = spec["target"]["primary_otype"]
                allowed_confirmed = scope.get('confirmed_otypes', [])
                if allowed_confirmed and not string_list(allowed_confirmed):
                    raise DomainError('PROFILE_SCOPE_UNAVAILABLE', '已确认类型资格范围格式无效')
                confirmed = set()
                for assertion in spec['target'].get('classification_assertions', []):
                    subject = assertion.get('subject_identity_ref')
                    subject = subject.get('id') if isinstance(subject, dict) else subject
                    if assertion.get('state') == 'current_verified' and subject == spec['target']['target_id'] and assertion.get('evidence_refs'):
                        confirmed.add(assertion.get('canonical_otype'))
                if (
                    not string_list(scope.get("primary_otypes"))
                    or primary not in scope["primary_otypes"] and not confirmed.intersection(allowed_confirmed)
                ):
                    raise DomainError(
                        "PROFILE_TARGET_NOT_VALIDATED", "当前天体类型未被此科学校准覆盖"
                    )
                from .models import Ref

                for field in ("definition_refs", "output_profile_refs"):
                    if not isinstance(scope.get(field), list) or not scope[field]:
                        raise DomainError(
                            "PROFILE_SCOPE_UNAVAILABLE", "科学资格缺少精确性质与输出配置引用"
                        )
                    try:
                        for item in scope[field]:
                            Ref.model_validate(item)
                    except ValueError as exc:
                        raise DomainError(
                            "PROFILE_SCOPE_UNAVAILABLE", "科学资格的性质或输出引用结构无效"
                        ) from exc
                approved = {digest(ref) for ref in scope.get("definition_refs", [])}
                approved_outputs = {digest(ref) for ref in scope.get("output_profile_refs", [])}
                for binding in spec['properties']:
                    if binding.get('user_execution_ref') and binding.get('property_id') in user_bindings:
                        continue
                    definition = binding["definition"]
                    exact = {
                        "id": definition["property_id"],
                        "version": definition["definition_version"],
                        "content_sha256": definition["content_sha256"],
                    }
                    if digest(exact) not in approved:
                        raise DomainError(
                            "PROFILE_PROPERTY_NOT_VALIDATED", "所选性质或定义版本未被此科学校准覆盖"
                        )
                    output = binding["output_profile"]
                    output_ref = {
                        "id": output["profile_id"],
                        "version": output["version"],
                        "content_sha256": output["content_sha256"],
                    }
                    if digest(output_ref) not in approved_outputs:
                        raise DomainError(
                            "PROFILE_OUTPUT_NOT_VALIDATED", "当前输出单位/表示配置未被科学校准覆盖"
                        )
            return {
                **({'user_execution_refs': user_refs, 'authorization_origin': 'user_declared_local_publication',
                    'scientific_review_granted': False} if user_refs else {}),
                "qualification_ref": reference,
                "model": profile.model,
                "operation": profile.operation,
                "scope_hash": digest(scope),
                "synthetic": bool(report.get("synthetic", False)),
            }
