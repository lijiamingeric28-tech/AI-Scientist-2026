"""
output_validator.py — Tool 6: OutputValidator

5 维输出校验: Schema 完整性 / 数据完整性 / 格式一致性 /
          溯源一致性 / 质量一致性。
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def validate_output(
    organized_data: dict[str, Any],
    metadata: dict[str, Any],
    traceability: dict[str, Any],
    target_schema: dict[str, Any] | None,
    report_state: dict[str, Any],
    workflow_state: dict[str, Any],
) -> dict[str, Any]:
    """5 维输出校验。

    Returns: {is_valid, checks, validation_errors, summary}
    """
    errors = []
    checks: dict[str, dict] = {}

    records = organized_data.get("records", [])
    sources = organized_data.get("sources", [])
    quality = report_state.get("quality") or {}
    normalization = report_state.get("normalization") or {}

    # ── 1. Schema 完整性 ──
    expected_fields = set()
    if target_schema:
        for f in target_schema.get("fields", []):
            expected_fields.add(f.get("name", ""))
    actual_fields = set(r.get("field_name", "") for r in records)
    missing_from_schema = expected_fields - actual_fields
    extra_from_schema = actual_fields - expected_fields if expected_fields else set()

    schema_pass = True
    if missing_from_schema:
        errors.append({"dimension": "schema", "field": ", ".join(sorted(missing_from_schema)),
                       "expected": "present", "actual": "missing", "severity": "warning"})
    checks["schema"] = {"passed": len(missing_from_schema) == 0,
                        "missing_fields": sorted(missing_from_schema),
                        "extra_fields": sorted(extra_from_schema)}

    # ── 2. 数据完整性 ──
    records_without_source = sum(1 for r in records if not r.get("source_id"))
    num_recs = [r for r in records if isinstance(r.get("field_value"), (int, float))]
    records_without_unit = sum(1 for r in num_recs if not r.get("field_unit"))
    records_without_prov = sum(1 for r in records
                               if not r.get("provenance")
                               or (isinstance(r.get("provenance"), dict)
                                   and not r["provenance"].get("page")))

    data_pass = records_without_source == 0
    checks["data_integrity"] = {
        "passed": data_pass,
        "records_without_source": records_without_source,
        "records_missing_unit": records_without_unit,
        "records_missing_provenance": records_without_prov,
    }
    if records_without_source > 0:
        errors.append({"dimension": "data_integrity", "field": "source_id",
                       "expected": "all present", "actual": f"{records_without_source} missing",
                       "severity": "error"})

    # ── 3. 格式一致性 (V2.2: 从 target_schema 动态获取别名列表) ──
    # 构建所有已知别名集合
    known_aliases: set[str] = set()
    if target_schema:
        for f in target_schema.get("fields", []):
            for alias in f.get("aliases", []):
                known_aliases.add(alias)

    alias_fields = []
    residual_tilde = []
    for r in records:
        fn = r.get("field_name", "")
        # 如果 field_name 在 target_schema 的 aliases 列表中 → 别名残留
        if fn in known_aliases:
            alias_fields.append(fn)
        fv = r.get("field_value")
        if isinstance(fv, str) and fv.startswith("~"):
            residual_tilde.append(r.get("record_id", "?"))

    format_pass = len(alias_fields) == 0 and len(residual_tilde) == 0
    checks["format_consistency"] = {
        "passed": format_pass,
        "alias_fields_remaining": sorted(set(alias_fields)),
        "residual_tilde_values": len(residual_tilde),
    }
    if alias_fields:
        errors.append({"dimension": "format", "field": ", ".join(sorted(set(alias_fields))),
                       "expected": "standard names", "actual": "alias still present",
                       "severity": "warning"})

    # ── 4. 溯源一致性 ──
    trace_completeness = traceability.get("trace_completeness", {})
    trace_pass = True
    if trace_completeness.get("records_without_trace", 0) > 0:
        trace_pass = False
        errors.append({"dimension": "traceability",
                       "expected": "all records traced",
                       "actual": f"{trace_completeness['records_without_trace']} untraced",
                       "severity": "warning"})
    checks["traceability_consistency"] = {
        "passed": trace_pass,
        "traced_records": trace_completeness.get("records_with_trace", 0),
        "untraced_records": trace_completeness.get("records_without_trace", 0),
    }

    # ── 5. 质量一致性 ──
    scoring = quality.get("quality_scoring", {})
    mod_total = normalization.get("modifications", {}).get("total", 0)
    records_modified = trace_completeness.get("modified_count", 0)
    quality_pass = records_modified >= mod_total * 0.8  # 允许 20% 误差
    checks["quality_consistency"] = {
        "passed": quality_pass,
        "overall_score": scoring.get("overall_score", 0),
        "modifications_reported": mod_total,
        "records_modified": records_modified,
    }
    if not quality_pass:
        errors.append({"dimension": "quality_consistency",
                       "expected": f"~{mod_total} modifications",
                       "actual": f"{records_modified} modified records",
                       "severity": "warning"})

    is_valid = all(c["passed"] for c in checks.values())

    summary = f"{sum(1 for c in checks.values() if c['passed'])}/{len(checks)} checks passed"
    if errors:
        summary += f", {len(errors)} issue(s)"

    logger.info("[OutputValidator] Valid=%s, %s", is_valid, summary)
    for e in errors[:5]:
        logger.info("  %s: %s (severity=%s)", e["dimension"], e.get("field", ""), e["severity"])

    return {
        "is_valid": is_valid,
        "checks": checks,
        "validation_errors": errors,
        "summary": summary,
    }
