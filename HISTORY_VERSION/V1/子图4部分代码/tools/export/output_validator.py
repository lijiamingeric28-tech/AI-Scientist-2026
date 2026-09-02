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

    # ── 1. Schema 完整性 (V3.2: 部分提取合法, missing 只报告不阻塞) ──
    expected_fields = set()
    if target_schema:
        for f in target_schema.get("fields", []):
            expected_fields.add(f.get("name", ""))
    actual_fields = set(r.get("field_name", "") for r in records)
    missing_from_schema = expected_fields - actual_fields
    extra_from_schema = actual_fields - expected_fields if expected_fields else set()

    if missing_from_schema:
        errors.append({"dimension": "schema", "field": ", ".join(sorted(missing_from_schema)),
                       "expected": "present", "actual": "missing", "severity": "warning"})
    checks["schema"] = {"passed": True,  # V3.2: 部分提取场景下字段缺失不是结构错误
                        "missing_fields": sorted(missing_from_schema),
                        "extra_fields": sorted(extra_from_schema)}

    # ── 2. 数据完整性 (V3.2: provenance 参与校验; unit 统计不阻塞 — catalog 字段可无量纲) ──
    records_without_source = sum(1 for r in records if not r.get("source_id"))
    from tools._parse_utils import is_numeric
    num_recs = [r for r in records if is_numeric(r.get("field_value"))]
    records_without_unit = sum(1 for r in num_recs if not r.get("field_unit"))
    from tools.assessment.source_utils import provenance_is_complete
    records_without_prov = sum(1 for r in records if not provenance_is_complete(r))

    data_pass = records_without_source == 0 and records_without_prov == 0
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
    if records_without_prov > 0:
        errors.append({"dimension": "data_integrity", "field": "provenance",
                       "expected": "all complete", "actual": f"{records_without_prov} incomplete",
                       "severity": "error"})

    # ── 3. 格式一致性 (V2.2: 从 target_schema 动态获取别名列表) ──
    # 构建所有已知别名集合 (V3.2 fix: 排除标准字段名本身 — 否则恒报 alias 残留)
    known_aliases: set[str] = set()
    if target_schema:
        for f in target_schema.get("fields", []):
            fname = f.get("name", "")
            for alias in f.get("aliases", []):
                if alias != fname:
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
    # V4 fix: paper 记录必须有 trace_id (DB 记录按 provenance 四要素校验,
    # 由 traceability_builder 统计) — 此前只查自报的修改事件统计, 空转
    paper_missing_trace_id = trace_completeness.get("paper_records_missing_trace_id", 0)
    if paper_missing_trace_id > 0:
        trace_pass = False
        errors.append({"dimension": "traceability",
                       "expected": "all paper records have trace_id",
                       "actual": f"{paper_missing_trace_id} paper records missing trace_id",
                       "severity": "warning"})
    checks["traceability_consistency"] = {
        "passed": trace_pass,
        "traced_records": trace_completeness.get("records_with_trace", 0),
        "untraced_records": trace_completeness.get("records_without_trace", 0),
        # V4: 实际 trace_id 覆盖率
        "records_with_trace_id": trace_completeness.get("records_with_trace_id", 0),
        "paper_records_missing_trace_id": paper_missing_trace_id,
        "database_records": trace_completeness.get("database_records", 0),
        "db_provenance_complete": trace_completeness.get("db_provenance_complete", 0),
    }

    # ── 5. 质量一致性 (V4 fix: 事件数 vs 记录数同口径) ──
    # 此前 modifications.total (修改事件条数, 同记录可多次修改) 与
    # modified_count (值变化的记录数) 直接比较, 0.8 容差掩盖的是口径错配
    # → 真实 e2e 恒失败 (170 >= 336×0.8 不成立)。
    # 现改为: 被修改记录 (有 trace 或无 trace 的) 必须覆盖事件去重后的记录集。
    scoring = quality.get("quality_scoring", {})
    mods = normalization.get("modifications", {})
    mod_total = mods.get("total", 0)
    details = mods.get("details", {}) or {}
    event_record_ids: set[str] = set()
    for layer in ("base", "adapted", "generated"):
        for e in details.get(layer, []) or []:
            rid = e.get("record_id") or e.get("id")
            if rid:
                event_record_ids.add(str(rid))
    unique_event_records = len(event_record_ids)
    records_modified = trace_completeness.get("modified_count", 0)
    records_without_trace = trace_completeness.get("records_without_trace", 0)
    # 每个被改记录必须要么有 trace, 要么被显式记为 untraced
    # (后者已使维度 4 失败, 此处不重复阻塞)
    quality_pass = (records_modified + records_without_trace) >= unique_event_records
    checks["quality_consistency"] = {
        "passed": quality_pass,
        "overall_score": scoring.get("overall_score", 0),
        "modifications_reported": mod_total,
        "unique_event_records": unique_event_records,
        "records_modified": records_modified,
    }
    if not quality_pass:
        errors.append({"dimension": "quality_consistency",
                       "expected": f"{unique_event_records} unique modified records",
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
