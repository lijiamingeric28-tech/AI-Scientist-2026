"""
assessment_graph.py — Assessment SubGraph

架构: 一个 Stage = 一个 Agent
  START → ProfilingAgent → QualityAssessmentAgent
        → QualityScoringAgent → DecisionReasoningAgent → END

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

# ── 4 个 Agent ──
from subgraphs.data_assessment.agents.profiling_agent import ProfilingAgent
from subgraphs.data_assessment.agents.quality_assessment_agent import QualityAssessmentAgent
from subgraphs.data_assessment.agents.quality_scoring_agent import QualityScoringAgent
from subgraphs.data_assessment.agents.decision_reasoning_agent import DecisionReasoningAgent


# ── 实例化 ──
_profiling = ProfilingAgent()
_assessment = QualityAssessmentAgent()
_scoring = QualityScoringAgent()
_decision = DecisionReasoningAgent()


# ==========================================================
# Stage Nodes — 极简: 只调用 Agent.run()
# ==========================================================

# Web 埋点包装（模块 ③：agent 事件；离线 no-op）
from quality_pipeline.agent_events import wrap_agent_node as _wrap


def _profiling_node(state: QualityGraphState) -> dict[str, Any]:
    return _wrap("ProfilingAgent", _profiling.run, "assessment")(state)


def _assessment_node(state: QualityGraphState) -> dict[str, Any]:
    return _wrap("QualityAssessmentAgent", _assessment.run, "assessment")(state)


def _scoring_node(state: QualityGraphState) -> dict[str, Any]:
    return _wrap("QualityScoringAgent", _scoring.run, "assessment")(state)


def _decision_node(state: QualityGraphState) -> dict[str, Any]:
    return _wrap("DecisionReasoningAgent", _decision.run, "assessment")(state)


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

def build_assessment_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("profiling", _profiling_node)
    graph.add_node("quality_assessment", _assessment_node)
    graph.add_node("scoring", _scoring_node)
    graph.add_node("decision", _decision_node)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("profiling")
    graph.add_edge("profiling", "quality_assessment")
    graph.add_edge("quality_assessment", "scoring")
    graph.add_edge("scoring", "decision")
    graph.add_edge("decision", "finalize")
    graph.add_edge("finalize", END)

    logger.info("[Workflow] Assessment SubGraph built (4 Agents + finalize).")
    return graph
