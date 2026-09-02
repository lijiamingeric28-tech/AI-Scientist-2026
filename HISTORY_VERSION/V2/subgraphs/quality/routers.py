"""
routers.py — Workflow Orchestration 控制层

职责划分:
  - Retry Controller: 检查 execution_status, 决定是否重入当前 SubGraph
  - Router:           只读 route_decision, 查 RouteMap 返回下一节点
  - Loop Controller:  维护 iteration_counter, 超限时覆写 route_decision=Export

设计约束:
  - 不包含任何业务规则 (Quality Score / Confidence / Threshold)
  - 不调用 LLM / Tool
  - Loop Controller 只修改 workflow_state
  - Workflow History 追加不覆盖
"""

from __future__ import annotations

import datetime
from typing import Any

from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)

# 常量
MAX_ITERATIONS = 3
MAX_RETRIES = 3

# 节点名称
NODE_ASSESSMENT = "assessment_graph"
NODE_NORMALIZATION = "normalization_graph"
NODE_CONFLICT = "conflict_graph"
NODE_EXPORT = "export_graph"
NODE_HUMAN_REVIEW = "human_review"
NODE_LOOP = "loop_controller"


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


def _append_history(wf: dict, agent: str, stage: str, status: str, reason: str, duration: float = 0.0) -> list:
    """
    追加一条workflow history记录

    Args:
        wf: workflow_state字典
        agent: Agent名称
        stage: 阶段名称
        status: 状态
        reason: 原因
        duration: 持续时间

    Returns:
        更新后的workflow_history列表
    """
    history = list(wf.get("workflow_history", []))
    new_entry = _make_history_entry(agent, stage, status, reason, duration)
    history.append(new_entry)
    return history


# ==========================================================
# Part A: Retry Controller (职责单一: 只检查 execution_status)
# ==========================================================

def check_retry(state: QualityGraphState, current_subgraph: str) -> str | None:
    """
    纯 Retry 检查。不读 route_decision, 不做路由。

    Returns:
        current_subgraph  — 需要重试 (重入自身)
        NODE_HUMAN_REVIEW  — 重试耗尽或 Failed
        None              — 无需重试, 交给 Router
    """
    wf = _wf(state)
    status = wf.get("execution_status", "Success")
    retries = wf.get("retry_counter", 0)

    if status == "Retry":
        if retries < MAX_RETRIES:
            logger.warning("[Retry] %s (retry %d/%d)", current_subgraph, retries + 1, MAX_RETRIES)
            return current_subgraph
        else:
            logger.warning("[Retry] %s max retries (%d) → HumanReview", current_subgraph, MAX_RETRIES)
            return NODE_HUMAN_REVIEW

    if status == "Failed":
        logger.warning("[Retry] %s Failed → HumanReview", current_subgraph)
        return NODE_HUMAN_REVIEW

    return None


# ==========================================================
# Part B: Router (职责单一: 只读 route_decision 查表)
# ==========================================================

# 统一 Route Map: 所有空决策 → HumanReview
ASSESSMENT_ROUTE_MAP: dict[str, str] = {
    "Normalization": NODE_NORMALIZATION,
    "Conflict": NODE_CONFLICT,
    "Export": NODE_EXPORT,
    "HumanReview": NODE_HUMAN_REVIEW,
    "": NODE_HUMAN_REVIEW,
}

NORMALIZATION_ROUTE_MAP: dict[str, str] = {
    "Export": NODE_EXPORT,         # B→D: 清洗完成直接导出
    "Conflict": NODE_CONFLICT,     # B→C: 清洗后仍需冲突分析
    "HumanReview": NODE_HUMAN_REVIEW,
    "": NODE_EXPORT,                # 默认出口
}

CONFLICT_ROUTE_MAP: dict[str, str] = {
    "Normalization": NODE_NORMALIZATION,  # C→B: 需要执行清洗
    "Export": NODE_EXPORT,                # C→D: 冲突已解决
    "HumanReview": NODE_HUMAN_REVIEW,     # C→E: 无法裁决
    "": NODE_HUMAN_REVIEW,
}

# HumanReview 条件路由: 人工决策后可跳任意 SubGraph
HUMAN_REVIEW_ROUTE_MAP: dict[str, str] = {
    "Assessment": NODE_ASSESSMENT,
    "Normalization": NODE_NORMALIZATION,
    "Conflict": NODE_CONFLICT,
    "Export": NODE_EXPORT,
    "HumanReview": NODE_HUMAN_REVIEW,  # 未决策 → 停留在 HumanReview
    "": NODE_HUMAN_REVIEW,              # 空 → 停留
}


def _pure_route(decision: str, route_map: dict[str, str], source: str) -> str:
    """纯路由: 查表, 不判断业务。"""
    target = route_map.get(decision, NODE_HUMAN_REVIEW)
    logger.info("[Router] %s → %s (decision=%s)", source, target,
                decision if decision else "(empty)")
    return target


# ==========================================================
# Part C: 对外路由函数 (Retry → Router 串联)
# ==========================================================

def route_after_assessment(state: QualityGraphState) -> str:
    retry = check_retry(state, NODE_ASSESSMENT)
    if retry:
        return retry
    return _pure_route(_wf(state).get("route_decision", ""),
                       ASSESSMENT_ROUTE_MAP, "Assessment")


def route_after_normalization(state: QualityGraphState) -> str:
    retry = check_retry(state, NODE_NORMALIZATION)
    if retry:
        return retry
    return _pure_route(_wf(state).get("route_decision", ""),
                       NORMALIZATION_ROUTE_MAP, "Normalization")


def route_after_conflict(state: QualityGraphState) -> str:
    retry = check_retry(state, NODE_CONFLICT)
    if retry:
        return retry
    return _pure_route(_wf(state).get("route_decision", ""),
                       CONFLICT_ROUTE_MAP, "Conflict")


def route_after_human_review(state: QualityGraphState) -> str:
    """
    HumanReview 条件路由。
    默认停留在 HumanReview (保守策略: 无决策不继续)。
    """
    wf = _wf(state)
    decision = wf.get("route_decision", "")
    target = HUMAN_REVIEW_ROUTE_MAP.get(decision, NODE_HUMAN_REVIEW)
    logger.info("[Router] HumanReview → %s (decision=%s)", target, decision)
    return target


# ==========================================================
# Part D: Loop Controller (职责单一: 只维护 iteration_counter)
# ==========================================================

def loop_controller_node(state: QualityGraphState) -> dict[str, Any]:
    """
    Loop Controller — 管理 Normalization↔Conflict 循环。

    每次进入:
      1. 递增 iteration_counter (写回 State)
      2. 超过 MAX_ITERATIONS → 覆写 route_decision="Export"
      3. 追加 Workflow History (不覆盖已有记录)

    只修改 workflow_state，不触碰 data/report/output。
    """
    wf = dict(state.get("workflow_state", {}))
    iteration = wf.get("iteration_counter", 0)
    decision = wf.get("route_decision", "")

    # ── 关键修复: 递增计数器 ──
    next_iteration = iteration + 1

    logger.info("[Loop] iteration %d/%d, current decision=%s",
                next_iteration, MAX_ITERATIONS, decision)

    # ── 超限 → 强制终止 ──
    if next_iteration >= MAX_ITERATIONS:
        logger.warning("[Loop] Max iterations (%d/%d) → force Export",
                       next_iteration, MAX_ITERATIONS)
        return {
            "workflow_state": {
                "iteration_counter": next_iteration,
                "route_decision": "Export",
                "current_node": "loop_controller",
                "retry_counter": 0,
                "execution_status": "Success",
                "workflow_history": _append_history(
                    wf, "LoopController", "LoopCheck", "Success",
                    f"Max iterations ({next_iteration}/{MAX_ITERATIONS}) → forced Export",
                ),
            },
        }

    # ── 未超限 → 继续 ──
    return {
        "workflow_state": {
            "iteration_counter": next_iteration,
            "current_node": "loop_controller",
            "retry_counter": 0,
            "execution_status": "Success",
            "workflow_history": _append_history(
                wf, "LoopController", "LoopCheck", "Success",
                f"Iteration {next_iteration}/{MAX_ITERATIONS}, continuing with {decision}",
            ),
        },
    }
