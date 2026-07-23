"""
resolution_report_agent.py — Node 6: ResolutionReportAgent

职责: 汇总所有分析结果, 生成标准化 Conflict Resolution Report,
      设置 route_decision 和 resolution_plan。
LLM: 是 (摘要生成) | Tools: 0
"""
from __future__ import annotations
import datetime, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.llm import get_llm, set_agent_context, track_raw_llm_call
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


class ResolutionReportAgent:
    """Node 6: 报告生成 — 汇总 + 路由"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        domain = state.get("context_state", {}).get("research_domain", "default")

        identification = conflict_state.get("identification", {})
        classification = conflict_state.get("classification", {})
        reasoning = conflict_state.get("reasoning", {})
        confidence = conflict_state.get("confidence", {})

        agg = reasoning.get("aggregated", {})
        plan = agg.get("resolution_plan", {})
        resolutions = reasoning.get("per_conflict", [])

        auto_resolved = agg.get("auto_resolved", 0)
        human_required = agg.get("human_required", 0)
        total = identification.get("total_conflicts", 0)

        # ── 路由决策 ──
        actions_to_normalize = plan.get("actions_to_normalize", [])
        human_review_items = plan.get("human_review_items", [])

        if total == 0:
            route = "Export"
            status = "No_Conflicts"
        elif human_required == 0 and actions_to_normalize:
            route = "Normalization"
            status = "All_Resolved"
        elif human_required == 0 and not actions_to_normalize:
            route = "Export"
            status = "All_Resolved"
        elif human_required > 0 and auto_resolved > 0:
            route = "Normalization"
            status = "Partially_Resolved"
        elif human_required > 0 and auto_resolved == 0:
            route = "HumanReview"
            status = "All_Escalated"
        else:
            route = "HumanReview"
            status = "All_Escalated"

        # ── LLM 摘要 ──
        strategies_used = list(set(r.get("strategy", "?") for r in resolutions))
        llm_count = wf.get("llm_call_count", 0)
        summary = ""
        try:
            set_agent_context("conflict_report")
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([
                {"role": "system", "content": "You are a scientific data analysis reporter. Generate a concise 2-3 sentence summary of conflict resolution results."},
                {"role": "user", "content": f"{total} conflicts analyzed in {domain}. Auto-resolved: {auto_resolved}, Escalated: {human_required}. Strategies: {strategies_used}. Route: {route}. Summary:"},
            ])
            summary = (resp.content if hasattr(resp, "content") else str(resp))[:400]
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="conflict_report")
        except Exception as e:
            logger.warning("[ResolutionReport] LLM summary failed: %s", e)
            summary = f"{total} conflicts analyzed in {domain}. {auto_resolved} auto-resolved using {strategies_used}, {human_required} escalated to human review. Route: {route}."

        # ── 构建 Report ──
        # 补全 resolution_plan 中的 field 信息
        classified_conflicts = classification.get("classified_conflicts", [])
        field_map = {c.get("conflict_id"): c.get("field_name", "") for c in classified_conflicts}
        for action in actions_to_normalize:
            if action.get("field") == action.get("conflict_id", ""):
                action["field"] = field_map.get(action["conflict_id"], action["field"])

        enriched_plan = {
            "actions_to_normalize": actions_to_normalize,
            "annotations_to_add": plan.get("annotations_to_add", []),
            "human_review_items": human_review_items,
        }

        report = {
            "metadata": {
                "generated_at": datetime.datetime.now().isoformat(),
                "trigger_path": identification.get("trigger_path", "unknown"),
                "iteration": wf.get("iteration_counter", 0),
                "total_conflicts": total,
                "auto_resolved": auto_resolved,
                "human_required": human_required,
            },
            "per_conflict": resolutions,
            "confidence": confidence,
            "resolution_plan": enriched_plan,
            "route_decision": route,
            "status": status,
            "summary": summary,
        }

        elapsed = round(time.time() - t0, 3)
        logger.info("[ResolutionReport] %s, route=%s, %.2fs", status, route, elapsed)

        return {
            "report_state": {"conflict": {
                "resolution_report": report,
            }},
            "workflow_state": {
                "route_decision": route,
                "execution_status": "Success",
                "current_node": "resolution_report",
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "ResolutionReportAgent", "stage": "Report",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{status}: {auto_resolved}/{total} auto-resolved, route={route}",
                }],
            },
        }
