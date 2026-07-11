"""validation_agent.py — Stage 4: ValidationAgent"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
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

        # Schema check
        present = sorted(set(r.get("field_name","") for r in records))
        expected = sorted(f.get("name","") for f in target_schema.get("fields",[])) if target_schema else []
        still_missing = [f for f in expected if f not in present]

        # Format check
        missing_units = sum(1 for r in records if isinstance(r.get("field_value"),(int,float)) and r.get("field_unit") is None)
        missing_prov = sum(1 for r in records if not r.get("provenance") or r["provenance"].get("page") is None)

        # Conflict check
        conflicts = 0
        try:
            from tools.assessment.statistical_conflict import detect_conflicts_statistical
            conflicts = detect_conflicts_statistical(data).get("conflict_count", 0)
        except Exception: pass

        # Semantic check
        oor = 0
        try:
            from tools.assessment.semantic_type import infer_all_fields
            oor = sum(1 for s in infer_all_fields(records).values() if s.get("out_of_range"))
        except Exception: pass

        remaining = []
        if still_missing: remaining.append(f"Schema: {still_missing}")
        if missing_units: remaining.append(f"Units: {missing_units} records missing")
        if oor: remaining.append(f"Range: {oor} out of feasible range")
        needs_conflict = conflicts > 0
        is_valid = len(remaining) == 0

        validation = {"is_valid": is_valid, "schema_check": {"passed": not still_missing},
                      "format_check": {"passed": missing_units==0, "missing_units": missing_units},
                      "conflict_check": {"has_conflicts": needs_conflict, "conflict_count": conflicts},
                      "semantic_check": {"out_of_range_count": oor},
                      "remaining_issues": remaining, "needs_conflict_analysis": needs_conflict,
                      "retry_count": 0, "confidence": 0.7}
        route = "Conflict" if needs_conflict else "Export"
        norm["validation"] = validation

        history = list(wf.get("workflow_history", []))
        history.append({"agent": "ValidationAgent", "stage": "Validation", "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(), "duration": round(time.time()-t0,3),
                        "reason": f"Valid={is_valid}, conflicts={conflicts}, route={route}"})
        logger.info("[Validation] valid=%s conflicts=%d route=%s", is_valid, conflicts, route)
        return {"report_state": {"normalization": norm},
                "workflow_state": {"route_decision": route, "execution_status": "Success",
                                   "current_node": "validation", "workflow_history": history}}
