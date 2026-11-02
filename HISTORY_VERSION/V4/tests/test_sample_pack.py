"""演示样例包（2026-09-02）：source 隔离 / 启动导入 / 守卫契约测试。

覆盖：
- TaskStore source 列（迁移默认 user）与 source 过滤、回放任务继承
- sample_pack.import_sample_pack：全新导入（行+事件+文件）/ 幂等 /
  本机同 id 行升级身份（不重复占位、事件清空时补录）
- API：?source 过滤、样例本体删除/内容清理/批量/记录删除 403、改名放行

全 mock 离线：不设 LLM_CASSETTE，不启动真实 executor（replay 路由 submit 打桩）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from web.sample_pack import import_sample_pack
from web.task_store import TaskStore

SAMPLE_ID = "11111111-2222-4333-8444-555555555555"
USER_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


# ══════════════════════════════════════════════════════
# 合成样例包（与 scripts/rebuild_sample_pack.py 产出同构：catalog.db + 文件）
# ══════════════════════════════════════════════════════

def _build_pack(tmp_path):
    pack = tmp_path / "sample_pack"
    pack.mkdir(parents=True)
    cat = TaskStore(pack / "catalog.db")
    cat.restore_task(
        SAMPLE_ID, "M87 的中央黑洞质量、爱丁顿比和6cm射电流量",
        title="M87中心黑洞质量爱丁顿比射电流量查询", status="completed",
        created_at="2026-09-01T00:00:00+00:00",
        completed_at="2026-09-01T00:05:00+00:00",
        state_json=json.dumps({"final_output": {"quality_report": {"report_state": {"quality": {"quality_scoring": {"overall_score": 0.9345}}}}}}),
        record_count=34, source_count=22, source="sample",
    )
    cat.restore_events(SAMPLE_ID, [
        (1.0, json.dumps({"type": "stage_started", "stage_id": "understand", "title": "任务理解"})),
        (2.5, json.dumps({"type": "agent_started", "stage_id": "understand", "agent": "classify"})),
        (4.0, json.dumps({"type": "stage_completed", "stage_id": "understand", "status": "ok"})),
    ])
    fig = pack / "figures" / SAMPLE_ID
    fig.mkdir(parents=True)
    (fig / "page_1.png").write_bytes(b"fake-png")
    exp = pack / "exports" / SAMPLE_ID[:8]
    exp.mkdir(parents=True)
    (exp / "grounded_data_x.json").write_text("{}", encoding="utf-8")
    return pack


# ══════════════════════════════════════════════════════
# TaskStore：source 列与过滤
# ══════════════════════════════════════════════════════

def test_store_source_column_filter(tmp_path):
    store = TaskStore(tmp_path / "t.db")
    u = store.create_task("我的查询")
    s = store.create_task("样例查询", source="sample")
    r = store.create_task("回放", source="sample", replay_of=s["task_id"])
    assert store.get_task(u["task_id"])["source"] == "user"  # 老任务默认 user
    assert store.get_task(s["task_id"])["source"] == "sample"
    only_user = store.list_tasks(limit=50, source="user")["items"]
    only_smp = store.list_tasks(limit=50, source="sample")["items"]
    assert {x["task_id"] for x in only_user} == {u["task_id"]}
    assert {x["task_id"] for x in only_smp} == {s["task_id"], r["task_id"]}
    assert store.list_tasks(limit=50)["total"] == 3  # source=None 兼容旧行为


def test_store_source_migration_legacy_db(tmp_path):
    """老库（无 source 列）打开时幂等加列，存量行默认 user。"""
    db = tmp_path / "old.db"
    import sqlite3
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, query TEXT NOT NULL, title TEXT DEFAULT '',"
                " status TEXT DEFAULT 'queued', created_at TEXT, completed_at TEXT, output_dir TEXT DEFAULT '',"
                " pdf_paths TEXT DEFAULT '[]', state_json TEXT DEFAULT '{}', replay_of TEXT DEFAULT NULL,"
                " record_count INTEGER DEFAULT 0, source_count INTEGER DEFAULT 0)")
    con.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,"
                " payload TEXT NOT NULL, ts REAL DEFAULT NULL)")
    con.commit(); con.close()
    store = TaskStore(db)
    store.create_task("老任务")
    items = store.list_tasks(limit=10, source="user")["items"]
    assert len(items) == 1 and items[0]["source"] == "user"


# ══════════════════════════════════════════════════════
# import_sample_pack：全新导入 / 幂等 / 升级
# ══════════════════════════════════════════════════════

def test_import_fresh_and_idempotent(tmp_path):
    pack = _build_pack(tmp_path)
    store = TaskStore(tmp_path / "main.db")
    out = tmp_path / "output"
    s1 = import_sample_pack(store, out, pack)
    assert s1["imported"] == 1 and s1["upgraded"] == 0
    rec = store.get_task(SAMPLE_ID)
    assert rec is not None and rec["source"] == "sample"
    assert rec["title"] == "M87中心黑洞质量爱丁顿比射电流量查询"
    assert rec["state_json"] and "overall_score" in rec["state_json"]
    evs = store.get_events(SAMPLE_ID, 0)
    assert [e["type"] for e in evs] == ["stage_started", "agent_started", "stage_completed"]
    assert evs[1]["ts"] == 2.5  # ts 原样保留 → 回放节奏真实等比
    assert (out / "figures" / SAMPLE_ID / "page_1.png").is_file()
    assert (out / SAMPLE_ID[:8] / "grounded_data_x.json").is_file()
    # 幂等：第二次导入零新增、零重复事件、不重复拷文件
    s2 = import_sample_pack(store, out, pack)
    assert s2["imported"] == 0 and s2["upgraded"] == 0 and s2["copied"] == 0
    assert store.list_tasks(limit=10, source="sample")["total"] == 1
    assert len(store.get_events(SAMPLE_ID, 0)) == 3


def test_import_upgrade_existing_user_task(tmp_path):
    """本机同 id 行（真实任务）→ 升级 source=sample，行内容零改写；事件被清空时补录。"""
    pack = _build_pack(tmp_path)
    store = TaskStore(tmp_path / "main.db")
    store.restore_task(SAMPLE_ID, "自定义查询文本", title="自定义标题", source="user")
    assert store.list_tasks(limit=10, source="sample")["total"] == 0
    s = import_sample_pack(store, tmp_path / "output", pack)
    assert s["upgraded"] == 1 and s["imported"] == 0
    rec = store.get_task(SAMPLE_ID)
    assert rec["source"] == "sample"
    assert rec["query"] == "自定义查询文本"  # 行内容保留（本地真身不被覆盖）
    assert len(store.get_events(SAMPLE_ID, 0)) == 3  # 事件清空 → 从包补录


def test_import_missing_pack_noop(tmp_path):
    store = TaskStore(tmp_path / "main.db")
    s = import_sample_pack(store, tmp_path / "output", tmp_path / "nope")
    assert s["pack"] is None and store.list_tasks(limit=10)["total"] == 0


# ══════════════════════════════════════════════════════
# API：source 过滤 / 样例本体守卫 / 回放继承（全离线）
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
    m.bus = None
    from web.executor import Executor
    from web.event_bus import EventBus
    m.bus = EventBus(m.store)
    m.executor = Executor(m.bus, m.store, str(m.CHECKPOINT_PATH), str(m.OUTPUT_DIR))
    monkeypatch.setattr(m.executor, "submit", lambda *a, **k: None)  # 不真跑线程
    yield TestClient(m.app)


def _seed_sample(m_store):
    m_store.restore_task(
        SAMPLE_ID, "M87 的中央黑洞质量、爱丁顿比和6cm射电流量",
        title="M87中心黑洞质量爱丁顿比射电流量查询", status="completed",
        created_at="2026-09-01T00:00:00+00:00", completed_at="2026-09-01T00:05:00+00:00",
        state_json="{}", record_count=34, source_count=22, source="sample",
    )
    m_store.restore_events(SAMPLE_ID, [(1.0, json.dumps({"type": "stage_started", "stage_id": "understand"}))])
    m_store.create_task("真实用户查询", source="user")


def test_api_list_source_filter(client):
    from web import main as m
    _seed_sample(m.store)
    smp = client.get("/api/tasks?source=sample").json()
    usr = client.get("/api/tasks?source=user").json()
    assert {x["task_id"] for x in smp["items"]} == {SAMPLE_ID}
    assert SAMPLE_ID not in {x["task_id"] for x in usr["items"]}
    assert client.get("/api/tasks?source=bogus").status_code == 400


def test_api_sample_delete_guards(client):
    from web import main as m
    _seed_sample(m.store)
    assert client.delete(f"/api/tasks/{SAMPLE_ID}").status_code == 403
    assert client.delete(f"/api/tasks/{SAMPLE_ID}/data").status_code == 403
    batch = client.post("/api/tasks/batch-delete", json={"task_ids": [SAMPLE_ID]}).json()
    assert batch["results"][0]["reason"] == "sample"
    # 改名放行
    r = client.put(f"/api/tasks/{SAMPLE_ID}/title", json={"title": "新名字"})
    assert r.status_code == 200 and m.store.get_task(SAMPLE_ID)["title"] == "新名字"


def test_api_replay_inherits_sample_source(client):
    from web import main as m
    _seed_sample(m.store)
    r = client.post(f"/api/tasks/{SAMPLE_ID}/replay", json={"speed": 10})
    assert r.status_code == 200
    replay_id = r.json()["task_id"]
    rec = m.store.get_task(replay_id)
    assert rec["replay_of"] == SAMPLE_ID and rec["source"] == "sample"
    usr = client.get("/api/tasks?source=user").json()
    assert replay_id not in {x["task_id"] for x in usr["items"]}
    smp = client.get("/api/tasks?source=sample").json()
    assert replay_id in {x["task_id"] for x in smp["items"]}
    # 回放副本可删（样例本体不可删，副本是派生演示产物）——先置完成（submit 已打桩）
    m.store.update_task(replay_id, status="completed", state_json="{}")
    assert client.delete(f"/api/tasks/{replay_id}").status_code == 200
