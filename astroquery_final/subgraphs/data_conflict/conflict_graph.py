"""
conflict_graph.py — Data Variance & Anomaly Detection SubGraph (V3.0)

V3.0 重构: 从 "冲突检测+裁决淘汰" 改为 "多源方差特征化+异常检测+全量保留标注"。

5 Stage 流水线:
  START → VarianceAggregation → DifferenceClassification
        → AnomalyVerification → AnnotationConfidence → AnnotationReport → END

条件边:
  - Aggregation: total_variances==0 && total_anomalies==0 → 直接 END (route=Export)
  - Confidence: 分类置信度不足 + retry<2 → 重入 Verification (内部重试)

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

# ── V3.0: 5 个 Agent ──
from subgraphs.data_conflict.agents.conflict_identification_agent import VarianceAggregationAgent
from subgraphs.data_conflict.agents.conflict_classification_agent import DifferenceClassificationAgent
from subgraphs.data_conflict.agents.evidence_collection_agent import AnomalyVerificationAgent
from subgraphs.data_conflict.agents.confidence_evaluation_agent import AnnotationConfidenceAgent
from subgraphs.data_conflict.agents.resolution_report_agent import AnnotationReportAgent
# Note: resolution_reasoning_agent 在 V3.0 中被移除

# ── 实例化 ──
_aggregation = VarianceAggregationAgent()
_classification = DifferenceClassificationAgent()
_verification = AnomalyVerificationAgent()
_confidence = AnnotationConfidenceAgent()
_report = AnnotationReportAgent()


# ==========================================================
# Stage Nodes
# ==========================================================

def _aggregation_node(state: QualityGraphState) -> dict[str, Any]:
    return _aggregation.run(state)


def _classification_node(state: QualityGraphState) -> dict[str, Any]:
    return _classification.run(state)


def _verification_node(state: QualityGraphState) -> dict[str, Any]:
    return _verification.run(state)


def _confidence_node(state: QualityGraphState) -> dict[str, Any]:
    return _confidence.run(state)


def _report_node(state: QualityGraphState) -> dict[str, Any]:
    return _report.run(state)


# ==========================================================
# 条件边函数
# ==========================================================

def _after_aggregation(state: QualityGraphState) -> str:
    """
    Aggregation → Classification 或 跳过 (无方差/无异常直接 Export)
    """
    conflict_state = state.get("report_state", {}).get("conflict", {})
    agg = conflict_state.get("aggregation", {})
    total_v = agg.get("total_variances", 0)
    total_a = agg.get("total_anomalies", 0)
    if total_v == 0 and total_a == 0:
        logger.info("[VarianceGraph] No variances or anomalies → skip Stage 2-5")
        return "finalize"  # V3.3: 统一出口
    return "difference_classification"


def _after_confidence(state: QualityGraphState) -> str:
    """
    Confidence → Report 或 重入 Verification (内部重试)
    """
    wf = state.get("workflow_state", {})
    status = wf.get("execution_status", "Success")
    if status == "Retry":
        retry_count = state.get("report_state", {}).get("conflict", {}).get(
            "annotation_confidence", {}).get("retry_count", 0)
        if retry_count < 2:
            logger.info("[VarianceGraph] Classification confidence low → retry Verification (%d/2)", retry_count + 1)
            return "anomaly_verification"
    return "annotation_report"


# ==========================================================
# 子图出口状态透传 (V3.3: 供主图 Stage Gate 消费)
# ==========================================================

def _finalize(state: QualityGraphState) -> dict[str, Any]:
    """透传子图最终 execution_status (Retry/Failed 冒泡到主图 Gate)。"""
    status = state.get("workflow_state", {}).get("execution_status", "Success")
    return {"workflow_state": {"execution_status": status}}


# ==========================================================
# 构建 SubGraph
# ==========================================================

def build_conflict_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("variance_aggregation", _aggregation_node)
    graph.add_node("difference_classification", _classification_node)
    graph.add_node("anomaly_verification", _verification_node)
    graph.add_node("annotation_confidence", _confidence_node)
    graph.add_node("annotation_report", _report_node)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("variance_aggregation")

    # Aggregation → Classification (or finalize → END, V3.3 统一出口)
    graph.add_conditional_edges(
        "variance_aggregation",
        _after_aggregation,
        {"difference_classification": "difference_classification", "finalize": "finalize"},
    )

    # 线性流水线: Classification → Verification
    graph.add_edge("difference_classification", "anomaly_verification")

    # Verification → Confidence
    graph.add_edge("anomaly_verification", "annotation_confidence")

    # Confidence → Report (or retry Verification)
    graph.add_conditional_edges(
        "annotation_confidence",
        _after_confidence,
        {"anomaly_verification": "anomaly_verification", "annotation_report": "annotation_report"},
    )

    # Report → finalize → END
    graph.add_edge("annotation_report", "finalize")
    graph.add_edge("finalize", END)

    logger.info("[Workflow] Variance SubGraph V3.0 built (5 Agents + finalize).")
    return graph
