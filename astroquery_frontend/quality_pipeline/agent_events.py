"""质量管线 agent 事件包装（模块 ③：agent_started/agent_completed，含 data_trace 增量）。

用法：子图构建时用 wrap_agent_node(label, agent.run) 包装节点函数：
    _planning_node = wrap_agent_node("PlanningAgent", _planning.run)

- stage_id 由调用方传入（前端 7 卡：assessment→quality_check / normalization|conflict→clean / export|insights→deliver）
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


def _traces_of(state: Dict[str, Any]) -> list:
    ds = state.get("data_state") or {}
    return ds.get("data_trace") or []


def _emit_agent(qid: str, stage_id: str, agent: str, status: str,
                duration: float = 0.0, traces: list = None,
                reason: str = None) -> None:
    ev: Dict[str, Any] = {"type": f"agent_{status}", "stage_id": stage_id, "agent": agent}
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
        _emit_agent(qid, stage_id, label, "started")
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
                        duration=time.time() - t0, traces=new_traces or None,
                        reason=reason)

    return wrapped
