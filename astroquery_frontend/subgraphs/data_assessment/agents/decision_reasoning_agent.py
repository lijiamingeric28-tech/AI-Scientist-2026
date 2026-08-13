"""
decision_reasoning_agent.py — Stage 4: DecisionReasoningAgent (V3.0)

天文数据路由策略 (V3.0):
  正常多源差异 (method/instrument/temporal variance) → Export (全量保留)
  真正异常 (extraction_error/unit_error/cross_id_error) → Conflict
  可修复问题 (别名/格式/单位) → Normalization
  提取质量极差 → HumanReview
"""
from __future__ import annotations
import datetime
import time
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
logger = get_logger(__name__)
# A13 fix: 单份模块级严重度表 (原在循环内重复定义一份局部 dict)
_ROUTE_SEVERITY = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}
# A13 fix: 删除 _DECISION_SYSTEM (LLM 决策 prompt 定义但从不调用 —
# V3.x 为纯规则决策, LLM 增强已移除, 保留会造成文档-实现漂移)


class DecisionReasoningAgent:
    """Stage 4: V2.1 严格路由 — 不完美即 Normalization (纯规则决策, 0 LLM)。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})
        quality = dict(rs.get("quality", {}) or {})
        source_reports = quality.get("sources", {})
        profile = quality.get("profile", {})

        per_source_routes: dict[str, str] = {}
        per_source_reasons: dict[str, str] = {}

        # A11 fix: repair_cost/extraction 阈值从 quality_scoring_runtime 读 (fallback 旧值)
        from quality_pipeline.configs import load_quality_scoring_runtime
        _runtime_cfg = load_quality_scoring_runtime()
        _repair_cost_cfg = _runtime_cfg.get("repair_cost", {"anomaly": [1, 3], "issues": [3, 10]})
        _anom_med, _anom_high = _repair_cost_cfg.get("anomaly", [1, 3])
        _iss_med, _iss_high = _repair_cost_cfg.get("issues", [3, 10])
        _extr_threshold = float(_runtime_cfg.get("extraction_human_threshold", 0.3))

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
            # V2: 使用 per-entity 数据, 避免 Entity-A 掩盖 Entity-B 的别名
            expected = set(sr_completeness.get("expected_fields", []))
            actual = set(sr_completeness.get("present_fields", []))
            aliases = actual - expected  # fields present but not in target schema
            # A5 fix-③: expected 为空 (target_schema 缺失) 时不算 alias —
            # 否则全部字段被误判 → 全量误路由 Normalization
            if aliases and expected:
                issues_found.append(f"alias_fields: {sorted(aliases)}")
            # V2: per-entity 别名检测
            per_entity_missing = sr_completeness.get("per_entity_missing", {})
            for elabel, missing_fields in per_entity_missing.items():
                if missing_fields:
                    issues_found.append(f"[{elabel}] missing_expected_fields: {sorted(missing_fields)}")

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

            # A5 fix-①: 外键断裂 (records 引用了不存在的 source) → Normalization
            # (此前只记入 completeness issues, Decision 无对应检查 → 可直达 Export)
            missing_source = sr_completeness.get("records_missing_source", 0)
            if missing_source > 0:
                issues_found.append(f"missing_source: {missing_source} records")

            # A4 fix: 自适应阈值第 9 项检查 — 低完整度无其他问题时不直达 Export
            if sr.get("below_adaptive_threshold"):
                adaptive_issues = sr.get("adaptive_issues") or []
                issues_found.append(
                    "below_adaptive_threshold: "
                    + ("; ".join(adaptive_issues) if adaptive_issues
                       else "coverage below dynamic threshold")
                )

            # 5a. 单位不一致 (同一字段多单位)
            unit_cons = sr_consistency.get("unit_consistency", {})
            unit_issues = {k: v for k, v in unit_cons.items()
                           if isinstance(v, str) and "inconsistent" in v}
            if unit_issues:
                issues_found.append(f"unit_inconsistency: {sorted(unit_issues.keys())}")

            # 5b. 单位与标准不符 (V1.1: entity 感知)
            target_schema = state.get("context_state", {}).get("target_schema", {})
            schema_fields = {f.get("name"): f.get("standard_unit") for f in target_schema.get("fields", [])
                             if f.get("standard_unit")}
            ds = state.get("data_state", {}).get("current_data", {})
            src_records = [r for r in ds.get("records", []) if r.get("source_id") == sid]

            # A10 fix: 统一单位归一化 (K≡Kelvin, yr≡year ...) — 原局部替换只做
            # °/℃→C, 'K' vs 'Kelvin' 会误报 unit_mismatch → 误路由 Normalization
            from quality_pipeline.tools.assessment.source_utils import canonical_unit
            _norm_unit = canonical_unit

            # 按 (entity, field_name) 分组检查单位
            entity_unit_groups: dict[tuple, set] = {}
            for r in src_records:
                fn = r.get("field_name", "")
                std_unit = schema_fields.get(fn)
                if not std_unit or not r.get("field_unit"):
                    continue
                key = (r.get("entity_type", ""), r.get("entity_name", ""), fn)
                entity_unit_groups.setdefault(key, set()).add(r["field_unit"])

            for (et, en, fn), units in entity_unit_groups.items():
                std_unit = schema_fields.get(fn)
                norm_current = {_norm_unit(u) for u in units}
                norm_std = _norm_unit(std_unit)
                if norm_current != {norm_std}:
                    entity_label = f" ({et}:{en})" if en else ""
                    issues_found.append(f"unit_mismatch: {fn}{entity_label} has {sorted(units)} (expected {std_unit})")

            # ── V3.0: 异常检测 (替代旧冲突检测) ──
            # has_conflicts 现在等于 has_anomalies (只有真正异常才标记)
            has_anomaly = sr_conflict.get("has_conflicts", False)
            anomaly_count = sr_conflict.get("conflict_count", 0)
            # has_variance: 正常多源差异 (不阻塞 Export)
            has_variance = sr_conflict.get("has_variance", False)
            variance_count = sr_conflict.get("variance_count", 0)

            # ── V3.1 fix: 全局 cross_id_error 检查 ──
            # cross_id_error 不属于任何特定 source (quality_assessment 不广播),
            # 但需要全局判定 → 该实体相关 source 路由 HumanReview
            global_anomalies = quality.get("multi_source_variance", {}).get("anomalies", [])
            entity_cross_id = [
                a for a in global_anomalies
                if a.get("anomaly_type") == "cross_id_error"
                and a.get("entity_name")
            ]
            # A5 fix-④: cross_id 无辜 source 过滤 — 仅当本 source 记录包含
            # 该实体的 entity_name 才判 HumanReview (否则同实体全部 source 被
            # 一并送审, 包括无辜者)
            sid_cross_id = any(
                (sid in a.get("source_ids", []) or
                 sid == a.get("source_a", "") or sid == a.get("source_b", "") or
                 sid == a.get("source_id", "")) and
                (not a.get("entity_name") or
                 any(r.get("entity_name") == a.get("entity_name") for r in src_records))
                for a in entity_cross_id
            )

            # ═══ V3.0: 决策逻辑 — 只对可操作问题路由 ═══
            # Step 1: 计算 Repair Cost (anomaly_count 替代旧 conflict_count)
            # A11 fix: 阈值从 quality_scoring_runtime.repair_cost 读
            issue_count = len(issues_found)
            # L-09 fix: 存 sr 供 D2 决策矩阵复用 (与主路径同源, 不再读 sr.issue_count)
            sr["issues_found"] = list(issues_found)
            repair_cost = "low"
            if anomaly_count >= _anom_high or issue_count >= _iss_high:
                repair_cost = "high"
            elif anomaly_count >= _anom_med or issue_count >= _iss_med:
                repair_cost = "medium"

            # ── V3.0 路由决策: issues_found 优先于 has_anomaly ──
            # 同时有格式+异常 → 先 Normalization 清洗, 再 Conflict 分析
            # V3.0: 正常多源差异 (has_variance) 不阻塞 Export
            extraction_q = sr.get("extraction_quality", {})
            extr_score = extraction_q.get("score", 1.0)

            # A5 fix-②: 物理不可行值 (out_of_range) — Assessment 阶段拦截
            # (此前只有 Normalization validation 事后消费, Assessment 不路由)
            # L-21 fix: profile.out_of_range_count 已是记录级计数 (覆盖越界字段的
            # 记录数), 分子分母同为记录数, 比率口径一致
            oor_count = (quality.get("profile", {}) or {}).get("out_of_range_count", 0)
            n_all_recs = max(len(ds.get("records", [])), 1)
            oor_ratio = oor_count / n_all_recs
            oor_route_override = None
            if oor_ratio > 0.5:
                oor_route_override = "HumanReview"  # 越界记录过半 — 数据本身不可信
            elif oor_count > 0:
                oor_route_override = "Normalization"

            if extr_score < _extr_threshold:
                # 提取质量极差: trace_id/provenance/extraction_method 大面积缺失
                base_route = "HumanReview"
            elif oor_route_override == "HumanReview":
                base_route = "HumanReview"
            elif sid_cross_id:
                # V3.1 fix: 全局 cross_id_error → HumanReview (跨源异常无法自动裁决)
                base_route = "HumanReview"
            elif oor_route_override == "Normalization":
                base_route = "Normalization"  # A5 fix-②: 存在物理不可行值 → 清洗
            elif issues_found:
                base_route = "Normalization"
            elif has_anomaly:
                base_route = "Conflict"
            elif has_variance:
                base_route = "Export"
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

            # Step 4: 取两路判断中最严重的 (escalate_only: 矩阵只单向升级)
            if _ROUTE_SEVERITY.get(matrix_route, 0) > _ROUTE_SEVERITY.get(base_route, 0):
                route = matrix_route
                reason = f"Matrix escalation: {ql} quality × {repair_cost} repair cost → {route}"
            else:
                route = base_route
                if oor_route_override:
                    reason = (f"out_of_range: {oor_count} records beyond feasible ranges "
                              f"({oor_ratio:.0%} of data)")
                elif sid_cross_id:
                    reason = "Global cross_id_error detected for entity (needs human review)"
                elif has_anomaly:
                    reason = f"Anomalies: {anomaly_count} record-level anomalies detected"
                elif issues_found:
                    reason = "; ".join(issues_found[:5])
                elif has_variance:
                    reason = f"Multi-source variance: {variance_count} groups (normal, all preserved)"
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
            issues = len(sr.get("issues_found", []))  # L-09 fix: 与主路由同源 (原 sr.issue_count 含 info 级条目)
            anomalies = sr.get("conflict_risk", {}).get("conflict_count", 0)
            rc = "high" if anomalies >= _anom_high or issues >= _iss_high else (
                "medium" if anomalies >= _anom_med or issues >= _iss_med else "low")
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
                # M-05 fix: expected 为空 (target_schema 缺失) 时不算 alias —
                # 与主路由 :64 同款 A5 fix-③ 守卫, 否则全字段误附 alias_fields 条件
                if src_aliases and src_expected:
                    conditions.append({"condition": "alias_fields", "route": "Normalization", "reason": f"需映射别名: {sorted(src_aliases)}"})
                if not conditions:
                    conditions.append({"condition": "general", "route": "Normalization", "reason": "需字段映射和单位转换"})
            elif route == "Conflict":
                conditions.append({"condition": "has_anomaly", "route": "Conflict", "reason": f"存在{sr.get('conflict_risk',{}).get('conflict_count',0)}个数据异常需要分析"})
            elif route == "Export":
                has_var = sr.get("conflict_risk", {}).get("has_variance", False)
                if has_var:
                    conditions.append({"condition": "multi_source_variance_annotated", "route": "Export", "reason": "存在多源差异(已标注),数据可直接使用"})
                else:
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

        # A7 fix: 透传上游 execution_status (与 quality_assessment 一致) —
        # 硬编码 Success 会抹掉 profiling 的 Failed/Retry
        prev_status = wf.get("execution_status", "Success")
        exec_status = prev_status if prev_status in ("Failed", "Retry") else "Success"

        return {"report_state": {"quality": quality},
                "workflow_state": {"execution_status": exec_status,
                                   "current_node": "decision", "retry_counter": 0,
                                   "workflow_history": [{"agent": "DecisionReasoningAgent", "stage": "DecisionReasoning",
                                        "status": exec_status, "timestamp": datetime.datetime.now().isoformat(),
                                        "duration": elapsed,
                                        "reason": f"{len(source_reports)} sources, distribution={route_counts}"}]}}
