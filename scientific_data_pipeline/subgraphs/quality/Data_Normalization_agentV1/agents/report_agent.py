"""report_agent.py — Stage 5: ReportAgent"""
from __future__ import annotations
import datetime, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

class ReportAgent:
    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {}); wf = state.get("workflow_state", {})
        norm = dict(rs.get("normalization", {}) or {})
        validation = norm.get("validation", {})
        sp = norm.get("source_plan", {})

        total_issues = len(validation.get("remaining_issues", []))
        if not sp.get("sources_to_normalize"):
            status = "Skipped_No_Sources"
        elif total_issues > 0:
            status = "Completed_With_Issues"
        else:
            status = "Completed"

        norm["normalization_status"] = status
        mods = norm.get("modifications", {})
        by_layer = mods.get("by_layer", {})
        registry = norm.get("tool_registry", {})
        norm["normalization_summary"] = (
            f"Normalization {status}: {sp.get('total_to_normalize',0)} sources processed, "
            f"{mods.get('total',0)} modifications "
            f"(base={by_layer.get('base',0)} adapted={by_layer.get('adapted',0)} generated={by_layer.get('generated',0)}), "
            f"{total_issues} remaining issues, "
            f"route={validation.get('needs_conflict_analysis',False) and 'Conflict' or 'Export'}"
        )
        norm["tool_registry_summary"] = {
            "base_tools_used": len(registry.get("base_tools", [])),
            "adapted_tools_used": len(registry.get("adapted_tools", [])),
            "generated_tools_used": len(registry.get("generated_tools", [])),
        }
        route = "Conflict" if validation.get("needs_conflict_analysis") else "Export"
        norm["route_decision"] = route
        norm["total_tool_calls"] = wf.get("tool_call_count", 0)

        history = list(wf.get("workflow_history", []))
        history.append({"agent": "ReportAgent", "stage": "Report", "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(), "duration": round(time.time()-t0,3),
                        "reason": status})
        logger.info("[Report] status=%s, route=%s", status, route)
        return {"report_state": {"normalization": norm},
                "workflow_state": {"route_decision": route, "current_node": "report",
                                   "execution_status": "Success", "workflow_history": history}}
