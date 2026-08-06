"""
graph.py — Quality Pipeline Main Graph (V3.1)

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

职责 (V3.1 图路由分离):
  - graph.py: 仅负责节点装配 + 条件边注册 (纯编排)
  - routers.py: 所有路由函数 (Retry/Router/Loop/Dispatch)
  - 不调用 Tool/Prompt/LLM/Rule
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from .quality_state import QualityGraphState
from .utils.logger import get_logger

logger = get_logger(__name__)

from .Data_Assessment_agentV1.assessment_graph import build_assessment_graph
from .Data_Normalization_agentV1.normalization_graph import build_normalization_graph
from .Data_Conflict_agentV1.conflict_graph import build_conflict_graph
from .Data_Export_agentV1.export_graph import build_export_graph
from .Data_Insights_agentV1.insights_graph import build_insights_graph  # V3.4

from .routers import (
    # 节点 (控制层)
    loop_controller_node,
    dispatch_node,
    before_normalization_node,
    _make_stage_gate,  # V3.3: 统一 Stage Gate 工厂
    # 路由函数 (唯一路由来源)
    route_after_dispatch,
    route_after_loop,
    route_after_human_review,
    # 常量
    NODE_ASSESSMENT,
    NODE_NORMALIZATION,
    NODE_CONFLICT,
    NODE_EXPORT,
    NODE_HUMAN_REVIEW,
    NODE_LOOP,
    NODE_DISPATCH,
    NODE_PRE_NORMALIZATION,
)

# V3.4: DataInsights 子图节点
NODE_INSIGHTS = "insights_graph"


# ==========================================================
# Human Review Node (V3.0) — 唯一留在 graph 的节点实现
# ==========================================================

def human_review_node(state: QualityGraphState) -> dict[str, Any]:
    """Human Review — 命令行交互。"""
    from .Data_HumanReview_agentV1.human_review_agent import HumanReviewAgent
    return HumanReviewAgent().run(state)


# ==========================================================
# V3.3: Stage Gate 条件边 — 读 Gate 写入的 route_decision
# ==========================================================

def _route_after_gate(node: str, next_node: str, human_target: str = NODE_HUMAN_REVIEW):
    """Gate 条件边: __retry__ → 重入子图 / HumanReview → 簿记节点 / 其他 → 下一节点。

    V4 fix: HumanReview 不再直达 HR — 跳过 loop_controller/dispatch 会导致
    pending_sources 清理等簿记丢失 (C→E 后 pending["Conflict"] 残留 → 无限循环)。
    Assessment gate 经 dispatch (队列路由 + 计数器重置), Norm/Conflict gate 经 loop。
    """
    def route(state: QualityGraphState) -> str:
        decision = state.get("workflow_state", {}).get("route_decision", "Success")
        if decision == "__retry__":
            return node
        if decision == "HumanReview":
            return human_target
        return next_node
    return route


# 实例化 Gate 节点
_gate_assessment = _make_stage_gate(NODE_ASSESSMENT)
_gate_normalization = _make_stage_gate(NODE_NORMALIZATION)
_gate_conflict = _make_stage_gate(NODE_CONFLICT)
_route_after_gate_assessment = _route_after_gate(NODE_ASSESSMENT, NODE_DISPATCH, human_target=NODE_DISPATCH)
_route_after_gate_normalization = _route_after_gate(NODE_NORMALIZATION, NODE_LOOP, human_target=NODE_LOOP)
_route_after_gate_conflict = _route_after_gate(NODE_CONFLICT, NODE_LOOP, human_target=NODE_LOOP)


# ==========================================================
# 构建 Main Graph (V3.4)
# ==========================================================

def build_quality_graph() -> StateGraph[QualityGraphState]:
    """
    V3.4 图结构:

        START → Assessment → Gate(A) → Dispatch
          ├── Normalization → Gate(N) → LoopCnt → Export → Insights → END
          ├── Conflict → Gate(C) → LoopCnt → Norm → ...          (C→B→C loop)
          ├── Export → Insights → END                             (A→D)
          └── HumanReview
               ├── Assessment (E→A)
               └── Normalization (E→B)
    """
    logger.info("[Workflow] Building Quality Main Graph V3.4...")

    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    # 节点
    graph.add_node(NODE_ASSESSMENT, build_assessment_graph().compile())
    graph.add_node(NODE_NORMALIZATION, build_normalization_graph().compile())
    graph.add_node(NODE_CONFLICT, build_conflict_graph().compile())
    graph.add_node(NODE_EXPORT, build_export_graph().compile())
    graph.add_node(NODE_INSIGHTS, build_insights_graph().compile())  # V3.4
    graph.add_node(NODE_LOOP, loop_controller_node)
    graph.add_node(NODE_HUMAN_REVIEW, human_review_node)
    graph.add_node(NODE_DISPATCH, dispatch_node)
    graph.add_node(NODE_PRE_NORMALIZATION, before_normalization_node)
    # V3.3: Stage Gates
    graph.add_node("gate_assessment", _gate_assessment)
    graph.add_node("gate_normalization", _gate_normalization)
    graph.add_node("gate_conflict", _gate_conflict)

    graph.set_entry_point(NODE_ASSESSMENT)

    # Assessment → Gate(A) → Dispatch / 重入 / HumanReview (V4: HR 经 dispatch 簿记)
    graph.add_edge(NODE_ASSESSMENT, "gate_assessment")
    graph.add_conditional_edges("gate_assessment", _route_after_gate_assessment, {
        NODE_ASSESSMENT: NODE_ASSESSMENT,
        NODE_DISPATCH: NODE_DISPATCH,
    })

    # Dispatch → Norm / Conflict / Export / Human (V3.3: 基于 pending_sources 队列)
    graph.add_conditional_edges(NODE_DISPATCH, route_after_dispatch, {
        NODE_NORMALIZATION: NODE_NORMALIZATION,
        NODE_CONFLICT: NODE_CONFLICT,
        NODE_EXPORT: NODE_EXPORT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # Normalization → Gate(N) → LoopController (V4: HR 经 loop 簿记, 清理 pending)
    graph.add_edge(NODE_NORMALIZATION, "gate_normalization")
    graph.add_conditional_edges("gate_normalization", _route_after_gate_normalization, {
        NODE_NORMALIZATION: NODE_NORMALIZATION,
        NODE_LOOP: NODE_LOOP,
    })

    # Conflict → Gate(C) → LoopController (V4: HR 经 loop 簿记, 清理 pending)
    graph.add_edge(NODE_CONFLICT, "gate_conflict")
    graph.add_conditional_edges("gate_conflict", _route_after_gate_conflict, {
        NODE_CONFLICT: NODE_CONFLICT,
        NODE_LOOP: NODE_LOOP,
    })

    # LoopController → 统一路由 (routers.py: route_after_loop 读 next_route)
    graph.add_conditional_edges(NODE_LOOP, route_after_loop, {
        NODE_PRE_NORMALIZATION: NODE_PRE_NORMALIZATION,
        NODE_EXPORT: NODE_EXPORT,
        NODE_CONFLICT: NODE_CONFLICT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # pre_normalization → Normalization (C→B with loop_round increment)
    graph.add_edge(NODE_PRE_NORMALIZATION, NODE_NORMALIZATION)

    # HumanReview → Assessment / Normalization / Conflict / Export (V3.3: 队列继续)
    graph.add_conditional_edges(NODE_HUMAN_REVIEW, route_after_human_review, {
        NODE_ASSESSMENT: NODE_ASSESSMENT,
        NODE_NORMALIZATION: NODE_NORMALIZATION,
        NODE_CONFLICT: NODE_CONFLICT,
        NODE_EXPORT: NODE_EXPORT,
        NODE_HUMAN_REVIEW: NODE_HUMAN_REVIEW,
    })

    # Export → Insights → END (V3.4)
    graph.add_edge(NODE_EXPORT, NODE_INSIGHTS)
    graph.add_edge(NODE_INSIGHTS, END)

    logger.info("[Workflow] Quality Main Graph V3.4 built.")
    return graph


def compile_quality_graph():
    return build_quality_graph().compile()
