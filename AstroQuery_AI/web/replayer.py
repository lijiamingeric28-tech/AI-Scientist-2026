"""事件级重放（2026-08-27）——演示回放机制核心。

原理：真实运行的每个 SSE 事件已落库（events 表，seq 自增 + ts 时间戳）。
演示 = 新建"回放任务"，把源任务的已落库事件按压缩时间节奏重新 emit 一遍：
走既有 EventBus/SSE 通道，前端零解析改动，行为逐事件一致（就是真实事件本身），
不存在 cassette 重跑（LLM 再次推理 + VLM 宽松匹配 + 顺序消费）的级联错位问题。

与 VCR 回放（executor.py LLM_CASSETTE 路径）完全独立：本文件不碰网络、不碰
LLM、不依赖 cassette；旧路径保留不动（demo 不再使用，回归测试仍覆盖）。

节奏：
- 源事件 ts 存在（新真实任务）→ 相邻间隔 = clamp(Δts / speed, CLAMP_MIN, CLAMP_MAX)
- 源事件 ts 为 NULL（老任务）→ 按事件类型默认间隔（DEFAULT_INTERVAL）
- 澄清事件：emit 后调用 get_answer 真实等待用户回答（复用 _AnswerSlot，
  超时 → fatal error + task_cancelled + slot.cancel，由 executor 闭包实现）
- 取消：睡眠按 50ms 分片，中途检查 should_cancel（响应 ≤100ms）

跳过清单（生命周期事件由回放任务自身承担，不转发源记录）：
- task_queued / task_started / task_title_ready / task_completed /
  task_cancelled / task_failed / clarification_answered（live resume 会重新落库）
- message：不即时转发，仅记录最后一条 ai 总结原文 → executor 在自身
  task_completed 之后补发（与真实时序同构：message 紧随 task_completed，
  前端 awaitSummaryRef 命中即关 SSE）

注意：EventBus.publish 会把 {"seq": seq, **event} 落库——重放事件必须剥离
seq/ts/task_id 等元数据键，否则旧 seq 覆盖新 seq（前端 seq 幂等去重崩溃）。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

# 不转发的源事件类型（生命周期由回放任务自身承担 / 澄清回答 live 重新产生）
REPLAY_SKIP = frozenset({
    "task_queued", "task_started", "task_completed",
    "task_cancelled", "task_failed", "task_title_ready", "clarification_answered",
})

# 源事件无 ts（老任务）时的类型默认间隔（秒）
DEFAULT_INTERVAL = {
    "log": 0.04,
    "step_progress": 0.04,
    "error": 0.15,
    "agent_started": 0.15,
    "agent_completed": 0.15,
    "stage_started": 0.15,
    "stage_completed": 0.15,
    "flow_started": 0.15,
    "flow_completed": 0.15,
    "message": 0.15,
}

# 节奏钳制（2026-08-27 用户决策）：下限保留 20ms（防连发 log 段 SSE 洪泛
# 丢事件——演示日志滚动需完整）；上限取消——长停顿（LLM/检索等）真实等比
# 呈现（20.5min 真实任务 → 2.0min 重放，最长停顿 74s → 7.4s 静观）。
CLAMP_MIN = 0.020
CLAMP_MAX = None  # 去除上限：真实间隔 / speed 即真实等待

# 睡眠分片（取消响应粒度）
_SLEEP_SLICE = 0.05


def interval_between(prev_ts: Optional[float], cur_ts: Optional[float],
                     cur_type: str, speed: float) -> float:
    """相邻事件的重放间隔（纯函数，可单测）。

    - 任一侧 ts 缺失 → 类型默认间隔
    - ts 齐全 → max((cur_ts - prev_ts) / speed, CLAMP_MIN)（无上限：真实等比）
    """
    if prev_ts is None or cur_ts is None:
        return DEFAULT_INTERVAL.get(cur_type, 0.15)
    gap = (cur_ts - prev_ts) / max(speed, 1.0)
    return max(gap, CLAMP_MIN)


def _sleep_checked(duration: float, sleep: Callable[[float], None],
                   should_cancel: Optional[Callable[[], bool]]) -> bool:
    """分片睡眠（50ms），中途检查取消；返回 True 表示应停止（被取消）。"""
    remaining = duration
    while remaining > 0:
        if should_cancel and should_cancel():
            return True
        step = min(remaining, _SLEEP_SLICE)
        sleep(step)
        remaining -= step
    return False


def run_replay(bus: Any, store: Any, task_id: str, replay_of: str,
               speed: float = 10,
               get_answer: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None,
               should_cancel: Optional[Callable[[], bool]] = None,
               sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """把源任务的已落库事件按压缩节奏重放到 task_id（回放任务）。

    Args:
        bus: EventBus（publish 落库 + SSE 推送）
        store: TaskStore（读源事件与源 state_json）
        task_id: 回放任务 id
        replay_of: 源任务 id（调用方保证存在且 completed）
        speed: 压缩倍率（间隔 = Δts / speed）
        get_answer: 澄清等待回调（executor 闭包；None 时澄清事件立即继续）
        should_cancel: 取消检查（executor 闭包；None 时全程不检查）
        sleep: 睡眠函数（测试注入即时睡眠）

    Returns:
        {"cancelled": bool, "state_json_text": 源 state_json 原文（未取消时）,
         "summary": 源 ai 总结原文（未取消时，可能为 None）}
    """
    src = store.get_task(replay_of)
    if not src:
        return {"cancelled": True, "state_json_text": None, "summary": None}
    events: List[Dict[str, Any]] = store.get_events(replay_of, 0)

    prev_ts: Optional[float] = None
    summary: Optional[str] = None

    def _abort() -> Dict[str, Any]:
        return {"cancelled": True, "state_json_text": None, "summary": summary}

    for ev in events:
        if should_cancel and should_cancel():
            return _abort()
        etype = ev.get("type")
        if etype in REPLAY_SKIP:
            continue
        # 源 message 不即时转发：记录 ai 总结原文，收尾由 executor 补发
        if etype == "message":
            if ev.get("role") == "ai" and ev.get("content"):
                summary = ev.get("content")
            continue
        # P0-1：剥离元数据键——EventBus.publish 会注入新 seq；旧 seq/ts/task_id
        # 残留会覆盖新 seq（前端 seq 幂等去重崩溃）或污染 payload
        payload = {k: v for k, v in ev.items() if k not in ("seq", "ts", "task_id")}
        if etype == "clarification":
            bus.publish(task_id, payload)
            ans = get_answer(task_id, payload) if get_answer else None
            if ans is None or (should_cancel and should_cancel()):
                return _abort()  # 超时/取消：get_answer 闭包已发 fatal + task_cancelled
            prev_ts = ev.get("ts") or prev_ts
            continue
        wait = interval_between(prev_ts, ev.get("ts"), etype, speed)
        prev_ts = ev.get("ts") or prev_ts
        if _sleep_checked(wait, sleep, should_cancel):
            return _abort()
        bus.publish(task_id, payload)

    return {"cancelled": False, "state_json_text": src.get("state_json") or "{}",
            "summary": summary}
