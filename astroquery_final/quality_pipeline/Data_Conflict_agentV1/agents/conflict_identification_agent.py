"""
conflict_identification_agent.py → V3.0: VarianceAggregationAgent (Stage 1)

职责: 接收 Assessment 的多源方差分析结果, 按 entity+field 聚合,
     构建差异摘要卡片, 确定触发路径。
LLM: 否 | Tools: 0 (直接读取 quality report 中的 multi_source_variance)
"""
from __future__ import annotations
import datetime, time
from typing import Any
from ...quality_state import QualityGraphState
from ...utils.logger import get_logger
logger = get_logger(__name__)


class VarianceAggregationAgent:
    """V3.0 Stage 1: 多源方差聚合 — 接收 Assessment 结果, 构建摘要。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        wf = state.get("workflow_state", {})

        quality = state.get("report_state", {}).get("quality", {}) or {}

        # ── V4 fix: B→C 数据断链桥接 ──
        # Normalization 复检 (detect_conflicts_statistical) 的冲突存在
        # validation.conflict_check, 与 Assessment 的 multi_source_variance 是
        # 两套检测; 此前 Conflict 子图只读后者, B→C 派发后也读不到冲突。
        # needs_variance_analysis 为历史字段, 保留兼容。
        norm_report = state.get("report_state", {}).get("normalization", {}) or {}
        norm_validation = norm_report.get("validation", {}) or {}
        is_b_to_c = bool(norm_validation.get("needs_conflict_analysis")
                         or norm_validation.get("needs_variance_analysis"))

        # ── V3.0: 读取多源方差分析结果 (B→C 时优先 Normalization 复检结果) ──
        msv = quality.get("multi_source_variance", {})
        conflict_check = norm_validation.get("conflict_check") or {}
        if is_b_to_c and (conflict_check.get("variance_count", 0) > 0
                          or conflict_check.get("anomaly_count", 0) > 0):
            # 字段结构兼容: variances/anomalies/variance_count/anomaly_count
            msv = conflict_check
        variances = msv.get("variances", [])
        anomalies = msv.get("anomalies", [])
        total_variances = msv.get("variance_count", len(variances))
        total_anomalies = msv.get("anomaly_count", len(anomalies))

        # ── 确定触发路径 ──
        trigger_path = "B→C" if is_b_to_c else "A→C"

        # ── 无方差/异常 → 快速出口 ──
        if total_variances == 0 and total_anomalies == 0:
            return self._no_variance_result(t0)

        # ── 聚合: 收集涉及的 sources/fields/entities ──
        involved_sources: set[str] = set()
        involved_fields: set[str] = set()
        involved_entities: set[str] = set()

        for v in variances:
            involved_sources.update(v.get("source_ids", []))
            involved_fields.add(v.get("field_name", ""))
            et = v.get("entity_type", "") or ""
            en = v.get("entity_name", "") or ""
            if et or en:
                involved_entities.add(f"{et}:{en}" if et else en)

        for a in anomalies:
            sid = a.get("source_id", "")
            if sid:
                involved_sources.add(sid)
            sa = a.get("source_a", "")
            sb = a.get("source_b", "")
            if sa:
                involved_sources.add(sa)
            if sb:
                involved_sources.add(sb)
            involved_fields.add(a.get("field_name", ""))
            et = a.get("entity_type", "") or ""
            en = a.get("entity_name", "") or ""
            if et or en:
                involved_entities.add(f"{et}:{en}" if et else en)

        # ── 构建每组的差异摘要卡片 ──
        variance_cards = []
        for v in variances:
            sources_detail = {}
            for sid, ss in v.get("source_stats", {}).items():
                sources_detail[sid] = {
                    "mean": ss.get("mean"),
                    "std": ss.get("std"),
                    "n": ss.get("n"),
                    "measurement_methods": ss.get("measurement_methods", []),
                    "condition_tags": ss.get("condition_tags", []),
                    "year": ss.get("year"),
                    "unit": ss.get("unit"),
                }
            variance_cards.append({
                "entity_type": v.get("entity_type", ""),
                "entity_name": v.get("entity_name", ""),
                "field_name": v.get("field_name", ""),
                "source_count": v.get("source_count", 0),
                "source_ids": v.get("source_ids", []),
                "value_range": v.get("value_range", []),
                "max_cohens_d": v.get("max_cohens_d", 0),
                "inferred_cause": v.get("inferred_cause", "unknown"),
                "cause_confidence": v.get("cause_confidence", 0),
                "source_details": sources_detail,
                "unit_mismatch": v.get("unit_mismatch_detected", False),
                "cross_id_risk": v.get("cross_id_risk", False),
            })

        elapsed = round(time.time() - t0, 3)
        logger.info("[VarianceAggregation] %d variances, %d anomalies, %d sources, trigger=%s",
                    total_variances, total_anomalies, len(involved_sources), trigger_path)

        return {
            "report_state": {"conflict": {
                "aggregation": {
                    "trigger_path": trigger_path,
                    "total_variances": total_variances,
                    "total_anomalies": total_anomalies,
                    "variances": variance_cards,
                    "anomalies": anomalies,
                    "involved_sources": sorted(involved_sources),
                    "involved_fields": sorted(involved_fields),
                    "involved_entities": sorted(involved_entities),
                    "summary": (
                        f"{total_variances} multi-source variance group(s), "
                        f"{total_anomalies} potential anomal(ies) across "
                        f"{len(involved_sources)} source(s)"
                    ),
                },
            }},
            "workflow_state": {
                "current_node": "variance_aggregation",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "VarianceAggregationAgent", "stage": "Aggregation",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": (
                        f"{total_variances} variance groups, "
                        f"{total_anomalies} anomalies, "
                        f"trigger={trigger_path}"
                    ),
                }],
            },
        }

    def _no_variance_result(self, t0: float) -> dict[str, Any]:
        """无方差/异常时的快速出口"""
        elapsed = round(time.time() - t0, 3)
        return {
            "report_state": {"conflict": {
                "aggregation": {
                    "trigger_path": "none",
                    "total_variances": 0,
                    "total_anomalies": 0,
                    "variances": [],
                    "anomalies": [],
                    "involved_sources": [],
                    "involved_fields": [],
                    "involved_entities": [],
                    "summary": "No multi-source variance or anomalies detected.",
                },
                "resolution_report": {
                    "route_decision": "Export",
                    "status": "No_Variance",
                    "summary": "No multi-source variance detected.",
                },
            }},
            "workflow_state": {
                "route_decision": "Export",
                "execution_status": "Success",
                "current_node": "variance_aggregation",
                "workflow_history": [{
                    "agent": "VarianceAggregationAgent", "stage": "Aggregation",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": "No variances or anomalies → Export",
                }],
            },
        }
