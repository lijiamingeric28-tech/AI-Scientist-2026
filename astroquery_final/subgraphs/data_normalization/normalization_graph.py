"""
normalization_graph.py — Normalization SubGraph (V2.1)

架构: 一个 Stage = 一个 Agent
  START → SourceRouterAgent → PlanningAgent → NormalizationAgent
        → ValidationAgent → ReportAgent → END

条件边 (V2.1):
  - SourceRouter: total_to_normalize==0 → 直接 END (跳过后续 Stage)
  - Validation: Retry → 回退 PlanningAgent (最多 2 次)

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

# ── 5 个 Agent ──
from subgraphs.data_normalization.agents.source_router_agent import SourceRouterAgent
from subgraphs.data_normalization.agents.planning_agent import PlanningAgent
from subgraphs.data_normalization.agents.normalization_agent import NormalizationAgent
from subgraphs.data_normalization.agents.validation_agent import ValidationAgent
from subgraphs.data_normalization.agents.report_agent import ReportAgent


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
# 条件边函数 (V2.1)
# ==========================================================

def _after_source_router(state: QualityGraphState) -> str:
    """total_to_normalize==0 → 跳过后续 Stage, 走 finalize 统一出口"""
    norm = state.get("report_state", {}).get("normalization", {})
    sp = norm.get("source_plan", {})
    total = sp.get("total_to_normalize", 0)
    if total == 0:
        logger.info("[NormalizationGraph] No sources to normalize → skip Stage 2-5")
        return "finalize"
    return "planning"


def _after_validation(state: QualityGraphState) -> str:
    """Retry → 回退 PlanningAgent 重新规划"""
    wf = state.get("workflow_state", {})
    status = wf.get("execution_status", "Success")
    norm = state.get("report_state", {}).get("normalization", {})
    val = norm.get("validation", {})
    retry_count = val.get("retry_count", 0)
    if status == "Retry" and retry_count < 2:
        logger.info("[NormalizationGraph] Validation retry %d/2 → back to Planning", retry_count + 1)
        return "planning"
    return "report"


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

def build_normalization_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("source_router", _source_router_node)
    graph.add_node("planning", _planning_node)
    graph.add_node("normalization", _normalization_node)
    graph.add_node("validation", _validation_node)
    graph.add_node("report", _report_node)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("source_router")

    # V2.1: SourceRouter → Planning (或 finalize → END, V3.3 统一出口)
    graph.add_conditional_edges(
        "source_router", _after_source_router,
        {"planning": "planning", "finalize": "finalize"},
    )

    graph.add_edge("planning", "normalization")
    graph.add_edge("normalization", "validation")

    # V2.1: Validation → Report (或 回退 Planning)
    graph.add_conditional_edges(
        "validation", _after_validation,
        {"planning": "planning", "report": "report"},
    )

    graph.add_edge("report", "finalize")
    graph.add_edge("finalize", END)

    logger.info("[Workflow] Normalization SubGraph built (5 Agents + finalize, V2.1).")
    return graph
