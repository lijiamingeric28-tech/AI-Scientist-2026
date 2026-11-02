"""
confidence_evaluation_agent.py → V3.0: AnnotationConfidenceAgent (Stage 4)

职责: 评估差异原因分类的置信度和异常验证的置信度。
      低于阈值 → Retry (重新分类/验证, 最多 2 次)。
LLM: 否 | Tools: 0
"""
from __future__ import annotations
import datetime
import time
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
logger = get_logger(__name__)

# V3.0: 分类置信度阈值
_CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.55
_ANOMALY_CONFIDENCE_THRESHOLD = 0.50


class AnnotationConfidenceAgent:
    """V3.0 Stage 4: 标注置信度评估 — 判断分类/验证是否足够可靠。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})

        classification = conflict_state.get("classification", {})
        verification = conflict_state.get("verification", {})
        classified_variances = verification.get("classified_variances",
                                               classification.get("classified_variances", []))
        verified_anomalies = verification.get("verified_anomalies", [])

        # ── 评估分类置信度 ──
        low_confidence_variances = []
        avg_classification_conf = 0.0

        for v in classified_variances:
            conf = v.get("cause_confidence_final", 0)
            # H-14 fix: 非法 confidence (字符串等) 按 0 处理并记 warning, 防 TypeError 击穿节点
            if not isinstance(conf, (int, float)):
                logger.warning(
                    "[AnnotationConfidence] 非法 confidence=%r 按 0 处理 (entity=%s, field=%s)",
                    conf, v.get("entity_name", ""), v.get("field_name", ""))
                conf = 0
            avg_classification_conf += conf
            if conf < _CLASSIFICATION_CONFIDENCE_THRESHOLD:
                low_confidence_variances.append({
                    "entity_type": v.get("entity_type", ""),
                    "entity_name": v.get("entity_name", ""),
                    "field_name": v.get("field_name", ""),
                    "classified_cause": v.get("classified_cause", "unknown"),
                    "confidence": conf,
                })

        if classified_variances:
            avg_classification_conf /= len(classified_variances)

        # ── 评估异常验证置信度 ──
        unverified_anomalies = []
        avg_anomaly_conf = 0.0

        for a in verified_anomalies:
            verdict = a.get("verdict", "unverified")
            severity = a.get("severity", "medium")

            # 将 verdict 映射为置信度分数
            verdict_scores = {
                "confirmed": 0.95,
                "likely": 0.75,
                "borderline": 0.45,
                "false_positive": 0.10,
                "unverified": 0.30,
            }
            score = verdict_scores.get(verdict, 0.30)
            avg_anomaly_conf += score

            if verdict in ("borderline", "unverified"):
                unverified_anomalies.append({
                    "anomaly_type": a.get("anomaly_type", "unknown"),
                    "entity_type": a.get("entity_type", ""),
                    "entity_name": a.get("entity_name", ""),
                    "field_name": a.get("field_name", ""),
                    "verdict": verdict,
                    "score": score,
                })

        if verified_anomalies:
            avg_anomaly_conf /= len(verified_anomalies)

        # ── 决定是否需要重试 (V3.1 fix: retry_count 递增, 防止无限重入) ──
        retry_count = conflict_state.get("annotation_confidence", {}).get("retry_count", 0)
        needs_retry = (
            (len(low_confidence_variances) > 0 or len(unverified_anomalies) > 0)
            and retry_count < 2
            and (len(classified_variances) > 0 or len(verified_anomalies) > 0)
        )
        if needs_retry:
            retry_count += 1  # V3.1 fix: 递增重试计数

        elapsed = round(time.time() - t0, 3)

        confidence_results = {
            "classification_confidence": {
                "average": round(avg_classification_conf, 3),
                "low_confidence_count": len(low_confidence_variances),
                "low_confidence_items": low_confidence_variances,
            },
            "anomaly_confidence": {
                "average": round(avg_anomaly_conf, 3),
                "unverified_count": len(unverified_anomalies),
                "unverified_items": unverified_anomalies,
            },
            "needs_retry": needs_retry,
            "retry_count": retry_count,
            "auto_annotation_threshold": _CLASSIFICATION_CONFIDENCE_THRESHOLD,
        }

        logger.info("[AnnotationConfidence] cls_conf=%.3f, anom_conf=%.3f, retry=%s",
                    avg_classification_conf, avg_anomaly_conf, needs_retry)

        return {
            "report_state": {"conflict": {
                "annotation_confidence": confidence_results,
            }},
            "workflow_state": {
                "current_node": "annotation_confidence",
                "execution_status": "Retry" if needs_retry else "Success",
                "workflow_history": [{
                    "agent": "AnnotationConfidenceAgent", "stage": "Confidence",
                    "status": "Retry" if needs_retry else "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": (
                        f"cls_conf={avg_classification_conf:.3f} ({len(low_confidence_variances)} low), "
                        f"anom_conf={avg_anomaly_conf:.3f} ({len(unverified_anomalies)} unverified)"
                        + (" → Retry" if needs_retry else "")
                    ),
                }],
            },
        }
