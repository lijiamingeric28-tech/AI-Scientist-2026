"""Local software eligibility, independent of immutable scientific permissions."""
from .codec import content_hash, loads


def verification_scope(repo, conn, task_id, spec):
    task = repo.task(conn, task_id)
    if task["kind"] not in {"validation", "live"}:
        return None
    scopes = repo.objects(conn, task_id, "validation_scope")
    matches = [s for s in scopes if s.get("schema_version") == "ReviewedBaselineVerification/1"
               and s.get("registry_ref") == spec["registry_release"]
               and set(b["property_id"] for b in spec["properties"]) <= set(s.get("property_ids", []))
               and s.get("fixed_input_only") is True and s.get("fixture_sha256")]
    return matches[0] if len(matches) == 1 else None


def authorize_verification(app, task_id, owner, profile, input_bound):
    from .errors import DomainError
    with app.repository.read() as conn:
        task = app.repository.task(conn, task_id)
        if not task["query_ref"]:
            raise DomainError("VERIFICATION_SCOPE", "限定验证必须绑定冻结请求")
        ref = loads(task["query_ref"])
        spec = app.repository.object(conn, task_id, "confirmed_query", ref["id"], ref["version"])
        scope = verification_scope(app.repository, conn, task_id, spec)
        if scope is None:
            raise DomainError("VERIFICATION_SCOPE", "没有准确登记的固定输入验证范围")
        release = app.registry.load(spec["registry_release"]["id"])
        if not any(f["file_sha256"] == scope["fixture_sha256"] for f in release["candidate"]["manifest"]["content_files"]):
            raise DomainError("VERIFICATION_FIXTURE", "验证输入未被已接受基线固定")
        execution = [e for e in scope.get("model_executions", []) if e.get("owner") == owner
                     and all(e.get(k) == getattr(profile, k) for k in ("model", "version", "operation", "source_format", "thinking"))]
        if len(execution) != 1 or input_bound > execution[0]["maximum_input_tokens"] or profile.max_output_tokens > execution[0]["maximum_output_tokens"]:
            raise DomainError("VERIFICATION_EXECUTION", "模型调用超出登记的验证配置")
        return {"kind": "bounded_fixed_input_verification", "scope_hash": content_hash(scope), "registry_ref": scope["registry_ref"], "scientific_profile_validated": False}


def operation_eligibility(app, conn, task_id, spec, operation, *, record=None):
    scope = verification_scope(app.repository, conn, task_id, spec)
    if scope is not None and not scope.get('production_processing') and operation in scope.get("operations", []):
        return {"allowed": True, "mode": "bounded_fixed_input_verification", "scope_hash": content_hash(scope)}
    registry_ref = spec['registry_release']
    row = conn.execute("SELECT payload FROM settings WHERE key=?", ("science_capabilities:" + registry_ref['id'],)).fetchone()
    if not row:
        from astroquery_ai.query.registry_context import qualification_reference
        base_ref = qualification_reference(app, spec)
        if base_ref and base_ref != registry_ref:
            registry_ref = base_ref
            row = conn.execute("SELECT payload FROM settings WHERE key=?", ("science_capabilities:" + registry_ref['id'],)).fetchone()
    if not row:
        return {"allowed": False, "reason": "software_operation_not_verified"}
    ref = loads(row[0])
    receipt = app.repository.object(conn, ref["task_id"], "software_capability_validation", ref["id"], ref["version"])
    if (content_hash(receipt) != ref["content_sha256"] or receipt.get("registry_ref") != registry_ref
            or receipt.get("state") != "passed" or not receipt.get("evidence_refs")):
        return {"allowed": False, "reason": "software_capability_receipt_invalid"}
    for evidence_ref in receipt['evidence_refs']:
        evidence = app.repository.object(conn, evidence_ref['task_id'], evidence_ref['kind'], evidence_ref['id'], evidence_ref['version'])
        if content_hash(evidence) != evidence_ref['content_sha256']:
            return {'allowed': False, 'reason': 'software_capability_evidence_changed'}
    allowed = operation in receipt.get("operations", [])
    if record is not None and allowed:
        scope = receipt.get('capability_scope', {})
        allowed = (record['representation'] in scope.get('native_representations', [])
            and record['value']['kind'] in scope.get('value_kinds', [])
            and record['limit'] in scope.get('limit_states', []))
    return {"allowed": allowed, "reason": "verified_software_operation" if allowed else "software_operation_not_verified", "receipt_ref": ref}
