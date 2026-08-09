"""
resolution_report_agent.py → V3.0: AnnotationReportAgent (Stage 5)

职责: 汇总标注结果, 生成 Variance Annotation Report,
     设置 route_decision (Export/Normalization/HumanReview)。
核心原则: 所有多源测量值全量保留, 只标注差异原因。
LLM: 是 (摘要生成) | Tools: 0
"""
from __future__ import annotations
import datetime
import time
from typing import Any
from ...quality_state import QualityGraphState
from ...utils.llm import get_llm, set_agent_context, track_raw_llm_call
from ...utils.logger import get_logger
logger = get_logger(__name__)


class AnnotationReportAgent:
    """V3.0 Stage 5: 标注报告 — 汇总 + 路由 + 摘要。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        domain = state.get("context_state", {}).get("research_domain", "astrophysics")

        aggregation = conflict_state.get("aggregation", {})
        classification = conflict_state.get("classification", {})
        verification = conflict_state.get("verification", {})
        confidence = conflict_state.get("annotation_confidence", {})

        total_variances = aggregation.get("total_variances", 0)
        total_anomalies = aggregation.get("total_anomalies", 0)

        classified_variances = verification.get("classified_variances",
                                               classification.get("classified_variances", []))
        verified_anomalies = verification.get("verified_anomalies", [])
        duplicate_groups = verification.get("duplicate_groups", [])

        # ── 构建 per-record 标注 ──
        annotations = []
        for v in classified_variances:
            cause = v.get("classified_cause", "unknown")
            annotations.append({
                "entity_type": v.get("entity_type", ""),
                "entity_name": v.get("entity_name", ""),
                "field_name": v.get("field_name", ""),
                "annotation_type": "multi_source_variance",
                "cause": cause,
                "cause_label": _get_cause_label(cause),
                "value_range": v.get("value_range", []),
                "source_count": v.get("source_count", 0),
                "source_ids": v.get("source_ids", []),
                "confidence": v.get("cause_confidence_final", 0),
                "action": "preserve_all",  # V3.0 核心: 全量保留
            })

        # ── 异常处理 ──
        confirmed_anomalies = [a for a in verified_anomalies
                              if a.get("verdict") in ("confirmed", "likely")]
        borderline_anomalies = [a for a in verified_anomalies
                               if a.get("verdict") == "borderline"]
        false_positives = [a for a in verified_anomalies
                          if a.get("verdict") == "false_positive"]

        anomaly_flags = []
        # V3.1 fix: Conflict→Normalization 数据契约 — unit_error 生成可执行的规范化动作
        normalization_ctions = []
        for a in confirmed_anomalies:
            atype = a.get("anomaly_type", "")
            if atype == "unit_error":
                anomaly_flags.append({
                    "anomaly_type": atype,
                    "field_name": a.get("field_name", ""),
                    "entity_name": a.get("entity_name", ""),
                    "action": "normalize_unit",  # → Normalization
                    "detail": a.get("units_found", {}),
                })
                # V3.2 fix: 生成精确的 resolution_plan.actions_to_normalize 供 SourceRouterAgent 消费
                units_found = a.get("units_found", {}) or {}
                src_ids = list(units_found.keys()) if isinstance(units_found, dict) else []
                # 目标单位: 优先 target_schema 标准单位, 否则取第一个来源单位
                target_schema = state.get("context_state", {}).get("target_schema") or {}
                std_unit = None
                for f_def in target_schema.get("fields", []):
                    if f_def.get("name") == a.get("field_name", ""):
                        std_unit = f_def.get("standard_unit")
                        break
                to_unit = std_unit
                # 每个来源生成一个 action (V3.2: 不再只处理 src_ids[0])
                for sid_tmp in src_ids:
                    u = units_found.get(sid_tmp)
                    if not u or not isinstance(u, str):
                        continue
                    if to_unit is None:
                        to_unit = u
                    normalization_ctions.append({
                        "source_id": sid_tmp,
                        "target_source": sid_tmp,
                        "record_ids": a.get("record_ids", []),
                        "field": a.get("field_name", ""),
                        "field_name": a.get("field_name", ""),
                        "entity_type": a.get("entity_type", ""),
                        "entity_name": a.get("entity_name", ""),
                        "from_unit": u,  # V3.2: 字符串而非列表
                        "to_unit": to_unit,
                        "action": "normalize_unit",
                        "reason": f"Unit dimension mismatch across sources: {units_found}",
                    })
            elif atype == "cross_id_error":
                anomaly_flags.append({
                    "anomaly_type": atype,
                    "entity_name": a.get("entity_name", ""),
                    "action": "human_review",  # → HumanReview
                    "detail": a.get("entity_types_found", []),
                })
            elif atype in ("extraction_error", "statistical_outlier"):
                anomaly_flags.append({
                    "anomaly_type": atype,
                    "field_name": a.get("field_name", ""),
                    "entity_name": a.get("entity_name", ""),
                    "action": "flag_for_review",  # 标记但不删除
                    "severity": a.get("severity", "high"),
                    "detail": a.get("evidence", {}),
                })

        # ── 路由决策 (与 graph.py CONFLICT_ROUTE_MAP 兼容) ──
        # Export / Normalization / HumanReview
        if total_variances == 0 and total_anomalies == 0:
            route = "Export"
            status = "No_Variance"
        else:
            has_unit_issues = any(f.get("action") == "normalize_unit" for f in anomaly_flags)
            has_cross_id = any(f.get("action") == "human_review" for f in anomaly_flags)
            has_critical = any(
                f.get("severity") == "critical" and f.get("action") == "flag_for_review"
                for f in anomaly_flags
            )

            if has_cross_id or has_critical:
                route = "HumanReview"
                status = "Unresolved_Anomalies"
            elif has_unit_issues:
                route = "Normalization"
                status = "Needs_Unit_Fix"
            else:
                route = "Export"
                status = "Annotated"

        # ── LLM 摘要 ──
        llm_count = wf.get("llm_call_count", 0)
        summary = ""
        try:
            set_agent_context("annotation_report")
            llm = get_llm(temperature=0.0)
            causes_used = list(set(a.get("cause", "?") for a in annotations))
            resp = llm.invoke([
                {"role": "system", "content": (
                    "You are an astronomical data analysis reporter. "
                    "Generate a concise 2-3 sentence summary of multi-source data variance analysis results. "
                    "Emphasize that all measurements are preserved, with differences attributed to "
                    "observational causes (not errors)."
                )},
                {"role": "user", "content": (
                    f"{total_variances} multi-source variance groups and {total_anomalies} anomalies "
                    f"analyzed in {domain}. "
                    f"Variance causes: {causes_used}. "
                    f"Route: {route}. "
                    f"Confirmed anomalies: {len(confirmed_anomalies)}. "
                    f"Duplicate groups: {len(duplicate_groups)}. "
                    f"All measurements preserved. Summary:"
                )},
            ])
            summary = (resp.content if hasattr(resp, "content") else str(resp))[:400]
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="annotation_report")
        except Exception as e:
            logger.warning("[AnnotationReport] LLM summary failed: %s", e)
            summary = (
                f"{total_variances} multi-source variance groups analyzed in {domain}. "
                f"All measurements preserved with difference annotations. "
                f"{len(confirmed_anomalies)} anomalies flagged, {len(duplicate_groups)} duplicates found. "
                f"Route: {route}."
            )

        # ── 构建完整 Annotation Report ──
        report = {
            "metadata": {
                "generated_at": datetime.datetime.now().isoformat(),
                "trigger_path": aggregation.get("trigger_path", "unknown"),
                "iteration": wf.get("iteration_counter", 0),
                "total_variances": total_variances,
                "total_anomalies": total_anomalies,
                "confirmed_anomalies": len(confirmed_anomalies),
                "borderline_anomalies": len(borderline_anomalies),
                "false_positives": len(false_positives),
                "duplicate_groups": len(duplicate_groups),
            },
            "annotations": annotations,
            "anomaly_flags": anomaly_flags,
            "duplicate_groups": duplicate_groups,
            "per_entity_routes": self._build_per_entity_routes(
                classified_variances, verified_anomalies
            ),
            # V3.1 fix: Conflict→Normalization 数据契约闭合 (SourceRouterAgent 消费)
            "resolution_plan": {
                "actions_to_normalize": normalization_ctions,
                "annotations_to_add": [],
                "human_review_tems": [
                    {
                        "conflict_d": f.get("anomaly_type", "?"),
                        "field_name": f.get("field_name", ""),
                        "entity_name": f.get("entity_name", ""),
                        "reason": f.get("action", ""),
                        "evidence_summary": f.get("detail", {}),
                    }
                    for f in anomaly_flags if f.get("action") == "human_review"
                ],
            },
            "confidence": {
                "classification": confidence.get("classification_confidence", {}),
                "anomaly": confidence.get("anomaly_confidence", {}),
            },
            "route_decision": route,
            "status": status,
            "summary": summary,
        }

        elapsed = round(time.time() - t0, 3)
        logger.info("[AnnotationReport] %s, route=%s, annotations=%d, %.2fs",
                    status, route, len(annotations), elapsed)

        return {
            "report_state": {"conflict": {
                "resolution_report": report,
            }},
            "workflow_state": {
                "route_decision": route,
                "execution_status": "Success",
                "current_node": "annotation_report",
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "AnnotationReportAgent", "stage": "Report",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": (
                        f"{status}: {len(annotations)} variance annotations, "
                        f"{len(anomaly_flags)} anomaly flags, route={route}"
                    ),
                }],
            },
        }

    def _build_per_entity_routes(
        self,
        classified_variances: list[dict],
        verified_anomalies: list[dict],
    ) -> dict[str, str]:
        """构建 per-entity 路由映射。"""
        routes: dict[str, str] = {}

        for v in classified_variances:
            et = v.get("entity_type", "") or ""
            en = v.get("entity_name", "") or "unknown"
            elabel = f"{et}:{en}" if et else en
            if elabel not in routes:
                routes[elabel] = "Export"  # 方差 → Export

        for a in verified_anomalies:
            et = a.get("entity_type", "") or ""
            en = a.get("entity_name", "") or "unknown"
            elabel = f"{et}:{en}" if et else en
            verdict = a.get("verdict", "")
            if verdict in ("confirmed", "likely"):
                atype = a.get("anomaly_type", "")
                if atype == "cross_id_error":
                    routes[elabel] = "HumanReview"
                elif atype == "unit_error":
                    routes[elabel] = "Normalization"
                elif routes.get(elabel, "Export") != "HumanReview":
                    routes[elabel] = "Export"  # 标记但不阻塞

        return routes


def _get_cause_label(cause: str) -> str:
    """差异原因的中文标签。"""
    labels = {
        "methodological_variance": "观测方法/仪器差异",
        "condition_variance": "观测条件/波段差异",
        "temporal_variation": "时间演化",
        "measurement_uncertainty": "测量误差范围",
        "duplicate_observation": "重复收录",
        "unknown": "未知原因",
    }
    return labels.get(cause, cause)
