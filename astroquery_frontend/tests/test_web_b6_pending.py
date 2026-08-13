"""批次 B6「pending/澄清生命周期」后端锚点（H-02 / M-23 的后端可测部分）。

前端侧修复（usePipeline/ClarificationCard/StageCard）由 node 语法检查 + 门禁
npm run build 验证；这里锁定前端消费所依赖的后端事件契约：
- H-02: 澄清超时 → error(fatal, D10-3 文案) 先于 task_cancelled 到达
  （前端 fatal 分支把 ev.message 追加为 AI 消息，task_cancelled 分支清理 pending）
- M-23: error warn 级事件（含 stage_id）经 bus→store 传输字段完整
  （前端消费侧依赖 level/node/message/stage_id）

fixture 模式沿用 tests/test_web_offline.py：tmp_path + TaskStore/EventBus +
monkeypatch 假图，全 mock 零 LLM/网络。
"""

from __future__ import annotations

import time
from typing_extensions import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from web.event_bus import EventBus
from web.task_store import TaskStore


class _FakeState(TypedDict, total=False):
    turns: int


def _fake_single_interrupt_graph(checkpointer=None):
    """单次澄清中断，get_answer 永不恢复（超时锚点用，同 test_web_offline）。"""

    def node(state: _FakeState):
        interrupt({"type": "ask_properties", "question": "要哪些性质？"})
        return {"turns": 1}

    g = StateGraph(_FakeState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def test_timeout_fatal_error_precedes_cancel(tmp_path, monkeypatch):
    """H-02 后端锚点：澄清超时 → error(fatal, D10-3 文案) 先于 task_cancelled 到达。

    前端 H-02 修复按此顺序依赖：fatal error 分支先收到 ev.message（追加为 AI
    消息）并清理 pending（输入栏恢复），随后 task_cancelled 幂等收尾。
    """
    from web.executor import Executor

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    monkeypatch.setattr("web.executor.CLARIFICATION_TIMEOUT", 0.4)
    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_single_interrupt_graph(checkpointer),
    )
    ex = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        t = store.create_task("q")
        ex.submit(t["task_id"], "q", [])
        deadline = time.time() + 8
        while time.time() < deadline and store.get_task(t["task_id"])["status"] in ("queued", "running"):
            time.sleep(0.05)
        assert store.get_task(t["task_id"])["status"] == "cancelled"
        events = store.get_events(t["task_id"])
        fatals = [e for e in events if e["type"] == "error" and e["level"] == "fatal"]
        cancels = [e for e in events if e["type"] == "task_cancelled"]
        assert fatals and cancels
        assert "澄清超时" in fatals[0]["message"], "D10-3 文案缺失（前端据此显示显式提示）"
        assert fatals[0]["seq"] < cancels[0]["seq"], "fatal error 应先于 task_cancelled"
    finally:
        ex.stop()


def test_error_warn_event_roundtrip_preserves_fields(tmp_path):
    """M-23 后端锚点：error warn 级事件经 bus→store 传输字段完整。

    前端消费侧（usePipeline warn 分支累积 stage.errors → StageCard 红态+错误行）
    依赖 level / node / message / stage_id 四字段；bus.error 默认 level='warn'。
    """
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")
    # ① bus.error 便捷发射（默认 warn）
    bus.error(t["task_id"], "vlm_extractor", "3 篇论文 VLM 提取降级", level="warn")
    # ② 阶段降级生产者形态：带 stage_id 的 warn 事件（节点降级处 emit）
    bus.emit(t["task_id"], "error", node="database_query", message="星表查询降级为缓存", level="warn", stage_id="retrieval")
    evs = store.get_events(t["task_id"])
    assert len(evs) == 2
    w1, w2 = evs
    assert (w1["type"], w1["level"]) == ("error", "warn")
    assert w1["node"] == "vlm_extractor" and "降级" in w1["message"]
    assert w2["stage_id"] == "retrieval" and w2["node"] == "database_query"
    assert (w2["type"], w2["level"]) == ("error", "warn")
