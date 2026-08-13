"""事件总线 —— 执行器线程发布 → sqlite 落库(seq) → SSE 订阅者队列。

契约：
- 事件带 seq（自增，TaskStore.append_event 分配）
- 轻量状态走 SSE；重度数据走 HTTP（事件不携带 records 等）
- 单条 SSE 流（12 种事件 + log，前端按 type 分流）
- M-06 ①：分级丢弃——log/step_progress 可丢（记录 dropped_seq 区间），
  关键事件（stage_*/clarification/task_*/message/error）队列满时腾位不丢
- M-06 ④：订阅时捕获归属 loop，执行器线程发布经 loop.call_soon_threadsafe
  投递（跨线程 put_nowait 安全化，Python 3.14 lost-wakeup 风险面收敛）
"""

from __future__ import annotations

import asyncio
import collections
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from .task_store import TaskStore

logger = logging.getLogger(__name__)


class EventQueue:
    """SSE 订阅队列（M-06 ①）：有界 deque + asyncio.Event 通知 + 分级丢弃策略。

    - 有界（maxsize）；超限时仅允许丢 log/step_progress，并记录 dropped_seq 区间
    - 关键事件队列满时腾位入队：移除队内最旧的可丢事件；全为关键事件时
      宁可短暂超界也不丢（锚点：队列满时关键事件不丢）
    - 线程约束：仅允许在归属 loop 线程内调用（跨线程由 EventBus.publish 经
      loop.call_soon_threadsafe 调度），内部无需加锁
    """

    DROPPABLE = frozenset({"log", "step_progress"})

    def __init__(self, maxsize: int = 200):
        self._items: collections.deque = collections.deque()
        self._maxsize = maxsize
        self._not_empty = asyncio.Event()
        self.dropped: List[Tuple[int, int]] = []  # 已合并的 (lo, hi) 丢弃区间

    def __len__(self) -> int:
        return len(self._items)

    def put_nowait(self, event: Dict[str, Any]) -> bool:
        """入队；返回 False 表示被丢弃（记录 dropped_seq 区间），True 表示已入队。"""
        if len(self._items) < self._maxsize:
            self._items.append(event)
            self._not_empty.set()
            return True
        if event.get("type") in self.DROPPABLE:
            self._record_drop(event["seq"])
            return False
        # 关键事件：腾位（移除队内最旧可丢事件）后入队
        for i, item in enumerate(self._items):
            if item.get("type") in self.DROPPABLE:
                del self._items[i]
                self._record_drop(item["seq"])
                self._items.append(event)
                return True
        # 队内全为关键事件且已满 → 宁可短暂超界也不丢关键事件
        logger.warning("[EventBus] subscriber queue full with critical-only events, grow seq=%s",
                       event["seq"])
        self._items.append(event)
        return True

    def get_nowait(self) -> Dict[str, Any]:
        if not self._items:
            raise asyncio.QueueEmpty
        return self._items.popleft()

    async def get(self) -> Dict[str, Any]:
        while not self._items:
            self._not_empty.clear()
            if not self._items:  # 双检：避免 clear-wait 之间 put 丢失唤醒
                await self._not_empty.wait()
        return self._items.popleft()

    def _record_drop(self, seq: int) -> None:
        if self.dropped and self.dropped[-1][1] == seq - 1:
            self.dropped[-1] = (self.dropped[-1][0], seq)  # 合并连续区间
        else:
            self.dropped.append((seq, seq))
            logger.warning("[EventBus] subscriber queue full, dropped_seq %s..%s", seq, seq)


class EventBus:
    def __init__(self, store: TaskStore):
        self._store = store
        self._subscribers: Dict[str, List[Tuple[Any, Optional[asyncio.AbstractEventLoop]]]] = {}
        self._lock = threading.Lock()

    # ── 发布（执行器线程调用；经归属 loop call_soon_threadsafe 投递，线程安全） ──
    def publish(self, task_id: str, event: Dict[str, Any]) -> int:
        """落库 + 通知订阅者，返回 seq。"""
        seq = self._store.append_event(task_id, event)
        event = {"seq": seq, **event}
        with self._lock:
            subs = list(self._subscribers.get(task_id, []))
        for queue, loop in subs:
            if loop is not None:
                try:
                    loop.call_soon_threadsafe(self._deliver, task_id, queue, event)
                except RuntimeError:
                    # 归属 loop 已关闭（SSE 断开/进程退出）→ 该订阅失效，丢弃
                    logger.warning("[EventBus] subscriber loop closed, drop seq=%s", seq)
            else:
                # 无归属 loop（离线测试直投路径）→ 当前线程即消费者所在线程
                self._deliver(task_id, queue, event)
        return seq

    def _deliver(self, task_id: str, queue: Any, event: Dict[str, Any]) -> None:
        """归属 loop 线程内投递（由 call_soon_threadsafe 调度执行）。"""
        try:
            if queue.put_nowait(event) is False:
                return  # EventQueue 已在内部记录 dropped_seq 区间并告警
        except asyncio.QueueFull:
            logger.warning("[EventBus] subscriber queue full, drop seq=%s", event["seq"])

    # ── 订阅（SSE 端点协程调用；捕获归属 loop 供跨线程投递） ──
    def subscribe(self, task_id: str, queue: Any) -> None:
        with self._lock:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            self._subscribers.setdefault(task_id, []).append((queue, loop))

    def unsubscribe(self, task_id: str, queue: Any) -> None:
        with self._lock:
            queues = self._subscribers.get(task_id)
            if queues:
                self._subscribers[task_id] = [s for s in queues if s[0] is not queue]
                if not self._subscribers[task_id]:
                    self._subscribers.pop(task_id, None)

    # ── 便捷发射（stage/step/message/澄清等，带类型校验） ──
    def emit(self, task_id: str, event_type: str, **fields: Any) -> int:
        event: Dict[str, Any] = {"type": event_type, **fields}
        return self.publish(task_id, event)

    def stage_started(self, task_id: str, stage_id: str, name: str) -> int:
        return self.emit(task_id, "stage_started", stage_id=stage_id, name=name)

    def stage_completed(self, task_id: str, stage_id: str, duration: float,
                        status: str = "completed") -> int:
        return self.emit(task_id, "stage_completed", stage_id=stage_id, duration=round(duration, 2), status=status)

    def message(self, task_id: str, role: str, content: str) -> int:
        return self.emit(task_id, "message", role=role, content=content)

    def clarification(self, task_id: str, cl_type: str, title: str,
                      fields: Optional[List[Dict[str, str]]] = None, question: str = "") -> int:
        ev: Dict[str, Any] = {"cl_type": cl_type, "title": title, "question": question}
        if fields:
            ev["fields"] = fields
        return self.publish(task_id, {"type": "clarification", **ev})

    def error(self, task_id: str, node: str, message: str, level: str = "warn") -> int:
        return self.emit(task_id, "error", node=node, message=message, level=level)
