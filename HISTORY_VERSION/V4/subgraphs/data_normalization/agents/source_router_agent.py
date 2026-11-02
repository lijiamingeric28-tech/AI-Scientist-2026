"""
source_router_agent.py — Stage 1: SourceRouterAgent

职责: 读取 Assessment per-source 路由，筛选出需要规范化的 sources。
"""
from __future__ import annotations
import datetime
import time
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
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

        # V2: per-entity routing awareness — 从 Assessment per-entity 数据中提取
        quality_scoring = quality.get("quality_scoring", {})
        per_entity_all = quality_scoring.get("per_entity_scores", {})

        # ── V2.1: 从 Assessment per_source_routes 筛选 ──
        for sid, route in per_source_routes.items():
            if route == "Normalization":
                src_info = quality.get("sources", {}).get(sid, {})
                conds = []
                for cr in conditional:
                    if cr.get("source_id") == sid:
                        conds = cr.get("conditions", [])
                # V2: extract entity info for this source
                src_entities = per_entity_all.get(sid, {})
                sources_to_process[sid] = {
                    "record_count": src_info.get("record_count", 0),
                    "conditions": conds,
                    "needs_full_normalization": trigger == "conflict_report",
                    "priority": len(conds),
                    # V2: per-entity breakdown
                    "entities": {elabel: edata for elabel, edata in src_entities.items()},
                }
            else:
                skipped.append(sid)

        # ── V2.1: 从 Conflict resolution_plan 提取需要规范化的 actions ──
        # V3.5 fix: 保留 record_ids/from_unit/to_unit (HumanReview 动作端到端落地)
        conflict_ctions = []
        plan_errors = []  # H-04 fix: 空 source_id 动作记 warning 入 errors, 不静默丢弃
        if trigger == "conflict_report" and conflict:
            resolution_report = conflict.get("resolution_report", {})
            plan = resolution_report.get("resolution_plan", {})
            for action in plan.get("actions_to_normalize", []):
                source_id = action.get("target_source") or action.get("source_id", "")
                field = action.get("field", action.get("field_name", ""))
                new_value = action.get("new_value")
                if source_id:
                    conflict_ctions.append({
                        "source_id": source_id, "field": field,
                        "record_ids": action.get("record_ids", []),   # V3.5: 保留
                        "entity_type": action.get("entity_type", ""),
                        "entity_name": action.get("entity_name", ""),
                        "from_unit": action.get("from_unit"),          # V3.5: 保留
                        "to_unit": action.get("to_unit"),              # V3.5: 保留
                        "new_value": new_value, "action": action.get("action", "normalize"),
                        "reason": action.get("reason", ""),
                    })
                    # 确保该 source 进入规范化列表
                    if source_id not in sources_to_process:
                        sources_to_process[source_id] = {
                            "record_count": 0, "conditions": [],
                            "needs_full_normalization": False, "priority": 0,
                        }
                    sources_to_process[source_id]["conflict_ctions"] = conflict_ctions
                else:
                    # H-04 fix: 空 source_id 无法定位目标 source — 记 warning 入 errors 而非静默跳过
                    logger.warning(
                        "[SourceRouter] 动作缺少 source_id, 跳过: action=%s field=%s reason=%s",
                        action.get("action", ""), field, action.get("reason", ""))
                    plan_errors.append({
                        "error": "action_missing_source_id",
                        "action": action.get("action", ""),
                        "field": field,
                        "reason": action.get("reason", ""),
                    })

            # 处理 annotations (retain_range/retain_both)
            # M5 fix: 并入 conflict_ctions (executor 唯一读取的键) — 原 typo 键
            # conflict_nnotations 从未被消费, 且"仅新 source 挂载"条件使已存在
            # source 的标注直接丢弃 → retain_range/retain_both 裁决永远不落地
            for annotation in plan.get("annotations_to_add", []):
                source_id = annotation.get("target_source", "*")
                if source_id == "*":
                    continue  # 全 source 标注暂不支持逐 source 挂载
                annotate_action = {
                    "source_id": source_id,
                    "field": annotation.get("field", annotation.get("field_name", "")),
                    "record_ids": annotation.get("record_ids", []),
                    "entity_type": annotation.get("entity_type", ""),
                    "entity_name": annotation.get("entity_name", ""),
                    "new_value": None,
                    "action": "annotate",
                    "reason": annotation.get("reason", "annotated"),
                }
                if source_id not in sources_to_process:
                    sources_to_process[source_id] = {
                        "record_count": 0, "conditions": [],
                        "needs_full_normalization": False, "priority": 0,
                    }
                sources_to_process[source_id].setdefault("conflict_ctions", []).append(
                    annotate_action
                )

        source_plan = {
            "trigger_source": trigger,
            "sources_to_normalize": sources_to_process,
            "sources_skipped": skipped,
            "total_to_normalize": len(sources_to_process),
            "total_skipped": len(skipped),
            "errors": plan_errors,  # H-04 fix: 空 source_id 动作明细 (消费方可见, 不静默)
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
