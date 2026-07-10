"""
decision_reasoning_agent.py — Stage 4: DecisionReasoningAgent

职责: 对每篇论文独立做路由决策, 然后聚合为整体 route_decision。
- 每个 source 独立判断: Export / Normalization / Conflict / HumanReview
- 聚合: 取最严重的 (Conflict > Normalization > Export > HumanReview)
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from quality_state import QualityGraphState
from utils.llm import set_agent_context
from utils.logger import get_logger

logger = get_logger(__name__)

_ROUTE_SEVERITY = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}


class DecisionReasoningAgent:
    """Stage 4: Per-Source Decision + Aggregate Route。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        quality = dict(rs.get("quality", {}) or {})
        source_reports = quality.get("sources", {})

        # ── 逐 source 决策 ──
        per_source_routes: dict[str, str] = {}
        per_source_reasons: dict[str, str] = {}
        llm_count = wf.get("llm_call_count", 0)

        for sid, sr in source_reports.items():
            sr_scoring = sr.get("quality_scoring", {})
            sr_conflict = sr.get("conflict_risk", {})
            sr_completeness = sr.get("completeness", {})
            sr_consistency = sr.get("consistency", {})
            sr_format = sr.get("format", {})

            # ── V2.0 D1: LLM 决策 (优先) + 规则引擎回退 ──
            n_recs = sr.get("record_count", 0)
            outlier_info = ""
            dist_info = ""
            if state.get("report_state", {}).get("quality", {}).get("profile", {}).get("outliers", {}):
                ol = state["report_state"]["quality"]["profile"]["outliers"].get(sr.get("completeness", {}).get("field_name", ""), {})
                if ol.get("outlier_ratio", 0) > 0:
                    outlier_info = f"Outliers: {ol.get('definite_count',0)} definite, {ol.get('suspected_count',0)} suspected. "

            try:
                from utils.llm import get_structured_llm, set_agent_context
                from schemas import AssessmentDecision

                llm_prompt = (
                    f"Source: {sr.get('title','?')[:80]} ({sr.get('year','?')}), {n_recs} records. "
                    f"Completeness={sr_completeness.get('score',0):.2f}, "
                    f"Consistency={sr_consistency.get('score',0):.2f}, "
                    f"Format={sr_format.get('score',0):.2f}, "
                    f"Conflicts={sr_conflict.get('conflict_count',0)} ({sr_conflict.get('risk_level','none')}), "
                    f"Quality={sr_scoring.get('quality_level','?')} ({sr_scoring.get('overall_score',0):.2f}). "
                    f"{outlier_info}"
                    f"Issues: {sr.get('issue_count',0)}. "
                    f"Decide route: Export/Normalization/Conflict/HumanReview. "
                    f"Priority: Conflict > Normalization > Export. "
                    f"Consider: small sample={n_recs<10}, outlier presence, data value for research."
                )
                set_agent_context("assessment")
                llm = get_structured_llm(AssessmentDecision, temperature=0.0)
                decision = llm.invoke([
                    {"role": "system", "content": "Decide workflow route for this data source."},
                    {"role": "user", "content": llm_prompt},
                ])
                route = decision.route
                reason = decision.reasoning[:200]
                if decision.confidence < 0.5 and route != "HumanReview":
                    route = "HumanReview"
            except Exception:
                # 回退规则引擎
                from tools.assessment.adaptive_threshold import AdaptiveThresholdEngine
                adaptive_eng = AdaptiveThresholdEngine()
                comp_threshold = adaptive_eng.get_completeness_threshold("", n_recs)

                has_conflict = sr_conflict.get("has_conflicts", False)
                need_norm = (
                    sr_completeness.get("score", 1.0) < comp_threshold
                    or sr_consistency.get("score", 1.0) < 0.9
                    or sr_format.get("score", 1.0) < 0.9
                )
                if has_conflict:
                    route = "Conflict"
                    reason = f"Conflict: {sr_conflict.get('conflict_count',0)} conflicts"
                elif need_norm:
                    route = "Normalization"
                    reason = f"Needs normalization (comp={sr_completeness.get('score',0):.2f})"
                elif sr_scoring.get("quality_level") == "poor":
                    route = "HumanReview"
                    reason = f"Poor quality (score={sr_scoring.get('overall_score',0):.2f})"
                else:
                    route = "Export"
                    reason = f"Clean (score={sr_scoring.get('overall_score',0):.2f})"

            per_source_routes[sid] = route
            per_source_reasons[sid] = reason
            sr["route_decision"] = route
            sr["decision_reason"] = reason

        # ── 聚合: 取最严重的路由 ──
        worst_route = "Export"
        worst_severity = 0
        for route in per_source_routes.values():
            sev = _ROUTE_SEVERITY.get(route, 0)
            if sev > worst_severity:
                worst_severity = sev
                worst_route = route

        # ── V2.0 D2: 多准则决策矩阵 ──
        # Quality × Repair Cost → refined route
        _DECISION_MATRIX = {
            # (quality, repair_cost) → route
            ("excellent", "low"): "Export",
            ("excellent", "medium"): "Export",
            ("excellent", "high"): "Normalization",
            ("good", "low"): "Export",
            ("good", "medium"): "Normalization",
            ("good", "high"): "Normalization",
            ("fair", "low"): "Normalization",
            ("fair", "medium"): "Normalization",
            ("fair", "high"): "Conflict",
            ("poor", "low"): "Normalization",
            ("poor", "medium"): "Conflict",
            ("poor", "high"): "HumanReview",
        }

        # 计算 repair cost
        def _estimate_repair_cost(sr: dict) -> str:
            """估算修复成本: low/medium/high"""
            issues = sr.get("issue_count", 0)
            conflicts = sr.get("conflict_risk", {}).get("conflict_count", 0)
            if conflicts >= 3 or issues >= 10:
                return "high"
            elif conflicts >= 1 or issues >= 3:
                return "medium"
            else:
                return "low"

        matrix_routes = {}
        for sid, sr in source_reports.items():
            ql = sr.get("quality_scoring", {}).get("quality_level", "fair")
            rc = _estimate_repair_cost(sr)
            matrix_route = _DECISION_MATRIX.get((ql, rc), per_source_routes[sid])
            matrix_routes[sid] = {
                "quality_level": ql,
                "repair_cost": rc,
                "matrix_route": matrix_route,
                "rule_route": per_source_routes[sid],
            }

        quality["decision_matrix"] = matrix_routes

        # ── LLM 生成聚合摘要 ──
        try:
            from utils.llm import get_llm
            set_agent_context("assessment")

            route_summary = ", ".join(f"{sid[:20]}={r}" for sid, r in per_source_routes.items())
            llm_prompt = (
                f"{len(source_reports)} sources assessed. Routes: {route_summary}. "
                f"Overall route: {worst_route}. "
                f"Generate a 1-2 sentence assessment summary."
            )
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([
                {"role": "system", "content": "你是科学数据评估专家。生成简短评估摘要。"},
                {"role": "user", "content": llm_prompt},
            ])
            llm_summary = (resp.content if hasattr(resp, "content") else str(resp))[:300]
            llm_count += 1
        except Exception:
            route_counts = {}
            for r in per_source_routes.values():
                route_counts[r] = route_counts.get(r, 0) + 1
            llm_summary = f"{len(source_reports)} sources: {route_counts}. Overall→{worst_route}"

        # ── V2.0 D3: 条件路由 ──
        conditional_routes = []
        for sid, sr in source_reports.items():
            route = per_source_routes[sid]
            conditions = []
            if route == "Normalization":
                if sr.get("completeness", {}).get("score", 1.0) < 0.9:
                    conditions.append({
                        "condition": "completeness_low",
                        "route": "Normalization",
                        "reason": "需补充缺失数据或修复溯源信息"
                    })
                if sr.get("format", {}).get("total_issues", 0) > 0:
                    conditions.append({
                        "condition": "format_issues",
                        "route": "Normalization",
                        "reason": "需标准化字段格式"
                    })
                if not conditions:
                    conditions.append({
                        "condition": "general",
                        "route": "Normalization",
                        "reason": "需字段映射和单位转换"
                    })
            elif route == "Conflict":
                conditions.append({
                    "condition": "has_conflict",
                    "route": "Conflict",
                    "reason": f"存在{sr.get('conflict_risk',{}).get('conflict_count',0)}个跨来源冲突"
                })
            elif route == "Export":
                conditions.append({
                    "condition": "clean",
                    "route": "Export",
                    "reason": "数据可直接使用"
                })
            conditional_routes.append({
                "source_id": sid,
                "primary_route": route,
                "conditions": conditions,
            })

        quality["conditional_routes"] = conditional_routes
        quality["per_source_routes"] = per_source_routes
        quality["per_source_reasons"] = per_source_reasons
        quality["route_decision"] = worst_route
        quality["decision_reasoning"] = llm_summary
        quality["need_normalization"] = worst_route == "Normalization"
        quality["need_conflict_analysis"] = worst_route == "Conflict"
        quality["assessment_summary"] = (
            f"{len(source_reports)} sources. Routes: "
            + ", ".join(f"{sid[:15]}→{r}" for sid, r in per_source_routes.items())
            + f". Overall→{worst_route}."
        )

        elapsed = round(time.time() - t0, 3)
        logger.info("[DecisionReasoningAgent] %d sources, overall=%s, %.2fs",
                    len(source_reports), worst_route, elapsed)

        return {
            "report_state": {"quality": quality},
            "workflow_state": {
                "route_decision": worst_route,
                "execution_status": "Success",
                "current_node": "decision",
                "retry_counter": 0,
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "DecisionReasoningAgent", "stage": "DecisionReasoning",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(source_reports)} sources, overall={worst_route}",
                }],
            },
        }
