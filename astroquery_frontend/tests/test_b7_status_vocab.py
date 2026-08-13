"""B7 H-01 回归测试：失败状态词表统一（D2/D8 状态映射表，终态为 error）。

覆盖：
- executor 异常路径终态写 'error'（旧词表 'failed' 不再写入）且 _finish 不覆写
- main.py API 面对存量 'failed' 记录归一为 'error'（列表/详情/state）
- list_tasks status='error' 筛选同时匹配旧词表 'failed'（词表别名）
- 前端 status.jsx / Sidebar 源码静态断言（error 主词表 + failed 别名）

全 mock 离线：不设 LLM_CASSETTE / LLM_RECORD_MODE，不启动后端，零网络。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.event_bus import EventBus
from web.task_store import TaskStore


# ══════════════════════════════════════════════════════
# TestClient fixture（沿用 tests/test_web_offline.py 的 M-07 模式：
# tmp_path + monkeypatch + 重建单例 + 回收 executor 线程）
# ══════════════════════════════════════════════════════

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from web import main as m

    monkeypatch.setattr(m, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(m, "OUTPUT_DIR", tmp_path / "output")
    m.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    m.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(m, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(m, "CHECKPOINT_PATH", tmp_path / "cp.sqlite")
    m.store = TaskStore(m.DB_PATH)
    m.bus = EventBus(m.store)
    from web.executor import Executor
    m.executor = Executor(m.bus, m.store, str(m.CHECKPOINT_PATH), str(m.OUTPUT_DIR))
    from events import configure as configure_emitter
    configure_emitter(m.bus.publish)
    from web import log_bridge
    log_bridge.install(m.bus)
    yield TestClient(m.app)
    m.executor.stop()


def _wait_terminal(store, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline and store.get_task(task_id)["status"] in ("queued", "running"):
        time.sleep(0.05)


# ── H-01: executor 终态 error ──

def test_executor_failure_terminal_status_is_error(tmp_path, monkeypatch):
    """H-01 锚点：执行线程异常 → DB 终态 'error'（契约 D8 状态映射表；
    旧词表 'failed' 不再写入），且 _finish 不把 error 覆写为 completed。"""
    from web.executor import Executor

    def boom_runner(**kwargs):
        raise RuntimeError("boom offline")

    monkeypatch.setattr("web.executor.run_task_streaming", boom_runner)
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex_obj = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        t = store.create_task("M31 的距离")
        ex_obj.submit(t["task_id"], "M31 的距离", [])
        _wait_terminal(store, t["task_id"])
        rec = store.get_task(t["task_id"])
        assert rec["status"] == "error", f"失败终态应为 error，实为 {rec['status']!r}"
        evs = store.get_events(t["task_id"])
        types = {e["type"] for e in evs}
        assert "task_failed" in types
        errs = [e for e in evs if e["type"] == "error"]
        assert errs and "boom offline" in errs[-1].get("message", "")
    finally:
        ex_obj.stop()


# ── H-01: main.py 存量 failed 归一 ──

def test_main_normalizes_legacy_failed(client):
    """H-01 锚点：存量 'failed' 记录在 API 面（列表/详情/state）归一为 'error'，
    前端无需感知旧词表。"""
    from web import main as m
    t = m.store.create_task("M31 的距离")
    m.store.update_task(t["task_id"], status="failed", completed_at="2026-01-01T00:00:00+00:00")
    items = client.get("/api/tasks").json()["items"]
    assert len(items) == 1 and items[0]["task_id"] == t["task_id"]
    assert items[0]["status"] == "error"
    d = client.get(f"/api/tasks/{t['task_id']}").json()
    assert d["status"] == "error"
    st = client.get(f"/api/tasks/{t['task_id']}/state").json()
    assert st["task"]["status"] == "error"


def test_list_tasks_error_filter_matches_failed(tmp_path):
    """H-01 锚点（store 级）：status='error' 筛选同时匹配旧词表 'failed' 存量记录。"""
    store = TaskStore(tmp_path / "t.db")
    a = store.create_task("q1")
    b = store.create_task("q2")
    c = store.create_task("q3")
    store.update_task(a["task_id"], status="error", completed_at="2026-01-01T00:00:00+00:00")
    store.update_task(b["task_id"], status="failed", completed_at="2026-01-01T00:00:00+00:00")
    store.update_task(c["task_id"], status="completed", completed_at="2026-01-01T00:00:00+00:00")
    got = store.list_tasks(status="error")["items"]
    assert {r["task_id"] for r in got} == {a["task_id"], b["task_id"]}
    got_c = store.list_tasks(status="completed")["items"]
    assert [r["task_id"] for r in got_c] == [c["task_id"]]


# ── H-01: 前端词表静态锚点（无前端测试基建，源码断言） ──

def test_frontend_status_vocab_error():
    """H-01 锚点（前端源码静态断言）：status.jsx 主词表 error→失败 + 旧词表 failed
    别名；Sidebar 失败筛选档按 error 匹配并兼容 failed（重试按钮同理）。"""
    root = Path(__file__).resolve().parent.parent
    status_src = (root / "frontend/src/components/status.jsx").read_text(encoding="utf-8")
    assert "error: '失败'" in status_src
    assert "failed: '失败'" in status_src
    assert "failed: 'var(--status-error)'" in status_src
    side = (root / "frontend/src/components/layout/Sidebar.jsx").read_text(encoding="utf-8")
    assert "filter === 'error' && t.status === 'failed'" in side
