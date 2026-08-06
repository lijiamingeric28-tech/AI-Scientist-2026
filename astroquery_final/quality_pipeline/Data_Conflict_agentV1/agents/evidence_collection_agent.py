"""
evidence_collection_agent.py → V3.0: AnomalyVerificationAgent (Stage 3)

职责: 对标记为异常的记录做 3 维验证:
  1. 提取质量检查 (extraction_confidence + context_snippet)
  2. 单位一致性检查 (跨源单位维度匹配)
  3. 重复记录检测 (相同值+相同entity+不同source)
LLM: 否 | Tools: 0 (确定性验证)
"""
from __future__ import annotations
import datetime, time
from typing import Any
from ...quality_state import QualityGraphState
from ...utils.logger import get_logger
logger = get_logger(__name__)


# ── V3.0: 异常验证阈值 ──
_EXTRACTION_CONFIDENCE_CRITICAL = 0.3    # 提取置信度低于此值 → confirmed anomaly
_EXTRACTION_CONFIDENCE_LIKELY = 0.5      # 提取置信度低于此值 → likely anomaly
_COHENS_D_CONFIRMED = 2.0               # Cohen's d 高于此值(同方法/条件/单位) → confirmed
_COHENS_D_LIKELY = 3.0                  # Cohen's d 高于此值 → likely
_DUPLICATE_MAX_GROUPS = 10              # 最多记录重复组数


class AnomalyVerificationAgent:
    """V3.0 Stage 3: 异常验证 — 3 维确定性检查。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        classification = conflict_state.get("classification", {})
        anomalies = classification.get("anomalies", [])
        classified_variances = classification.get("classified_variances", [])

        data = state.get("data_state", {}).get("current_data", {})
        all_records = data.get("records", [])
        sources = {s.get("source_id", ""): s for s in data.get("sources", [])}

        verified_anomalies = []
        duplicate_groups = []

        for a in anomalies:
            atype = a.get("anomaly_type", "unknown")
            verified = dict(a)
            verified["verification"] = {}
            verified["verdict"] = "unverified"  # default

            # ── 验证 1: 提取质量 ──
            if atype == "extraction_error":
                record_ids = a.get("record_ids", [])
                confidence_ok = a.get("extraction_confidence", 1.0)
                # 查找相关 records 的 context_snippet
                related_records = [r for r in all_records if r.get("record_id") in record_ids]
                snippets = [r.get("context_snippet", "") for r in related_records if r.get("context_snippet")]

                verified["verification"]["extraction_quality"] = {
                    "extraction_confidence": confidence_ok,
                    "has_context_snippet": len(snippets) > 0,
                    "sample_snippets": snippets[:2],  # 最多2条
                }

                if confidence_ok < 0.3:
                    verified["verdict"] = "confirmed"
                    verified["severity"] = "critical"
                elif confidence_ok < 0.5:
                    verified["verdict"] = "likely"
                    verified["severity"] = "high"
                else:
                    verified["verdict"] = "borderline"
                    verified["severity"] = "medium"

            # ── 验证 2: 单位一致性 ──
            elif atype == "unit_error":
                units_found = a.get("units_found", {})
                dimensions_found = a.get("dimensions_found", {})
                unique_dims = set(dimensions_found.values())
                # 排除 dimensionless 和 unknown
                meaningful_dims = {d for d in unique_dims if d not in ("dimensionless", "") and not d.startswith("unknown:")}

                verified["verification"]["unit_consistency"] = {
                    "units_found": units_found,
                    "dimensions_found": dimensions_found,
                    "unique_dimensions": list(unique_dims),
                    "dimension_mismatch": len(meaningful_dims) > 1,
                }

                if len(meaningful_dims) > 1:
                    verified["verdict"] = "confirmed"
                    verified["severity"] = "critical"
                else:
                    verified["verdict"] = "false_positive"
                    verified["severity"] = "low"

            # ── 验证 3: 统计异常 ──
            elif atype == "statistical_outlier":
                evidence = a.get("evidence", {})
                same_method = evidence.get("same_method", False)
                same_conditions = evidence.get("same_conditions", False)
                same_unit = evidence.get("same_unit", False)
                cohens_d = a.get("cohens_d", 0)

                verified["verification"]["statistical"] = {
                    "same_method": same_method,
                    "same_conditions": same_conditions,
                    "same_unit": same_unit,
                    "cohens_d": cohens_d,
                }

                if same_method and same_conditions and same_unit and cohens_d > 2.0:
                    verified["verdict"] = "confirmed"
                    verified["severity"] = "high"
                elif cohens_d > 3.0:
                    verified["verdict"] = "likely"
                    verified["severity"] = "high"
                else:
                    verified["verdict"] = "borderline"
                    verified["severity"] = "medium"

            # ── 验证 4: 交叉ID错误 ──
            elif atype == "cross_id_error":
                entity_types = a.get("entity_types_found", [])
                entity_name = a.get("entity_name", "")

                verified["verification"]["cross_id"] = {
                    "entity_name": entity_name,
                    "entity_types_found": entity_types,
                    "type_count": len(entity_types),
                }

                if len(entity_types) > 1:
                    verified["verdict"] = "confirmed"
                    verified["severity"] = "critical"
                else:
                    verified["verdict"] = "false_positive"
                    verified["severity"] = "low"

            verified_anomalies.append(verified)

        # ── 重复检测: 相同值+相同entity+不同source ──
        from collections import defaultdict
        value_groups: dict[tuple, list[dict]] = defaultdict(list)
        for rec in all_records:
            et = rec.get("entity_type", "") or ""
            en = rec.get("entity_name", "") or ""
            fn = rec.get("field_name", "")
            fv = rec.get("field_value", "")
            sid = rec.get("source_id", "")
            key = (et, en, fn, str(fv).strip())
            value_groups[key].append({"record_id": rec.get("record_id", ""), "source_id": sid})

        for key, recs in value_groups.items():
            unique_sources = set(r["source_id"] for r in recs)
            if len(unique_sources) > 1:
                duplicate_groups.append({
                    "entity_type": key[0],
                    "entity_name": key[1],
                    "field_name": key[2],
                    "field_value": key[3],
                    "source_count": len(unique_sources),
                    "source_ids": sorted(unique_sources),
                    "record_ids": [r["record_id"] for r in recs],
                })

        # 将重复组也加入 classified_variances
        for dg in duplicate_groups[:10]:  # 最多10组
            classified_variances.append({
                "entity_type": dg["entity_type"],
                "entity_name": dg["entity_name"],
                "field_name": dg["field_name"],
                "source_count": dg["source_count"],
                "source_ids": dg["source_ids"],
                "classified_cause": "duplicate_observation",
                "cause_confidence_final": 0.95,
                "classification_method": "rule",
                "classification_reason": "Same value found in multiple sources",
                "value_range": [dg["field_value"], dg["field_value"]],
            })

        # ── 汇总 ──
        confirmed_count = sum(1 for a in verified_anomalies if a["verdict"] in ("confirmed", "likely"))
        false_positive_count = sum(1 for a in verified_anomalies if a["verdict"] == "false_positive")
        borderline_count = sum(1 for a in verified_anomalies if a["verdict"] == "borderline")

        elapsed = round(time.time() - t0, 3)
        logger.info("[AnomalyVerification] %d anomalies: %d confirmed, %d borderline, %d false_positive, %d duplicates",
                    len(verified_anomalies), confirmed_count, borderline_count,
                    false_positive_count, len(duplicate_groups))

        return {
            "report_state": {"conflict": {
                "verification": {
                    "verified_anomalies": verified_anomalies,
                    "duplicate_groups": duplicate_groups,
                    "confirmed_count": confirmed_count,
                    "false_positive_count": false_positive_count,
                    "borderline_count": borderline_count,
                    "classified_variances": classified_variances,
                }
            }},
            "workflow_state": {
                "current_node": "anomaly_verification",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "AnomalyVerificationAgent", "stage": "Verification",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": (
                        f"{confirmed_count} anomalies confirmed, "
                        f"{false_positive_count} false positives, "
                        f"{len(duplicate_groups)} duplicate groups"
                    ),
                }],
            },
        }
