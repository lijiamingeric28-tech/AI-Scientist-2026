"""
normalization_graph.py — Normalization SubGraph (V1.1)

架构: 一个 Stage = 一个 Agent
  START → SourceRouterAgent → PlanningAgent → NormalizationAgent
        → ValidationAgent → ReportAgent → END

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_state import QualityGraphState
from utils.logger import get_logger

logger = get_logger(__name__)

# ── 5 个 Agent ──
from Data_Normalization_agentV1.agents.source_router_agent import SourceRouterAgent
from Data_Normalization_agentV1.agents.planning_agent import PlanningAgent
from Data_Normalization_agentV1.agents.normalization_agent import NormalizationAgent
from Data_Normalization_agentV1.agents.validation_agent import ValidationAgent
from Data_Normalization_agentV1.agents.report_agent import ReportAgent


# ── 实例化 ──
_router = SourceRouterAgent()
_planning = PlanningAgent()
_normalization = NormalizationAgent()
_validation = ValidationAgent()
_report = ReportAgent()


# ==========================================================
# Stage Nodes — 极简: 只调用 Agent.run()
# ==========================================================

def _source_router_node(state: QualityGraphState) -> dict[str, Any]:
    return _router.run(state)


def _planning_node(state: QualityGraphState) -> dict[str, Any]:
    return _planning.run(state)


def _normalization_node(state: QualityGraphState) -> dict[str, Any]:
    return _normalization.run(state)


def _validation_node(state: QualityGraphState) -> dict[str, Any]:
    return _validation.run(state)


def _report_node(state: QualityGraphState) -> dict[str, Any]:
    return _report.run(state)


# ==========================================================
# 构建 SubGraph
# ==========================================================

def build_normalization_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("source_router", _source_router_node)
    graph.add_node("planning", _planning_node)
    graph.add_node("normalization", _normalization_node)
    graph.add_node("validation", _validation_node)
    graph.add_node("report", _report_node)

    graph.set_entry_point("source_router")
    graph.add_edge("source_router", "planning")
    graph.add_edge("planning", "normalization")
    graph.add_edge("normalization", "validation")
    graph.add_edge("validation", "report")
    graph.add_edge("report", END)

    logger.info("[Workflow] Normalization SubGraph built (5 Agents).")
    return graph
