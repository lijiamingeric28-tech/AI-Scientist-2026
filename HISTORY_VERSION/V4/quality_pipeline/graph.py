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

from subgraphs.data_assessment.assessment_graph import build_assessment_graph
from subgraphs.data_normalization.normalization_graph import build_normalization_graph
from subgraphs.data_conflict.conflict_graph import build_conflict_graph
from subgraphs.data_export.export_graph import build_export_graph
from subgraphs.data_insights.insights_graph import build_insights_graph  # V3.4

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
# M-13: 卡5/6 事件埋点 — flow 事件 + clean/deliver 出口 stage_completed
# ==========================================================

def _qid_of(state: QualityGraphState) -> str:
    ctx = state.get("context_state") or {}
    return str(ctx.get("query_id", ""))


def _flow_round(state: QualityGraphState) -> int:
    wf = state.get("workflow_state") or {}
    return int(wf.get("loop_round", 0) or 0)


def _call_node(fn, state: QualityGraphState):
    """调用节点函数：compiled 子图走 .invoke（Pregel 不可直接 __call__）。"""
    invoke = getattr(fn, "invoke", None)
    if callable(invoke):
        return invoke(state)
    return fn(state)


def _flow_wrap(flow_id: str, stage_id: str, fn):
    """M-13: 卡5/6 动态流转节点 flow 事件（flow_started/flow_completed 配对）。

    flow_id=轮次（normalization/conflict/export/insights），round=loop_round
    （dispatch 清零，pre_normalization 在 C→B 前递增）。离线未 configure 时
    events.emit 为 no-op，行为零变化。
    """
    from events import emit as _emit_event

    def wrapped(state: QualityGraphState) -> dict[str, Any]:
        qid = _qid_of(state)
        r = _flow_round(state)
        _emit_event(qid, {"type": "flow_started", "flow_id": flow_id,
                          "round": r, "stage_id": stage_id})
        try:
            return _call_node(fn, state)
        finally:
            _emit_event(qid, {"type": "flow_completed", "flow_id": flow_id,
                              "round": r, "stage_id": stage_id})
    return wrapped


def _pipeline_exit_wrap(fn):
    """M-13 最小修复: 管线出口（insights → END）补发 clean/deliver 卡
    stage_completed —— clean/deliver 无 stage_started，前端靠 agent 事件/
    stage_completed 弹卡，缺本事件则卡 5/6 永久「进行中…」。

    2026-08-27 时机修正（用户反馈：卡 5/6 全部跑完才显示完成的普遍性问题）：
    - clean 的 stage_completed 由 _clean_entry_wrap 在**进入 Export 前**发
      （normalization/conflict/human_review 全部结束 = Dispatch 队列清空转入导出）
    - deliver 的 stage_completed 由 _deliver_entry_wrap 在**进入 Insights 前**发
      （export 子图结束即数据交付完成；insights 是增值子流程）
    - 本 wrap 保留出口兜底（重复事件幂等），但不再承担主要完成信号
    """
    from events import emit as _emit_event

    def wrapped(state: QualityGraphState) -> dict[str, Any]:
        result = _call_node(fn, state)
        qid = _qid_of(state)
        # 出口兜底（前端 stage_completed 幂等，先到的 entry wrap 已置 completed）
        _emit_event(qid, {"type": "stage_completed", "stage_id": "clean",
                          "status": "completed"})
        _emit_event(qid, {"type": "stage_completed", "stage_id": "deliver",
                          "status": "completed"})
        return result
    return wrapped


def _assessment_wrap(fn):
    """2026-08-27: 质量检查完成时机 —— assessment 子图结束即发
    stage_completed(quality_check)（main_graph quality 节点改 mode='start'，
    不再由它等整条管线结束后才发 completed）。

    此前前端卡 4 恒「进行中」直到清洗/交付/洞察全部完成（用户实测观感
    「明明已完成却显示进行中」）；quality_check 的完成语义 = 评估完毕。
    """
    from events import emit as _emit_event
    import time as _time

    def wrapped(state: QualityGraphState) -> dict[str, Any]:
        qid = _qid_of(state)
        t0 = _time.time()
        result = _call_node(fn, state)
        _emit_event(qid, {"type": "stage_completed", "stage_id": "quality_check",
                          "status": "completed",
                          "duration": round(_time.time() - t0, 2)})
        return result
    return wrapped


def _clean_entry_wrap(fn):
    """2026-08-27: clean 完成时机 = 清洗子图（规范化/冲突/人工审核）全部结束、
    进入 Export **前** —— Dispatch/loop 队列清空转入导出即清洗完毕（而非等
    export 子图本身跑完才显示清洗完成；此前 clean 的 stage_completed 只在管线
    出口补发，卡 5 观感恒「进行中」直到交付/洞察全部跑完，与卡 4 同根问题）。
    """
    from events import emit as _emit_event

    def wrapped(state: QualityGraphState) -> dict[str, Any]:
        qid = _qid_of(state)
        _emit_event(qid, {"type": "stage_completed", "stage_id": "clean",
                          "status": "completed"})
        return _call_node(fn, state)
    return wrapped


def _deliver_entry_wrap(fn):
    """2026-08-27: deliver 完成时机 = export 子图结束、进入 Insights **前**
    （数据导出完成即交付；insights 为增值子流程，其完成由前端 insights flow
    completed 独立推导）。此前 deliver 只随管线出口补发，观感同样延迟。
    """
    from events import emit as _emit_event

    def wrapped(state: QualityGraphState) -> dict[str, Any]:
        qid = _qid_of(state)
        _emit_event(qid, {"type": "stage_completed", "stage_id": "deliver",
                          "status": "completed"})
        return _call_node(fn, state)
    return wrapped


# ==========================================================
# Human Review Node (V3.0) — 唯一留在 graph 的节点实现
# ==========================================================

def human_review_node(state: QualityGraphState) -> dict[str, Any]:
    """Human Review — 命令行交互 + Web agent 事件（M-16 修复）。

    不能直接包 agent_events.wrap_agent_node：其 finally 在 fn 抛异常
    （HITL interrupt 挂起）时对未赋值的 result 求值，会 NameError 掩盖
    GraphInterrupt，质量管线 HITL 直接死。这里本地实现同构 agent 包装：
    正常返回发 agent_completed；interrupt 挂起只发 agent_started（挂起中）。
    """
    from subgraphs.data_human_review.human_review_agent import HumanReviewAgent
    from events import emit as _emit_event
    import time as _time

    def _agent_ev(qid: str, status: str, **extra) -> None:
        ev = {"type": f"agent_{status}", "stage_id": "clean",
              "agent": "HumanReviewAgent",
              "flow_id": "human_review",  # 2026-08-27：前端人工审核块归组依据
              "round": _flow_round(state)}
        ev.update(extra)
        _emit_event(qid, ev)

    qid = _qid_of(state)
    _agent_ev(qid, "started")
    t0 = _time.time()
    try:
        result = HumanReviewAgent().run(state)
    except BaseException:
        raise  # interrupt 挂起等 → 不发 completed，原异常原样上浮
    ds = result.get("data_state") or {}
    traces = ds.get("data_trace") or []
    # P0-4：HumanReview 结论 reason（冲突消解摘要 / 路由决策 / traces 兜底）
    reason = None
    res = result.get("conflict") or {}
    rr = res.get("resolution_report") or {}
    if isinstance(rr, dict) and rr.get("summary"):
        reason = str(rr["summary"])[:300]
    elif (result.get("workflow_state") or {}).get("route_decision"):
        reason = f"路由决策：{result['workflow_state']['route_decision']}"
    elif traces:
        reason = f"修改 {len(traces)} 条数据"
    _agent_ev(qid, "completed", duration=round(_time.time() - t0, 2),
              traces=traces or None, reason=reason)
    return result


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

    # 节点（M-13: 阶段子图包 flow 事件 — 卡5/6 动态流转 + 轮次分组）
    # 2026-08-27: assessment 包 _assessment_wrap — 评估结束即发 quality_check
    # completed（main_graph quality 节点 mode 改 'start'，见 astroquery_ai/main_graph.py）
    graph.add_node(NODE_ASSESSMENT, _assessment_wrap(build_assessment_graph().compile()))
    graph.add_node(NODE_NORMALIZATION, _flow_wrap("normalization", "clean", build_normalization_graph().compile()))
    graph.add_node(NODE_CONFLICT, _flow_wrap("conflict", "clean", build_conflict_graph().compile()))
    graph.add_node(NODE_EXPORT, _clean_entry_wrap(_flow_wrap("export", "deliver", build_export_graph().compile())))
    graph.add_node(NODE_INSIGHTS, _pipeline_exit_wrap(_deliver_entry_wrap(_flow_wrap("insights", "deliver", build_insights_graph().compile()))))  # V3.4
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
