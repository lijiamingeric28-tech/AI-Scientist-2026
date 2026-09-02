"""事件发射器（顶层单例）—— subgraphs 埋点与 web 事件总线之间的桥。

设计：
- subgraphs 节点埋点只调 `emitter.emit(task_id, event)`，不依赖 web 层
- web 执行器启动时 `emitter.configure(publish_fn)` 接入事件总线
- 离线测试（pytest / CLI）未 configure 时 emit 为 no-op，零副作用

事件格式见 docs/API_CONTRACT.md（12 种事件，带 seq 由总线分配）。
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

_emit_fn: Optional[Callable[[str, Dict[str, Any]], None]] = None
_lock = threading.Lock()


def configure(publish_fn: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
    """接入发布函数（web 事件总线）；传 None 恢复 no-op。"""
    global _emit_fn
    with _lock:
        _emit_fn = publish_fn


def emit(task_id: str, event: Dict[str, Any]) -> None:
    """发射事件（未配置时为 no-op）。"""
    fn = _emit_fn
    if fn is not None:
        try:
            fn(task_id, event)
        except Exception:
            # 事件发射失败绝不击穿节点（埋点必须无副作用）
            import logging
            logging.getLogger("events").exception("emit failed task=%s", task_id)


def emit_progress(task_id: str, stage_id: str, step: str, status: str,
                  progress: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> None:
    """step_progress 事件便捷封装（埋点统一入口）。"""
    event: Dict[str, Any] = {
        "type": "step_progress",
        "stage_id": stage_id,
        "step": step,
        "status": status,
    }
    if progress is not None:
        event["progress"] = progress
    if data is not None:
        event["data"] = data
    emit(task_id, event)
