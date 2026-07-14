"""
decision_reasoning_agent.py — Stage 4: DecisionReasoningAgent (V2.1)

严格路由策略: 只有数据格式完全无问题才能 Export。
任何可修复问题 → Normalization, 冲突 → Conflict, 无法判断 → HumanReview。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from utils.llm import set_agent_context
from utils.logger import get_logger
logger = get_logger(__name__)
_ROUTE_SEVERITY = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}

_DECISION_SYSTEM = """你是科学数据质量评估专家。决定工作流路由: Export / Normalization / Conflict / HumanReview。

**严格 Export 标准 (必须全部满足):**
1. 所有 field_name 都是目标 Schema 中的标准名 (无别名 YS/UTS/EL/σ_y)
2. 所有数值字段都有 field_unit (无缺失单位)
3. 所有数值值都是干净数字 (无 ~ ≈ approx 前缀)
4. 所有记录都有完整 provenance (page + bbox)
5. 无跨来源冲突
6. 无格式问题
7. completeness=1.0, consistency=1.0, format=1.0

**如果以上任何一条不满足 → Normalization**
**如果有跨来源数值冲突 → Conflict**
**只有全部满足才能 Export**

返回 JSON: {"route": "string", "reasoning": "string", "critical_issues": [...], "confidence": 0.9}"""


class DecisionReasoningAgent:
    """Stage 4: V2.1 严格路由 — 不完美即 Normalization。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})
        quality = dict(rs.get("quality", {}) or {})
        source_reports = quality.get("sources", {})
        profile = quality.get("profile", {})

        per_source_routes: dict[str, str] = {}
        per_source_reasons: dict[str, str] = {}
        llm_count = wf.get("llm_call_count", 0)

        for sid, sr in source_reports.items():
            sr_scoring = sr.get("quality_scoring", {})
            sr_conflict = sr.get("conflict_risk", {})
            sr_completeness = sr.get("completeness", {})
            sr_consistency = sr.get("consistency", {})
            sr_format = sr.get("format", {})
            n_recs = sr.get("record_count", 0)

            # ═══ V2.1: 严格问题检测 (per-source) ═══
            issues_found = []

            # 1. 别名检测: per-source present_fields vs expected_fields
            expected = set(sr_completeness.get("expected_fields", []))
            actual = set(sr_completeness.get("present_fields", []))
            aliases = actual - expected  # fields present but not in target schema
            if aliases:
                issues_found.append(f"alias_fields: {sorted(aliases)}")

            # 2. 格式问题: field_value 包含 ~ ≈ 前缀的字符串
            fmt_issues = sr_format.get("total_issues", 0)
            if fmt_issues > 0:
                issues_found.append(f"format_issues: {fmt_issues} records")

            # 3. 缺失单位
            missing_units = sr_completeness.get("records_missing_unit", 0)
            if missing_units > 0:
                issues_found.append(f"missing_units: {missing_units} records")

            # 4. 缺失溯源
            missing_prov = sr_completeness.get("records_missing_provenance", 0)
            if missing_prov > 0:
                issues_found.append(f"missing_provenance: {missing_prov} records")

            # 5a. 单位不一致 (同一字段多单位)
            unit_cons = sr_consistency.get("unit_consistency", {})
            unit_issues = {k: v for k, v in unit_cons.items()
                           if isinstance(v, str) and "inconsistent" in v}
            if unit_issues:
                issues_found.append(f"unit_inconsistency: {sorted(unit_issues.keys())}")

            # 5b. 单位与标准不符 (直接查 target_schema)
            target_schema = state.get("context_state", {}).get("target_schema", {})
            schema_fields = {f.get("name"): f.get("standard_unit") for f in target_schema.get("fields", [])
                             if f.get("standard_unit")}
            ds = state.get("data_state", {}).get("current_data", {})
            src_records = [r for r in ds.get("records", []) if r.get("source_id") == sid]
            for fn in set(r.get("field_name") for r in src_records):
                std_unit = schema_fields.get(fn)
                if not std_unit:
                    continue
                current_units = {r.get("field_unit") for r in src_records
                                 if r.get("field_name") == fn and r.get("field_unit")}
                if not current_units:
                    continue  # already caught by missing_units check
                # 标准化比较: "C" = "°C" = "℃"
                def _norm_unit(u): return (u or "").replace("°","").replace("℃","C").strip()
                norm_current = {_norm_unit(u) for u in current_units}
                norm_std = _norm_unit(std_unit)
                if norm_current != {norm_std}:
                    issues_found.append(f"unit_mismatch: {fn} has {sorted(current_units)} (expected {std_unit})")

            # 6. 冲突 — 不计入 issues_found, 单独用 has_conflict 判断路由
            has_conflict = sr_conflict.get("has_conflicts", False)
            conflict_count = sr_conflict.get("conflict_count", 0)

            # 6. 完整性不完美 — 不计入可操作路由 (缺失字段不是Normalization能修复的)

            # ═══ V3.0: 决策逻辑 — 只对可操作问题路由 ─
            # Step 1: 计算 Repair Cost (通用公式, 不限于特定领域)
            issue_count = len(issues_found)
            repair_cost = "low"
            if conflict_count >= 3 or issue_count >= 10:
                repair_cost = "high"
            elif conflict_count >= 1 or issue_count >= 3:
                repair_cost = "medium"

            # ── 路由决策: issues_found 优先于 has_conflict ──
            # 同时有格式+冲突 → 先 Normalization 清洗, 再 Conflict 分析
            # V3.0: 提取质量极低 → 无法评估 → HumanReview (A→E)
            extraction_q = sr.get("extraction_quality", {})
            extr_score = extraction_q.get("score", 1.0)

            if extr_score < 0.3:
                # 提取质量极差: trace_id/provenance/extraction_method 大面积缺失
                base_route = "HumanReview"
            elif issues_found:
                base_route = "Normalization"
            elif has_conflict:
                base_route = "Conflict"
            else:
                base_route = "Export"

            # Step 3: 决策矩阵调整 (Quality × Repair Cost)
            ql = sr_scoring.get("quality_level", "good")
            matrix = {
                "excellent": {"low": "Export", "medium": "Export", "high": "Normalization"},
                "good": {"low": "Export", "medium": "Normalization", "high": "Normalization"},
                "fair": {"low": "Normalization", "medium": "Normalization", "high": "Conflict"},
                "poor": {"low": "Normalization", "medium": "Conflict", "high": "HumanReview"},
            }
            matrix_route = matrix.get(ql, {}).get(repair_cost, base_route)

            # Step 4: 取两路判断中最严重的
            route_severity = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}
            if route_severity.get(matrix_route, 0) > route_severity.get(base_route, 0):
                route = matrix_route
                reason = f"Matrix escalation: {ql} quality × {repair_cost} repair cost → {route}"
            else:
                route = base_route
                if has_conflict:
                    reason = f"Conflict: {conflict_count} cross-source conflicts detected"
                elif issues_found:
                    reason = "; ".join(issues_found[:5])
                else:
                    reason = f"All checks passed (score={sr_scoring.get('overall_score',0):.2f})"

            per_source_routes[sid] = route
            per_source_reasons[sid] = reason
            sr["route_decision"] = route
            sr["decision_reason"] = reason

        # ── V2.3: 仅保留 per-source 路由, 不再聚合为全局 worst_route ──
        # 下游 dispatch 节点根据 per_source_routes 分发

        # ── 决策矩阵 (D2) ──
        matrix_routes = {}
        for sid, sr in source_reports.items():
            ql = sr.get("quality_scoring", {}).get("quality_level", "fair")
            issues = sr.get("issue_count", 0)
            conflicts = sr.get("conflict_risk", {}).get("conflict_count", 0)
            rc = "high" if conflicts >= 3 or issues >= 10 else ("medium" if conflicts >= 1 or issues >= 3 else "low")
            matrix = {"excellent": {"low": "Export", "medium": "Export", "high": "Normalization"},
                      "good": {"low": "Export", "medium": "Normalization", "high": "Normalization"},
                      "fair": {"low": "Normalization", "medium": "Normalization", "high": "Conflict"},
                      "poor": {"low": "Normalization", "medium": "Conflict", "high": "HumanReview"}}
            matrix_routes[sid] = {"quality_level": ql, "repair_cost": rc,
                                  "matrix_route": matrix.get(ql, {}).get(rc, "Normalization"),
                                  "rule_route": per_source_routes[sid]}
        quality["decision_matrix"] = matrix_routes

        # ── 条件路由 (D3) ──
        conditional_routes = []
        for sid, sr in source_reports.items():
            route = per_source_routes[sid]
            conditions = []
            if route == "Normalization":
                if sr.get("completeness", {}).get("records_missing_unit", 0) > 0:
                    conditions.append({"condition": "missing_units", "route": "Normalization", "reason": "需补全缺失单位"})
                if sr.get("completeness", {}).get("records_missing_provenance", 0) > 0:
                    conditions.append({"condition": "missing_provenance", "route": "Normalization", "reason": "需补全溯源信息"})
                unit_cons = sr.get("consistency", {}).get("unit_consistency", {})
                unit_issues = {k: v for k, v in unit_cons.items() if isinstance(v, str) and "inconsistent" in v}
                if unit_issues:
                    conditions.append({"condition": "unit_inconsistency", "route": "Normalization", "reason": f"需统一单位: {sorted(unit_issues.keys())}"})
                if sr.get("format", {}).get("total_issues", 0) > 0:
                    conditions.append({"condition": "format_issues", "route": "Normalization", "reason": "需标准化字段格式"})
                src_expected = set(sr.get("completeness", {}).get("expected_fields", []))
                src_actual = set(sr.get("completeness", {}).get("present_fields", []))
                src_aliases = src_actual - src_expected
                if src_aliases:
                    conditions.append({"condition": "alias_fields", "route": "Normalization", "reason": f"需映射别名: {sorted(src_aliases)}"})
                if not conditions:
                    conditions.append({"condition": "general", "route": "Normalization", "reason": "需字段映射和单位转换"})
            elif route == "Conflict":
                conditions.append({"condition": "has_conflict", "route": "Conflict", "reason": f"存在{sr.get('conflict_risk',{}).get('conflict_count',0)}个跨来源冲突"})
            elif route == "Export":
                conditions.append({"condition": "clean", "route": "Export", "reason": "数据可直接使用"})
            conditional_routes.append({"source_id": sid, "primary_route": route, "conditions": conditions})
        quality["conditional_routes"] = conditional_routes

        # ── V2.3: per-source 统计摘要 (无 LLM, 无全局聚合) ──
        route_counts = {}
        for r in per_source_routes.values():
            route_counts[r] = route_counts.get(r, 0) + 1

        quality["per_source_routes"] = per_source_routes
        quality["per_source_reasons"] = per_source_reasons
        quality["route_counts"] = route_counts  # 替换旧 route_decision
        quality["assessment_summary"] = (
            f"{len(source_reports)} sources. "
            + ", ".join(f"{sid[:15]}→{r}" for sid, r in per_source_routes.items())
            + f". Distribution: {route_counts}."
        )

        elapsed = round(time.time() - t0, 3)
        logger.info("[DecisionReasoningAgent] %d sources, distribution=%s, %.2fs",
                    len(source_reports), route_counts, elapsed)

        return {"report_state": {"quality": quality},
                "workflow_state": {"execution_status": "Success",
                                   "current_node": "decision", "retry_counter": 0,
                                   "workflow_history": [{"agent": "DecisionReasoningAgent", "stage": "DecisionReasoning",
                                        "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                                        "duration": elapsed,
                                        "reason": f"{len(source_reports)} sources, distribution={route_counts}"}]}}
