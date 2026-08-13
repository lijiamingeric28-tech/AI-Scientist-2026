"""日志桥 —— 节点 logger 输出 → SSE log 事件（契约 D3-3：log 并入单条事件流）。

机制：logging.Handler 转发 + contextvars 当前 task_id。
- executor 执行线程 set_task 设置 ContextVar（L-11：threading.local 不随
  子线程传播，全版本 worker 线程日志都会被丢弃）
- 节点内 ThreadPoolExecutor 并行 worker（VLM/bbox/下载/图提取等）不会隐式
  继承 ContextVar（实测 3.14.5 亦为空），install() 时对 submit 做显式透传：
  提交时 copy_context()，worker 内 ctx.run 执行 → worker 线程日志可见 task_id
- 所有 logger 输出（INFO 及以上）转发到事件总线（带 node/level/message）
- 离线测试（未 configure）时无总线，handler no-op
"""

from __future__ import annotations

import contextvars
import functools
import logging
from typing import Optional

_task_id: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("log_bridge_task_id", default=None)

_level_map = {logging.DEBUG: "DEBUG", logging.INFO: "INFO", logging.WARNING: "WARN", logging.ERROR: "ERROR"}


class _EventLogHandler(logging.Handler):
    def __init__(self, bus):
        super().__init__(level=logging.INFO)
        self._bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            task_id = _task_id.get()
            if not task_id:
                return
            level = _level_map.get(record.levelno, "INFO")
            # 只转发业务节点的日志（过滤框架噪音）
            msg = record.getMessage()[:500]
            self._bus.emit(task_id, "log", node=record.name.split(".")[-1], level=level, message=msg)
        except Exception:
            pass  # 日志转发失败绝不击穿


_bus_ref: Optional[object] = None
_handler: Optional[_EventLogHandler] = None


def _install_tpe_context_propagation() -> None:
    """ThreadPoolExecutor 提交时显式透传调用方 context（L-11）。

    contextvars 不会隐式进入线程池 worker（Python 3.14.5 实测子线程读为空），
    而节点内 VLM/bbox/下载/图提取等大量用 TPE 并行处理 → 这些子线程的日志
    会被 log_bridge 丢弃。提交时 copy_context 并在 worker 内 ctx.run 执行，
    handler 即可在 worker 线程读到 task_id。幂等：已安装则跳过。
    """
    import concurrent.futures.thread as _cft

    tpe = _cft.ThreadPoolExecutor
    original = tpe.submit
    if getattr(original, "_lb_context_aware", False):
        return

    @functools.wraps(original)
    def _submit_context_aware(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()

        def _wrapped(*a, **kw):
            return ctx.run(fn, *a, **kw)

        return original(self, _wrapped, *args, **kwargs)

    _submit_context_aware._lb_context_aware = True
    tpe.submit = _submit_context_aware


def install(bus) -> None:
    """安装日志桥（web/main 启动时调用）；重复调用仅重绑总线（测试 fixture 换新 bus）。"""
    global _bus_ref, _handler
    _bus_ref = bus
    if _handler is None:
        _handler = _EventLogHandler(bus)
        logging.getLogger().addHandler(_handler)
    else:
        _handler._bus = bus  # 重绑（M-07：测试重建单例后必须跟随新 bus）
    _install_tpe_context_propagation()


def set_task(task_id: Optional[str]) -> None:
    """执行线程设置当前任务（executor._run_one 调用）。"""
    _task_id.set(task_id)
