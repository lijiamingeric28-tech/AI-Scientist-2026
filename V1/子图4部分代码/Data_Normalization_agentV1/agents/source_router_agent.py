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
    """Stage 1: SourceRouterAgent — 筛选 Normalization sources (V2.1)"""

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

        # ── V2.1: 从 Assessment per_source_routes 筛选 ──
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

        # ── V2.1: 从 Conflict resolution_plan 提取需要规范化的 actions ──
        conflict_actions = []
        if trigger == "conflict_report" and conflict:
            resolution_report = conflict.get("resolution_report", {})
            plan = resolution_report.get("resolution_plan", {})
            for action in plan.get("actions_to_normalize", []):
                source_id = action.get("target_source") or action.get("source_id", "")
                field = action.get("field", "")
                new_value = action.get("new_value")
                if source_id:
                    conflict_actions.append({
                        "source_id": source_id, "field": field,
                        "entity_type": action.get("entity_type", ""),
                        "entity_name": action.get("entity_name", ""),
                        "new_value": new_value, "action": action.get("action", "normalize"),
                        "reason": action.get("reason", ""),
                    })
                    # 确保该 source 进入规范化列表
                    if source_id not in sources_to_process:
                        sources_to_process[source_id] = {
                            "record_count": 0, "conditions": [],
                            "needs_full_normalization": False, "priority": 0,
                        }
                    sources_to_process[source_id]["conflict_actions"] = conflict_actions

            # 处理 annotations (retain_range/retain_both)
            for annotation in plan.get("annotations_to_add", []):
                source_id = annotation.get("target_source", "*")
                if source_id != "*" and source_id not in sources_to_process:
                    sources_to_process[source_id] = {
                        "record_count": 0, "conditions": [],
                        "needs_full_normalization": False, "priority": 0,
                    }
                    sources_to_process[source_id]["conflict_annotations"] = [
                        annotation
                    ]

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

        return {
            "report_state": {"normalization": {"source_plan": source_plan}},
            "workflow_state": {"current_node": "source_router", "execution_status": "Success",
                               "workflow_history": [{"agent": "SourceRouterAgent", "stage": "SourceRouter",
                                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                                    "duration": round(time.time()-t0,3),
                                    "reason": f"{len(sources_to_process)} to normalize, {len(skipped)} skipped"}]},
        }
