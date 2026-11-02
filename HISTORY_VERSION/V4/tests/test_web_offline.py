"""Web 服务层离线测试（测试策略第 1 层：全 mock，零 LLM/网络调用）。

覆盖：TaskStore / EventBus / Executor（状态机+排队+取消）/
web_runner interrupt 循环（假图）/ 上传校验 / 端点校验。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from web.event_bus import EventBus
from web.task_store import TaskStore


# ══════════════════════════════════════════════════════
# TaskStore
# ══════════════════════════════════════════════════════

def test_store_crud(tmp_path):
    store = TaskStore(tmp_path / "t.db")
    t = store.create_task("M31 的距离", pdf_paths=["/x/a.pdf"])
    assert t["status"] == "queued"
    rec = store.get_task(t["task_id"])
    assert rec["query"] == "M31 的距离"
    assert rec["pdf_paths"] == ["/x/a.pdf"]
    store.update_task(t["task_id"], status="running")
    assert store.get_task(t["task_id"])["status"] == "running"
    listing = store.list_tasks(limit=10)
    assert listing["total"] == 1


def test_store_events_seq(tmp_path):
    store = TaskStore(tmp_path / "t.db")
    t = store.create_task("q")
    s1 = store.append_event(t["task_id"], {"type": "stage_started", "stage_id": "understand"})
    s2 = store.append_event(t["task_id"], {"type": "message", "role": "ai"})
    assert s2 == s1 + 1  # seq 递增（D1-4/D8-3）
    evs = store.get_events(t["task_id"], after_seq=s1)
    assert len(evs) == 1 and evs[0]["type"] == "message"


# ══════════════════════════════════════════════════════
# EventBus（发布 → 落库 + 订阅队列）
# ══════════════════════════════════════════════════════

def test_event_bus_publish_subscribe(tmp_path):
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")
    q: asyncio.Queue = asyncio.Queue()
    bus.subscribe(t["task_id"], q)
    seq = bus.stage_started(t["task_id"], "understand", "任务理解")
    ev = q.get_nowait()
    assert ev["seq"] == seq and ev["type"] == "stage_started"
    assert store.last_seq(t["task_id"]) == seq
    bus.unsubscribe(t["task_id"], q)


# ══════════════════════════════════════════════════════
# 上传 / 任务端点校验（TestClient）
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
    # 重建单例（避免跨测试共享）
    m.store = TaskStore(m.DB_PATH)
    m.bus = EventBus(m.store)
    from web.executor import Executor
    m.executor = Executor(m.bus, m.store, str(m.CHECKPOINT_PATH), str(m.OUTPUT_DIR))
    # M-07: 模块导入时 events 发射器与 log_bridge handler 已绑到真实 bus → 真实
    # web/data/tasks.db；此处重绑到新单例，防离线测试把孤儿 log/埋点事件写进真实库
    from events import configure as configure_emitter
    configure_emitter(m.bus.publish)
    from web import log_bridge
    log_bridge.install(m.bus)
    yield TestClient(m.app)
    m.executor.stop()  # 回收后台 loop 线程


def test_upload_rejects_non_pdf(client):
    r = client.post("/api/upload", files={"files": ("a.txt", b"hello world", "text/plain")})
    assert r.status_code == 200
    body = r.json()
    # L-15: 扩展名维度先拦截（reason 变为"扩展名不是 .pdf"）——兼容两种拒绝文案
    assert body["pdf_ids"] == [] and (
        body["rejected"][0]["reason"].startswith("非 PDF")
        or "扩展名" in body["rejected"][0]["reason"]
    )


def test_upload_accepts_pdf(client):
    r = client.post("/api/upload", files={"files": ("p.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 200 and len(r.json()["pdf_ids"]) == 1


def test_create_task_validation(client):
    assert client.post("/api/tasks", json={"query": "  "}).status_code == 400
    assert client.post("/api/tasks", json={"query": "x" * 501}).status_code == 400
    assert client.post("/api/tasks", json={"query": "M31", "pdf_ids": ["nope"]}).status_code == 400


def test_create_task_moves_pdf(client, monkeypatch):
    from web import main as m
    # M-07: 阻断真实流水线（离线全 mock），executor 线程只跑假 runner
    monkeypatch.setattr("web.executor.run_task_streaming", lambda **kwargs: {})
    up = client.post("/api/upload", files={"files": ("p.pdf", b"%PDF-1.4", "application/pdf")}).json()
    pid = up["pdf_ids"][0]
    r = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": [pid]})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    # D4-3: 暂存区已 move 到任务目录（双端断言；旧断言用 app.extra 取不到
    # monkeypatch 后的 UPLOAD_DIR 恒为 True，见 M-21 恒真断言修复）
    assert not (m.UPLOAD_DIR / f"{pid}.pdf").exists()
    pdf_dir = m.OUTPUT_DIR / tid / "user_pdfs"
    assert (pdf_dir / f"{pid}.pdf").exists()
    # 等假 runner 收尾（避免线程跨测试边界）
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert m.store.get_task(tid)["status"] == "completed"


def test_offline_tests_do_not_pollute_real_db(client, monkeypatch):
    """M-07 回归锚点：离线任务跑完，真实 web/data/tasks.db 事件数不变。

    fixture 已把 events 发射器与 log_bridge handler 重绑到 tmp 单例；若重绑
    失效，executor 线程的日志/埋点会以不存在于真实 tasks 表的 task_id 写入
    真实 DB。假 runner 内显式触发两个污染通道（logger.info + events.emit），
    断言事件只落在 tmp store、真实库计数不变。
    """
    import sqlite3
    import logging as _logging
    from events import emit as events_emit
    from web import main as m

    real_db = Path(m.__file__).resolve().parent / "data" / "tasks.db"

    def _real_events() -> int:
        if not real_db.exists():
            return 0
        try:
            with sqlite3.connect(f"file:{real_db.as_posix()}?mode=ro", uri=True) as conn:
                return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def _probe_runner(**kwargs):
        # 两个污染通道：节点 logger（走 log_bridge）+ subgraph 埋点（走 events）
        # 注意用 WARNING：pytest 的 logging 插件先挂 root handler，web.main 的
        # basicConfig 不会生效，root 保持 WARNING 级别会丢弃 INFO 记录
        _logging.getLogger("subgraphs.subgraph2.nodes.pdf_download").warning("pollution probe")
        events_emit(kwargs["task_id"], {"type": "step_progress", "stage_id": "understand", "step": "x", "status": "running"})
        return {}

    before = _real_events()
    monkeypatch.setattr("web.executor.run_task_streaming", _probe_runner)
    up = client.post("/api/upload", files={"files": ("p.pdf", b"%PDF-1.4", "application/pdf")}).json()
    r = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": up["pdf_ids"]})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert m.store.get_task(tid)["status"] == "completed"
    # 两通道事件落在 tmp store（重绑生效）
    evs = m.store.get_events(tid)
    assert any(e["type"] == "log" and e["message"] == "pollution probe" for e in evs)
    assert any(e["type"] == "step_progress" for e in evs)
    # 真实库零污染
    assert _real_events() == before


# ══════════════════════════════════════════════════════
# M-21 覆盖补全：SSE 续播 / /state 澄清 / retry / config / export / resume / 上传分支
# ══════════════════════════════════════════════════════

def test_sse_replay_after_seq(client):
    """D1-4/D8-3 锚点①：SSE after_seq=N 首帧补发 seq>N 且升序，与 store 逐条相等。

    注：starlette TestClient / httpx ASGITransport 在本环境与 EventSourceResponse
    流式交互会阻塞（传输层限制，非业务问题；生产走 uvicorn + 浏览器 EventSource），
    故直接调用端点协程取 EventSourceResponse，逐帧解析 body_iterator 断言重放语义。
    """
    import asyncio
    from web import main as m
    t = m.store.create_task("q")
    for i in range(3):
        m.bus.emit(t["task_id"], "message", role="user", content=f"m{i}")

    async def _collect():
        resp = await m.stream_events(t["task_id"], 1)
        assert resp.status_code == 200
        frames = []
        async for frame in resp.body_iterator:
            frames.append(json.loads(frame["data"]))
            if len(frames) >= 2:  # seq 2,3 补发完即可断开
                break
        await resp.body_iterator.aclose()  # 触发 gen() finally → 退订
        return frames

    frames = asyncio.run(_collect())
    expected = m.store.get_events(t["task_id"], 1)
    assert [f["seq"] for f in frames] == [e["seq"] for e in expected]  # 升序补发
    assert frames == expected  # 与 store 逐条相等


def test_state_pending_clarification(client, monkeypatch):
    """D5-4/H-04 锚点②：/state 的 pending_clarification 仅当 executor 槽位真实
    等待时返回；任务完成后挂起清空。"""
    from web import main as m
    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_once_interrupt_graph(checkpointer),
    )
    r = client.post("/api/tasks", json={"query": "M31 的距离"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    # 等到澄清槽真实进入等待（图已发澄清事件且阻塞在 get_answer）
    deadline = time.time() + 8
    while time.time() < deadline:
        slot = m.executor._slots.get(tid)
        if slot and slot.waiting:
            break
        time.sleep(0.02)
    assert m.executor._slots.get(tid) is not None, "澄清槽未建立"
    assert m.executor._slots.get(tid).waiting, "澄清槽未进入等待"
    body = client.get(f"/api/tasks/{tid}/state").json()
    pc = body["pending_clarification"]
    assert pc is not None and pc["cl_type"] == "ask_properties"
    # 等待期 resume → 200，答案被真实消费 → 任务完成，挂起清空
    r2 = client.post(f"/api/tasks/{tid}/resume", json={"answer": "y"})
    assert r2.status_code == 200
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert m.store.get_task(tid)["status"] == "completed"
    body = client.get(f"/api/tasks/{tid}/state").json()
    assert body["pending_clarification"] is None


def test_retry_new_task_keeps_history(client, monkeypatch):
    """D2-4 锚点③：retry 新 task_id + 旧事件保留 + pdf copy 到新任务目录。"""
    from web import main as m
    monkeypatch.setattr("web.executor.run_task_streaming", lambda **kwargs: {})
    up = client.post("/api/upload", files={"files": ("p.pdf", b"%PDF-1.4", "application/pdf")}).json()
    r = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": up["pdf_ids"]})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)
    old_events = m.store.get_events(tid)
    assert old_events, "原任务应已有事件"
    r2 = client.post(f"/api/tasks/{tid}/retry")
    assert r2.status_code == 200
    tid2 = r2.json()["task_id"]
    assert tid2 != tid  # 新 task_id
    assert m.store.get_task(tid2)["query"] == "M31 的距离"
    assert m.store.get_events(tid) == old_events  # 旧事件保留
    new_pdfs = m.store.get_task(tid2)["pdf_paths"]
    assert len(new_pdfs) == 1  # pdf copy 到新任务目录
    assert Path(new_pdfs[0]).exists()
    assert (m.OUTPUT_DIR / tid2 / "user_pdfs").exists()
    assert m.store.get_task(tid2)["status"] in ("queued", "running", "completed")


def test_config_get_never_leaks_plaintext_and_put_writes(tmp_path, monkeypatch, client):
    """D10 锚点④：GET 不回传明文 + PUT（monkeypatch _ENV_FILE）写回断言。"""
    from web import main as m
    env = tmp_path / ".env"
    monkeypatch.setattr(m, "_ENV_FILE", env)
    r = client.get("/api/config")
    body = r.json()
    assert set(body["configured"]) == {"DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL",
                                       "ADS_API_TOKEN", "UNPAYWALL_EMAIL"}
    assert all(isinstance(v, bool) for v in body["configured"].values())  # 无明文
    # H-05④: 缺少来源校验头 → 403（防跨源投毒）；带正确头才允许写
    r_nohead = client.put("/api/config", json={"dashscope_api_key": "sk-secret-123"})
    assert r_nohead.status_code == 403
    r2 = client.put(
        "/api/config", json={"dashscope_api_key": "sk-secret-123"},
        headers={"X-Requested-With": "AstroQuery"})
    assert r2.status_code == 200
    assert "DASHSCOPE_API_KEY=sk-secret-123" in env.read_text(encoding="utf-8")
    r3 = client.get("/api/config")
    assert r3.json()["configured"]["DASHSCOPE_API_KEY"] is True
    assert "sk-secret-123" not in r3.text  # GET 永不回传明文


def test_config_put_keeps_comments_and_sanitizes_value(tmp_path, monkeypatch, client):
    """L-05 锚点：重写 .env 保留注释行；值内换行被单行化（不注入新键）。"""
    from web import main as m
    env = tmp_path / ".env"
    env.write_text("# 注释说明\n\nADS_API_TOKEN=old\n", encoding="utf-8")
    monkeypatch.setattr(m, "_ENV_FILE", env)
    h = {"X-Requested-With": "AstroQuery"}
    r = client.put("/api/config", json={"ads_api_token": "tok1\ntok2"}, headers=h)
    assert r.status_code == 200
    text = env.read_text(encoding="utf-8")
    assert "# 注释说明" in text  # 注释保留
    assert "ADS_API_TOKEN=tok1tok2" in text  # 换行已单行化
    assert "tok2" not in text.replace("ADS_API_TOKEN=tok1tok2", "")


def test_export_path_traversal_404(client):
    """D9-3 锚点⑤：/export/{file} 用 ../ 断言 404；合法文件 200。
    M-18：导出目录 = output/{task_id[:8]}/（run_id 绑定），文件写该目录。"""
    from web import main as m
    t = m.store.create_task("q")
    out = m.OUTPUT_DIR / t["task_id"][:8]
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.csv").write_bytes(b"a,b\n1,2\n")
    r = client.get(f"/api/tasks/{t['task_id']}/export/data.csv")
    assert r.status_code == 200
    r2 = client.get(f"/api/tasks/{t['task_id']}/export/..%2F..%2Fmain.py")
    assert r2.status_code == 404
    r3 = client.get(f"/api/tasks/{t['task_id']}/export/%2e%2e%2Fdata.csv")
    assert r3.status_code == 404


def test_resume_not_clarification_409(client):
    """D1-4 锚点⑥：resume 对非澄清等待（无槽位）→ 409。"""
    from web import main as m
    t = m.store.create_task("q")
    r = client.post(f"/api/tasks/{t['task_id']}/resume", json={"answer": "x"})
    assert r.status_code == 409


def test_upload_over_50mb_rejected(client):
    """D4-1 锚点⑦：超限 rejected[0].reason 含 50MB；混合「部分拒收」。"""
    big = b"%PDF" + b"x" * (50 * 1024 * 1024 + 16)
    r = client.post("/api/upload", files={"files": ("big.pdf", big, "application/pdf")})
    body = r.json()
    assert body["pdf_ids"] == []
    assert len(body["rejected"]) == 1 and "50MB" in body["rejected"][0]["reason"]
    # 混合：一个超限 + 一个合法 → 部分拒收
    r2 = client.post("/api/upload", files=[
        ("files", ("ok.pdf", b"%PDF-1.4", "application/pdf")),
        ("files", ("big.pdf", big, "application/pdf")),
    ])
    b2 = r2.json()
    assert len(b2["pdf_ids"]) == 1 and len(b2["rejected"]) == 1
    assert "50MB" in b2["rejected"][0]["reason"]


# ══════════════════════════════════════════════════════
# Executor（并发 1 排队 / cancel）
# ══════════════════════════════════════════════════════

def test_executor_queue_and_cancel(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    from web.executor import Executor
    ex = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))

    started = threading.Event()
    release = threading.Event()
    captured = {}

    def fake_runner(**kwargs):
        captured["task_id"] = kwargs["task_id"]
        started.set()
        release.wait(10)
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)

    t1 = store.create_task("q1")
    ex.submit(t1["task_id"], "q1", [])
    assert started.wait(3), "runner 未启动"
    assert store.get_task(t1["task_id"])["status"] == "running"

    # 并发 1：第二个排队
    t2 = store.create_task("q2")
    ex.submit(t2["task_id"], "q2", [])
    assert store.get_task(t2["task_id"])["status"] == "queued"

    # 取消运行中
    assert ex.cancel(t1["task_id"]) is True
    assert store.get_task(t1["task_id"])["status"] == "cancelled"
    release.set()  # 释放 fake_runner → _finish → 排队任务自动启动

    # 排队任务自动启动（轮询等待线程调度；fake_runner 立即返回 → 可能直接 completed）
    deadline = time.time() + 20
    while time.time() < deadline and store.get_task(t2["task_id"])["status"] == "queued":
        time.sleep(0.05)
    assert store.get_task(t2["task_id"])["status"] in ("running", "completed"), "排队任务未自动启动"


# ══════════════════════════════════════════════════════
# web_runner interrupt 循环（假图：两次 interrupt）
# ══════════════════════════════════════════════════════

class _FakeState(TypedDict, total=False):
    turns: int
    final_output: dict
    clarification_status: str
    query_type: str


def _fake_graph(checkpointer=None):
    def node(state: _FakeState):
        # interrupt 恢复后在同一调用内继续 → 连续两次澄清
        t = state.get("turns", 0)
        if t == 0:
            interrupt({"type": "ask_properties", "question": "要哪些性质？"})
            t = 1
        if t == 1:
            interrupt({"type": "final_confirm", "question": "确认？", "target_entity": "M31"})
            t = 2
        return {"turns": t}

    g = StateGraph(_FakeState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def _fake_done_graph(checkpointer=None, event_cb=None):
    """一次走完：发 done 事件并返回含 final_output 的终态（模拟真实主图 END 前路径）。

    CR-01 锚点用：stage_completed(done) 由 wrap finally 在 invoke 返回前触发，
    断言 runner 尾部的 on_final_summary 收到的是最终 state 而非陈旧 result。
    """

    def node(state: _FakeState):
        if event_cb:
            event_cb("stage_completed", stage_id="done", duration=0.1, status="completed")
        return {
            "final_output": {
                "sources": [{"source_id": "s1", "name": "VizieR/J/MNRAS"}],
                "records": [{"source_id": "s1", "property": "distance"}],
            }
        }

    g = StateGraph(_FakeState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def _fake_single_interrupt_graph(checkpointer=None):
    """单次澄清中断（H-07 超时锚点用，get_answer 永不恢复）。"""

    def node(state: _FakeState):
        interrupt({"type": "ask_properties", "question": "要哪些性质？"})
        return {"turns": 1}

    g = StateGraph(_FakeState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def _fake_once_interrupt_graph(checkpointer=None):
    """单次澄清中断，resume 后即完成（H-04 等待期 resume / /state 锚点用）。"""

    def node(state: _FakeState):
        if state.get("turns", 0) == 0:
            interrupt({"type": "ask_properties", "question": "要哪些性质？"})
            return {"turns": 1}
        return {"turns": 2}

    g = StateGraph(_FakeState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def _fake_cancel_graph(checkpointer=None):
    """选 n 取消（H-09 锚点）：澄清中断恢复后返回 clarification_status='cancelled'。"""

    def node(state: _FakeState):
        if state.get("turns", 0) == 0:
            interrupt({"type": "final_confirm", "question": "确认？", "target_entity": "M31"})
            return {"turns": 1, "clarification_status": "cancelled", "query_type": "astronomical"}
        return {}

    g = StateGraph(_FakeState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def test_runner_interrupt_loop(tmp_path, monkeypatch):
    from astroquery_ai.web_runner import run_task_streaming
    from web.event_bus import EventBus
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")

    answers = iter(["距离和金属丰度", "y"])
    got_payloads = []

    def get_answer(_tid, payload):
        got_payloads.append(payload)
        return next(answers)

    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_graph(checkpointer),
    )

    result = run_task_streaming(
        task_id=t["task_id"], user_query="q", extra_pdfs=[], bus=bus,
        get_answer=get_answer, should_cancel=lambda: False,
        checkpointer_path=str(tmp_path / "cp.sqlite"),
    )
    assert result["turns"] == 2
    # 两次 interrupt → 两次 clarification 事件 + resume
    clar = [e for e in store.get_events(t["task_id"]) if e["type"] == "clarification"]
    assert len(clar) == 2
    assert clar[0]["cl_type"] == "ask_properties"
    assert clar[1]["cl_type"] == "final_confirm"
    assert clar[1]["fields"] == [{"label": "天体名称", "value": "M31"}]


def test_runner_cancel_on_timeout(tmp_path, monkeypatch):
    """get_answer 返回 None（超时）→ 终止且无 task_completed。

    H-08② 起 task_cancelled 由调用方（executor.cancel / get_answer 超时分支）
    发出，runner 不再自行发——本测试的 get_answer 模拟 executor 超时分支。
    """
    from astroquery_ai.web_runner import run_task_streaming
    from web.event_bus import EventBus
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")

    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_graph(checkpointer),
    )

    def get_answer(_tid, _payload):
        # 模拟 executor.get_answer 超时分支（H-07）：先发 task_cancelled 再返回 None
        bus.emit(t["task_id"], "task_cancelled", reason="timeout")
        return None

    result = run_task_streaming(
        task_id=t["task_id"], user_query="q", extra_pdfs=[], bus=bus,
        get_answer=get_answer,  # 模拟超时/取消
        should_cancel=lambda: True,
        checkpointer_path=str(tmp_path / "cp.sqlite"),
    )
    types = [e["type"] for e in store.get_events(t["task_id"])]
    assert "task_cancelled" in types
    assert "task_completed" not in types


# ══════════════════════════════════════════════════════
# log_bridge（L-11：ContextVar + TPE 提交透传）
# ══════════════════════════════════════════════════════

def test_log_bridge_worker_thread_log(tmp_path):
    """L-11 回归锚点：ThreadPoolExecutor worker 线程日志 → 事件落库。

    threading.local 不随子线程传播（VLM/bbox/下载/图提取等 TPE worker 日志
    全丢）；ContextVar + 提交时显式透传后，worker 线程 emit 的事件应落库。
    """
    import concurrent.futures
    import logging as _logging

    from web import log_bridge
    from web.event_bus import EventBus
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    log_bridge.install(bus)  # 安装 handler + TPE 提交 context 透传
    t = store.create_task("q")

    # 同线程路径（executor 线程本体）仍工作
    log_bridge.set_task(t["task_id"])
    _logging.getLogger("subgraphs.subgraph2.nodes.database_query").warning("same thread probe")
    # 注意用 WARNING：pytest 的 logging 插件先挂 root handler，web.main 的
    # basicConfig 不生效，root 保持 WARNING 级别会丢弃 INFO 记录
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        ex.submit(
            lambda: _logging.getLogger("subgraphs.subgraph3.nodes.vlm_extractor").warning("worker thread probe")
        ).result()
    log_bridge.set_task(None)

    logs = [e for e in store.get_events(t["task_id"]) if e["type"] == "log"]
    assert any(e["message"] == "same thread probe" for e in logs), "同线程日志未落库"
    assert any(e["message"] == "worker thread probe" for e in logs), "worker 线程日志未落库（context 透传失效）"


# ══════════════════════════════════════════════════════
# 批次 B2 状态机终态簇（CR-01 / H-07 / H-08 / H-09 / M-12 / M-17）
# ══════════════════════════════════════════════════════

def test_runner_summary_receives_true_final_state(tmp_path, monkeypatch):
    """CR-01 锚点（DP-04）：假图发 done 事件后，on_final_summary 收到含
    final_output 的真实终态——不再取 wrap finally 时的陈旧 result（{} 或
    上一轮 __interrupt__ dict，恒报 0 数据源/0 记录）。
    """
    from astroquery_ai.web_runner import run_task_streaming
    from web.event_bus import EventBus
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")
    received: dict = {}
    called = threading.Event()

    def fake_summary(task_id, state):
        received["state"] = state
        called.set()
        return "任务完成：共提取 1 个数据源、1 条记录。"

    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_done_graph(checkpointer, event_cb),
    )
    run_task_streaming(
        task_id=t["task_id"], user_query="q", extra_pdfs=[], bus=bus,
        get_answer=lambda _tid, _p: None, should_cancel=lambda: False,
        checkpointer_path=str(tmp_path / "cp.sqlite"),
        on_final_summary=fake_summary,
    )
    assert called.wait(3), "on_final_summary 未被调用（总结未生成）"
    final_output = (received["state"] or {}).get("final_output") or {}
    assert len(final_output.get("sources", [])) == 1
    assert len(final_output.get("records", [])) == 1
    # P0-1：task_completed 改由 executor._finish 在 status 落库后发（时序竞态根治），
    # runner 层不再发——终态事件链见 test_executor_task_completed_after_persist
    types = [e["type"] for e in store.get_events(t["task_id"])]
    assert "task_completed" not in types


def test_executor_task_completed_after_persist_before_slow_summary(tmp_path, monkeypatch):
    """M-12 + P0-1 锚点：task_completed 由 executor._finish 在 status 落库之后发出——
    慢 LLM 总结（0.3s）不阻塞 task_completed；ai 总结消息仍晚于 task_completed；
    事件到达时 DB status 已是 completed（时序竞态根治的断言核心）。"""
    from web.event_bus import EventBus
    from web.executor import Executor
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")
    summary_started = threading.Event()
    summary_done = threading.Event()

    def slow_summary(task_id, state):
        summary_started.set()
        time.sleep(2.0)  # 模拟 LLM 慢/悬挂（2s：全量高负载下 0.3s 窗口会被轮询错过）
        summary_done.set()
        return "慢总结完成"

    # runner 真跑（假图发 done 事件），仅替换图构造
    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_done_graph(checkpointer, event_cb),
    )
    ex = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"),
                  summary_fn=slow_summary)
    try:
        ex.submit(t["task_id"], "q", [])
        assert summary_started.wait(5), "总结未开始"
        # 慢总结仍阻塞：task_completed 已到（_finish 不等待总结）、ai 消息未到
        deadline = time.time() + 10
        while time.time() < deadline:
            events_now = store.get_events(t["task_id"])
            if any(e["type"] == "task_completed" for e in events_now):
                break
            time.sleep(0.05)
        assert "task_completed" in [e["type"] for e in store.get_events(t["task_id"])], \
            "慢总结阻塞了 task_completed"
        # P0-1 核心：task_completed 到达时 DB status 已落 completed（快照/状态就绪）
        rec = store.get_task(t["task_id"])
        assert rec and rec["status"] == "completed", "task_completed 应先于 status 落库？"
        assert not any(e["type"] == "message" and e["role"] == "ai"
                       for e in store.get_events(t["task_id"]))
        assert summary_done.wait(5)
        # 轮询等 ai 消息落库（总结线程在 summary_done 之后才发消息，需短轮询）
        deadline = time.time() + 3
        while time.time() < deadline:
            events = store.get_events(t["task_id"])
            if any(e["type"] == "message" and e["role"] == "ai" for e in events):
                break
            time.sleep(0.05)
        tc = next(i for i, e in enumerate(events) if e["type"] == "task_completed")
        ai = next(i for i, e in enumerate(events) if e["type"] == "message" and e["role"] == "ai")
        assert tc < ai, "ai 总结消息应晚于 task_completed 到达"
    finally:
        ex.stop()


def test_executor_clarification_timeout_marks_db_cancelled(tmp_path, monkeypatch):
    """H-07 锚点（W08-05）：注入短超时 → DB status=='cancelled'（不被 _finish
    覆写为 completed）且事件含 task_cancelled + error fatal。"""
    from web.executor import Executor
    from web.event_bus import EventBus
    from web.task_store import TaskStore

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
        rec = store.get_task(t["task_id"])
        assert rec["status"] == "cancelled", f"超时任务终态应为 cancelled，实际 {rec['status']}"
        events = store.get_events(t["task_id"])
        types = [e["type"] for e in events]
        assert "task_cancelled" in types
        assert any(e["type"] == "error" and e["level"] == "fatal" for e in events)
        assert "task_completed" not in types
    finally:
        ex.stop()


def test_executor_cancel_emits_events_running_and_queued(tmp_path, monkeypatch):
    """H-08② 锚点（DP-08）：cancel 立即发 task_cancelled——含 queued 分支
    （runner 未运行，事件只能由 cancel 发出）与运行中分支（无 task_completed）。"""
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    from web.executor import Executor
    ex = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        started = threading.Event()
        release = threading.Event()

        def fake_runner(**kwargs):
            started.set()
            release.wait(10)
            return {}

        monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)

        t1 = store.create_task("q1")
        ex.submit(t1["task_id"], "q1", [])
        assert started.wait(3), "runner 未启动"

        # queued 取消 → 事件立即送达（DP-08 锚点）
        t2 = store.create_task("q2")
        ex.submit(t2["task_id"], "q2", [])
        assert store.get_task(t2["task_id"])["status"] == "queued"
        assert ex.cancel(t2["task_id"]) is True
        assert "task_cancelled" in [e["type"] for e in store.get_events(t2["task_id"])]
        assert store.get_task(t2["task_id"])["status"] == "cancelled"

        # 运行中取消 → 事件立即送达；线程结束后不发 task_completed
        assert ex.cancel(t1["task_id"]) is True
        assert "task_cancelled" in [e["type"] for e in store.get_events(t1["task_id"])]
        release.set()
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t1["task_id"])["status"] == "running":
            time.sleep(0.05)
        assert store.get_task(t1["task_id"])["status"] == "cancelled"
        assert "task_completed" not in [e["type"] for e in store.get_events(t1["task_id"])]
    finally:
        ex.stop()


def test_runner_should_cancel_skips_task_completed(tmp_path, monkeypatch):
    """H-08③：发 task_completed 前检查 should_cancel，已取消只发 task_cancelled。"""
    from astroquery_ai.web_runner import run_task_streaming
    from web.event_bus import EventBus
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")

    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_done_graph(checkpointer, event_cb),
    )
    # 调用方（executor.cancel）已发 task_cancelled
    bus.emit(t["task_id"], "task_cancelled", reason="cancelled")
    run_task_streaming(
        task_id=t["task_id"], user_query="q", extra_pdfs=[], bus=bus,
        get_answer=lambda _tid, _p: None, should_cancel=lambda: True,
        checkpointer_path=str(tmp_path / "cp.sqlite"),
    )
    types = [e["type"] for e in store.get_events(t["task_id"])]
    assert "task_cancelled" in types
    assert "task_completed" not in types


def test_main_graph_wrap_cancel_boundary():
    """H-08①：节点边界 should_cancel 为真 → 抛 _CancelledError 终止图执行。"""
    from langgraph.checkpoint.memory import MemorySaver
    from astroquery_ai.main_graph import create_main_graph, _CancelledError

    app = create_main_graph(
        checkpointer=MemorySaver(),
        event_cb=lambda *a, **k: None,
        should_cancel=lambda: True,
    )
    with pytest.raises(_CancelledError):
        app.invoke({"user_query": "q"}, {"configurable": {"thread_id": "b2-cancel"}})


def test_main_graph_stage_started_dedup_on_reentry():
    """H-09④：同图实例内已 start 未 completed 的 stage 去重（澄清重入不重复
    stage_started，DP-06 started=2/completed=1 实证）。"""
    from langgraph.checkpoint.memory import MemorySaver
    from astroquery_ai.main_graph import create_main_graph

    events = []
    app = create_main_graph(
        checkpointer=MemorySaver(),
        event_cb=lambda ev, **f: events.append({"type": ev, **f}),
    )
    node = app.nodes["clarification"]
    # 走 clarification_node 的免子图快路径（已有 target_entity + confirmed）
    confirmed = {
        "user_query": "M31 的距离",
        "target_entity": "M31",
        "clarification_status": "confirmed",
        "query_type": "astronomical",
        "requested_properties": [],
    }
    node.invoke(confirmed)
    node.invoke(confirmed)  # 澄清重入 → stage_started 不得重复
    starts = [e for e in events if e["type"] == "stage_started" and e["stage_id"] == "understand"]
    assert len(starts) == 1, f"重复 stage_started: {starts}"


def test_runner_user_cancel_emits_task_cancelled_not_completed(tmp_path, monkeypatch):
    """H-09①③ 锚点（选 n）：事件流含 task_cancelled 且无 task_completed；
    understand 卡补发 stage_completed(status='cancelled') 灰态。"""
    from astroquery_ai.web_runner import run_task_streaming
    from web.event_bus import EventBus
    from web.task_store import TaskStore

    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")

    monkeypatch.setattr(
        "astroquery_ai.web_runner.create_main_graph",
        lambda checkpointer=None, event_cb=None, should_cancel=None: _fake_cancel_graph(checkpointer),
    )
    result = run_task_streaming(
        task_id=t["task_id"], user_query="q", extra_pdfs=[], bus=bus,
        get_answer=lambda _tid, _p: "n", should_cancel=lambda: False,
        checkpointer_path=str(tmp_path / "cp.sqlite"),
    )
    assert result.get("clarification_status") == "cancelled"
    events = store.get_events(t["task_id"])
    types = [e["type"] for e in events]
    assert "task_cancelled" in types
    assert "task_completed" not in types
    assert any(
        e["type"] == "stage_completed" and e["stage_id"] == "understand" and e["status"] == "cancelled"
        for e in events
    ), "understand 卡未补发灰态完成"


def test_executor_cancelled_result_db_final_state(client, monkeypatch):
    """H-09②：runner 返回 clarification_status='cancelled' → DB 终态 cancelled
    而非 completed（_finish 不覆写）。"""
    from web import main as m
    monkeypatch.setattr(
        "web.executor.run_task_streaming",
        lambda **kwargs: {"clarification_status": "cancelled"},
    )
    r = client.post("/api/tasks", json={"query": "M31 的距离"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert m.store.get_task(tid)["status"] == "cancelled"


def test_executor_title_async_does_not_block_finish(tmp_path, monkeypatch):
    """M-12：标题 LLM 阻塞时 _finish/队列释放不受影响（D8-2 异步语义）。"""
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    from web.executor import Executor
    title_blocked = threading.Event()
    title_release = threading.Event()

    def slow_title(task_id, query, state):
        title_blocked.set()
        title_release.wait(5)
        return "标题"

    ex = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"),
                  title_fn=slow_title)
    try:
        monkeypatch.setattr("web.executor.run_task_streaming", lambda **kwargs: {})
        t1 = store.create_task("q1")
        ex.submit(t1["task_id"], "q1", [])
        t2 = store.create_task("q2")
        ex.submit(t2["task_id"], "q2", [])
        assert title_blocked.wait(5), "标题 LLM 未进入阻塞"
        # 标题 LLM 仍阻塞中 → t2 已脱离 queued（_finish 未等标题）
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t2["task_id"])["status"] == "queued":
            time.sleep(0.05)
        assert store.get_task(t2["task_id"])["status"] in ("running", "completed")
        assert not title_release.is_set(), "队列释放前标题 LLM 不应被放行"
    finally:
        title_release.set()
        ex.stop()


def test_summary_prompt_uses_target_entity(monkeypatch):
    """M-17 锚点：总结 prompt 引用 state.target_entity / user_query 兜底，
    不再硬编码 M13（非 M13 查询不错误引用天体名）。"""
    from web import summary as s

    captured: dict = {}

    def fake_llm(prompt, max_tokens=400):
        captured["prompt"] = prompt
        return "已提取 M31 的数据，质量良好，可直接使用。"

    monkeypatch.setattr(s, "_try_llm", fake_llm)
    state = {
        "user_query": "M31 的距离和年龄",
        "target_entity": "M31",
        "final_output": {
            "sources": [{"source_id": "s1"}],
            "records": [{"source_id": "s1", "x": 1}],
            "quality_report": {"skipped": True},
        },
    }
    text = s.generate_final_summary("tid", state)
    assert "M31" in captured["prompt"]
    assert "M31" in text
    # 无 target_entity → user_query 兜底；prompt 不得含硬编码 M13
    captured.clear()
    s.generate_final_summary("tid", {
        "user_query": "猎户座星云的距离",
        "final_output": {"sources": [], "records": []},
    })
    assert "猎户座星云" in captured["prompt"]
    assert "M13" not in captured["prompt"]


# ══════════════════════════════════════════════════════
# 批次 B3 resume/取消端点（H-04 / L-06 / L-07）
# ══════════════════════════════════════════════════════

def test_answer_slot_waiting_semantics():
    """H-04① 锚点：_AnswerSlot.waiting 标志——非等待期/已取消的 set_answer 拒绝。"""
    from astroquery_ai.web_runner import _AnswerSlot
    slot = _AnswerSlot()
    # 未进入等待 → 拒绝（陈旧答案不得注入）
    assert slot.set_answer("garbage") is False
    assert slot.answer is None
    w = threading.Thread(target=slot.wait, args=(5,), daemon=True)
    w.start()
    deadline = time.time() + 3
    while time.time() < deadline and not slot.waiting:
        time.sleep(0.01)
    assert slot.waiting
    # 等待期 set_answer 生效并唤醒 wait
    assert slot.set_answer("y") is True
    assert slot.answer == "y"
    w.join(3)
    assert not w.is_alive(), "set_answer 未唤醒 wait"
    # wait 返回后（非等待期）再 set_answer → 拒绝
    assert slot.set_answer("stale") is False
    # 已取消 → 拒绝且不视为挂起
    slot2 = _AnswerSlot()
    w2 = threading.Thread(target=slot2.wait, args=(5,), daemon=True)
    w2.start()
    deadline = time.time() + 3
    while time.time() < deadline and not slot2.waiting:
        time.sleep(0.01)
    slot2.cancel()
    assert slot2.set_answer("x") is False
    assert slot2.waiting is False  # cancelled → 不视为挂起
    w2.join(3)


def test_resume_409_task_running_not_waiting(client, monkeypatch):
    """H-04 锚点（DP-07 红测）：任务 running、槽存在但未到澄清等待 → resume 409，
    陈旧答案不被接受。"""
    from web import main as m
    release = threading.Event()

    def fake_runner(**kwargs):
        release.wait(10)
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)
    r = client.post("/api/tasks", json={"query": "M31 的距离"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    # submit 同步完成：槽已建、任务 running、但 runner 未到澄清点（waiting=False）
    slot = m.executor._slots.get(tid)
    assert slot is not None and not slot.waiting
    assert m.store.get_task(tid)["status"] == "running"
    r2 = client.post(f"/api/tasks/{tid}/resume", json={"answer": "garbage"})
    assert r2.status_code == 409
    assert slot.answer is None  # 陈旧答案未被写入
    release.set()
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert m.store.get_task(tid)["status"] == "completed"


def test_state_pending_clarification_null_when_not_waiting(client, monkeypatch):
    """H-04② 锚点：任务 running 且末事件为澄清，但槽位不在等待（已答复）→ null，
    不再误显挂起卡。"""
    from web import main as m
    release = threading.Event()

    def fake_runner(**kwargs):
        release.wait(10)
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)
    r = client.post("/api/tasks", json={"query": "M31 的距离"})
    tid = r.json()["task_id"]
    assert m.store.get_task(tid)["status"] == "running"
    # 已答复的澄清：末事件为 clarification、任务 running、但槽位未在等待
    m.bus.clarification(tid, "ask_properties", "选择查询性质", question="要哪些性质？")
    body = client.get(f"/api/tasks/{tid}/state").json()
    assert body["pending_clarification"] is None
    release.set()
    deadline = time.time() + 20
    while time.time() < deadline and m.store.get_task(tid)["status"] in ("queued", "running"):
        time.sleep(0.05)


def test_resume_cancel_404_nonexistent(client):
    """L-06 锚点：resume/cancel 对不存在任务 → 404（同族端点语义一致）。"""
    r = client.post("/api/tasks/nonexistent-404/resume", json={"answer": "x"})
    assert r.status_code == 404
    r2 = client.post("/api/tasks/nonexistent-404/cancel")
    assert r2.status_code == 404


def test_cancel_does_not_overwrite_completed(tmp_path, monkeypatch):
    """L-07 锚点：cancel 拿到 slot 后二次校验当前状态——已完成任务（含与 _finish
    竞态中 pop 前的陈旧槽）终态不被覆写为 cancelled。"""
    from web.executor import Executor
    from astroquery_ai.web_runner import _AnswerSlot
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        monkeypatch.setattr("web.executor.run_task_streaming", lambda **kwargs: {})
        t = store.create_task("q")
        store.update_task(t["task_id"], status="completed", completed_at="now")
        # 场景 1：已完成且槽已弹出 → cancel False，终态不变
        assert ex.cancel(t["task_id"]) is False
        assert store.get_task(t["task_id"])["status"] == "completed"
        # 场景 2：竞态模拟——_finish 已写 completed，cancel 拿到 pop 前的陈旧槽
        ex._slots[t["task_id"]] = _AnswerSlot()
        assert ex.cancel(t["task_id"]) is False
        assert store.get_task(t["task_id"])["status"] == "completed"  # 未被覆写
        assert store.get_task(t["task_id"])["completed_at"] == "now"
        ex._slots.pop(t["task_id"], None)
    finally:
        ex.stop()


# ══════════════════════════════════════════════════════
# 批次 B4 VCR 回放链路（H-11 / H-12 / H-14 / M-11 / L-14）
# ══════════════════════════════════════════════════════

def _write_cassette(path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _chat_cassette_yaml(prompt: str) -> str:
    """单个 LLM chat 交互的最小 cassette（H-11/H-14 校验锚点用）。

    vcrpy 8.3.0 序列化形态：request body 为纯标量字符串（含 \\uXXXX 转义），
    response body 为 {encoding, string} 且 string 为 bytes（!!binary）。
    """
    body = json.dumps({"messages": [{"role": "user", "content": prompt}]}, ensure_ascii=True)
    return f"""interactions:
- request:
    method: POST
    uri: https://api.deepseek.com/chat/completions
    body: '{body}'
    headers: {{}}
  response:
    status: {{code: 200, message: OK}}
    headers: {{}}
    body:
      encoding: utf-8
      string: !!binary {_b64("ok")}
"""


def _body_cassette_yaml() -> str:
    """同 URL 三个交互：POST AAA / POST BBB / GET——H-11 match_on=body 乱序回放锚点。"""
    return f"""interactions:
- request:
    method: POST
    uri: http://example.test/chat/completions
    body: '{{"query": "AAA"}}'
    headers: {{}}
  response:
    status: {{code: 200, message: OK}}
    headers: {{}}
    body:
      encoding: utf-8
      string: !!binary {_b64("resp-AAA")}
- request:
    method: POST
    uri: http://example.test/chat/completions
    body: '{{"query": "BBB"}}'
    headers: {{}}
  response:
    status: {{code: 200, message: OK}}
    headers: {{}}
    body:
      encoding: utf-8
      string: !!binary {_b64("resp-BBB")}
- request:
    method: GET
    uri: http://example.test/download/file.pdf
    body: null
    headers: {{}}
  response:
    status: {{code: 200, message: OK}}
    headers: {{}}
    body:
      encoding: utf-8
      string: !!binary {_b64("pdf-bytes")}
"""


def _download_cassette_yaml() -> str:
    """仅 GET 下载交互（无 LLM chat）——H-11「无 LLM 交互拒绝回放」锚点。"""
    return f"""interactions:
- request:
    method: GET
    uri: https://example.test/pdf/file.pdf
    body: null
    headers: {{}}
  response:
    status: {{code: 200, message: OK}}
    headers: {{}}
    body:
      encoding: utf-8
      string: !!binary {_b64("pdf")}
"""


class _RacyCassette:
    """模拟 vcrpy 8.3.0 的 play_counts 检查-自增非原子（H-12 锚点：并发重复消费）。"""

    def __init__(self, n: int):
        self.data = [(f"req{i}", f"resp{i}") for i in range(n)]
        self.play_counts = [0] * n
        self.played: list = []

    def _responses(self, request):
        return list(enumerate(self.data))

    def play_response(self, request):
        for index, (_, resp) in self._responses(request):
            if self.play_counts[index] == 0:
                time.sleep(0.001)  # 放大竞态窗口（vcrpy 检查-自增间无锁）
                self.play_counts[index] += 1
                self.played.append(resp)
                return resp
        raise RuntimeError("unhandled")


# ── H-11: 回放按 body（prompt）区分 + 回放前 query 一致性校验 ──

def test_vcr_match_on_includes_body_and_replays_per_body(tmp_path):
    """H-11 锚点：match_on 含 smart_body——同 URL 乱序请求各取各的响应（不再按
    「首个未播放」错位交付）；GET（body=None）不受影响。
    smart_body（验收回归修复）：chat/completions 严格按 body 区分，VLM
    （multimodal-generation）宽松（prompt 含动态内容无法稳定回放）。"""
    import requests
    from web import executor as ex
    path = _write_cassette(tmp_path / "body.yaml", _body_cassette_yaml())
    vcr_obj, cp = ex._build_replay_vcr(str(path), "none")
    assert vcr_obj.match_on == list(ex._VCR_MATCH_ON)
    assert "smart_body" in vcr_obj.match_on  # H-11: 回放专用 match_on 含 smart_body
    with vcr_obj.use_cassette(cp.name) as cass:
        r1 = requests.post("http://example.test/chat/completions", json={"query": "BBB"})
        r2 = requests.post("http://example.test/chat/completions", json={"query": "AAA"})
        r3 = requests.get("http://example.test/download/file.pdf")
        assert r1.text == "resp-BBB", f"乱序回放错位: {r1.text}"
        assert r2.text == "resp-AAA", f"乱序回放错位: {r2.text}"
        assert r3.text == "pdf-bytes"
    assert sorted(cass.play_counts.values()) == [1, 1, 1]  # 每条恰消费一次


def test_smart_body_matcher_vlm_loose(tmp_path):
    """H-11 smart_body 回归锚点：VLM（multimodal-generation）body 不同仍匹配
    （prompt 含动态文件名/页码）；chat/completions 严格区分。"""
    from web import executor as ex
    m = ex._make_smart_body_matcher()

    class _R:
        def __init__(self, uri, body):
            self.uri = uri
            self.body = body
            self.headers = {"content-type": "application/json"}

    chat_a = _R("https://api.deepseek.com/chat/completions", '{"a":1}')
    chat_b = _R("https://api.deepseek.com/chat/completions", '{"a":2}')
    vlm_a = _R("https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation", '{"p":1}')
    vlm_b = _R("https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation", '{"p":999}')

    def _match(a, b):
        try:
            m(a, b)
            return True
        except AssertionError:
            return False

    assert _match(chat_a, chat_a) is True      # chat 相同 body 匹配
    assert _match(chat_a, chat_b) is False     # chat 不同 body 拒绝（防错位）
    assert _match(vlm_a, vlm_b) is True        # VLM 不同 body 放行（可回放）


def test_validate_replay_query_unit(tmp_path):
    """H-11 单元锚点：首条 prompt 含当前查询 → 通过；不一致 → 拒绝；
    无 LLM chat 交互 → 拒绝；缺失文件/空查询由他处负责（不抛）。"""
    from web import executor as ex
    cassette = _write_cassette(tmp_path / "c.yaml", _chat_cassette_yaml("用户输入：M31 的距离"))
    ex.validate_replay_query(str(cassette), "M31 的距离")  # 一致 → 通过
    with pytest.raises(RuntimeError, match="拒绝回放"):
        ex.validate_replay_query(str(cassette), "NGC 999 的距离")
    dl = _write_cassette(tmp_path / "dl.yaml", _download_cassette_yaml())
    with pytest.raises(RuntimeError, match="无 LLM chat 交互"):
        ex.validate_replay_query(str(dl), "M31 的距离")
    ex.validate_replay_query(str(tmp_path / "nope.yaml"), "M31 的距离")  # 缺失 → H-14 负责
    ex.validate_replay_query(str(cassette), "")  # 空查询 → no-op
    ex.validate_replay_query("", "M31 的距离")  # 空路径 → no-op


def test_executor_replay_query_mismatch_fails_task(tmp_path, monkeypatch):
    """H-11 锚点（executor 级）：修改 prompt 后回放拒绝命中旧交互——查询与录制
    不一致 → 任务失败且不进入 runner（不再静默返回错位响应）。"""
    from web import executor as ex
    from web.executor import Executor
    cassette = _write_cassette(
        tmp_path / "old.yaml", _chat_cassette_yaml("用户输入：M13 的距离、年龄和金属丰度"))
    monkeypatch.setattr(ex, "_CASSETTE_PATH", str(cassette))
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "none")
    called = {"n": 0}

    def fake_runner(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex_obj = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        t = store.create_task("M31 的距离和年龄")  # 与录制不一致
        ex_obj.submit(t["task_id"], "M31 的距离和年龄", [])
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t["task_id"])["status"] in ("queued", "running"):
            time.sleep(0.05)
        assert store.get_task(t["task_id"])["status"] in ("error", "failed")  # B7 H-01: 词表统一 error, 兼容旧 failed
        assert called["n"] == 0, "校验失败后仍进入 runner"
        errs = [e for e in store.get_events(t["task_id"]) if e["type"] == "error"]
        assert errs and "拒绝回放" in errs[-1].get("message", "")
    finally:
        ex_obj.stop()


def test_executor_replay_query_match_runs(tmp_path, monkeypatch):
    """H-11 反向锚点：查询与录制一致 → 通过校验进入回放（runner 被调用）。"""
    from web import executor as ex
    from web.executor import Executor
    cassette = _write_cassette(tmp_path / "c.yaml", _chat_cassette_yaml("用户输入：M31 的距离"))
    monkeypatch.setattr(ex, "_CASSETTE_PATH", str(cassette))
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "none")
    called = {"n": 0}

    def fake_runner(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex_obj = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        t = store.create_task("M31 的距离")
        ex_obj.submit(t["task_id"], "M31 的距离", [])
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t["task_id"])["status"] in ("queued", "running"):
            time.sleep(0.05)
        assert store.get_task(t["task_id"])["status"] == "completed"
        assert called["n"] == 1
    finally:
        ex_obj.stop()


# ── H-12: 回放线程安全（RLock 串行化 play_response + VLM 并发降为 1） ──

def test_guard_cassette_play_serializes_concurrent_consumption():
    """H-12 锚点：RLock 串行化 play_response 检查-自增——多线程并发回放
    无重复消费 seq（每条恰消费一次，消费完明确抛错而非越界/错配）。"""
    from web import executor as ex
    n = 8
    cassette = _RacyCassette(n)
    ex._guard_cassette_play(cassette)
    ex._guard_cassette_play(cassette)  # 幂等：重复包装不叠加锁
    barrier = threading.Barrier(n)
    results = []
    exhausted = []

    def worker():
        barrier.wait()
        for _ in range(n):
            try:
                results.append(cassette.play_response("req"))
            except RuntimeError:
                exhausted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(results) == n, f"并发重复消费/丢失: {len(results)} 条"
    assert sorted(results) == [f"resp{i}" for i in range(n)]
    assert len(exhausted) == n * (n - 1)  # 其余全部明确报"已消费完"


def test_replay_mode_vlm_max_workers_one(tmp_path, monkeypatch):
    """H-12 锚点：回放模式 VLM max_workers 降为 1（vcrpy 单线程回放语义）。"""
    from web import executor as ex
    from web.executor import Executor
    from subgraphs.subgraph3.config.settings import settings as vlm_settings
    cassette = _write_cassette(tmp_path / "c.yaml", _chat_cassette_yaml("用户输入：M31 的距离"))
    monkeypatch.setattr(ex, "_CASSETTE_PATH", str(cassette))
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "none")
    saw = {}

    def fake_runner(**kwargs):
        saw["max_workers"] = vlm_settings.concurrency.max_workers
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex_obj = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        t = store.create_task("M31 的距离")
        ex_obj.submit(t["task_id"], "M31 的距离", [])
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t["task_id"])["status"] in ("queued", "running"):
            time.sleep(0.05)
        assert store.get_task(t["task_id"])["status"] == "completed"
        assert saw.get("max_workers") == 1, "回放模式 VLM 并发未降为 1"
    finally:
        ex_obj.stop()
        vlm_settings.concurrency.max_workers = 15  # 还原全局配置


# ── H-14: 默认 'none' + cassette 缺失 fail-fast ──

def test_default_record_mode_is_none():
    """H-14 锚点：LLM_RECORD_MODE 默认 'none'——未匹配即抛错，
    显式录制才用 all/once（缺失文件不再静默真实录制/计费）。"""
    from web import executor as ex
    assert ex._CASSETTE_MODE == "none"


def test_validate_cassette_missing_mode_none_raises(tmp_path):
    """H-14 单元锚点：cassette 缺失 + 'none' → 抛错（fail-fast 而非发请求）；
    显式录制模式（all/once）允许缺失；存在/未配置 → no-op。"""
    from web import executor as ex
    missing = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError, match="LLM_CASSETTE"):
        ex.validate_cassette_config(str(missing), "none")
    ex.validate_cassette_config(str(missing), "all")   # 显式录制允许创建
    ex.validate_cassette_config(str(missing), "once")
    ex.validate_cassette_config("", "none")            # 未配置 → no-op
    existing = _write_cassette(tmp_path / "ok.yaml", _chat_cassette_yaml("hi"))
    ex.validate_cassette_config(str(existing), "none")  # 存在 → no-op


def test_executor_missing_cassette_fails_fast(tmp_path, monkeypatch):
    """H-14 锚点（executor 级）：默认 'none' + cassette 缺失 → 任务 fail-fast
    （不进 runner、不发任何请求）；显式录制模式 → 正常进入。"""
    from web import executor as ex
    from web.executor import Executor
    missing = tmp_path / "nope.yaml"
    monkeypatch.setattr(ex, "_CASSETTE_PATH", str(missing))
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "none")
    called = {"n": 0}

    def fake_runner(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("web.executor.run_task_streaming", fake_runner)
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    ex_obj = Executor(bus, store, str(tmp_path / "cp.sqlite"), str(tmp_path / "out"))
    try:
        t = store.create_task("M31 的距离")
        ex_obj.submit(t["task_id"], "M31 的距离", [])
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t["task_id"])["status"] in ("queued", "running"):
            time.sleep(0.05)
        assert store.get_task(t["task_id"])["status"] in ("error", "failed")  # B7 H-01: 词表统一 error, 兼容旧 failed
        assert called["n"] == 0, "缺失 cassette 仍进入 runner（可能真实录制/计费）"
        errs = [e for e in store.get_events(t["task_id"]) if e["type"] == "error"]
        assert errs and "LLM_CASSETTE" in errs[-1].get("message", "")
        # 显式录制模式（all）→ 缺失允许，正常进入
        monkeypatch.setattr(ex, "_CASSETTE_MODE", "all")
        t2 = store.create_task("q2")
        ex_obj.submit(t2["task_id"], "q2", [])
        deadline = time.time() + 20
        while time.time() < deadline and store.get_task(t2["task_id"])["status"] in ("queued", "running"):
            time.sleep(0.05)
        assert store.get_task(t2["task_id"])["status"] == "completed"
        assert called["n"] == 1
    finally:
        ex_obj.stop()


# ── M-11: 启动自测移出 import 期（startup 钩子 + 诊断开关） ──

def test_startup_selftest_noop_failfast_and_probe(tmp_path, monkeypatch):
    """M-11/H-14 锚点：启动自测——无配置 no-op；缺失 + 'none' → 启动失败（抛错）；
    缺失 + 显式录制 → 跳过探针；存在 + 'none' → 探针不抛错（'none' 未匹配即抛错，
    探针零网络；失败仅告警不阻塞启动）。"""
    from web import main as m
    from web import executor as ex
    missing = tmp_path / "nope.yaml"
    # 1) 未配置 → no-op（import/启动无网络、无动作）
    monkeypatch.setattr(ex, "_CASSETTE_PATH", "")
    assert m._vcr_startup_selftest() is None
    # 2) 缺失 + 默认 'none' → fail-fast（启动报错退出，而非真实录制）
    monkeypatch.setattr(ex, "_CASSETTE_PATH", str(missing))
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "none")
    with pytest.raises(FileNotFoundError):
        m._vcr_startup_selftest()
    # 3) 缺失 + 显式录制模式 → 跳过探针（不抛错，首任务录制）
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "all")
    assert m._vcr_startup_selftest() is None
    # 4) 存在 + 'none' → 探针完成不抛错（未命中仅告警；'none' 下零网络）
    cassette = _write_cassette(tmp_path / "c.yaml", _chat_cassette_yaml("hi"))
    monkeypatch.setattr(ex, "_CASSETTE_PATH", str(cassette))
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "none")
    assert m._vcr_startup_selftest() is None
    # 5) 存在 + 显式录制模式 → 不做回放探针（跳过）
    monkeypatch.setattr(ex, "_CASSETTE_MODE", "once")
    assert m._vcr_startup_selftest() is None


def test_appending_log_downgraded_to_debug():
    """M-11/L-14 锚点：vcrpy 的 'Appending request/response'（响应含 58MB PDF
    内容）INFO 日志降级为 DEBUG——INFO 配置下加载期不再洪泛（141 行/9.6MB/任务）。"""
    import logging as _logging
    logger = _logging.getLogger("vcr.cassette")
    rec = _logging.LogRecord("vcr.cassette", _logging.INFO, __file__, 1,
                             "Appending request %s and response %s", ("r", "resp"), None)
    assert logger.filter(rec)
    assert rec.levelno == _logging.DEBUG
    # 非 Appending 记录不受影响
    rec2 = _logging.LogRecord("vcr.cassette", _logging.INFO, __file__, 1,
                              "Loading cassette", (), None)
    assert logger.filter(rec2)
    assert rec2.levelno == _logging.INFO


# ── L-14: 进程级单例缓存 cassette 解析（每次任务不重复全量 YAML 解析） ──

def test_cassette_parse_cache_single_load(tmp_path, monkeypatch):
    """L-14 锚点：进程级单例缓存——多次访问同一 cassette 只做一次全量 YAML
    解析（58MB 文件不再每次任务/启动重复解析）；缺失文件负缓存。"""
    import yaml as _yaml
    from web import executor as ex
    path = _write_cassette(tmp_path / "c.yaml", _chat_cassette_yaml("用户输入：M31 的距离"))
    calls = {"n": 0}
    real = _yaml.safe_load

    def counting_load(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(ex, "_CASSETTE_PARSE_CACHE", {})  # 干净缓存
    monkeypatch.setattr(_yaml, "safe_load", counting_load)
    a = ex._cassette_interactions(str(path))
    b = ex._cassette_interactions(str(path))
    assert calls["n"] == 1, "cassette 被重复解析"
    assert a is b and len(a) == 1
    c = ex._cassette_interactions(str(tmp_path / "nope.yaml"))
    d = ex._cassette_interactions(str(tmp_path / "nope.yaml"))
    assert c is None and d is None
    assert calls["n"] == 1  # 缺失也负缓存，不重复尝试


# ══════════════════════════════════════════════════════
# 批次 B5 SSE 去重簇（CR-02 / M-06）
# ══════════════════════════════════════════════════════

def test_events_history_http_endpoint(client):
    """CR-02④/D8-3 锚点：历史事件 HTTP 批量端点——回看走 HTTP、SSE 只做
    实时+断点续播；after_seq 过滤与 store.get_events 同源（DP-12 双份修复侧）。"""
    from web import main as m
    t = m.store.create_task("q")
    for i in range(3):
        m.bus.emit(t["task_id"], "message", role="user", content=f"m{i}")
    r = client.get(f"/api/tasks/{t['task_id']}/events/history")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == t["task_id"]
    assert body["events"] == m.store.get_events(t["task_id"], 0)
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]  # 升序全量
    r2 = client.get(f"/api/tasks/{t['task_id']}/events/history?after_seq=1")
    assert [e["seq"] for e in r2.json()["events"]] == [2, 3]  # 断点过滤
    assert client.get("/api/tasks/nope-404/events/history").status_code == 404


def test_sse_no_gap_events_published_during_replay(client):
    """M-06②/CR-02 锚点：先订阅再重放——重放中途发布的实时事件不丢不重
    （旧实现「重放 → subscribe」间隙丢事件）；流内无重复 seq（DP-12 后端侧）。
    旧实现下该事件落入间隙 → 永久缺失 → 本测试 wait_for 超时红测。"""
    from web import main as m
    t = m.store.create_task("q")
    m.bus.emit(t["task_id"], "message", role="user", content="m1")
    m.bus.emit(t["task_id"], "message", role="user", content="m2")

    async def _collect():
        resp = await m.stream_events(t["task_id"], 0)
        frames = []
        async for frame in resp.body_iterator:
            frames.append(json.loads(frame["data"]))
            if frames[-1]["seq"] == 2:
                # 恰在重放中途发布（旧实现该事件落入重放-订阅间隙 → 永久缺失）
                m.bus.message(t["task_id"], "user", "during-replay")
            if len(frames) >= 3:
                break
        await resp.body_iterator.aclose()
        return frames

    frames = asyncio.run(asyncio.wait_for(_collect(), timeout=5))
    assert [f["seq"] for f in frames] == [1, 2, 3]
    assert frames[-1]["content"] == "during-replay"
    assert len({f["seq"] for f in frames}) == len(frames), "流内出现重复 seq"


def test_sse_closes_after_terminal_event(client, monkeypatch):
    """M-06③ 锚点：终态事件后 TTL 超时 → 流自然关闭（不再永续占连接，
    DP-10）。旧实现流永不结束 → wait_for 超时红测。"""
    from web import main as m
    monkeypatch.setattr(m, "SSE_DONE_TTL", 0.3)
    t = m.store.create_task("q")
    m.bus.emit(t["task_id"], "message", role="user", content="m1")
    m.bus.emit(t["task_id"], "task_completed")

    async def _collect():
        resp = await m.stream_events(t["task_id"], 0)
        frames = []
        async for frame in resp.body_iterator:  # async for 自然结束才返回
            frames.append(json.loads(frame["data"]))
        return frames

    frames = asyncio.run(asyncio.wait_for(_collect(), timeout=5))
    assert [f["type"] for f in frames] == ["message", "task_completed"]


def test_sse_done_ttl_delivers_trailing_then_closes(client, monkeypatch):
    """M-06③ 锚点（M-12 联动）：终态后 TTL 收尾窗口内尾随事件（慢 ai 总结）
    仍投递，窗口超时后关闭。"""
    from web import main as m
    # 时序余量：全量测试高负载下事件循环调度延迟可能错过过窄的 TTL 窗口
    # （晚发 0.1s vs 窗口 0.4s 曾偶发 flaky）→ 窗口放宽至 2.0s，机制语义不变
    monkeypatch.setattr(m, "SSE_DONE_TTL", 2.0)
    t = m.store.create_task("q")
    m.bus.emit(t["task_id"], "message", role="user", content="m1")
    m.bus.emit(t["task_id"], "task_completed")

    async def _late_ai():
        await asyncio.sleep(0.1)
        m.bus.message(t["task_id"], "ai", "尾随总结")

    async def _collect():
        resp = await m.stream_events(t["task_id"], 0)
        frames = []
        async for frame in resp.body_iterator:
            frames.append(json.loads(frame["data"]))
        return frames

    async def _main():
        late = asyncio.create_task(_late_ai())
        frames = await asyncio.wait_for(_collect(), timeout=5)
        await late
        return frames

    frames = asyncio.run(_main())
    assert [f["type"] for f in frames] == ["message", "task_completed", "message"]
    assert frames[-1]["role"] == "ai"  # TTL 窗口内尾随事件不丢


def test_event_bus_dropped_range_and_critical_kept(tmp_path):
    """M-06① 锚点：队列满时仅丢 log/step_progress 并记录 dropped_seq 合并区间；
    关键事件腾位入队不丢（移除队内最旧可丢事件，锚点：关键事件不丢）。"""
    from web.event_bus import EventQueue
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")
    q = EventQueue(maxsize=5)
    bus.subscribe(t["task_id"], q)
    for i in range(7):
        bus.emit(t["task_id"], "log", node="n", level="info", message=f"m{i}")  # seq 1..7
    assert q.dropped == [(6, 7)] and len(q) == 5
    bus.emit(t["task_id"], "message", role="ai", content="critical")  # seq 8 关键
    assert q.dropped == [(6, 7), (1, 1)], f"dropped={q.dropped}"  # 按发生顺序
    assert len(q) == 5
    got = []
    while True:
        try:
            got.append(q.get_nowait()["seq"])
        except asyncio.QueueEmpty:
            break
    assert got == [2, 3, 4, 5, 8]  # seq1 被腾位、seq6-7 被丢弃，关键 seq8 不丢
    assert len(store.get_events(t["task_id"])) == 8  # 落库不受队列策略影响
    bus.unsubscribe(t["task_id"], q)


def test_event_bus_publish_threadsafe_from_worker_thread(tmp_path):
    """M-06④ 锚点：订阅时捕获归属 loop → 执行器线程发布经
    loop.call_soon_threadsafe 投递（跨线程 put_nowait 安全化）。"""
    from web.event_bus import EventQueue
    store = TaskStore(tmp_path / "t.db")
    bus = EventBus(store)
    t = store.create_task("q")

    async def _run():
        q = EventQueue()
        bus.subscribe(t["task_id"], q)
        assert bus._subscribers[t["task_id"]][0][1] is not None, "loop 未在订阅时捕获"

        def _pub():
            bus.publish(t["task_id"], {"type": "message", "role": "ai", "content": "cross-thread"})

        th = threading.Thread(target=_pub)
        th.start()
        th.join()
        deadline = time.time() + 3
        while True:
            try:
                ev = q.get_nowait()
                break
            except asyncio.QueueEmpty:
                if time.time() > deadline:
                    raise AssertionError("跨线程事件未投递（call_soon_threadsafe 失效）")
                await asyncio.sleep(0.01)
        assert ev["seq"] == store.last_seq(t["task_id"])
        assert ev["type"] == "message" and ev["content"] == "cross-thread"
        bus.unsubscribe(t["task_id"], q)

    asyncio.run(_run())


# ══════════════════════════════════════════════════════
# B10 上传与任务创建（L-15 扩展名校验 / M-10 move 原子性）
# ══════════════════════════════════════════════════════

def test_upload_rejects_disguised_extension(client):
    """L-15 锚点：扩展名非 .pdf 的文件（即使 %PDF 魔数可伪造）计入 rejected。"""
    r = client.post("/api/upload", files={"files": ("a.txt", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["pdf_ids"] == [] and len(body["rejected"]) == 1
    assert "扩展名" in body["rejected"][0]["reason"]


def test_create_task_conflicting_pdf_id_409_no_orphan(client, monkeypatch):
    """M-10 锚点：同 pdf_id 被两任务引用 → 第二个 move 失败 → 409 + 任务 cancelled
    （不再 500 + 永久 queued 孤儿）。"""
    from web import main as m
    monkeypatch.setattr("web.executor.run_task_streaming", lambda **kwargs: {})
    up = client.post("/api/upload", files={"files": ("p.pdf", b"%PDF-1.4", "application/pdf")}).json()
    pid = up["pdf_ids"][0]

    r1 = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": [pid]})
    assert r1.status_code == 200
    tid1 = r1.json()["task_id"]

    # 第二个任务引用同一 pdf_id：校验仍通过（文件已被 A move，不存在 → 400 先行）
    # 直接绕过校验验证 move 失败路径：文件不存在时校验层 400；为覆盖 move 层，
    # 构造"校验通过但 move 失败"：手动把文件放回暂存区后立即删除（TOCTOU 模拟）
    src = m.UPLOAD_DIR / f"{pid}.pdf"
    if not src.exists():
        # 文件已被 A 移走 → 校验层直接 400（D4-6 语义），无孤儿任务
        r2 = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": [pid]})
        assert r2.status_code == 400
    else:
        r2 = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": [pid]})
        assert r2.status_code in (400, 409)
    # 无 queued 孤儿：列表里不应出现第二个 running/queued 同 query 任务
    tasks = client.get("/api/tasks").json()["items"]
    same = [t for t in tasks if t["task_id"] != tid1 and t["title"] == "M31 的距离"]
    assert not any(t["status"] in ("queued", "running") for t in same), same


# ══════════════════════════════════════════════════════
# B11 数据交付导出（M-18 导出目录与任务绑定）
# ══════════════════════════════════════════════════════

def test_exports_resolves_task_bound_directory(client, monkeypatch):
    """M-18 锚点：导出文件落在 output/{task_id[:8]}/（run_id=query_id=task_id），
    /exports 与 /export/{file} 从该目录服务（此前扫描 tasks.output_dir 恒空）。"""
    from web import main as m
    monkeypatch.setattr("web.executor.run_task_streaming", lambda **kwargs: {})
    r = client.post("/api/tasks", json={"query": "M31 的距离", "pdf_ids": []})
    assert r.status_code == 200
    tid = r.json()["task_id"]

    # 任务目录（user_pdfs 等）与导出目录分离：导出目录 = output/{tid[:8]}/
    export_dir = m.OUTPUT_DIR / tid[:8]
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "grounded_data_2026.json").write_text('{"a": 1}', encoding="utf-8")
    (export_dir / "manifest_2026.json").write_text('{"b": 2}', encoding="utf-8")

    ex = client.get(f"/api/tasks/{tid}/exports").json()
    assert isinstance(ex, list) and len(ex) >= 2, f"exports 应非空，got {ex}"
    names = {i["name"] for i in ex}
    assert "grounded_data_2026.json" in names and "manifest_2026.json" in names

    dl = client.get(f"/api/tasks/{tid}/export/grounded_data_2026.json")
    assert dl.status_code == 200


# ══════════════════════════════════════════════════════
# B12 安全与图证（H-06 image_url 修复 / L-04 open-file 分隔符 / H-05 CORS）
# ══════════════════════════════════════════════════════

def test_figures_image_url_uses_image_path(client):
    """H-06 锚点：image_url 由生产字段 image_path（figures/{qid}/{fname}）推导，
    不再读不存在的 file_name（此前恒 404）。"""
    from web import main as m
    t = m.store.create_task("q")
    m.store.update_task(t["task_id"], state_json=json.dumps({
        "final_output": {
            "figure_evidence": [
                {"figure_id": "f1", "source_id": "s1", "page": 3,
                 "bbox": [1, 2, 3, 4], "caption": "c",
                 "image_path": f"figures/{t['task_id']}/a_p3_f1.png"},
            ],
        },
    }))
    body = client.get(f"/api/tasks/{t['task_id']}/figures").json()
    assert len(body) == 1
    assert body[0]["image_url"] == f"/static/figures/{t['task_id']}/a_p3_f1.png"


def test_open_file_rejects_path_separator(client, monkeypatch):
    """L-04 锚点：open-file 的 name 含分隔符（../ 等）→ 404（JSON body 不可穿越）。"""
    from web import main as m
    monkeypatch.setattr(m, "_os_open", lambda p: None)  # 不真打开
    t = m.store.create_task("q")
    (m.OUTPUT_DIR / t["task_id"][:8]).mkdir(parents=True, exist_ok=True)
    r = client.post(f"/api/tasks/{t['task_id']}/open-file", json={"name": "../main.py"})
    assert r.status_code == 404
    r2 = client.post(f"/api/tasks/{t['task_id']}/open-file", json={"name": "a/b.csv"})
    assert r2.status_code == 404


# ══════════════════════════════════════════════════════
# 事件级重放（2026-08-27：web/replayer.py + executor 分流）
# ══════════════════════════════════════════════════════

_SUMMARY_TEXT = "任务完成总结：共提取 10 条记录。"


def _make_source_task(store, with_clarification=False):
    """构造一个 completed 源任务：带 ts 的完整事件序列 + state_json。"""
    src = store.create_task("M45 的距离")
    src_id = src["task_id"]
    evs = [
        {"type": "stage_started", "stage_id": "understand", "name": "任务理解"},
        {"type": "step_progress", "stage_id": "understand", "step": "confirm", "status": "completed"},
    ]
    if with_clarification:
        evs.append({"type": "clarification", "cl_type": "final_confirm", "stage_id": "understand",
                    "title": "确认查询", "question": "请确认目标天体", "fields": [{"label": "目标", "value": "M45"}]})
        evs.append({"type": "clarification_answered", "answer": "y"})  # 重放应跳过（live resume 重新落库）
    evs += [
        {"type": "stage_completed", "stage_id": "understand", "duration": 5.0, "status": "completed"},
        {"type": "stage_started", "stage_id": "retrieval", "name": "数据检索"},
        {"type": "step_progress", "stage_id": "retrieval", "step": "database/match", "status": "completed",
         "data": {"matched_catalogs": 3, "total_queries": 4}},
        {"type": "agent_started", "stage_id": "quality_check", "agent": "ProfilingAgent"},
        {"type": "agent_completed", "stage_id": "quality_check", "agent": "ProfilingAgent",
         "duration": 1.2, "reason": "8 tools"},
        {"type": "flow_started", "stage_id": "clean", "flow_id": "normalization", "round": 1},
        {"type": "flow_completed", "stage_id": "clean", "flow_id": "normalization", "round": 1},
        {"type": "stage_completed", "stage_id": "done", "duration": 0, "status": "completed"},
        {"type": "message", "role": "ai", "content": _SUMMARY_TEXT},
        {"type": "task_completed", "summary": "任务完成"},
        {"type": "task_title_ready", "task_id": src_id, "title": "M45 查询"},
    ]
    for i, ev in enumerate(evs):
        store.append_event(src_id, ev, ts=1000.0 + i * 0.05)  # 全部带 ts（模拟新真实任务）
    store.update_task(src_id, status="completed", state_json=json.dumps({
        "target_entity": "M45",
        "final_output": {
            "records": [{"record_id": "r1", "entity_name": "M45", "field_name": "age",
                         "field_value": "100", "field_unit": "Myr"}],
            "sources": [], "figure_evidence": [],
        },
    }))
    return src_id


def _wait_status(store, task_id, statuses, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = store.get_task(task_id)["status"]
        if st in statuses:
            return st
        time.sleep(0.05)
    raise AssertionError(f"task {task_id[:8]} 未在 {timeout}s 内到达 {statuses}（当前 {store.get_task(task_id)['status']}）")


def _wait_replay_completed(store, rid, timeout=30):
    """等回放任务稳定完成：status=completed **且** task_completed/尾随 message 均已落库。

    _finish 内 status 落库 → emit task_completed → publish message 之间存在落库间隙，
    只轮询 status 可能恰在间隙中读到 completed（全量高负载下必现）。以尾部 message
    （回放正常完成的最后落库事件）作为完成标志，消除竞态窗口。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = store.get_task(rid)
        evs = store.get_events(rid, 0)
        if rec and rec["status"] == "completed" and evs and evs[-1]["type"] == "message":
            return
        time.sleep(0.05)
    raise AssertionError(f"replay {rid[:8]} 未稳定完成（status={store.get_task(rid)['status']}）")


def test_replay_migration_idempotent(tmp_path):
    """老 schema 库初始化两遍无错；tasks.replay_of / events.ts 列迁移齐全。"""
    import sqlite3 as _s
    db = tmp_path / "old.db"
    con = _s.connect(db)
    con.execute("""CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY, query TEXT NOT NULL, title TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL,
        completed_at TEXT, output_dir TEXT DEFAULT '', pdf_paths TEXT DEFAULT '[]',
        state_json TEXT DEFAULT '{}')""")
    con.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, payload TEXT NOT NULL)")
    con.commit()
    con.close()

    TaskStore(db)  # 第一次初始化（触发迁移）
    TaskStore(db)  # 第二次（幂等）
    cols = {r[1] for r in _s.connect(db).execute("PRAGMA table_info(tasks)")}
    assert "replay_of" in cols
    ecols = {r[1] for r in _s.connect(db).execute("PRAGMA table_info(events)")}
    assert "ts" in ecols
    # 新库直接建全（不依赖 ALTER）
    store2 = TaskStore(tmp_path / "new.db")
    assert store2.create_task("q", replay_of="src-id")["replay_of"] == "src-id"


def test_replay_interval_between_clamp_and_defaults():
    from web.replayer import interval_between
    # 无 ts → 类型默认
    assert interval_between(None, None, "log", 10) == 0.04
    assert interval_between(1.0, None, "stage_started", 10) == 0.15
    assert interval_between(None, 1.0, "unknown_type", 10) == 0.15
    # 有 ts → 除速 + 下界钳制（2026-08-27：上限取消，长停顿真实等比）
    assert interval_between(0, 0.1, "stage_started", 10) == 0.02   # 下界钳制（0.01 → 0.02）
    assert interval_between(0, 30000, "stage_started", 1) == 30000.0  # 无上限（真实等比）
    assert interval_between(0, 60, "stage_started", 10) == 6.0     # 60ms/10 → 无上限
    assert interval_between(0, 0.6, "stage_started", 1) == 0.6     # 正常除速


def test_replay_endpoint_guards(client):
    """404 + 409 守卫：不存在 / 非终态 / 非 completed / 空事件 / 已有活跃回放。"""
    from web import main as m
    # 404
    assert client.post("/api/tasks/nope/replay", json={}).status_code == 404
    # queued 源
    q = m.store.create_task("q1")
    assert client.post(f"/api/tasks/{q['task_id']}/replay", json={}).status_code == 409
    # error 源（v1 仅允许 completed）
    e = m.store.create_task("q2")
    m.store.update_task(e["task_id"], status="error")
    assert client.post(f"/api/tasks/{e['task_id']}/replay", json={}).status_code == 409
    # completed 但无事件
    c = m.store.create_task("q3")
    m.store.update_task(c["task_id"], status="completed")
    assert client.post(f"/api/tasks/{c['task_id']}/replay", json={}).status_code == 409
    # 已有活跃回放（人为造一行 queued 回放）→ 409
    src = _make_source_task(m.store)
    m.store.create_task("回放：q", replay_of=src)
    assert client.post(f"/api/tasks/{src}/replay", json={}).status_code == 409


def test_replay_run_event_order_and_tail(client):
    """回放任务事件序列：跳过生命周期/澄清回答/源 message；唯一 task_completed
    后紧跟 message(ai, 源总结)；源 events 不变。"""
    from web import main as m
    src = _make_source_task(m.store)
    src_events = m.store.get_events(src, 0)
    r = client.post(f"/api/tasks/{src}/replay", json={"speed": 100})
    assert r.status_code == 200
    rid = r.json()["task_id"]
    assert r.json()["replay_of"] == src
    _wait_replay_completed(m.store, rid)

    evs = m.store.get_events(rid, 0)
    types = [e["type"] for e in evs]
    # 回放任务自身生命周期允许：task_started（executor 正常发出）；其余源跳过类不得残留
    assert types.count("task_started") == 1
    for t in ("task_queued", "task_title_ready", "task_cancelled", "task_failed",
              "clarification_answered"):
        assert t not in types
    assert types.count("task_completed") == 1
    assert types.count("message") == 1
    # message(ai 总结) 紧随 task_completed（真实时序同构 → 前端 awaitSummary 关流）
    assert evs[-2]["type"] == "task_completed"
    assert evs[-1]["type"] == "message" and evs[-1]["role"] == "ai"
    assert evs[-1]["content"] == _SUMMARY_TEXT
    # 源 events 未被修改
    assert m.store.get_events(src, 0) == src_events
    # 回放任务行：replay_of + state_json 已拷贝为源最终 state
    rec = m.store.get_task(rid)
    assert rec["replay_of"] == src and rec["status"] == "completed"
    assert json.loads(rec["state_json"]).get("target_entity") == "M45"


def test_replay_payload_no_stale_seq(client):
    """直连 run_replay：payload 剥离 seq/ts/task_id；行级 ts 落库；type 集合=源（剔除跳过类）。"""
    import sqlite3 as _s
    from web import main as m
    from web.replayer import run_replay
    src = _make_source_task(m.store)
    t = m.store.create_task("回放：q", replay_of=src)
    out = run_replay(m.bus, m.store, t["task_id"], src, speed=100,
                     sleep=lambda d: None)  # 即时睡眠
    assert out["cancelled"] is False
    assert json.loads(out["state_json_text"])["target_entity"] == "M45"
    con = _s.connect(str(m.DB_PATH))
    rows = con.execute(
        "SELECT payload, ts FROM events WHERE task_id=?", (t["task_id"],)).fetchall()
    assert rows, "回放任务无事件"
    expected = {e["type"] for e in m.store.get_events(src, 0)
                if e["type"] not in {"task_queued", "task_started", "task_completed",
                                     "task_cancelled", "task_failed", "task_title_ready",
                                     "clarification_answered", "message"}}
    actual = set()
    for payload_text, ts in rows:
        p = json.loads(payload_text)
        assert "seq" not in p, "payload 残留旧 seq（会覆盖 EventBus 注入的新 seq）"
        assert "ts" not in p and "task_id" not in p
        assert ts is not None, "行级 ts 未落库"
        actual.add(p["type"])
    assert actual == expected
    con.close()


def test_replay_clarification_waits_and_resume(client):
    """澄清事件真实等待：resume 前后续事件不落库；/state pending_clarification 非空；
    resume 后继续直至 completed。"""
    from web import main as m
    src = _make_source_task(m.store, with_clarification=True)
    r = client.post(f"/api/tasks/{src}/replay", json={"speed": 100})
    rid = r.json()["task_id"]
    # 等澄清事件落地
    deadline = time.time() + 10
    while time.time() < deadline:
        evs = m.store.get_events(rid, 0)
        if evs and evs[-1]["type"] == "clarification":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("澄清事件未到达")
    # 澄清等待期间：澄清必须是末事件（get_answer 阻塞 → 源后续事件不得落库）
    assert [e["type"] for e in evs][-1] == "clarification"
    # /state 挂起判定（slot waiting + 末事件 clarification + running）
    snap = client.get(f"/api/tasks/{rid}/state").json()
    assert snap["pending_clarification"] is not None
    assert snap["pending_clarification"]["cl_type"] == "final_confirm"
    # resume → 继续 → completed
    assert client.post(f"/api/tasks/{rid}/resume", json={"answer": "y"}).status_code == 200
    _wait_replay_completed(m.store, rid)
    types = [e["type"] for e in m.store.get_events(rid, 0)]
    # 源事件中的 clarification_answered 被跳过；resume 时 executor 落一条新 answered
    assert types.count("clarification_answered") == 1
    assert types[-2] == "task_completed" and types[-1] == "message"


def test_replay_clarification_timeout_cancels(client, monkeypatch):
    """澄清等待超时 → fatal error + task_cancelled + cancelled；无 task_completed。"""
    from web import main as m
    monkeypatch.setattr("web.executor.CLARIFICATION_TIMEOUT", 0.3)
    src = _make_source_task(m.store, with_clarification=True)
    r = client.post(f"/api/tasks/{src}/replay", json={"speed": 100})
    rid = r.json()["task_id"]
    _wait_status(m.store, rid, {"cancelled"})
    types = [e["type"] for e in m.store.get_events(rid, 0)]
    assert "task_cancelled" in types
    assert "task_completed" not in types
    errs = [e for e in m.store.get_events(rid, 0) if e["type"] == "error"]
    assert any(e.get("level") == "fatal" for e in errs)
    # 取消后 state_json 未被源 state 覆盖（保留 replay_meta）
    assert "replay_meta" in json.loads(m.store.get_task(rid)["state_json"])


def test_replay_cancel_midway(client):
    """回放中途取消 → cancelled、无 task_completed、无 message 补发。"""
    from web import main as m
    src = m.store.create_task("M45 的距离")["task_id"]
    for i in range(50):  # 50 条 log × 0.1s(ts) / speed=1 → 总时长 ~5s，足够中途取消
        m.store.append_event(src, {"type": "log", "node": "main_graph", "level": "INFO",
                                   "message": f"log {i}"}, ts=1000.0 + i * 0.1)
    m.store.update_task(src, status="completed", state_json="{}")
    r = client.post(f"/api/tasks/{src}/replay", json={"speed": 1})
    rid = r.json()["task_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        if len(m.store.get_events(rid, 0)) >= 3:
            break
        time.sleep(0.05)
    assert client.post(f"/api/tasks/{rid}/cancel").status_code == 200
    _wait_status(m.store, rid, {"cancelled"})
    types = [e["type"] for e in m.store.get_events(rid, 0)]
    assert "task_completed" not in types
    assert "message" not in types
    # 取消后可再次重放
    r2 = client.post(f"/api/tasks/{src}/replay", json={"speed": 100})
    assert r2.status_code == 200


def test_replay_state_copy_and_endpoint_mapping(client):
    """回放完成后数据端点映射到源：/records /quality /result 一致；/figures 指向源 id；
    /exports 走源目录；/state 与 /events 是回放自己的。"""
    from web import main as m
    src = m.store.create_task("M45 的距离")["task_id"]
    src_state = {
        "target_entity": "M45",
        "final_output": {
            "records": [{"record_id": "r1", "entity_name": "M45", "field_name": "age",
                         "field_value": "100", "field_unit": "Myr"}],
            "quality_report": {
                "output_state": {"structured_data": {"json": {
                    "records": [{"record_id": "r1", "entity_name": "M45", "field_name": "age",
                                 "field_value": "100", "field_unit": "Myr", "provenance": {}}],
                    "sources": [],
                }}},
                "report_state": {"quality": {"quality_scoring": {"overall_score": 0.9}}},
            },
            "figure_evidence": [{"figure_id": "f1", "source_id": "s1", "page": 3,
                                 "bbox": [1, 2, 3, 4], "caption": "c",
                                 "image_path": f"figures/{src}/a_p3_f1.png"}],
        },
    }
    m.store.update_task(src, status="completed", state_json=json.dumps(src_state))
    # 源结果/导出/图证文件
    (m.OUTPUT_DIR / src[:8]).mkdir(parents=True, exist_ok=True)
    (m.OUTPUT_DIR / src[:8] / "data.csv").write_text("a,b\n")
    (m.OUTPUT_DIR / "figures" / src).mkdir(parents=True, exist_ok=True)
    (m.OUTPUT_DIR / "figures" / src / "a_p3_f1.png").write_bytes(b"png")
    for ev in [{"type": "stage_started", "stage_id": "understand", "name": "任务理解"},
               {"type": "stage_completed", "stage_id": "understand", "duration": 1.0, "status": "completed"},
               {"type": "stage_completed", "stage_id": "done", "duration": 0, "status": "completed"},
               {"type": "message", "role": "ai", "content": _SUMMARY_TEXT},
               {"type": "task_completed", "summary": "任务完成"}]:
        m.store.append_event(src, ev, ts=time.time())
    r = client.post(f"/api/tasks/{src}/replay", json={"speed": 100})
    rid = r.json()["task_id"]
    _wait_replay_completed(m.store, rid)
    # /records（质量管线记录）、/quality、/result 与源一致
    assert client.get(f"/api/tasks/{rid}/records").json() == client.get(f"/api/tasks/{src}/records").json()
    assert client.get(f"/api/tasks/{rid}/quality").json() == client.get(f"/api/tasks/{src}/quality").json()
    assert client.get(f"/api/tasks/{rid}/result").json()["records"][0]["record_id"] == "r1"
    # /figures image_url 前缀为源 id（静态路由文件在源目录）
    figs = client.get(f"/api/tasks/{rid}/figures").json()
    assert figs[0]["image_url"].startswith(f"/static/figures/{src}/")
    # /exports 走源导出目录
    exps = client.get(f"/api/tasks/{rid}/exports").json()
    assert any(f["name"] == "data.csv" for f in exps)
    assert client.get(f"/api/tasks/{rid}/export/data.csv").status_code == 200
    # /state 是回放自己的事件（数量 ≠ 源），state 与源一致
    snap = client.get(f"/api/tasks/{rid}/state").json()
    assert snap["task"]["replay_of"] == src
    assert len(snap["events"]) < len(m.store.get_events(src, 0)) or snap["events"]
    assert snap["state"]["target_entity"] == "M45"
    # /events/history 仅回放事件
    hist = client.get(f"/api/tasks/{rid}/events/history").json()["events"]
    assert all(e["seq"] in {x["seq"] for x in m.store.get_events(rid, 0)} for e in hist)


def test_replay_of_replay_flattens(client):
    """嵌套重放扁平化：重放一个回放任务 → replay_of 指向最上游源。"""
    from web import main as m
    src = _make_source_task(m.store)
    r1 = client.post(f"/api/tasks/{src}/replay", json={"speed": 100}).json()
    _wait_replay_completed(m.store, r1["task_id"])
    r2 = client.post(f"/api/tasks/{r1['task_id']}/replay", json={"speed": 100}).json()
    assert r2["replay_of"] == src
    assert m.store.get_task(r2["task_id"])["replay_of"] == src
    # 等 r2 完成再结束——遗留的 daemon 回放线程在全量高负载下会饿死后续测试
    _wait_replay_completed(m.store, r2["task_id"])


def test_delete_source_cascades_replays(client):
    """整删/批删源 → 级联删除回放行 + events。"""
    from web import main as m
    src = _make_source_task(m.store)
    rid = client.post(f"/api/tasks/{src}/replay", json={"speed": 100}).json()["task_id"]
    _wait_replay_completed(m.store, rid)
    assert m.store.get_task(rid) is not None
    assert client.delete(f"/api/tasks/{src}").status_code == 200
    assert m.store.get_task(rid) is None
    assert m.store.get_events(rid, 0) == []
    # 批删
    src2 = _make_source_task(m.store)
    rid2 = client.post(f"/api/tasks/{src2}/replay", json={"speed": 100}).json()["task_id"]
    _wait_status(m.store, rid2, {"completed"})
    br = client.post("/api/tasks/batch-delete", json={"task_ids": [src2]}).json()
    assert br["results"][0]["deleted"] is True
    assert m.store.get_task(rid2) is None


def test_delete_source_blocked_by_active_replay(client):
    """源存在活跃（queued/running）回放 → 单删 409 / 批删 reason=active_replay。"""
    from web import main as m
    src = _make_source_task(m.store)
    m.store.create_task("回放：q", replay_of=src)  # 人为造活跃回放行（queued）
    assert client.delete(f"/api/tasks/{src}").status_code == 409
    br = client.post("/api/tasks/batch-delete", json={"task_ids": [src]}).json()
    assert br["results"][0]["deleted"] is False
    assert br["results"][0]["reason"] == "active_replay"


def test_update_task_title(client):
    """手动改名（2026-08-27）：PUT /tasks/{id}/title —— 404/400/成功 + 列表联动。"""
    from web import main as m
    t = m.store.create_task("原始查询")
    # 404
    assert client.put("/api/tasks/nope/title", json={"title": "x"}).status_code == 404
    # 400 空/超长
    assert client.put(f"/api/tasks/{t['task_id']}/title", json={"title": "  "}).status_code == 400
    assert client.put(f"/api/tasks/{t['task_id']}/title", json={"title": "x" * 101}).status_code == 400
    # 成功
    r = client.put(f"/api/tasks/{t['task_id']}/title", json={"title": " 自定义任务名 "})
    assert r.status_code == 200 and r.json()["title"] == "自定义任务名"
    # 落库 + 详情可见
    assert m.store.get_task(t["task_id"])["title"] == "自定义任务名"
    assert client.get(f"/api/tasks/{t['task_id']}").json()["title"] == "自定义任务名"
