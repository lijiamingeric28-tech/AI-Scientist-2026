"""
routers.py — Workflow Orchestration 控制层 (V3.1: 唯一路由来源)

职责划分:
  - Retry Controller: 检查 execution_status, 决定是否重入当前 SubGraph
  - Router:           只读 route_decision, 查 RouteMap 返回下一节点
  - Loop Controller:  维护 iteration_counter, 超限时覆写 route_decision=Export
  - Dispatch Node:    Assessment 后按 per_source_routes 分发
  - 所有路由函数集中于此, graph.py 只做节点装配 (图路由分离)

设计约束:
  - 不包含任何业务规则 (Quality Score / Confidence / Threshold)
  - 不调用 LLM / Tool
  - Loop Controller 只修改 workflow_state
  - Workflow History 追加不覆盖
"""

from __future__ import annotations

import datetime
from typing import Any

from .quality_state import QualityGraphState
from .utils.logger import get_logger

logger = get_logger(__name__)

# 常量 (V3.5: 从 quality_rules.yaml loop_control 单一入口加载, fallback 默认值)
def _load_loop_config(key: str, default: int) -> int:
    try:
        from .configs import load_yaml
        lc = (load_yaml("quality_rules.yaml") or {}).get("loop_control", {}) or {}
        return int(lc.get(key, default))
    except Exception:
        return default

MAX_ITERATIONS = _load_loop_config("max_iterations", 3)
MAX_RETRIES = _load_loop_config("max_retries", 3)
MAX_LOOP = _load_loop_config("max_loop", 3)  # C→B→C 最大循环次数

# 节点名称
NODE_ASSESSMENT = "assessment_graph"
NODE_NORMALIZATION = "normalization_graph"
NODE_CONFLICT = "conflict_graph"
NODE_EXPORT = "export_graph"
NODE_HUMAN_REVIEW = "human_review"
NODE_LOOP = "loop_controller"
NODE_DISPATCH = "dispatch"
NODE_PRE_NORMALIZATION = "pre_normalization"


# ==========================================================
# Helpers
# ==========================================================

def _wf(state: QualityGraphState) -> dict[str, Any]:
    return state.get("workflow_state", {})


def _make_history_entry(agent: str, stage: str, status: str,
                        reason: str, duration: float = 0.0) -> dict:
    """创建一条 WorkflowRecord, reducer 自动拼接列表。"""
    return {
        "agent": agent,
        "stage": stage,
        "status": status,
        "timestamp": datetime.datetime.now().isoformat(),
        "duration": duration,
        "reason": reason,
    }


def _append_history(wf: dict, agent: str, stage: str, status: str,
                    reason: str) -> list:
    """V3.1 fix: 只返回新增条目 — Reducer 会自动拼接, 避免重复累积。"""
    return [_make_history_entry(agent, stage, status, reason)]


# ==========================================================
# Part A: Retry Controller (职责单一: 只检查 execution_status)
# ==========================================================

# L-20 fix: check_retry 死代码已删除 (零调用点, 被 _make_stage_gate 取代)

def _make_stage_gate(node: str):
    """V3.3: 统一 Stage Gate 节点工厂 — 子图出口的 Retry 控制器。

    Gate 返回 route_decision:
      - "__retry__"  → 重入对应子图 (retry_by_node[node] 已递增)
      - "HumanReview" → 重试耗尽或 Failed
      - "Success"    → 继续下一阶段
    """
    def gate(state: QualityGraphState) -> dict[str, Any]:
        wf = _wf(state)
        status = wf.get("execution_status", "Success")
        retries = (wf.get("retry_by_node") or {}).get(node, 0)

        if status == "Retry":
            if retries < MAX_RETRIES:
                retry_by_node = dict(wf.get("retry_by_node") or {})
                retry_by_node[node] = retries + 1
                logger.warning("[Gate] %s Retry → re-enter (%d/%d)", node, retries + 1, MAX_RETRIES)
                return {"workflow_state": {
                    "retry_by_node": retry_by_node,
                    "route_decision": "__retry__",
                    "phase": node,
                    "execution_status": "Success",  # 清除 Retry, 避免重复触发
                }}
            logger.warning("[Gate] %s max retries → HumanReview", node)
            return {"workflow_state": {"route_decision": "HumanReview",
                                       "phase": "human_review"}}

        if status == "Failed":
            logger.warning("[Gate] %s Failed → HumanReview", node)
            return {"workflow_state": {"route_decision": "HumanReview",
                                       "phase": "human_review"}}

        # V3.5 fix: 子图返回 HumanReview 状态 → 显式路由人工审核
        if status == "HumanReview":
            logger.warning("[Gate] %s → HumanReview", node)
            return {"workflow_state": {"route_decision": "HumanReview",
                                       "phase": "human_review"}}

        # V4 fix: 不再覆写业务 route_decision (validation/report agent 已写入
        # "Conflict"/"Export")。此前无条件覆写为 "Success", 导致 Normalization
        # 复检发现的冲突被抹掉, loop_controller 落入 else → Export (B→C 死代码)。
        # H2 fix: 记录来源 (loop_source) — loop_controller 据此区分读
        # resolution_report (C 本轮) 还是 wf.route_decision (B 本轮)
        return {"workflow_state": {"phase": node, "execution_status": "Success",
                                   "loop_source": node}}

    return gate


# ==========================================================
# Part B: Router (职责单一: 只读 state 查路由)
# ==========================================================

def route_after_dispatch(state: QualityGraphState) -> str:
    """
    Dispatch 分发逻辑 (V3.3: 基于 pending_sources 队列).

      - 有 HumanReview 待处理 → HumanReview (优先, 修复混合来源丢失)
      - 有 Normalization 待处理 → Normalization
      - 有 Conflict 待处理 → Conflict
      - 队列全空 → Export
    """
    wf = _wf(state)

    # G11 M-03 fix: dispatch 保留的失败/HR 信号 → 直达 HumanReview
    # (失败时 per_source_routes 可能为空, 队列判空会漏, 不能只依赖 pending_sources)
    if wf.get("route_decision") == "HumanReview" or wf.get("execution_status") == "Failed":
        return NODE_HUMAN_REVIEW

    pending = wf.get("pending_sources", {})

    if pending.get("HumanReview"):
        return NODE_HUMAN_REVIEW  # V3.3: 人工来源优先, 不被 Norm/Conflict 跳过
    if pending.get("Normalization"):
        return NODE_NORMALIZATION
    if pending.get("Conflict"):
        return NODE_CONFLICT
    return NODE_EXPORT


def route_after_loop(state: QualityGraphState) -> str:
    """
    LoopController 统一路由 (V3.2: 只读 loop_controller_node 写入的 next_route).

    loop_controller_node 是唯一决定 next_route 的地方 (状态机):
      - 从 Normalization 来 (_from_conflict=True, C→B 后): next_route=Conflict, 并清除 _from_conflict
      - 从 Normalization 来 (_from_conflict=False, A→B 后): 读 wf.route_decision
        (Conflict→B→C, Export→A→B→D)
      - 从 Conflict 来: 读最新 resolution_report.route_decision
        (Normalization→C→B, Export→C→D, HumanReview→C→E)
    """
    wf = _wf(state)
    next_route = wf.get("next_route", "")

    # 强制 Export 优先 — LoopController 超限必须生效 (V3.3 显式字段)
    if wf.get("iteration_counter", 0) >= MAX_ITERATIONS or wf.get("force_export", False):
        logger.warning("[Router] Loop limit reached → force Export")
        return NODE_EXPORT

    if next_route == "Conflict":
        return NODE_CONFLICT
    elif next_route == "Normalization":
        return NODE_PRE_NORMALIZATION
    elif next_route == "HumanReview":
        return NODE_HUMAN_REVIEW
    else:
        logger.info("[Router] Loop → Export (next_route=%s)", next_route or "export")
        return NODE_EXPORT


def route_after_human_review(state: QualityGraphState) -> str:
    """
    Human Review 完成后 (V3.3):
      - "Normalization" → Normalization (E→B)
      - "Assessment" → Assessment (E→A)
      - 其他 (HR 无待审核项/完成) → 复用 dispatch 队列逻辑, 继续处理剩余来源
        (pending_sources["HumanReview"] 已由 HR agent 清空)
    """
    wf = _wf(state)
    decision = wf.get("route_decision", "")
    if decision == "Normalization":
        return NODE_NORMALIZATION
    elif decision == "Assessment":
        return NODE_ASSESSMENT
    return route_after_dispatch(state)


# ==========================================================
# Part C: 控制节点 (供 graph.py 装配)
# ==========================================================

def dispatch_node(state: QualityGraphState) -> dict[str, Any]:
    """Assessment 后分发: 统计 per_source_routes + 清理旧报告。"""
    quality = state.get("report_state", {}).get("quality", {}) or {}
    per_source_routes = quality.get("per_source_routes", {})
    wf = _wf(state)

    # G11 M-03 fix: Assessment Failed/HR 信号在 dispatch 边界不丢失。
    # gate 失败分支 (Failed/Retry 耗尽/HumanReview 状态) 只写
    # route_decision="HumanReview" 不清 execution_status, 本检查必须在
    # 下方清空 route_decision 之前; 正常 per-source HumanReview
    # (execution_status=Success, 路由已进队列) 不进此分支。
    human_signal = (wf.get("route_decision") == "HumanReview"
                    or wf.get("execution_status") == "Failed")

    # V3.3: 初始化来源处理队列 (pending_sources)
    pending = {"Normalization": [], "Conflict": [], "Export": [], "HumanReview": []}
    for sid, route in per_source_routes.items():
        pending.setdefault(route, []).append(sid)

    if human_signal:
        # M-03: 失败信号 → Assessment 结果不可信, 全部来源并入 HumanReview 队列
        pending["HumanReview"] = (pending["HumanReview"] + pending["Normalization"]
                                  + pending["Conflict"] + pending["Export"])
        pending["Normalization"] = []
        pending["Conflict"] = []
        pending["Export"] = []

    logger.info("[Dispatch] Norm=%d Conflict=%d Export=%d Human=%d",
                len(pending["Normalization"]), len(pending["Conflict"]),
                len(pending["Export"]), len(pending["HumanReview"]))

    now = datetime.datetime.now().isoformat()

    # V3.2 fix: 真正清除旧报告 — reducer 对 None 会覆盖旧 dict,
    # 显式置 None 使 E→A 重新评估后 conflict/normalization/export 不再残留
    return {
        "report_state": {
            "quality": quality if quality else None,
            "conflict": None,      # 清除旧 Conflict 报告
            "normalization": None, # 清除旧 Normalization 报告
            "export": None,        # 清除旧 Export 报告
        },
        "workflow_state": {
            "current_node": NODE_DISPATCH, "execution_status": "Success",
            # V3.3: 显式阶段 + 队列
            "phase": "human_review" if human_signal else "dispatch",
            "pending_sources": pending,
            "completed_sources": [],
            # V3.5 fix: E→A 重新评估时重置全部计数器 (防止继承上一轮计数提前 Export/HumanReview)
            # V4 fix: 清空 route_decision — dispatch 是路由边界, 防止 E→A 后
            # HumanReview 写入的 "Normalization" 残留被 loop_controller 误读为 C→B
            # M-03 fix: 失败信号时保留 "HumanReview", 供 route_after_dispatch 路由
            "route_decision": "HumanReview" if human_signal else "",
            "loop_round": 0,
            "from_conflict": False,
            "next_route": "",
            "force_export": False,
            "iteration_counter": 0,
            # M-02 fix: 置 None 走 _merge_dict 覆盖分支 — {} 会被递归合并
            # (merge({retry_by_node:{A:3}}, {retry_by_node:{}}) → 旧计数残留,
            #  E→B 后重试预算不归零导致 HR⇄B 循环), 所有读取点均有 `or {}` 兜底
            "retry_by_node": None,
            "retry_counter": 0,
            "workflow_history": [{"agent": "Dispatch", "stage": "Routing",
                "status": "Success", "timestamp": now, "duration": 0.0,
                "reason": f"Norm={len(pending['Normalization'])} Conflict={len(pending['Conflict'])} Export={len(pending['Export'])} Human={len(pending['HumanReview'])}"}],
        },
    }


def before_normalization_node(state: QualityGraphState) -> dict[str, Any]:
    """Conflict → Normalization 时设置 C→B 标记 + 递增循环轮次 (V3.3 显式字段)。"""
    wf = _wf(state)
    loop = wf.get("loop_round", 0)
    return {"workflow_state": {
        "from_conflict": True,
        "loop_round": loop + 1,
        "phase": "normalization",
        "current_node": NODE_PRE_NORMALIZATION,
    }}


def loop_controller_node(state: QualityGraphState) -> dict[str, Any]:
    """
    Loop Controller — 路由状态机 (V3.2: 唯一决定 next_route 的地方).

    每次进入 (Normalization 或 Conflict 完成后):
      1. 递增 iteration_counter
      2. 超过 MAX_ITERATIONS → _force_export=True
      3. 决定 _next_route (供 route_after_loop 读取):
         - 从 Normalization 来 (_from_conflict=True, C→B 后):
             → Conflict (回 C 重新验证), 并清除 _from_conflict
         - 从 Normalization 来 (_from_conflict=False, A→B 后):
             wf.route_decision: Conflict → Conflict (B→C) / 其他 → Export (A→B→D)
         - 从 Conflict 来 (_from_conflict=False):
             读最新 resolution_report.route_decision:
             Normalization → pre_normalization (C→B) / Export → Export (C→D)
             / HumanReview → HumanReview (C→E)
      4. 追加 Workflow History

    只修改 workflow_state，不触碰 data/report/output。
    """
    wf = dict(_wf(state))
    iteration = wf.get("iteration_counter", 0)
    from_conflict = wf.get("from_conflict", False)
    loop_count = wf.get("loop_round", 0)

    next_iteration = iteration + 1

    # V3.3: 标记完成 — 从 pending_sources 移除已处理来源
    pending = {k: list(v) for k, v in (wf.get("pending_sources") or {}).items()}
    completed = list(wf.get("completed_sources", []))
    src_plan = (state.get("report_state", {}).get("normalization") or {}).get("source_plan", {})
    done_norm = list(src_plan.get("sources_to_normalize", {}).keys()) if src_plan else []
    conf = state.get("report_state", {}).get("conflict") or {}
    done_conf = (conf.get("aggregation") or {}).get("involved_sources", []) or []
    if done_norm:
        pending["Normalization"] = [s for s in pending.get("Normalization", []) if s not in done_norm]
        completed = list(dict.fromkeys(completed + done_norm))
    if done_conf:
        pending["Conflict"] = [s for s in pending.get("Conflict", []) if s not in done_conf]
        completed = list(dict.fromkeys(completed + done_conf))

    # 超限 → 强制终止
    if next_iteration >= MAX_ITERATIONS:
        logger.warning("[Loop] Max iterations (%d/%d) → force Export",
                       next_iteration, MAX_ITERATIONS)
        return {
            "workflow_state": {
                "iteration_counter": next_iteration,
                "route_decision": "Export",
                "next_route": "Export",
                "force_export": True,
                "from_conflict": False,
                "phase": "export",
                "pending_sources": pending,
                "completed_sources": completed,
                "current_node": NODE_LOOP,
                "retry_counter": 0,
                "execution_status": "Success",
                "workflow_history": _append_history(
                    wf, "LoopController", "LoopCheck", "Success",
                    f"Max iterations ({next_iteration}/{MAX_ITERATIONS}) → forced Export",
                ),
            },
        }

    # ── 状态机: 决定 next_route (V3.3 显式字段) ──
    if from_conflict:
        # 来源: C→B (Conflict 要求 Normalization 执行修改)
        # M2 fix: 复检无冲突 (needs_conflict_analysis=False) → 直接 Export (C→B→D),
        # 不再无条件回 Conflict 制造轮次 (与 H3 数据源修复配合干净收敛)
        norm_validation = ((state.get("report_state", {}).get("normalization") or {})
                           .get("validation", {}) or {})
        if not norm_validation.get("needs_conflict_analysis", True):
            logger.info("[Loop] C→B 复检无冲突 → Export (C→B→D)")
            next_route, _force, _phase = "Export", False, "export"
        elif loop_count > MAX_LOOP:
            logger.warning("[Loop] C→B max loops (%d) → force Export", MAX_LOOP)
            next_route, _force, _phase = "Export", True, "export"
        else:
            logger.info("[Loop] C→B done → back to Conflict (loop %d)", loop_count)
            next_route, _force, _phase = "Conflict", False, "conflict"
        from_conflict_flag = False  # 清除标记
    else:
        # 来源: A→B (Normalization) 或 Conflict 完成
        conflict = state.get("report_state", {}).get("conflict") or {}
        report = conflict.get("resolution_report", {})
        # H2 fix: 按 gate 记录的 loop_source 读"本轮"决策 —
        #   从 Conflict 来 → resolution_report 是 C 本轮决策
        #   从 Normalization 来 → wf.route_decision 是 B 本轮 report_agent 新写,
        #     陈旧 resolution_report (如 HumanReview 残留) 不再覆盖新决策
        if wf.get("loop_source") == NODE_CONFLICT:
            route = report.get("route_decision", wf.get("route_decision", "Export"))
        else:
            route = wf.get("route_decision", "Export")

        if route == "Normalization":
            # Conflict 要求规范化 → C→B (pre_normalization 递增 loop_round)
            if loop_count + 1 > MAX_LOOP:
                logger.warning("[Loop] C→B max loops (%d) → force Export", MAX_LOOP)
                next_route, _force, _phase = "Export", True, "export"
            else:
                logger.info("[Loop] C→B: Need normalization (loop %d/%d)", loop_count + 1, MAX_LOOP)
                next_route, _force, _phase = "Normalization", False, "normalization"
        elif route == "Conflict":
            # Normalization 检测到冲突 → B→C
            if loop_count + 1 > MAX_LOOP:
                logger.warning("[Loop] B→C max loops (%d) → force Export", MAX_LOOP)
                next_route, _force, _phase = "Export", True, "export"
            else:
                logger.info("[Loop] B→C: Normalization found conflict (loop %d/%d)", loop_count + 1, MAX_LOOP)
                next_route, _force, _phase = "Conflict", False, "conflict"
        elif route == "HumanReview":
            next_route, _force, _phase = "HumanReview", False, "human_review"
        else:
            logger.info("[Loop] → Export (route=%s)", route)
            next_route, _force, _phase = "Export", False, "export"
        from_conflict_flag = from_conflict  # 非 C→B 完成, 保持原值 (通常 False)

    return {
        "workflow_state": {
            "iteration_counter": next_iteration,
            "route_decision": next_route,
            "next_route": next_route,
            "force_export": _force,
            "from_conflict": from_conflict_flag,
            "phase": _phase,
            "pending_sources": pending,
            "completed_sources": completed,
            "current_node": NODE_LOOP,
            "retry_counter": 0,
            "execution_status": "Success",
            "workflow_history": _append_history(
                wf, "LoopController", "LoopCheck", "Success",
                f"Iteration {next_iteration}/{MAX_ITERATIONS} → next={next_route}",
            ),
        },
    }
