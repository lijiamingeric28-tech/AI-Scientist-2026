"""FastAPI 应用装配 —— 契约端点全量实现（模块 ① + ② 接线）。

运行：
    python -m web.main            # 127.0.0.1:8000
    uvicorn web.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from events import configure as configure_emitter
from astroquery_ai.config import get_settings

from .event_bus import EventBus, EventQueue
from .executor import Executor
from .task_store import TaskStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("web")

# ── 路径配置 ──
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent
DATA_DIR = WEB_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "tasks.db"
CHECKPOINT_PATH = DATA_DIR / "checkpoints.sqlite"
OUTPUT_DIR = ROOT / "output"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # D4-1: 50MB 统一口径
MAX_QUERY_LEN = 500  # D4-5

for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ── 核心单例 ──
store = TaskStore(DB_PATH)
bus = EventBus(store)


# 模块⑤：LLM 总结（契约 D1-5：qwen3.7-flash；失败降级模板）
from .summary import generate_final_summary, generate_task_title


def _summary_fn(task_id: str, state: Dict[str, Any]) -> str:
    # runner 直接传最终 state（web_runner 顺序修复：不再从 store 读未落库的快照）
    return generate_final_summary(task_id, state or {})


def _title_fn(task_id: str, query: str, state: Dict[str, Any]) -> str:
    return generate_task_title(query, state)


executor = Executor(
    bus, store, str(CHECKPOINT_PATH), str(OUTPUT_DIR),
    summary_fn=_summary_fn, title_fn=_title_fn,
)
configure_emitter(bus.publish)  # subgraphs 埋点接入总线
from .log_bridge import install as install_log_bridge
install_log_bridge(bus)  # 节点 logger → SSE log 事件（契约 D3-3）

# 启动诊断：确认 executor 的 VCR 回放配置（LLM_CASSETTE）
import web.executor as _ex
logger.info("[Web] executor LLM_CASSETTE=%r mode=%r", _ex._CASSETTE_PATH, _ex._CASSETTE_MODE)


def _vcr_startup_selftest() -> None:
    """M-11/H-14: VCR 启动自测（移出模块 import 期——import 零网络、零阻塞、日志可控）。

    - 未配置 LLM_CASSETTE → 直接返回（无任何自测动作）
    - cassette 缺失 + 默认 'none' → fail-fast（启动报错退出，绝不静默真实录制/计费）
    - cassette 缺失 + 显式录制模式 → 跳过探针（M-11：先 exists() 检查，避免探针误入录制）
    - cassette 存在 + 'none' → 诊断探针（'none' 下未匹配即抛错，探针不会产生网络请求；
      timeout=3s 不阻塞启动路径，失败仅告警）
    """
    from .executor import _CASSETTE_PATH, _CASSETTE_MODE, validate_cassette_config
    if not _CASSETTE_PATH:
        return
    cp = Path(_CASSETTE_PATH)
    # H-14: 缺失 + 非显式录制 → 抛错（启动失败），日志不再谎报 "(replay)"
    validate_cassette_config(_CASSETTE_PATH, _CASSETTE_MODE)
    if not cp.exists():
        logger.warning(
            "[Web] VCR 录制模式（%s），cassette 尚不存在（首次任务将录制）: %s",
            _CASSETTE_MODE, _CASSETTE_PATH,
        )
        return
    if _CASSETTE_MODE != "none":
        return  # 显式录制模式不做回放探针
    try:
        from .executor import _build_replay_vcr
        _vcrt, _cp = _build_replay_vcr(_CASSETTE_PATH, "none")
        with _vcrt.use_cassette(_cp.name) as _cass:
            from openai import OpenAI
            _cfg = get_settings()
            _base = _cfg.dashscope_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            _c = OpenAI(api_key="x", base_url=_base)
            _c.chat.completions.create(
                model=_cfg.dashscope_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
                timeout=3,  # M-11: 3s 上限，不阻塞启动路径
            )
            logger.info("[Web] VCR 启动自测: play_count=%s (回放模式已生效)", _cass.play_count)
    except Exception as _exc:
        logger.warning("[Web] VCR 启动自测失败（回放诊断，不影响启动）: %s", _exc)

app = FastAPI(title="AstroQuery AI Web", version="2.0.0")
# H-05①: CORS 白名单（本地开发端口），禁用 *——任意网页不再能跨源读取
# 任务数据 / 调用 API（含无认证的 PUT /api/config 投毒）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════
# 上传（D4：暂存区 → 任务创建时 Move）
# ══════════════════════════════════════════════════════

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    pdf_ids: List[str] = []
    rejected: List[Dict[str, str]] = []
    for f in files:
        name = f.filename or "?"
        # D4-2（L-15）: 扩展名白名单（%PDF 魔数可伪造，扩展名维度独立校验）
        if Path(name).suffix.lower() != ".pdf":
            rejected.append({"name": name, "reason": "扩展名不是 .pdf"})
            continue
        # M-09: 分块读取（1MB/块），累计超限立即截断拒绝——不再整文件读入内存
        # （此前 2GB 上传先 read 全量进内存再判 50MB，峰值≈文件大小 → OOM）
        total = 0
        chunks: List[bytes] = []
        while True:
            chunk = await f.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                rejected.append({"name": name, "reason": f"超过 50MB 限制（{total//1024//1024}MB）"})
                chunks = None
                break
            chunks.append(chunk)
        if chunks is None:
            continue
        data = b"".join(chunks)
        # D4-2: %PDF 魔数校验
        if not data.startswith(b"%PDF"):
            rejected.append({"name": name, "reason": "非 PDF 文件（文件头校验失败）"})
            continue
        pid = uuid.uuid4().hex
        (UPLOAD_DIR / f"{pid}.pdf").write_bytes(data)
        pdf_ids.append(pid)
    return {"pdf_ids": pdf_ids, "rejected": rejected}


def _normalize_status(status: str) -> str:
    """H-01: 失败状态词表归一——旧词表 'failed' → 'error'（契约 D8 状态映射表；
    executor 自 B7 起写 'error'，此处兼容存量 'failed' 记录，前端无需感知）。"""
    return "error" if status == "failed" else status


# ══════════════════════════════════════════════════════
# 任务（创建 / 列表 / 详情 / 状态机）
# ══════════════════════════════════════════════════════

class TaskCreateBody(BaseModel):
    query: str
    pdf_ids: List[str] = []


@app.post("/api/tasks")
async def create_task(body: TaskCreateBody):
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "查询不能为空")
    if len(query) > MAX_QUERY_LEN:
        raise HTTPException(400, f"查询超长（上限 {MAX_QUERY_LEN} 字符）")
    # D4-6: pdf_ids 整体校验（任一不存在 → 400）
    if body.pdf_ids:
        missing = [pid for pid in body.pdf_ids if not (UPLOAD_DIR / f"{pid}.pdf").exists()]
        if missing:
            raise HTTPException(400, f"pdf_id 不存在: {missing[:5]}")
    task = store.create_task(query, output_dir=str(OUTPUT_DIR / "pending"))
    # D4-3: 暂存区 Move → 任务目录（user_pdfs/）
    task_dir = OUTPUT_DIR / task["task_id"]
    pdf_dir = task_dir / "user_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    moved: List[str] = []
    try:
        # M-10: pdf_ids 去重 + 逐文件 move；失败即回滚任务行（不再产生
        # 永久 queued 孤儿 + 500。TOCTOU：校验与 move 之间并发同 pdf_id 时
        # 第二个 move 抛 FileNotFoundError → 捕获 → 409 明确语义）
        seen: set = set()
        for pid in body.pdf_ids:
            if pid in seen:
                continue
            seen.add(pid)
            src = UPLOAD_DIR / f"{pid}.pdf"
            dst = pdf_dir / f"{pid}.pdf"
            shutil.move(str(src), str(dst))
            moved.append(str(dst))
    except FileNotFoundError:
        store.update_task(task["task_id"], status="cancelled")
        raise HTTPException(409, "pdf 文件已被其他任务占用或不存在")
    store.update_task(task["task_id"], output_dir=str(task_dir), pdf_paths=json.dumps(moved))
    executor.submit(task["task_id"], query, moved)
    return {"task_id": task["task_id"], "status": "queued", "created_at": task["created_at"]}


@app.get("/api/tasks")
async def list_tasks(limit: int = 50, offset: int = 0, status: Optional[str] = None):
    limit = min(max(limit, 1), 200)  # D8-4: 强制 limit/offset
    data = store.list_tasks(limit=limit, offset=max(offset, 0), status=status)
    for item in data["items"]:  # H-01: 存量 failed 记录归一为 error
        item["status"] = _normalize_status(item["status"])
    return data


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    rec["status"] = _normalize_status(rec["status"])  # H-01
    # 2026-08-24: 任务行不带 state_json（10MB+，重度数据走 /state 裁剪版）
    rec.pop("state_json", None)
    return rec


@app.get("/api/tasks/{task_id}/state")
async def get_state(task_id: str):
    """快照（契约 D6-1/D5-4）：任务 + 最终 state（stage output）+ 事件历史"""
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    rec["status"] = _normalize_status(rec["status"])  # H-01
    state = {}
    try:
        state = _slim_state(json.loads(rec.get("state_json") or "{}"))
    except json.JSONDecodeError:
        pass
    # 2026-08-24: 任务行不带 state_json（已裁剪进 state 字段）
    rec.pop("state_json", None)
    events = store.get_events(task_id, 0)
    # D5-4: 挂起的澄清仅当任务 running 且末事件为 clarification 时返回
    #（M-21 锚点②：已被 message/后续事件覆盖的旧澄清不算挂起）
    pending_clar = None
    if (rec["status"] == "running" and events and events[-1]["type"] == "clarification"
            and executor.is_waiting_clarification(task_id)):
        # H-04②：再经 executor 确认真实挂起——已答复/非等待的澄清不再当 pending
        pending_clar = events[-1]
    return {"task": rec, "state": state, "events": events, "pending_clarification": pending_clar}


class ResumeBody(BaseModel):
    answer: str


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str, body: ResumeBody):
    # L-06: 不存在任务 → 404（同族端点语义一致），存在但不可操作 → 409
    if not store.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    ok = executor.resume(task_id, body.answer)
    if not ok:
        raise HTTPException(409, "任务未在澄清等待中")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    # L-06: 不存在任务 → 404（同族端点语义一致），存在但不可取消 → 409
    if not store.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    ok = executor.cancel(task_id)
    if not ok:
        raise HTTPException(409, "任务不可取消（不存在或已完成）")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """契约 D2-4：同 query 重建任务（新 task_id，历史保留）"""
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    new_task = store.create_task(rec["query"], output_dir=str(OUTPUT_DIR / "pending"),
                                 pdf_paths=rec.get("pdf_paths") or [])
    task_dir = OUTPUT_DIR / new_task["task_id"]
    pdf_dir = task_dir / "user_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    moved: List[str] = []
    for src in rec.get("pdf_paths") or []:
        p = Path(src)
        if p.exists():
            dst = pdf_dir / p.name
            shutil.copy2(str(p), str(dst))
            moved.append(str(dst))
    store.update_task(new_task["task_id"], output_dir=str(task_dir), pdf_paths=json.dumps(moved))
    executor.submit(new_task["task_id"], rec["query"], moved)
    return {"task_id": new_task["task_id"], "status": "queued"}


# ══════════════════════════════════════════════════════
# 任务删除（2026-08-24：数据清理功能）
# ══════════════════════════════════════════════════════

PAPERS_ROOT = ROOT / "subgraphs" / "data" / "papers"
_DELETABLE_PARTS = ("pdfs", "figures", "checkpoints", "events")


def _task_data_paths(task_id: str) -> Dict[str, Path]:
    """任务各数据块的磁盘位置（可能不存在）。"""
    return {
        "pdfs": PAPERS_ROOT / task_id,
        "figures": OUTPUT_DIR / "figures" / task_id,
        "exports": OUTPUT_DIR / task_id[:8],
        "task_dir": OUTPUT_DIR / task_id,
    }


def _rmtree_if_exists(p: Path) -> bool:
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
        return True
    return False


def _delete_task_data(task_id: str, parts: List[str]) -> Dict[str, Any]:
    """按 parts 删除任务的数据块（不含任务行本身）。"""
    paths = _task_data_paths(task_id)
    removed: Dict[str, bool] = {}
    for part in parts:
        if part == "checkpoints":
            try:
                import sqlite3 as _sqlite3
                con = _sqlite3.connect(str(CHECKPOINT_PATH), timeout=10)
                try:
                    n = 0
                    cur = con.cursor()
                    for table in ("writes", "checkpoints"):
                        n += cur.execute(f"DELETE FROM {table} WHERE thread_id=?", (task_id,)).rowcount
                    con.commit()
                    removed["checkpoints"] = n > 0
                finally:
                    con.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("[Web] checkpoint 删除失败 %s: %s", task_id, e)
                removed["checkpoints"] = False
        elif part == "events":
            removed["events"] = store.delete_events(task_id) > 0
        elif part in ("pdfs", "figures", "exports"):
            removed[part] = _rmtree_if_exists(paths.get(part, Path(".")))
    return removed


@app.delete("/api/tasks/{task_id}/data")
async def delete_task_data(task_id: str, parts: str = ""):
    """内容级清理：删除任务的部分数据（pdfs/figures/checkpoints/events）。

    parts 为逗号分隔的可删除块清单；空/未指定时默认全部四块。
    任务行与结果 state_json 保留（历史任务仍可点开查看结果）。
    """
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    if _normalize_status(rec["status"]) in ("running", "queued"):
        raise HTTPException(409, "任务运行中，不可清理")
    wanted = [p.strip() for p in (parts or "").split(",") if p.strip()]
    if not wanted:
        wanted = list(_DELETABLE_PARTS)
    unknown = [p for p in wanted if p not in _DELETABLE_PARTS]
    if unknown:
        raise HTTPException(400, f"不支持的清理块: {unknown}（可选: {_DELETABLE_PARTS}）")
    return {"removed": _delete_task_data(task_id, wanted)}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """整任务删除：任务行 + events + checkpoints + 论文 PDF + 图证 + 导出 + 上传 PDF。"""
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    if _normalize_status(rec["status"]) in ("running", "queued"):
        raise HTTPException(409, "任务运行中，不可删除")
    removed = _delete_task_data(task_id, ["pdfs", "figures", "checkpoints", "events", "exports"])
    paths = _task_data_paths(task_id)
    removed["task_dir"] = _rmtree_if_exists(paths["task_dir"])
    removed["events"] = store.delete_events(task_id) > 0 or removed.get("events", False)
    store.delete_task(task_id)
    return {"deleted": True, "removed": removed}


class BatchDeleteBody(BaseModel):
    task_ids: List[str]


@app.post("/api/tasks/batch-delete")
async def batch_delete_tasks(body: BatchDeleteBody):
    """批量整任务删除（任务行 + 全部关联数据）。"""
    results = []
    for tid in body.task_ids:
        rec = store.get_task(tid)
        if not rec:
            results.append({"task_id": tid, "deleted": False, "reason": "not_found"})
            continue
        if _normalize_status(rec["status"]) in ("running", "queued"):
            results.append({"task_id": tid, "deleted": False, "reason": "active"})
            continue
        removed = _delete_task_data(tid, ["pdfs", "figures", "checkpoints", "events", "exports"])
        _rmtree_if_exists(_task_data_paths(tid)["task_dir"])
        store.delete_events(tid)
        store.delete_task(tid)
        results.append({"task_id": tid, "deleted": True, "removed": removed})
    return {"results": results}


# ══════════════════════════════════════════════════════
# SSE 事件流（契约 D3-3：单条流，12 种事件 + log；断线续播 D1-4）
# ══════════════════════════════════════════════════════

_TERMINAL_EVENT_TYPES = frozenset({"task_completed", "task_cancelled", "task_failed"})
SSE_QUEUE_MAX = 200  # 每连接订阅队列上限（M-06 ①：log 洪泛时可丢）
SSE_DONE_TTL = 15.0  # 终态事件后收尾窗口（ai 总结等尾随事件），超时关闭流（M-06 ③）


@app.get("/api/tasks/{task_id}/events/history")
async def events_history(task_id: str, after_seq: int = 0):
    """契约 D8-3：历史事件 HTTP 批量端点（回看走 HTTP，SSE 只做实时+断点续播）。

    CR-02 锚点：前端快照重放走本端点后，以 lastSeq 打开 SSE（after_seq=lastSeq）
    ——全量重放与 SSE 续播不再各交付一遍同一事件集（DP-12 双份实证的修复侧）。
    """
    if not store.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    return {"task_id": task_id, "events": store.get_events(task_id, max(0, after_seq))}


@app.get("/api/tasks/{task_id}/events")
async def stream_events(task_id: str, after_seq: int = 0):
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")

    async def gen():
        # M-06②/CR-02：先订阅再取快照——重放期间发布的实时事件入队，
        # 杜绝「DB 重放 → subscribe」间隙丢事件；快照与队列按 seq 去重
        q = EventQueue(maxsize=SSE_QUEUE_MAX)
        bus.subscribe(task_id, q)
        done = False
        try:
            def _frame(ev):
                nonlocal done
                if ev["type"] in _TERMINAL_EVENT_TYPES:
                    done = True
                return {"event": "message", "data": json.dumps(ev, ensure_ascii=False)}

            # ① 历史补发（断线续播 D1-4；after_seq 由前端 lastSeq 携带）
            history = store.get_events(task_id, after_seq)
            replayed_last = history[-1]["seq"] if history else after_seq
            for ev in history:
                yield _frame(ev)
            # ② 快照后已入队的实时事件：seq 去重补发（gap 窗口闭合，无重复 seq）
            while True:
                try:
                    ev = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if ev["seq"] > replayed_last:
                    yield _frame(ev)
            # ③ 实时订阅；终态事件后 TTL 收尾窗口结束 → 正常关闭流（M-06③）
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=SSE_DONE_TTL if done else None)
                except asyncio.TimeoutError:
                    return  # 终态后收尾窗口超时 → 关闭（不再永续占连接/订阅队列）
                yield _frame(ev)
        except asyncio.CancelledError:
            raise
        finally:
            bus.unsubscribe(task_id, q)

    return EventSourceResponse(gen(), ping=15)


# ══════════════════════════════════════════════════════
# 结果（重度数据走 HTTP，契约 D1-3）
# ══════════════════════════════════════════════════════

def _load_state(task_id: str) -> Dict[str, Any]:
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    try:
        return json.loads(rec.get("state_json") or "{}")
    except json.JSONDecodeError:
        return {}


# ══════════════════════════════════════════════════════════════
# 2026-08-24: /state 与 /quality 响应瘦身 — state_json 12MB/任务, 前端
# 实际只读少量路径。裁剪后 /state 19MB→~1MB, 点开任务秒开。
# 裁剪只发生在响应层 (落库的 state_json 保持完整, 历史数据零丢失);
# events 全量保留 (历史流水线回放依赖, 实测仅 0.26MB)。
# ══════════════════════════════════════════════════════════════

# 前端逐源实际读取的 sources 字段 (其余 ~2MB 明细裁剪)。
# quality_scoring 供质量分布图 per-source 等级 (缺失会全退化为 poor)
_QUALITY_SOURCE_KEEP_KEYS = ("title", "record_count", "extraction_quality", "quality_scoring")


def _slim_quality_report(qr: Any) -> Any:
    """裁剪 quality_report: 保留前端消费路径, 剔除重复/大明细字段。"""
    if not isinstance(qr, dict):
        return qr
    out: Dict[str, Any] = {}
    for key, val in qr.items():
        if key == "data_state":
            # 仅保留 data_trace (前端轨迹 Tab 用); input/current_data 是
            # records 的副本, 前端走 /records 独立接口
            out[key] = {"data_trace": (val or {}).get("data_trace", [])}
        elif key == "report_state":
            rs: Dict[str, Any] = {}
            q = (val or {}).get("quality") or {}
            # sources 明细裁剪: 只留标题/记录数/提取质量评分
            srcs = {}
            for sid, src in (q.get("sources") or {}).items():
                if isinstance(src, dict):
                    srcs[sid] = {k: src.get(k) for k in _QUALITY_SOURCE_KEEP_KEYS}
            q_out = {k2: v2 for k2, v2 in q.items() if k2 != "sources"}
            q_out["sources"] = srcs
            rs["quality"] = q_out
            rs["conflict"] = (val or {}).get("conflict")
            # normalization 只留 modifications (工具规划/校验明细前端不读)
            rs["normalization"] = {
                "modifications": ((val or {}).get("normalization") or {}).get("modifications")
            }
            rs["insights"] = (val or {}).get("insights")
            out[key] = rs
        elif key == "output_state":
            # 去掉 structured_data (~210KB, 导出文件独立走 /exports)
            out[key] = {k2: v2 for k2, v2 in (val or {}).items()
                        if k2 != "structured_data"}
        else:
            out[key] = val
    return out


def _slim_state(state: Any) -> Any:
    """裁剪完整 state: 剔除重复大字段与前端已有独立接口的数据。"""
    if not isinstance(state, dict):
        return state
    # 顶层重复/大字段 (前端全部有独立接口或从不读取)
    _DROP_TOP = (
        "quality_report",      # final_output.quality_report 的重复副本
        "figure_evidence",     # /figures
        "paper_records", "database_results", "paper_results",  # /records /sources
        "supplementary_sources", "supplementary_records",
        "conversation_history", "extra_pdfs",
    )
    out = {k: v for k, v in state.items() if k not in _DROP_TOP}
    fo = state.get("final_output") or {}
    out["final_output"] = {k: v for k, v in fo.items()
                           if k not in ("records", "figure_evidence")}
    qr = fo.get("quality_report")
    if qr is not None:
        out["final_output"]["quality_report"] = _slim_quality_report(qr)
    return out


@app.get("/api/tasks/{task_id}/result")
async def get_result(task_id: str):
    state = _load_state(task_id)
    return state.get("final_output") or {}


def _safe_name(s: str) -> str:
    """文件名安全化（与 subgraph3 result_builder/figure_extractor 同规则）"""
    return s.replace("/", "_").replace(":", "_").replace(" ", "_")


def _final_records(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """质量管线修改后的最终记录 (与导出文件同源) — 前端表格/下载一致性。

    管线输出在 quality_report.output_state.structured_data.json.records
    (数值化/单位统一/溯源字段最全); 无质量管线产出 (取消/失败任务) 时
    回退 final_output.records (管线输入原始值)。
    """
    try:
        recs = (state.get("final_output") or {}).get("quality_report", {}) \
            .get("output_state", {}).get("structured_data", {}) \
            .get("json", {}).get("records")
        if recs:
            return recs
    except Exception:  # noqa: BLE001 — 结构缺失回退原始记录
        pass
    return (state.get("final_output") or {}).get("records", [])


def _final_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """与 _final_records 同口径的最终来源列表。"""
    try:
        srcs = (state.get("final_output") or {}).get("quality_report", {}) \
            .get("output_state", {}).get("structured_data", {}) \
            .get("json", {}).get("sources")
        if srcs:
            return srcs
    except Exception:  # noqa: BLE001
        pass
    return (state.get("final_output") or {}).get("sources", [])


@app.get("/api/tasks/{task_id}/records")
async def get_records(task_id: str):
    """契约 D7-1 扩展 (2026-08-24): 返回质量管线修改后的最终记录
    (与导出 grounded_data 同源), 附加 page_image_url — 指向 bbox 溯源页图
    (/static/figures/{task_id}/source_pages/{bibcode}/page_{N}.png),
    文件不存在时为空串 (前端据此降级为只显示坐标文本)。"""
    records = _final_records(_load_state(task_id))
    pages_dir = OUTPUT_DIR / "figures" / task_id / "source_pages"
    out = []
    for rec in records:
        prov = rec.get("provenance") or {}
        page = prov.get("page")
        sid = rec.get("source_id")
        if isinstance(page, int) and isinstance(sid, str) and sid:
            img_path = pages_dir / _safe_name(sid) / f"page_{page}.png"
            rec = dict(rec)  # 不修改状态内的原 dict
            rec["page_image_url"] = (
                f"/static/figures/{task_id}/source_pages/{_safe_name(sid)}/page_{page}.png"
                if img_path.is_file() else ""
            )
        out.append(rec)
    return out


@app.get("/api/tasks/{task_id}/sources")
async def get_sources(task_id: str):
    # 2026-08-24: 与 /records 同口径 — 返回质量管线修改后的最终来源列表
    return _final_sources(_load_state(task_id))


@app.get("/api/tasks/{task_id}/figures")
async def get_figures(task_id: str):
    """契约 D7-3：图证元数据（image_url 指向静态路由）"""
    state = _load_state(task_id)
    figures = state.get("final_output", {}).get("figure_evidence", [])
    out = []
    for f in figures:
        # H-06: 生产字段是 image_path（"figures/{query_id}/{fname}"，query_id=task_id），
        # 此前读 file_name（不存在）→ image_url 恒 404；挂载根已收窄到 output/figures/
        img_path = f.get("image_path", "")
        fname = Path(img_path).name
        out.append({
            "id": f.get("figure_id") or f.get("id"),
            "source_id": f.get("source_id"),
            "page": f.get("page"),
            "bbox": f.get("bbox_2d") or f.get("bbox"),
            "caption": f.get("caption", ""),
            "image_url": f"/static/figures/{task_id}/{fname}" if fname else "",
        })
    return out


@app.get("/api/tasks/{task_id}/quality")
async def get_quality(task_id: str):
    """契约 D7-4：质量报告 + 洞察（轻量并入；2026-08-24 响应裁剪）"""
    state = _load_state(task_id)
    final = state.get("final_output") or {}
    return {
        "quality_report": _slim_quality_report(final.get("quality_report")),
        "insights": (state.get("quality_report") or {}).get("insights"),
    }


@app.get("/api/tasks/{task_id}/exports")
async def get_exports(task_id: str):
    """契约 D9-2：输出文件元数据（stat 本地文件，无下载语义）"""
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    # M-18: 导出文件实际落点 = EXPORT_OUTPUT_DIR/{run_id[:8]}/，Web 任务
    # run_id = query_id = task_id（quality_adapter 透传）→ output/{task_id[:8]}/
    # （此前扫描 tasks.output_dir 恒空，D9 数据交付整体失效）
    export_dir = OUTPUT_DIR / task_id[:8]
    out_dir = export_dir if export_dir.is_dir() else Path(rec.get("output_dir") or "")
    if not out_dir.exists() or not out_dir.is_dir():
        return []
    items = []
    for p in sorted(out_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in (".json", ".csv"):
            items.append({
                "name": p.name,
                "path": str(p),
                "size": _fmt_size(p.stat().st_size),
                "format": p.suffix.lstrip(".").upper(),
                "desc": _export_desc(p.name),
            })
    return items


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, n // 1024)} KB"


def _export_desc(name: str) -> str:
    base = name.split("_")[0]
    return {
        "grounded": "完整结构化数据（EAV 记录）",
        "data": "记录表（long/wide CSV）",
        "quality": "质量摘要",
        "metadata": "数据元数据",
        "traceability": "溯源",
        "manifest": "导出清单（审计）",
    }.get(base, "输出文件")


@app.get("/api/tasks/{task_id}/export/{file_name}")
async def export_file(task_id: str, file_name: str):
    """浏览器直接打开/保存（路径白名单校验，防目录穿越，D9-3 安全）"""
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    # M-18: 导出文件落点 output/{task_id[:8]}/（run_id=task_id）
    out_dir = (OUTPUT_DIR / task_id[:8]).resolve()
    target = (out_dir / file_name).resolve()
    # L-04: startswith 前缀匹配可被兄弟前缀目录绕过 → 严格包含判断
    if not target.is_relative_to(out_dir) or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(target), filename=file_name)


@app.post("/api/tasks/{task_id}/open-output")
async def open_output(task_id: str):
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    # M-18: 导出目录 output/{task_id[:8]}/；兜底任务目录
    d = OUTPUT_DIR / task_id[:8]
    if not d.exists():
        d = Path(rec.get("output_dir") or "")
    if not d.exists():
        raise HTTPException(404, "输出目录不存在")
    _os_open(str(d))
    return {"ok": True}


@app.post("/api/tasks/{task_id}/open-file")
async def open_file(task_id: str, body: Dict[str, str]):
    rec = store.get_task(task_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    # L-04: name 拒绝含分隔符输入（JSON body 可带 ../ 指向兄弟任务文件）；
    # M-18: 文件在导出目录 output/{task_id[:8]}/
    name = body.get("name", "")
    if not name or name != Path(name).name:
        raise HTTPException(404, "文件不存在")
    out_dir = (OUTPUT_DIR / task_id[:8]).resolve()
    target = (out_dir / name).resolve()
    if not target.is_relative_to(out_dir) or not target.is_file():
        raise HTTPException(404, "文件不存在")
    _os_open(str(target))
    return {"ok": True}


def _os_open(path: str) -> None:
    """打开文件/目录（本地工具场景，契约 D9-3）。"""
    import subprocess
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


# ══════════════════════════════════════════════════════
# 配置（契约 D10：GET 只返回是否配置；PUT 写回 .env）
# ══════════════════════════════════════════════════════

_ENV_FILE = ROOT / ".env"
_ENV_KEYS = ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL",
             "ADS_API_TOKEN", "UNPAYWALL_EMAIL"]


def _env_values() -> Dict[str, str]:
    vals: Dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


@app.get("/api/config")
async def get_config():
    vals = _env_values()
    return {
        "configured": {k: bool(vals.get(k)) for k in _ENV_KEYS},  # D10-2: 无明文
        "version": "2.0.0",
        "output_dir": str(OUTPUT_DIR),
    }


class ConfigBody(BaseModel):
    dashscope_api_key: Optional[str] = None
    dashscope_base_url: Optional[str] = None
    ads_api_token: Optional[str] = None
    unpaywall_email: Optional[str] = None


@app.put("/api/config")
async def put_config(body: ConfigBody, request: Request):
    """契约 D10-1：写回 .env（持久化）。"""
    # H-05④: 要求自定义请求头——跨源 PUT 必触发 CORS preflight，白名单外
    # origin 在预检阶段即被拒（配合白名单 CORS，防任意网页改 base_url 投毒）
    if request.headers.get("x-requested-with") != "AstroQuery":
        raise HTTPException(403, "缺少来源校验头（X-Requested-With: AstroQuery）")
    mapping = {
        "dashscope_api_key": "DASHSCOPE_API_KEY",
        "dashscope_base_url": "DASHSCOPE_BASE_URL",
        "ads_api_token": "ADS_API_TOKEN",
        "unpaywall_email": "UNPAYWALL_EMAIL",
    }
    # L-05②: 值单行化 + 限长（换行可注入新键，污染 .env）
    def _clean(v: str) -> str:
        return v.replace("\r", "").replace("\n", "")[:512]

    updates = {mapping[k]: _clean(v) for k, v in body.model_dump(exclude_none=True).items() if v}
    if not updates:
        return {"ok": True}
    vals = _env_values()
    vals.update(updates)
    existing = set(_ENV_KEYS)
    lines = []
    # L-05①: 重写时保留原注释行与空行（此前注释说明被静默删除）
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                lines.append(line)
                continue
            key = s.partition("=")[0].strip()
            if key in existing:
                continue  # 键值行稍后统一重写
            lines.append(line)  # 其他键保留原样
    for k in _ENV_KEYS:
        if k in vals:
            lines.append(f"{k}={vals[k]}")
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True}


# ══════════════════════════════════════════════════════
# 静态路由（图证预览，契约 D7-3）
# ══════════════════════════════════════════════════════

# H-05③/H-06: 静态挂载收窄到 output/figures/（图证专用）——用户上传 PDF
# （output/{task_id}/user_pdfs/）与导出文件不再经静态路由无鉴权可达
app.mount("/static/figures", StaticFiles(directory=str(OUTPUT_DIR / "figures")), name="figures")

# M-20①: 单进程交付——挂载前端构建产物（dist），'/api' 与 '/static/figures'
# 已先行注册优先匹配；dist 不存在（未 build）时跳过，仅 API 模式运行
_FRONTEND_DIST = ROOT / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")


# 启动清理：暂存区孤儿（D4-4：孤儿直接删）
@app.on_event("startup")
async def _cleanup_orphans():
    import time
    cutoff = time.time() - 24 * 3600
    for p in UPLOAD_DIR.iterdir():
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass
    # 2026-08-24: 队列为内存态, 重启后 running/queued 任务永远无法执行 —
    # 启动时纠偏为 cancelled, 避免卡住任务列表且不可删除
    try:
        n = store.update_orphan_status()
        if n:
            logger.info("[Web] 启动纠偏: %d 个孤儿 running/queued 任务标记为 cancelled", n)
    except Exception as e:  # noqa: BLE001
        logger.warning("[Web] 孤儿任务纠偏失败: %s", e)


# M-11: VCR 启动自测移入 startup（import 期零网络/零阻塞/日志可控）
@app.on_event("startup")
async def _vcr_startup_diagnostic():
    _vcr_startup_selftest()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
