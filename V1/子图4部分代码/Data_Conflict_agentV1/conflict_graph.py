"""
conflict_graph.py — Conflict Resolution SubGraph (V1.0)

架构: 一个 Stage = 一个 Agent
  START → ConflictIdentificationAgent → ConflictClassificationAgent
        → EvidenceCollectionAgent → ResolutionReasoningAgent
        → ConfidenceEvaluationAgent → ResolutionReportAgent → END

条件边:
  - Identification: total_conflicts==0 → 直接 END (跳过后续 Stage)
  - Confidence: 置信度不足 + retry<2 → 重入 Reasoning (内部重试)

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_state import QualityGraphState
from utils.logger import get_logger

logger = get_logger(__name__)

# ── 6 个 Agent ──
from Data_Conflict_agentV1.agents.conflict_identification_agent import ConflictIdentificationAgent
from Data_Conflict_agentV1.agents.conflict_classification_agent import ConflictClassificationAgent
from Data_Conflict_agentV1.agents.evidence_collection_agent import EvidenceCollectionAgent
from Data_Conflict_agentV1.agents.resolution_reasoning_agent import ResolutionReasoningAgent
from Data_Conflict_agentV1.agents.confidence_evaluation_agent import ConfidenceEvaluationAgent
from Data_Conflict_agentV1.agents.resolution_report_agent import ResolutionReportAgent


# ── 实例化 ──
_identification = ConflictIdentificationAgent()
_classification = ConflictClassificationAgent()
_evidence = EvidenceCollectionAgent()
_reasoning = ResolutionReasoningAgent()
_confidence = ConfidenceEvaluationAgent()
_report = ResolutionReportAgent()


# ==========================================================
# Stage Nodes — 极简: 只调用 Agent.run()
# ==========================================================

def _identification_node(state: QualityGraphState) -> dict[str, Any]:
    return _identification.run(state)


def _classification_node(state: QualityGraphState) -> dict[str, Any]:
    return _classification.run(state)


def _evidence_node(state: QualityGraphState) -> dict[str, Any]:
    return _evidence.run(state)


def _reasoning_node(state: QualityGraphState) -> dict[str, Any]:
    return _reasoning.run(state)


def _confidence_node(state: QualityGraphState) -> dict[str, Any]:
    return _confidence.run(state)


def _report_node(state: QualityGraphState) -> dict[str, Any]:
    return _report.run(state)


# ==========================================================
# 条件边函数
# ==========================================================

def _after_identification(state: QualityGraphState) -> str:
    """
    Identification → Classification 或 跳过 (无冲突直接 Export)
    """
    conflict_state = state.get("report_state", {}).get("conflict", {})
    ident = conflict_state.get("identification", {})
    total = ident.get("total_conflicts", 0)
    if total == 0:
        logger.info("[ConflictGraph] No conflicts → skip Stage 2-6 → END")
        return END
    return "conflict_classification"


def _after_confidence(state: QualityGraphState) -> str:
    """
    Confidence → Report 或 重入 Reasoning (内部重试)
    """
    wf = state.get("workflow_state", {})
    status = wf.get("execution_status", "Success")
    if status == "Retry":
        # 内部重试: 置信度不足 → 退回 Reasoning 重新推理
        retry_count = state.get("report_state", {}).get("conflict", {}).get(
            "reasoning", {}).get("confidence_retry_count", 0)
        if retry_count < 2:
            logger.info("[ConflictGraph] Confidence below threshold → retry Reasoning (%d/2)", retry_count + 1)
            return "resolution_reasoning"
    # 正常流程 → Report
    return "resolution_report"


# ==========================================================
# 构建 SubGraph
# ==========================================================

def build_conflict_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("conflict_identification", _identification_node)
    graph.add_node("conflict_classification", _classification_node)
    graph.add_node("evidence_collection", _evidence_node)
    graph.add_node("resolution_reasoning", _reasoning_node)
    graph.add_node("confidence_evaluation", _confidence_node)
    graph.add_node("resolution_report", _report_node)

    graph.set_entry_point("conflict_identification")

    # Identification → Classification (or END)
    graph.add_conditional_edges(
        "conflict_identification",
        _after_identification,
        {"conflict_classification": "conflict_classification", END: END},
    )

    # 线性流水线: Classification → Evidence → Reasoning
    graph.add_edge("conflict_classification", "evidence_collection")
    graph.add_edge("evidence_collection", "resolution_reasoning")

    # Reasoning → Confidence
    graph.add_edge("resolution_reasoning", "confidence_evaluation")

    # Confidence → Report (or retry Reasoning)
    graph.add_conditional_edges(
        "confidence_evaluation",
        _after_confidence,
        {"resolution_reasoning": "resolution_reasoning", "resolution_report": "resolution_report"},
    )

    # Report → END
    graph.add_edge("resolution_report", END)

    logger.info("[Workflow] Conflict SubGraph built (6 Agents).")
    return graph
