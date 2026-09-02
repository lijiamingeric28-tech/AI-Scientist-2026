"""
graph.py — Quality Pipeline Main Graph (V3.0)

流程:
    START
    ↓
    AssessmentGraph
    ↓  [per-source dispatch]
    ├── Normalization → Export → END       (A→B→D)
    ├── Conflict → Normalization → Conflict → Export → END  (A→C→B→C→D, 循环)
    ├── Export → END                       (A→D)
    └── HumanReview                        (A→E / C→E)
         ├── Assessment (E→A: 重新评估)
         └── Normalization (E→B: 执行修改)

职责: 仅负责 SubGraph 编排, 不调用 Tool/Prompt/LLM/Rule。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)

from subgraphs.quality.Data_Assessment_agentV1.assessment_graph import build_assessment_graph
from subgraphs.quality.Data_Normalization_agentV1.normalization_graph import build_normalization_graph
from subgraphs.quality.Data_Conflict_agentV1.conflict_graph import build_conflict_graph
from subgraphs.quality.Data_Export_agentV1.export_graph import build_export_graph

from subgraphs.quality.routers import (
    loop_controller_node,
    NODE_ASSESSMENT,
    NODE_NORMALIZATION,
    NODE_CONFLICT,
    NODE_EXPORT,
    NODE_HUMAN_REVIEW,
    NODE_LOOP,
)

NODE_DISPATCH = "dispatch"

MAX_LOOP = 3  # C→B→C 最大循环次数


# ==========================================================
# Dispatch Node
# ==========================================================

def dispatch_node(state: QualityGraphState) -> dict[str, Any]:
    """Assessment 后分发: 统计 per_source_routes。"""
    quality = state.get("report_state", {}).get("quality", {}) or {}
    per_source_routes = quality.get("per_source_routes", {})

    norm_s = [s for s, r in per_source_routes.items() if r == "Normalization"]
    conf_s = [s for s, r in per_source_routes.items() if r == "Conflict"]
    export_s = [s for s, r in per_source_routes.items() if r == "Export"]
    human_s = [s for s, r in per_source_routes.items() if r == "HumanReview"]

    logger.info("[Dispatch] Norm=%d Conflict=%d Export=%d Human=%d",
                len(norm_s), len(conf_s), len(export_s), len(human_s))

    now = __import__("datetime").datetime.now().isoformat()
    return {
        "workflow_state": {
            "current_node": "dispatch", "execution_status": "Success",
            "_norm_sources": norm_s, "_conflict_sources": conf_s,
            "_export_sources": export_s, "_human_sources": human_s,
            "_loop_count": 0,  # C→B→C 循环计数器
            "workflow_history": [{"agent": "Dispatch", "stage": "Routing",
                "status": "Success", "timestamp": now, "duration": 0.0,
                "reason": f"Norm={len(norm_s)} Conflict={len(conf_s)} Export={len(export_s)} Human={len(human_s)}"}],
        },
    }


# ==========================================================
# Human Review Node (V3.0)
# ==========================================================

def human_review_node(state: QualityGraphState) -> dict[str, Any]:
    """Human Review — 命令行交互。"""
    from subgraphs.quality.Data_HumanReview_agentV1.human_review_agent import HumanReviewAgent
    return HumanReviewAgent().run(state)


# ==========================================================
# 路由函数
# ==========================================================

def route_after_assessment(state: QualityGraphState) -> str:
    """Assessment → Dispatch (或 Retry/HumanReview)。"""
    status = state.get("workflow_state", {}).get("execution_status", "Success")
    if status == "Retry":
        return NODE_ASSESSMENT
    if status == "Failed":
        return NODE_HUMAN_REVIEW
    return NODE_DISPATCH


def route_after_dispatch(state: QualityGraphState) -> str:
    """
    Dispatch 分发逻辑:
      - 有 Human → HumanReview
      - 有 Normalization (无 Conflict) → Normalization
      - 有 Conflict (无 Normalization) → Conflict
      - 两者都有 → Normalization 优先 (先清洗再冲突)
      - 全 Export → Export
    """
    wf = state.get("workflow_state", {})
    human_n = len(wf.get("_human_sources", []))
    norm_n = len(wf.get("_norm_sources", []))
    conf_n = len(wf.get("_conflict_sources", []))

    if human_n > 0 and norm_n == 0 and conf_n == 0:
        return NODE_HUMAN_REVIEW
    if norm_n > 0:
        return NODE_NORMALIZATION  # 优先清洗
    if conf_n > 0:
        return NODE_CONFLICT
    return NODE_EXPORT


def route_after_normalization(state: QualityGraphState) -> str:
    """
    Normalization 完成后:
      - 来自 Assessment (A→B):
          - 无冲突 → Export (A→B→D)
          - 仍需冲突分析 → Conflict (B→C)
      - 来自 Conflict  (C→B) → Conflict (C→B→C loop)
    """
    wf = state.get("workflow_state", {})
    from_conflict = wf.get("_from_conflict", False)
    loop_count = wf.get("_loop_count", 0)

    if from_conflict:
        logger.info("[Router] C→B: Normalization done → back to Conflict (loop %d)", loop_count)
        return NODE_CONFLICT

    # V3.0 Merge Fix: A→B 路径 — 检查 Normalization 是否检测到剩余冲突
    normalization = state.get("report_state", {}).get("normalization", {})
    validation = normalization.get("validation", {})
    needs_conflict = validation.get("needs_conflict_analysis", False)

    if needs_conflict:
        logger.info("[Router] A→B→C: Normalization detected remaining conflicts → Conflict")
        return NODE_CONFLICT

    logger.info("[Router] A→B→D: Normalization done → Export")
    return NODE_EXPORT


def route_after_conflict(state: QualityGraphState) -> str:
    """
    Conflict 完成后:
      - Resolved → Export (C→D)
      - Need Normalization → Normalization (C→B, 设置 _from_conflict 标记)
      - Human Required → HumanReview (C→E)
    """
    wf = state.get("workflow_state", {})
    conflict = state.get("report_state", {}).get("conflict", {})
    report = conflict.get("resolution_report", {})
    route = report.get("route_decision", wf.get("route_decision", "Export"))

    if route == "Normalization":
        loop_count = wf.get("_loop_count", 0) + 1
        if loop_count > MAX_LOOP:
            logger.warning("[Router] C→B max loops (%d) → force Export", MAX_LOOP)
            return NODE_EXPORT
        logger.info("[Router] C→B: Need normalization (loop %d/%d)", loop_count, MAX_LOOP)
        # Merge Fix: 返回 NODE_NORMALIZATION, conditional edge map 会映射到 "pre_normalization"
        return NODE_NORMALIZATION
    elif route == "HumanReview":
        return NODE_HUMAN_REVIEW
    else:
        return NODE_EXPORT


def route_after_human_review(state: QualityGraphState) -> str:
    """
    Human Review 完成后:
      - "Normalization" → Normalization (E→B)
      - "Assessment" → Assessment (E→A)
      - 其他 → 停留在 HumanReview
    """
    wf = state.get("workflow_state", {})
    decision = wf.get("route_decision", "")
    if decision == "Normalization":
        return NODE_NORMALIZATION
    elif decision == "Assessment":
        return NODE_ASSESSMENT
    return NODE_HUMAN_REVIEW


# ==========================================================
# Conflict → Normalization 前设置 _from_conflict 标记
# ==========================================================

def before_normalization_node(state: QualityGraphState) -> dict[str, Any]:
    """Conflict → Normalization 时设置标记 + 递增循环计数。"""
    wf = state.get("workflow_state", {})
    loop = wf.get("_loop_count", 0)
    return {"workflow_state": {
        "_from_conflict": True,
        "_loop_count": loop + 1,
        "current_node": "pre_normalization",
    }}


# ==========================================================
# 构建 Main Graph (V3.0)
# ==========================================================

def build_quality_graph() -> StateGraph[QualityGraphState]:
    """
    V3.0 图结构:

        START → Assessment → Dispatch
          ├── Normalization → Export → END      (A→B→D)
          ├── Conflict → LoopCnt → Norm → Conflict → ...  (C→B→C loop)
          ├── Export → END                       (A→D)
          └── HumanReview
               ├── Assessment (E→A)
               └── Normalization (E→B)
    """
    logger.info("[Workflow] Building Quality Main Graph V3.0...")

    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    # 节点 — 与 V1 一致: 使用预编译的子图作为节点
    graph.add_node(NODE_ASSESSMENT, build_assessment_graph().compile())
    graph.add_node(NODE_NORMALIZATION, build_normalization_graph().compile())
    graph.add_node(NODE_CONFLICT, build_conflict_graph().compile())
    graph.add_node(NODE_EXPORT, build_export_graph().compile())
    graph.add_node(NODE_LOOP, loop_controller_node)
    graph.add_node(NODE_HUMAN_REVIEW, human_review_node)
    graph.add_node(NODE_DISPATCH, dispatch_node)
    graph.add_node("pre_normalization", before_normalization_node)

    graph.set_entry_point(NODE_ASSESSMENT)

    # Assessment → Dispatch
    graph.add_conditional_edges(NODE_ASSESSMENT, route_after_assessment, {
        NODE_DISPATCH: NODE_DISPATCH,
        NODE_ASSESSMENT: NODE_ASSESSMENT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # Dispatch → Norm / Conflict / Export / Human
    graph.add_conditional_edges(NODE_DISPATCH, route_after_dispatch, {
        NODE_NORMALIZATION: NODE_NORMALIZATION,
        NODE_CONFLICT: NODE_CONFLICT,
        NODE_EXPORT: NODE_EXPORT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # Normalization → LoopController → Export (or Conflict via C→B)
    graph.add_edge(NODE_NORMALIZATION, NODE_LOOP)
    graph.add_conditional_edges(NODE_LOOP, route_after_normalization, {
        NODE_EXPORT: NODE_EXPORT,
        NODE_CONFLICT: NODE_CONFLICT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # Conflict → LoopController → Norm / Export / Human
    graph.add_edge(NODE_CONFLICT, NODE_LOOP)
    graph.add_conditional_edges(NODE_LOOP, route_after_conflict, {
        NODE_NORMALIZATION: "pre_normalization",
        NODE_EXPORT: NODE_EXPORT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # pre_normalization → Normalization (C→B with loop count increment)
    graph.add_edge("pre_normalization", NODE_NORMALIZATION)

    # HumanReview → Assessment / Normalization
    graph.add_conditional_edges(NODE_HUMAN_REVIEW, route_after_human_review, {
        NODE_ASSESSMENT: NODE_ASSESSMENT,
        NODE_NORMALIZATION: NODE_NORMALIZATION,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # Export → END
    graph.add_edge(NODE_EXPORT, END)

    logger.info("[Workflow] Quality Main Graph V3.0 built.")
    return graph


def compile_quality_graph():
    return build_quality_graph().compile()
