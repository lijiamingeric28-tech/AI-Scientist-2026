"""
source_router_agent.py — Stage 1: SourceRouterAgent

职责: 读取 Assessment per-source 路由，筛选出需要规范化的 sources。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)

class SourceRouterAgent:
    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})
        quality = rs.get("quality", {}) or {}
        conflict = rs.get("conflict")

        per_source_routes = quality.get("per_source_routes", {})
        conditional = quality.get("conditional_routes", [])

        trigger = "conflict_report" if conflict else "quality_report"
        sources_to_process: dict[str, dict] = {}
        skipped = []

        for sid, route in per_source_routes.items():
            if route == "Normalization":
                src_info = quality.get("sources", {}).get(sid, {})
                conds = []
                for cr in conditional:
                    if cr.get("source_id") == sid:
                        conds = cr.get("conditions", [])
                sources_to_process[sid] = {
                    "record_count": src_info.get("record_count", 0),
                    "conditions": conds,
                    "needs_full_normalization": trigger == "conflict_report",
                    "priority": len(conds),
                }
            else:
                skipped.append(sid)

        source_plan = {
            "trigger_source": trigger,
            "sources_to_normalize": sources_to_process,
            "sources_skipped": skipped,
            "total_to_normalize": len(sources_to_process),
            "total_skipped": len(skipped),
        }

        # 无 source 需要规范化 → 直接 Export
        if not sources_to_process:
            logger.info("[SourceRouter] No sources to normalize → Export")
            return {
                "report_state": {"normalization": {"source_plan": source_plan}},
                "workflow_state": {"route_decision": "Export", "execution_status": "Success",
                                   "current_node": "source_router",
                                   "workflow_history": [{"agent": "SourceRouterAgent", "stage": "SourceRouter",
                                        "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                                        "duration": round(time.time()-t0,3), "reason": "No sources to normalize → Export"}]},
            }

        logger.info("[SourceRouter] %d sources to normalize (trigger=%s), %d skipped",
                    len(sources_to_process), trigger, len(skipped))

        history = list(wf.get("workflow_history", []))
        history.append({"agent": "SourceRouterAgent", "stage": "SourceRouter", "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(), "duration": round(time.time()-t0,3),
                        "reason": f"{len(sources_to_process)} to normalize, {len(skipped)} skipped"})

        return {
            "report_state": {"normalization": {"source_plan": source_plan}},
            "workflow_state": {"current_node": "source_router", "execution_status": "Success",
                               "workflow_history": history},
        }
