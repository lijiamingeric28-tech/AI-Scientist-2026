"""异步执行器（契约 D1-1/D4-8/D5-3）：
- 后台线程执行 web_runner.run_task_streaming
- 并发 = 1：运行中时新任务 queued 排队（D4-8）
- resume / cancel 经 _AnswerSlot 唤醒执行线程
- 任务状态机：queued → running → completed/cancelled/error（D2/D8 状态映射表；
  H-01 统一终态词表为 error，前端 STATUS_LABELS/筛选/重试均按 error 匹配）
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from astroquery_ai.web_runner import run_task_streaming, _AnswerSlot

from .event_bus import EventBus
from .log_bridge import set_task as log_set_task
from .task_store import TaskStore

logger = logging.getLogger(__name__)

# VCR 录制/回放（LLM 请求）：LLM_CASSETTE=cassettes/m31.yaml LLM_RECORD_MODE=all|once|none
_CASSETTE_PATH = os.environ.get("LLM_CASSETTE", "")
# H-14: 默认 'none'——未匹配即抛错，绝不静默降级为真实录制（真实计费）；显式录制才用 all/once
_CASSETTE_MODE = os.environ.get("LLM_RECORD_MODE", "none")
# 显式录制模式：cassette 缺失时允许创建（H-14 的 fail-fast 只针对非显式模式）
_RECORD_MODES = ("all", "once", "new_episodes")

# H-11: LLM 回放专用 match_on 增 body——所有 LLM 调用为 POST 同 URL（/chat/completions），
# 默认按「同 URL 首个未播放」顺序交付录制响应、与当前 prompt 无关 → 查询串/实体/数值错位。
# 加 body 后按请求体（prompt）区分；GET/下载请求 body 为空不受影响。
# 注意（验收回归）：dashscope VLM 请求（multimodal-generation）的 prompt 含动态内容
# （pdf 文件名/页码等），重放时 body 必然与录制不同——严格 body 匹配会全部不命中、
# 任务卡在提取阶段。故用自定义 smart_body matcher：deepseek 严格匹配 body（防错位），
# VLM 宽松（仅 URL 结构匹配，可回放）。
_VCR_MATCH_ON = ["method", "scheme", "host", "port", "path", "query", "smart_body"]


def _make_smart_body_matcher():
    """smart_body matcher：VLM（dashscope multimodal）宽松，其余严格 body。"""
    from vcr import matchers as _vcr_matchers

    def _smart_body(r1, r2):
        if "multimodal-generation" in r1.uri:
            return True  # VLM prompt 含动态内容（文件名/页码），无法按 body 稳定回放
        return _vcr_matchers.body(r1, r2)

    return _smart_body

# H-12: vcrpy 8.3.0 无任何线程锁，play_counts 检查-自增非原子 → 15 并发 VLM 回放
# 可重复消费同一记录（响应错配）或消费完重试抛越界异常。executor 级 RLock 串行化。
_CASSETTE_PLAY_LOCK = threading.RLock()

# L-14: 进程级单例缓存 cassette 解析结果（58MB YAML 全量解析每个进程只做一次，
# H-11 查询一致性校验与后续任务复用；避免每次任务提交/启动重复全量解析）
_CASSETTE_PARSE_CACHE: Dict[str, Optional[List[Dict[str, Any]]]] = {}


class _DowngradeAppendingFilter(logging.Filter):
    """M-11/L-14: vcrpy 8.3.0 以 INFO 输出 'Appending request %s and response %s'
    （响应序列化含 58MB PDF 内容）——cassette 加载期 141 行/9.6MB 日志洪泛。
    降级为 DEBUG：INFO 配置下不再输出，排查时可开启 DEBUG 恢复。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if "Appending" in record.getMessage():
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


# 挂到 vcr.cassette logger（vcrpy 尚未导入时 getLogger 也会创建同名 logger，
# vcrpy 导入后用 logging.getLogger(__name__) 取到的是同一实例）
logging.getLogger("vcr.cassette").addFilter(_DowngradeAppendingFilter())

# D5-3: 澄清超时自动取消（模块级常量，测试可 monkeypatch 缩短注入）
CLARIFICATION_TIMEOUT = 15 * 60


# ── VCR 回放前置校验（H-11/H-14/L-14 共用的轻量工具） ──

def validate_cassette_config(cassette_path: str, mode: str) -> None:
    """H-14: LLM_CASSETTE 已设置但文件不存在 + 非显式录制模式 → fail-fast。

    默认 'none' 下绝不静默降级为真实录制（真实计费 + 日志谎报 "(replay)"）；
    显式录制模式（all/once/new_episodes）允许缺失文件（首次录制语义）。
    """
    if not cassette_path or Path(cassette_path).exists():
        return
    if mode in _RECORD_MODES:
        return
    raise FileNotFoundError(
        f"LLM_CASSETTE 文件不存在: {cassette_path}（LLM_RECORD_MODE={mode}，回放前提不满足；"
        f"如需录制请显式设置 LLM_RECORD_MODE=all/once）"
    )


def _cassette_interactions(cassette_path: str) -> Optional[List[Dict[str, Any]]]:
    """按路径缓存 cassette 解析结果（L-14：进程级单例，避免每次任务全量 YAML 解析）。"""
    if cassette_path in _CASSETTE_PARSE_CACHE:
        return _CASSETTE_PARSE_CACHE[cassette_path]
    result: Optional[List[Dict[str, Any]]] = None
    if Path(cassette_path).exists():
        try:
            import yaml
            with open(cassette_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            result = list(data.get("interactions") or [])
        except Exception:
            result = None
    _CASSETTE_PARSE_CACHE[cassette_path] = result
    return result


def _first_llm_prompt(interactions: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """取 cassette 中首个 LLM chat 请求的 user 首条 prompt（H-11 校验锚点：
    录制时的 query/首条 prompt 即该内容）。"""
    for it in interactions or []:
        req = (it or {}).get("request") or {}
        if "chat/completions" not in str(req.get("uri", "")):
            continue
        body = req.get("body") or {}
        bstr = body.get("string", "") if isinstance(body, dict) else str(body or "")
        try:
            payload = json.loads(bstr)
        except Exception:
            continue
        messages = payload.get("messages") or []
        if messages and messages[0].get("role") == "user":
            return str(messages[0].get("content") or "")
    return None


def validate_replay_query(cassette_path: str, query: str) -> None:
    """H-11: 回放前校验——cassette 记录的首条 prompt 与当前查询一致，不一致拒绝回放。

    修改 prompt 后回放不得命中旧交互（静默错位响应）；文件缺失由 validate_cassette_config
    （H-14）负责，此处不重复报错。
    """
    if not cassette_path or not query:
        return
    interactions = _cassette_interactions(cassette_path)
    if interactions is None:
        return
    first = _first_llm_prompt(interactions)
    if first is None:
        raise RuntimeError(
            f"[VCR] cassette 无 LLM chat 交互，无法校验查询一致性，拒绝回放: {cassette_path}"
        )
    if query not in first:
        raise RuntimeError(
            f"[VCR] 当前查询与 cassette 录制内容不一致，拒绝回放（防错位响应）: "
            f"query={query[:80]!r}，cassette={cassette_path}"
        )


def _build_replay_vcr(cassette_path: str, mode: str):
    """构造回放 VCR 实例：match_on 含 "smart_body"（H-11 防错位 + VLM 宽松）。
    返回 (VCR, Path)。"""
    import vcr as _vcr_lib
    _cassette = Path(cassette_path)
    _vcr = _vcr_lib.VCR(
        record_mode=mode,
        cassette_library_dir=str(_cassette.parent),
        decode_compressed_response=False,
        match_on=list(_VCR_MATCH_ON),
    )
    _vcr.register_matcher("smart_body", _make_smart_body_matcher())
    return _vcr, _cassette


def _guard_cassette_play(cassette) -> None:
    """H-12: 以 executor 级 RLock 串行化 cassette.play_response 的检查-自增
    （vcrpy 8.3.0 无锁；幂等：重复包装不叠加锁）。"""
    orig = cassette.play_response
    if getattr(orig, "_vcr_guarded", False):
        return

    def _locked_play(request):
        with _CASSETTE_PLAY_LOCK:
            return orig(request)

    _locked_play._vcr_guarded = True
    cassette.play_response = _locked_play


def _limit_vlm_concurrency() -> None:
    """H-12: 回放/录制模式 VLM max_workers 降为 1——vcrpy 单线程回放语义，
    15 并发同 URL 请求必然竞争 play_counts；录制端对并发同 URL 请求也串行化。"""
    try:
        from subgraphs.subgraph3.config.settings import settings as _vlm_settings
        if _vlm_settings.concurrency.max_workers != 1:
            _vlm_settings.concurrency.max_workers = 1
    except Exception:
        logger.warning("[Executor] VLM 并发降级失败（忽略）", exc_info=True)


class Executor:
    def __init__(self, bus: EventBus, store: TaskStore, checkpointer_path: str,
                 output_dir: str, summary_fn=None, title_fn=None):
        self._bus = bus
        self._store = store
        self._checkpointer_path = checkpointer_path
        self._output_dir = Path(output_dir)
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._slots: Dict[str, _AnswerSlot] = {}
        self._current: Optional[str] = None
        self._lock = threading.Lock()
        # 模块⑤ 注入：卡 7 LLM 总结 / 任务标题摘要
        self._summary_fn = summary_fn
        self._title_fn = title_fn
        self._worker = threading.Thread(target=self._loop, daemon=True, name="executor")
        self._worker.start()

    # ── 提交（并发 1：运行中 → queued 排队） ──
    def submit(self, task_id: str, query: str, pdf_paths: List[str]) -> None:
        with self._lock:
            if self._current is not None:
                self._store.update_task(task_id, status="queued")
                self._bus.emit(task_id, "task_queued")
                self._pending.put(task_id)
                return
            self._start_locked(task_id, query, pdf_paths)

    def _start_locked(self, task_id: str, query: str, pdf_paths: List[str]) -> None:
        self._current = task_id
        self._store.update_task(task_id, status="running")
        self._bus.emit(task_id, "task_started")
        slot = _AnswerSlot()
        self._slots[task_id] = slot
        t = threading.Thread(
            target=self._run_one, args=(task_id, query, pdf_paths, slot),
            daemon=True, name=f"task-{task_id[:8]}",
        )
        t.start()

    def _loop(self) -> None:
        while True:
            task_id = self._pending.get()
            if task_id is None:  # stop() 哨兵 → 退出 loop 线程
                return
            rec = self._store.get_task(task_id)
            if not rec or rec["status"] == "cancelled":
                continue
            with self._lock:
                if self._current is not None:
                    self._pending.put(task_id)  # 仍有运行中，重新排队
                    continue
                self._start_locked(task_id, rec["query"], rec.get("pdf_paths") or [])

    def _run_one(self, task_id: str, query: str, pdf_paths: List[str], slot: _AnswerSlot) -> None:
        def get_answer(_tid: str, payload: Any) -> Optional[str]:
            # 阻塞等待 resume；超时 → 发 fatal error + task_cancelled（H-07：
            # task_cancelled 由执行器发出；DB 终态由 _finish 按 slot.cancelled 落 cancelled，
            # 不再被覆写为 completed）
            if not slot.wait(CLARIFICATION_TIMEOUT):
                self._bus.error(task_id, "clarification", "澄清超时（15 分钟），任务已取消", level="fatal")
                self._bus.emit(task_id, "task_cancelled", reason="timeout")
                slot.cancel()
                return None
            ans = slot.answer
            slot.reset()  # 多轮澄清复用
            return ans

        def should_cancel() -> bool:
            return slot.cancelled

        try:
            log_set_task(task_id)
            if _CASSETTE_PATH:
                # H-14: cassette 缺失 + 非显式录制 → fail-fast（不静默降级为真实录制）
                validate_cassette_config(_CASSETTE_PATH, _CASSETTE_MODE)
                # H-11: 回放前校验 query/首条 prompt 与录制一致，不一致拒绝回放
                validate_replay_query(_CASSETTE_PATH, query)
                # 录制/回放模式：cassette_library_dir + 文件名（与 pytest 完全一致）
                _vcr, _cassette = _build_replay_vcr(_CASSETTE_PATH, _CASSETTE_MODE)
                with _vcr.use_cassette(_cassette.name) as _cass:
                    _guard_cassette_play(_cass)   # H-12: RLock 串行化回放消费
                    _limit_vlm_concurrency()      # H-12: 回放模式 VLM 并发降为 1
                    # H-14: 日志同时打印 mode 与 interactions 数（不再谎报 "(replay)"）
                    logger.info("[Executor] VCR cassette loaded: %d interactions (mode=%s)", len(_cass), _CASSETTE_MODE)
                    result = run_task_streaming(
                        task_id=task_id,
                        user_query=query,
                        extra_pdfs=pdf_paths,
                        bus=self._bus,
                        get_answer=get_answer,
                        should_cancel=should_cancel,
                        checkpointer_path=self._checkpointer_path,
                        on_final_summary=self._summary_fn,
                    )
            else:
                result = run_task_streaming(
                    task_id=task_id,
                    user_query=query,
                    extra_pdfs=pdf_paths,
                    bus=self._bus,
                    get_answer=get_answer,
                    should_cancel=should_cancel,
                    checkpointer_path=self._checkpointer_path,
                    on_final_summary=self._summary_fn,
                )
            # H-09②：选 n 取消 → 终态 cancelled（_finish 见 slot.cancelled 不覆写 completed）
            if isinstance(result, dict) and result.get("clarification_status") == "cancelled":
                slot.cancel()
            # 快照持久化（契约 D6-1：state 接口取 stage output）
            try:
                import json as _json
                self._store.update_task(task_id, state_json=_json.dumps(result, ensure_ascii=False, default=str))
            except Exception:
                logger.exception("[Executor] state snapshot failed")
            # 模块⑤：任务标题摘要（D8-2 异步语义；M-12：移出执行器线程，
            # 慢/超时 LLM 不阻塞 _finish 与排队任务启动）
            if self._title_fn:
                threading.Thread(
                    target=self._gen_title, args=(task_id, query, result),
                    daemon=True, name=f"title-{task_id[:8]}",
                ).start()
        except Exception as exc:
            logger.exception("[Executor] task %s failed", task_id)
            self._bus.error(task_id, "executor", f"{type(exc).__name__}: {exc}", level="fatal")
            # H-01: 终态词表统一为 error（契约 D8 状态映射表；旧词表 failed 由 main.py 归一）
            self._store.update_task(task_id, status="error", completed_at=_now_iso())
            self._bus.emit(task_id, "task_failed", error=str(exc)[:500])
        finally:
            log_set_task(None)
            self._finish(task_id)

    def _gen_title(self, task_id: str, query: str, result: Dict[str, Any]) -> None:
        """异步任务标题摘要（D8-2 task_title_ready；M-12 移出执行器线程）。"""
        try:
            title = self._title_fn(task_id, query, result)
            self._store.update_task(task_id, title=title)
            # L-01: 事件 payload 显式携带 task_id（契约 D8-2 字段）——emit() 首个位置参数
            # 即 task_id，关键字 task_id= 会与位置参数冲突（TypeError，标题事件从未发出，
            # 即 DF-01 全库 0 条 task_title_ready）；改用 publish 直接构造 payload
            self._bus.publish(task_id, {"type": "task_title_ready", "task_id": task_id, "title": title})
        except Exception:
            logger.exception("[Executor] title gen failed")

    def _finish(self, task_id: str) -> None:
        with self._lock:
            slot = self._slots.pop(task_id, None)
            self._current = None
            rec = self._store.get_task(task_id)
            if rec and rec["status"] not in ("error", "cancelled"):
                if slot is not None and slot.cancelled:
                    # H-07/H-09②：超时/取消任务终态为 cancelled，不覆写为 completed
                    self._store.update_task(task_id, status="cancelled", completed_at=_now_iso())
                else:
                    self._store.update_task(task_id, status="completed", completed_at=_now_iso())

    # ── resume / cancel ──
    def resume(self, task_id: str, answer: str) -> bool:
        slot = self._slots.get(task_id)
        if not slot:
            return False
        # H-04①：仅 waiting 且未 cancelled 时写入（set_answer 返回 False → 409）
        return slot.set_answer(answer)

    def is_waiting_clarification(self, task_id: str) -> bool:
        """H-04②：真实挂起状态（slot 存在且正等待答案），供 /state 判 pending。"""
        with self._lock:
            slot = self._slots.get(task_id)
            return bool(slot and slot.waiting)

    def cancel(self, task_id: str) -> bool:
        # L-07：全程持 _lock，拿到 slot 后二次读取 rec 状态——已完成/失败的
        # 终态（含与 _finish 竞态中 pop 前的陈旧槽）不被覆写为 cancelled
        with self._lock:
            rec = self._store.get_task(task_id)
            if not rec or rec["status"] not in ("queued", "running"):
                return False
            slot = self._slots.get(task_id)
            if slot:
                slot.cancel()
                self._store.update_task(task_id, status="cancelled", completed_at=_now_iso())
                # H-08②：立即通知（含计算中途：wrap 边界终止前前端即可看到取消态）
                self._bus.emit(task_id, "task_cancelled", reason="cancelled")
                return True
            if rec["status"] == "queued":
                self._store.update_task(task_id, status="cancelled", completed_at=_now_iso())
                # H-08②：queued 分支 runner 不运行，事件必须在此发出（DP-08 锚点）
                self._bus.emit(task_id, "task_cancelled", reason="cancelled")
                return True
            return False

    def stop(self, timeout: float = 2.0) -> None:
        """停止后台 loop 线程（幂等；测试回收用，生产进程退出时 daemon 自动结束）。"""
        self._pending.put(None)  # 哨兵 → _loop 退出
        t = self._worker
        if t is not None and t.is_alive():
            t.join(timeout)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
