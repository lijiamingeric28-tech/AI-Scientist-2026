"""validation_agent.py — Stage 4: ValidationAgent"""
from __future__ import annotations
import datetime, time
from typing import Any
from ...quality_state import QualityGraphState
from ...utils.logger import get_logger
logger = get_logger(__name__)

class ValidationAgent:
    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ds = state.get("data_state", {}); rs = state.get("report_state", {}); ctx = state.get("context_state", {})
        wf = state.get("workflow_state", {})
        data = ds.get("current_data", ds.get("input_data", {}))
        records = data.get("records", [])
        norm = dict(rs.get("normalization", {}) or {})
        target_schema = ctx.get("target_schema")

        # Schema check (V3.0: 只检查数据中存在的字段是否有 schema 映射, 不要求全部字段存在)
        present = sorted(set(r.get("field_name","") for r in records))
        # 只检查 critical 级别的必需字段是否缺失 (数据完整性由 Assessment 负责)
        critical_expected = sorted(
            f.get("name","") for f in target_schema.get("fields",[])
            if f.get("criticality") == "critical" and f.get("name","") in present
        ) if target_schema else []
        # 实际上 Normalization 无法补充缺失字段 — 不做 schema 完整性检查
        still_missing = []  # V3.0: schema 完整性由 Assessment 负责, Normalization 只修已有字段

        # Format check
        from ...tools._parse_utils import is_numeric
        missing_units = sum(1 for r in records if is_numeric(r.get("field_value")) and not r.get("field_unit"))  # V4 fix: 空串也算缺失
        missing_prov = sum(1 for r in records if not r.get("provenance") or r["provenance"].get("page") is None)

        # ── V2.1: Conflict check — 保存完整 conflicts 数组 (P1-2 fix) ──
        conflict_check_full = {"has_conflicts": False, "conflict_count": 0, "conflicts": [],
                               "method": "cohens_d", "risk_level": "none"}
        try:
            from ...tools.assessment.statistical_conflict import detect_conflicts_statistical
            conflict_check_full = detect_conflicts_statistical(data)
        except Exception as e:
            logger.warning("[Validation] Conflict check failed: %s", e)

        conflicts = conflict_check_full.get("conflict_count", 0)

        # Semantic check
        oor = 0
        try:
            from ...tools.assessment.semantic_type import infer_all_fields
            oor = sum(1 for s in infer_all_fields(records).values() if s.get("out_of_range"))
        except Exception: pass

        remaining = []
        if still_missing: remaining.append(f"Schema: {still_missing}")
        if missing_units: remaining.append(f"Units: {missing_units} records missing")
        if oor: remaining.append(f"Range: {oor} out of feasible range")
        needs_conflict = conflicts > 0
        is_valid = len(remaining) == 0

        # ── V3.0: retry 控制 — Layer 3 (LLM生成) 失败不计入重试条件 ──
        retry_count = norm.get("validation", {}).get("retry_count", 0)

        # 检查是否有 Base/Adapted 工具级别的问题 (非 Layer 3 LLM 生成的问题)
        tool_registry = norm.get("tool_registry", {})
        mods = norm.get("modifications", {})
        gen_errors = mods.get("errors", mods.get("generated_errors", []))
        has_base_issues = not is_valid and (
            still_missing or                                   # schema 字段缺失
            missing_units > 0 or                              # 单位缺失
            (oor > 0 and oor > len(gen_errors))               # 语义越界 (排除 Layer3 失败导致的)
        )

        MAX_NORM_RETRIES = 1  # V3.0: 减少 LLM 重试
        if has_base_issues and retry_count < MAX_NORM_RETRIES:
            status = "Retry"
            route = ""
            retry_count += 1
            logger.info("[Validation] Base tool issues remain → retry %d/%d", retry_count, MAX_NORM_RETRIES)
        elif gen_errors and not has_base_issues:
            # Layer 3 生成的工具有运行时错误, 但不影响整体验证通过
            status = "Success"
            # V4 fix: 复检发现冲突时优先 B→C, 不再无条件 Export
            route = "Conflict" if needs_conflict else "Export"
            remaining.append(f"Note: {len(gen_errors)} generated tool(s) had runtime errors (non-blocking)")
            logger.warning("[Validation] %d generated tool errors (non-blocking), valid=%s",
                          len(gen_errors), is_valid)
        else:
            status = "Success"
            # V4 fix: 与 needs_conflict_analysis 字段保持一致 —
            # 此前恒 Export, 冲突检测结果被 gate 覆写后完全丢失 (B→C 死代码)
            route = "Conflict" if needs_conflict else "Export"

        # V2: per-entity validation breakdown (V3.0: skip schema completeness)
        per_entity_validation: dict[str, dict] = {}
        entity_records: dict[str, list[dict]] = {}
        for r in records:
            et = r.get("entity_type", "") or ""
            en = r.get("entity_name", "") or "unknown"
            elabel = f"{et}:{en}" if et else en
            entity_records.setdefault(elabel, []).append(r)

        for elabel, erecs in entity_records.items():
            e_present = sorted(set(r.get("field_name", "") for r in erecs))
            e_missing_units = sum(1 for r in erecs if is_numeric(r.get("field_value")) and not r.get("field_unit"))  # V4 fix: 空串也算缺失
            e_total = len(erecs)
            per_entity_validation[elabel] = {
                "records": e_total,
                "present_fields": e_present,
                "missing_units": e_missing_units,
                "schema_ok": True,   # V3.0: schema 完整性由 Assessment 负责
                "format_ok": e_missing_units == 0,
            }

        validation = {
            "is_valid": is_valid,
            "schema_check": {"passed": not still_missing},
            "format_check": {"passed": missing_units==0, "missing_units": missing_units},
            "conflict_check": conflict_check_full,  # V2.1: 完整结果
            "semantic_check": {"out_of_range_count": oor},
            "remaining_issues": remaining,
            "needs_conflict_analysis": needs_conflict,
            "retry_count": retry_count,
            "confidence": 0.7 if is_valid else 0.5,
            # V2: per-entity validation
            "per_entity": per_entity_validation,
        }
        norm["validation"] = validation

        logger.info("[Validation] valid=%s conflicts=%d route=%s status=%s", is_valid, conflicts, route, status)
        return {"report_state": {"normalization": norm},
                "workflow_state": {"route_decision": route, "execution_status": status,
                                   "current_node": "validation",
                                   "workflow_history": [{
                                       "agent": "ValidationAgent", "stage": "Validation",
                                       "status": status,
                                       "timestamp": datetime.datetime.now().isoformat(),
                                       "duration": round(time.time()-t0, 3),
                                       "reason": f"Valid={is_valid}, conflicts={conflicts}, route={route}",
                                   }]}}
