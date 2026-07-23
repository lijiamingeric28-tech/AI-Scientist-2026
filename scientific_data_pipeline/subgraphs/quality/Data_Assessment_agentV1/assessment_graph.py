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

from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)

# ── 4 个 Agent ──
from subgraphs.quality.Data_Assessment_agentV1.agents.profiling_agent import ProfilingAgent
from subgraphs.quality.Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
from subgraphs.quality.Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
from subgraphs.quality.Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent


# ── 实例化 ──
_profiling = ProfilingAgent()
_assessment = QualityAssessmentAgent()
_scoring = QualityScoringAgent()
_decision = DecisionReasoningAgent()


# ==========================================================
# Stage Nodes — 极简: 只调用 Agent.run()
# ==========================================================

def _profiling_node(state: QualityGraphState) -> dict[str, Any]:
    return _profiling.run(state)


def _assessment_node(state: QualityGraphState) -> dict[str, Any]:
    return _assessment.run(state)


def _scoring_node(state: QualityGraphState) -> dict[str, Any]:
    return _scoring.run(state)


def _decision_node(state: QualityGraphState) -> dict[str, Any]:
    return _decision.run(state)


# ==========================================================
# 构建 SubGraph
# ==========================================================

def build_assessment_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("profiling", _profiling_node)
    graph.add_node("quality_assessment", _assessment_node)
    graph.add_node("scoring", _scoring_node)
    graph.add_node("decision", _decision_node)

    graph.set_entry_point("profiling")
    graph.add_edge("profiling", "quality_assessment")
    graph.add_edge("quality_assessment", "scoring")
    graph.add_edge("scoring", "decision")
    graph.add_edge("decision", END)

    logger.info("[Workflow] Assessment SubGraph built (4 Agents).")
    return graph
