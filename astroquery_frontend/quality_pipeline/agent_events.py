"""质量管线 agent 事件包装（模块 ③：agent_started/agent_completed，含 data_trace 增量）。

用法：子图构建时用 wrap_agent_node(label, agent.run) 包装节点函数：
    _planning_node = wrap_agent_node("PlanningAgent", _planning.run, "normalization")

- stage_id 由调用方传入（前端 7 卡：assessment→quality_check / normalization|conflict→clean / export|insights→deliver）
- **flow_id = subgraph（2026-08-27）**：agent 事件携带所属子图（assessment/normalization/
  conflict/export/insights）——前端清洗卡按轮次块嵌套归组的事实依据。此前 payload 只有
  stage_id（clean/deliver），normalization 与 conflict 的 agent 混在一起，前端只能靠名字猜。
- agent_completed 携带本轮新增的 data_trace（契约：修改轨迹附事件内，前端累积）
- 离线测试（未 configure）时 emit 为 no-op，子图行为零变化
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict

from events import emit

_STAGE_IDS = {
    "assessment": "quality_check",
    "normalization": "clean",
    "conflict": "clean",
    "export": "deliver",
    "insights": "deliver",
}


def _qid(state: Dict[str, Any]) -> str:
    ctx = state.get("context_state") or {}
    return str(ctx.get("query_id", ""))


def _round_of(state: Dict[str, Any]) -> int:
    """当前 loop_round（0-based）——flow 轮次同源（graph.py._flow_round）。
    agent 事件带 round，前端可把 agent 精确归到「第 N 轮」块（多轮循环场景）。"""
    wf = state.get("workflow_state") or {}
    return int(wf.get("loop_round", 0) or 0)


def _traces_of(state: Dict[str, Any]) -> list:
    ds = state.get("data_state") or {}
    return ds.get("data_trace") or []


def _emit_agent(qid: str, stage_id: str, agent: str, status: str,
                flow_id: str = "", round_: int = 0, duration: float = 0.0,
                traces: list = None, reason: str = None) -> None:
    ev: Dict[str, Any] = {"type": f"agent_{status}", "stage_id": stage_id, "agent": agent}
    # flow_id/round = 子图归属（normalization/conflict/… + loop 轮次）：
    # 清洗卡按「轮次块」嵌套归组的权威依据（2026-08-27）
    if flow_id:
        ev["flow_id"] = flow_id
    ev["round"] = round_
    if status == "completed":
        ev["duration"] = round(duration, 2)
        if traces:
            ev["traces"] = traces
        if reason:
            ev["reason"] = reason
    emit(qid, ev)


def wrap_agent_node(label: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]],
                    subgraph: str):
    """包装子图 agent 节点：发 agent_started/completed + data_trace 增量 + reason。"""
    stage_id = _STAGE_IDS.get(subgraph, subgraph)

    def wrapped(state: Dict[str, Any]) -> Dict[str, Any]:
        qid = _qid(state)
        traces_before = len(_traces_of(state))
        # P0-4：调用前记录 workflow_history 长度，调用后取新增条目 reason
        #（前端 L3 下钻的 agent 结论；此前 payload 无 reason 字段，前端永空）
        wf_before = len((state.get("workflow_state") or {}).get("workflow_history") or [])
        _emit_agent(qid, stage_id, label, "started", flow_id=subgraph, round_=_round_of(state))
        t0 = time.time()
        try:
            result = fn(state)
            return result
        finally:
            # 增量 traces：本轮新增的 data_trace 条目
            new_traces = _traces_of(result)[traces_before:] if isinstance(result, dict) else []
            reason = None
            if isinstance(result, dict):
                hist = (result.get("workflow_state") or {}).get("workflow_history") or []
                added = hist[wf_before:]
                if added and isinstance(added[-1], dict) and added[-1].get("reason"):
                    reason = str(added[-1]["reason"])[:300]
                elif new_traces:
                    reason = f"修改 {len(new_traces)} 条数据"
                elif subgraph == "assessment":
                    reason = "评估完成（只读检查，未修改数据）"
            _emit_agent(qid, stage_id, label, "completed",
                        flow_id=subgraph, round_=_round_of(state),
                        duration=time.time() - t0,
                        traces=new_traces or None, reason=reason)

    return wrapped
