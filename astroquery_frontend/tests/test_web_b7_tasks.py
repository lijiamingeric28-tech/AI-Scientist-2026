"""B7 任务标识契约回归测试：CR-03（task_id 键名）/ M-08（列表列裁剪）/ L-01（标题事件归属）。

覆盖：
- list_tasks 显式列裁剪：items 仅 {task_id,query,title,status,created_at,completed_at}，
  不返回 state_json/pdf_paths（M-08），键名为 task_id 无 id 兼容键（CR-03）
- GET /api/tasks 与 /api/tasks/{id} 键名契约（CR-03）
- executor task_title_ready 事件携带 task_id + title（L-01 后端侧绿测）
- test_title_event_carries_task_id：L-01 前端归属链契约期望登记（xfail strict=False）

全 mock 离线：不设 LLM_CASSETTE / LLM_RECORD_MODE，不启动后端，零网络。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from web.event_bus import EventBus
from web.task_store import TaskStore


# ══════════════════════════════════════════════════════
# TestClient fixture（沿用 tests/test_web_offline.py 的 M-07 模式）
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


# ── M-08 + CR-03: 列表契约形状 ──

def test_list_tasks_contract_shape_pruned(tmp_path):
    """M-08 锚点：列表显式列裁剪——不返回 state_json/pdf_paths（大字段走 get_task
    /state）；CR-03 锚点：items 键名为 task_id（契约 D8-4），无 id 兼容键。"""
    store = TaskStore(tmp_path / "t.db")
    t = store.create_task("M31 的距离", pdf_paths=["/x/a.pdf"])
    store.update_task(
        t["task_id"], status="completed", completed_at="2026-01-01T00:00:00+00:00",
        state_json=json.dumps({"big": "x" * 1000}),
    )
    items = store.list_tasks(limit=50)["items"]
    assert len(items) == 1
    item = items[0]
    assert item["task_id"] == t["task_id"]
    assert "id" not in item                      # CR-03：契约 D8-4 键名，无兼容键
    assert "state_json" not in item              # M-08：列表不携带大字段
    assert "pdf_paths" not in item
    # 2026-09-01: 列表轻量统计列（侧边栏「N 条记录 · M 个来源」；仍无大字段）
    assert set(item) == {"task_id", "query", "title", "status", "created_at", "completed_at",
                         "replay_of", "record_count", "source_count"}
    assert item["record_count"] == 0
    assert item["source_count"] == 0
    # get_task（详情 /state 侧）仍完整返回大字段
    full = store.get_task(t["task_id"])
    assert full["pdf_paths"] == ["/x/a.pdf"]
    assert "big" in (full.get("state_json") or "")


def test_list_endpoint_task_id_contract(client):
    """CR-03 锚点：GET /api/tasks 与 GET /api/tasks/{id} 键名为 task_id。"""
    from web import main as m
    t = m.store.create_task("M31 的距离")
    r = client.get("/api/tasks")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["task_id"] == t["task_id"]
    assert "id" not in item
    d = client.get(f"/api/tasks/{t['task_id']}").json()
    assert d["task_id"] == t["task_id"]


# ── L-01: task_title_ready 携带 task_id（后端侧） ──

def test_executor_title_event_carries_task_id(tmp_path):
    """L-01 后端锚点（绿测）：task_title_ready 事件携带 task_id（契约 D8-2 字段），
    前端可凭它归属更新标题。"""
    from web.executor import Executor
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex_obj = Executor(
        bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"),
        title_fn=lambda tid, q, st: "M31 的距离与年龄",
    )
    try:
        t = store.create_task("M31 的距离")
        ex_obj._gen_title(t["task_id"], "M31 的距离", {})
        evs = store.get_events(t["task_id"])
        assert evs and evs[-1]["type"] == "task_title_ready"
        assert evs[-1]["task_id"] == t["task_id"]
        assert evs[-1]["title"] == "M31 的距离与年龄"
    finally:
        ex_obj.stop()


# ── L-01: 前端归属链契约期望登记（React 渲染链无 pytest 执行环境） ──

@pytest.mark.xfail(
    reason="B7 L-01 契约期望登记：task_title_ready 前端按 ev.task_id 归属更新列表标题"
           "（App.jsx handleTaskTitle + usePipeline 透传完整事件）；React 渲染链无 pytest"
           "执行环境，前端侧由 npm run build 门禁验证",
    strict=False,
)
def test_title_event_carries_task_id():
    """L-01 契约期望登记（strict=False 防门禁误判）：
    后端事件携带 task_id 由 test_executor_title_event_carries_task_id 绿测断言；
    前端 handleTaskTitle 按 ev.task_id 归属、usePipeline 透传完整事件——该链依赖
    React 渲染环境，pytest 无法执行，登记为期望并靠 node --check / npm run build 门禁护航。"""
    raise AssertionError(
        "前端归属链需 React 渲染环境（无 jsdom 组件测试基建），pytest 无法执行；"
        "契约期望登记，验证见 npm run build 门禁"
    )
