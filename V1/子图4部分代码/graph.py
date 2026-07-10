"""
graph.py — Quality Pipeline Main Graph (Workflow Orchestrator)

职责: 仅负责 SubGraph 编排、Conditional Edge、Retry/Loop/Interrupt
禁止: 业务规则、LLM Prompt、Tool 调用、Quality Score 判断

架构:
    START → AssessmentGraph → Router → NormalizationGraph
        → LoopController → Router → ConflictGraph
        → Router → ExportGraph → END
              ↕ HumanReview (条件路由)
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_state import QualityGraphState
from utils.logger import get_logger

logger = get_logger(__name__)

# ── 子图 ──
from Data_Assessment_agentV1.assessment_graph import build_assessment_graph
from normalization_graph import build_normalization_graph
from conflict_graph import build_conflict_graph
from export_graph import build_export_graph

# ── 路由 / Retry / Loop 控制器 ──
from routers import (
    route_after_assessment,
    route_after_normalization,
    route_after_conflict,
    route_after_human_review,
    loop_controller_node,
    NODE_ASSESSMENT,
    NODE_NORMALIZATION,
    NODE_CONFLICT,
    NODE_EXPORT,
    NODE_HUMAN_REVIEW,
    NODE_LOOP,
)

# ==========================================================
# Human Review Node (Mark II: 条件恢复 + 上下文)
# ==========================================================

def human_review_node(state: QualityGraphState) -> dict[str, Any]:
    """
    Human Review Node.

    设置打断标志, 收集上下文信息供 UI 展示。
    恢复后根据 __human_review_decision__ 中的 route_decision 跳转。
    """
    wf = dict(state.get("workflow_state", {}))
    rs = state.get("report_state", {})
    ds = state.get("data_state", {})

    # 已有人工决策 → 直接应用
    human_decision = wf.get("__human_review_decision__")
    if human_decision is not None:
        next_route = human_decision.get("route_decision", "Normalization") if isinstance(human_decision, dict) else "Normalization"
        logger.info("[Interrupt] Human decision received, routing to %s", next_route)
        return {
            "workflow_state": {
                "route_decision": next_route,
                "execution_status": "Success",
                "current_node": "human_review",
                "retry_counter": 0,
                "last_error": None,
                "__human_review_needed__": False,
                "__human_review_decision__": None,
                "__human_review_data__": None,
                "workflow_history": [{
                    "agent": "HumanReview", "stage": "Resolved",
                    "status": "Success",
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "duration": 0.0,
                    "reason": f"Human chose → {next_route}",
                }],
            },
        }

    # 首次进入：收集上下文, 请求人工
    conflict = rs.get("conflict", {}) or {}
    quality = rs.get("quality", {}) or {}
    pending = conflict.get("llm_resolution_detail", {}).get("resolutions", [])
    # 筛选 human_required 的冲突
    pending_human = [r for r in pending if r.get("decision") == "human_required" or r.get("needs_human")]

    review_context = {
        "pending_conflicts": pending_human,
        "quality_level": quality.get("quality_scoring", {}).get("quality_level", "unknown"),
        "quality_score": quality.get("quality_scoring", {}).get("overall_score", 0),
        "current_node": wf.get("current_node", ""),
        "last_error": wf.get("last_error"),
        "record_count": len(ds.get("current_data", {}).get("records", [])),
    }

    logger.warning("[Interrupt] Human Review requested (%d pending conflicts)",
                   len(pending_human))

    return {
        "workflow_state": {
            "execution_status": "HumanReview",
            "current_node": "human_review",
            "route_decision": "",
            "retry_counter": 0,
            "last_error": f"{len(pending_human)} conflicts need human decision",
            "__human_review_needed__": True,
            "__human_review_data__": review_context,
            "__human_review_decision__": None,
            "workflow_history": [{
                "agent": "HumanReview", "stage": "Interrupt",
                "status": "HumanReview",
                "timestamp": __import__("datetime").datetime.now().isoformat(),
                "duration": 0.0,
                "reason": f"{len(pending_human)} conflicts need human decision",
            }],
        },
    }


# ==========================================================
# 构建 Main Graph
# ==========================================================

def build_quality_graph() -> StateGraph[QualityGraphState]:
    """
    构建 Quality Main Graph。

    图结构:
        START
        ↓
        AssessmentGraph
        ↓  [route_after_assessment]
        ├── NormalizationGraph → LoopController → [route_after_normalization]
        │       ↑                    ↓
        │       └──── ConflictGraph ─┘  [route_after_conflict]
        ├── ExportGraph → END
        └── HumanReview → [route_after_human]
    """
    logger.info("[Workflow] Building Quality Main Graph...")

    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    # ── 添加节点 ──
    graph.add_node(NODE_ASSESSMENT, build_assessment_graph().compile())
    graph.add_node(NODE_NORMALIZATION, build_normalization_graph().compile())
    graph.add_node(NODE_CONFLICT, build_conflict_graph().compile())
    graph.add_node(NODE_EXPORT, build_export_graph().compile())
    graph.add_node(NODE_LOOP, loop_controller_node)
    graph.add_node(NODE_HUMAN_REVIEW, human_review_node)

    # ── 入口 ──
    graph.set_entry_point(NODE_ASSESSMENT)

    # ── Assessment → Router ──
    graph.add_conditional_edges(
        NODE_ASSESSMENT, route_after_assessment,
        {NODE_NORMALIZATION: NODE_NORMALIZATION,
         NODE_CONFLICT: NODE_CONFLICT,
         NODE_EXPORT: NODE_EXPORT,
         NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
         NODE_ASSESSMENT: NODE_ASSESSMENT},  # Retry → 自身
    )

    # ── Normalization → LoopController → Router ──
    graph.add_edge(NODE_NORMALIZATION, NODE_LOOP)
    graph.add_conditional_edges(
        NODE_LOOP, route_after_normalization,
        {NODE_CONFLICT: NODE_CONFLICT,
         NODE_EXPORT: NODE_EXPORT,
         NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
         NODE_NORMALIZATION: NODE_NORMALIZATION},  # Retry
    )

    # ── Conflict → LoopController → Router ──
    graph.add_edge(NODE_CONFLICT, NODE_LOOP)
    graph.add_conditional_edges(
        NODE_LOOP, route_after_conflict,
        {NODE_NORMALIZATION: NODE_NORMALIZATION,
         NODE_EXPORT: NODE_EXPORT,
         NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
         NODE_CONFLICT: NODE_CONFLICT},  # Retry
    )

    # ── HumanReview → 条件路由 (不固定 Normalization) ──
    graph.add_conditional_edges(
        NODE_HUMAN_REVIEW, route_after_human_review,
        {NODE_ASSESSMENT: NODE_ASSESSMENT,
         NODE_NORMALIZATION: NODE_NORMALIZATION,
         NODE_CONFLICT: NODE_CONFLICT,
         NODE_EXPORT: NODE_EXPORT},
    )

    # ── Export → END ──
    graph.add_edge(NODE_EXPORT, END)

    logger.info("[Workflow] Quality Main Graph built successfully.")
    return graph


def compile_quality_graph():
    return build_quality_graph().compile()
