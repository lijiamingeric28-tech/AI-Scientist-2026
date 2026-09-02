"""
confidence_evaluation_agent.py — Node 5: ConfidenceEvaluationAgent

职责: 4 维置信度评估 + 动态阈值调整 + 判定是否满足自动处理条件。
LLM: 无 | Tools: 1 (ConfidenceEvaluator)
"""
from __future__ import annotations
import datetime, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.tools.conflict.confidence_evaluator import evaluate_confidence
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


class ConfidenceEvaluationAgent:
    """Node 5: 置信度评估 — 4 维评分 + 动态阈值"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        reasoning = conflict_state.get("reasoning", {})
        evidence = conflict_state.get("evidence", {})
        resolutions = reasoning.get("per_conflict", [])
        iteration = wf.get("iteration_counter", 0)

        results = {}
        any_below = False

        for r in resolutions:
            cid = r.get("conflict_id", "")
            ev = evidence.get(cid, {})
            conf = evaluate_confidence(r, ev, iteration)
            results[cid] = conf
            if not conf["meets_auto_threshold"]:
                any_below = True

        # 重试: 置信度不足时回退 Node 4 (最多 2 次)
        retry_count = reasoning.get("confidence_retry_count", 0)
        if any_below and retry_count < 2:
            logger.info("[ConfidenceEvaluation] %d conflicts below threshold → retry %d/2",
                        sum(1 for c in results.values() if not c["meets_auto_threshold"]), retry_count + 1)
            elapsed = round(time.time() - t0, 3)
            return {
                "report_state": {"conflict": {
                    "confidence": results,
                    "reasoning": {"confidence_retry_count": retry_count + 1,
                                 "per_conflict": resolutions, "aggregated": reasoning.get("aggregated", {})},
                }},
                "workflow_state": {
                    "current_node": "confidence_evaluation",
                    "execution_status": "Retry",
                    "workflow_history": [{
                        "agent": "ConfidenceEvaluationAgent", "stage": "Confidence",
                        "status": "Retry", "timestamp": datetime.datetime.now().isoformat(),
                        "duration": elapsed,
                        "reason": f"Confidence below threshold, retry {retry_count+1}/2",
                    }],
                },
            }

        elapsed = round(time.time() - t0, 3)
        high = sum(1 for c in results.values() if c["confidence_level"] == "high")
        med = sum(1 for c in results.values() if c["confidence_level"] == "medium")
        low = sum(1 for c in results.values() if c["confidence_level"] == "low")

        logger.info("[ConfidenceEvaluation] %d conflicts: %dH/%dM/%dL, %.2fs",
                    len(results), high, med, low, elapsed)

        return {
            "report_state": {"conflict": {
                "confidence": results,
            }},
            "workflow_state": {
                "current_node": "confidence_evaluation",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "ConfidenceEvaluationAgent", "stage": "Confidence",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Confidence: {high}H/{med}M/{low}L, retries={retry_count}",
                }],
            },
        }
