"""事件化执行器（web 专用 runner，不动现有 run_pipeline / CLI）。

与 CLI run_pipeline 的差异：
- checkpointer = SqliteSaver（持久化，D1-6）
- interrupt 循环：发 clarification 事件 → get_answer() 阻塞等待前端 resume
- cancel 检查点：should_cancel() 为真时终止（D2/D4）
- 阶段事件经 create_main_graph(event_cb=...) 注入（模块 ②）
- 任务完成：task_completed 先发（终态即时），LLM 总结（模块 ⑤）异步补发 ai message（M-12）

澄清 payload 结构化（模块 ④ 精修前）：
从子图 interrupt 的原始 payload {type, question, target_entity, requested_properties}
推导前端卡所需的 title/fields。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .main_graph import create_main_graph, _CancelledError

logger = logging.getLogger(__name__)

# 前端 7 卡完成摘要模板（D6-3：阶段总结前端拼字段，runner 只发原始数据）
STAGE_TITLES = {
    "understand": "任务理解",
    "retrieval": "数据检索",
    "extraction": "数据提取",
    "quality_check": "质量检查",
    "clean": "数据清洗",
    "deliver": "数据交付",
    "done": "任务完成",
}

# interrupt type → 前端澄清卡标题（模块 ④ 结构化后由 payload 提供）
_CLAR_TITLES = {
    "ask_entity": "确认天体名称",
    "ask_properties": "选择查询性质",
    "final_confirm": "确认查询信息",
    "final_confirm_modify": "重新输入查询",
    "greeting": "对话",
    # 质量管线 human_review（已 HITL 化，Phase 4c）
    "human_review_next": "人工审核",
    "human_review_verdict": "冲突审查",
    "human_review_custom_value": "自定义值",
    "human_review_reason": "修改理由",
}

# interrupt type → 前端所属阶段卡（澄清卡定位渲染，契约补充字段）
_CLAR_STAGES = {
    "ask_entity": "understand",
    "ask_properties": "understand",
    "final_confirm": "understand",
    "final_confirm_modify": "understand",
    "greeting": "understand",
    # human_review 在质量管线（前端卡 5 数据清洗区域）
    "human_review_next": "clean",
    "human_review_verdict": "clean",
    "human_review_custom_value": "clean",
    "human_review_reason": "clean",
}


class _AnswerSlot:
    """resume 等待槽（可重置，供多轮澄清复用）：
    执行器线程阻塞等 answer；resume/cancel/超时唤醒。

    H-04: waiting 标志——wait() 前置 True、返回后置 False；set_answer 仅
    在 waiting 且未 cancelled 时生效（非等待期的陈旧答案不得注入）。
    """

    def __init__(self):
        self._evt = threading.Event()
        self.answer: Optional[str] = None
        self.cancelled = False
        self._waiting = False

    @property
    def waiting(self) -> bool:
        """真实挂起状态：正在等答案且未被取消（供 executor /state 使用）。"""
        return self._waiting and not self.cancelled

    def wait(self, timeout: Optional[float] = None) -> bool:
        self._waiting = True
        try:
            return self._evt.wait(timeout)
        finally:
            self._waiting = False

    def set_answer(self, answer: str) -> bool:
        """仅等待期写入答案；否则返回 False（调用方转 409）。"""
        if not self._waiting or self.cancelled:
            return False
        self.answer = answer
        self._evt.set()
        return True

    def cancel(self) -> None:
        self.cancelled = True
        self._evt.set()

    def reset(self) -> None:
        """新一轮澄清前重置（Event 已 set 后不 clear 会立即返回旧值）。"""
        self.answer = None
        self.cancelled = False
        self._waiting = False
        self._evt.clear()


def _clarification_payload(raw: Any) -> Dict[str, Any]:
    """原始 interrupt payload → 前端澄清卡字段（模块 ④ 结构化后续约）。

    langgraph 的 __interrupt__ 元素是 Interrupt 对象（value 为传入 payload）。
    子图 1 已结构化（title/fields/error），此处透传 + 兜底推导。
    """
    if hasattr(raw, "value"):  # Interrupt 对象
        raw = raw.value
    if not isinstance(raw, dict):
        return {"type": "clarification", "title": "澄清请求", "question": str(raw)}
    cl_type = raw.get("type", "clarification")
    title = raw.get("title") or _CLAR_TITLES.get(cl_type, "澄清请求")
    ev: Dict[str, Any] = {
        "type": "clarification",
        "cl_type": cl_type,
        "stage_id": _CLAR_STAGES.get(cl_type, "understand"),  # 前端澄清卡定位
        "title": title,
        # H-10: question 兜底取 text 指引（human_review / final_confirm_modify
        # 等旧 payload 无 question 键 → 澄清事件不再恒空，Web 端人工审核可见指引）
        "question": raw.get("question") or raw.get("text", ""),
    }
    if raw.get("fields"):
        ev["fields"] = raw["fields"]
    elif raw.get("target_entity"):  # 兜底推导（老 payload）
        ev["fields"] = [{"label": "天体名称", "value": str(raw["target_entity"])}]
    if raw.get("error"):  # M-09 重发提示
        ev["error"] = raw["error"]
    if raw.get("options"):  # H-10: human_review 候选选项透传（前端快捷按钮）
        ev["options"] = raw["options"]
    return ev


def run_task_streaming(
    task_id: str,
    user_query: str,
    extra_pdfs: List[str],
    bus,  # EventBus
    get_answer: Callable[[str, Dict[str, Any]], Optional[str]],
    should_cancel: Callable[[], bool],
    checkpointer_path: str,
    on_final_summary: Optional[Callable[[str], str]] = None,  # 模块⑤ LLM 总结
) -> Dict[str, Any]:
    """执行一次查询并推送事件。返回最终 state。

    get_answer(task_id, clarification_payload) 阻塞等待前端 resume：
      - 返回 answer → Command(resume=answer) 继续
      - 返回 None（取消/超时）→ 任务终止（task_cancelled 由调用方发出：
        executor.cancel / get_answer 超时分支，H-08② 防重复发）
    """
    result: Dict[str, Any] = {}

    def _answer_handler(raw_payload: Any) -> str:
        """interrupt → 发澄清事件 → get_answer 阻塞（executor 层管理超时/取消）。"""
        payload = _clarification_payload(raw_payload)
        bus.publish(task_id, payload)
        answer = get_answer(task_id, payload)
        if should_cancel() or answer is None:
            # H-08②：task_cancelled 由调用方发出（executor.cancel / get_answer
            # 超时分支），此处不再发，避免同一取消路径双份事件
            raise _CancelledError()
        return answer

    def _events(stage_event: str, **fields: Any) -> None:
        ev = {"type": stage_event, **fields}
        bus.publish(task_id, ev)

    try:
        with SqliteSaver.from_conn_string(checkpointer_path) as checkpointer:
            app = create_main_graph(
                checkpointer=checkpointer, event_cb=_events, should_cancel=should_cancel,
            )
            config = {
                # checkpointer 必须与主图共享同一实例（CLI run_pipeline 同款）：
                # quality 子图编译时 _shared_checkpointer(config) 用它，子图内 HITL
                # interrupt 才能持久化并上浮到主图 loop（web 模式此前缺该键 →
                # quality 子图冲突裁决 interrupt 无法上浮 → 降级路径，2026-08-17
                # 大角星任务 fatal 根因之一）
                "configurable": {"thread_id": task_id, "checkpointer": checkpointer},
                "recursion_limit": 50,
            }
            initial: Dict[str, Any] = {
                "user_query": user_query,
                "query_id": task_id,
                "extra_pdfs": list(extra_pdfs),
                "error_log": [],
            }
            result = app.invoke(initial, config)
            while isinstance(result, dict) and result.get("__interrupt__"):
                payloads = result["__interrupt__"]
                if not isinstance(payloads, list):
                    payloads = [payloads]
                for p in payloads:
                    answer = _answer_handler(p)
                    result = app.invoke(Command(resume=answer), config)
                    if isinstance(result, dict) and not result.get("__interrupt__"):
                        break
    except _CancelledError:
        logger.info("[Runner] task %s cancelled", task_id)
        return result

    # ── 终态（CR-01：最后一次 invoke 返回后 result 才是真实最终 state；
    #    stage_completed(done) 的 wrap finally 先于 invoke 返回触发，
    #    不能在那里取 result，否则恒为 {} 或上一轮 __interrupt__ dict）──
    if isinstance(result, dict) and not result.get("__interrupt__"):
        if should_cancel():
            # H-08③：已取消（executor.cancel 已发 task_cancelled）→ 不发 task_completed
            return result
        if result.get("clarification_status") == "cancelled":
            # H-09①③：选 n 取消 → 发 task_cancelled 而非 task_completed；
            # understand 卡未走 property_std，补发灰态完成（卡 1 不再永久进行中）
            bus.emit(task_id, "stage_completed", stage_id="understand", status="cancelled", duration=0)
            bus.emit(task_id, "task_cancelled", reason="user_cancelled")
            return result
        if result.get("query_type") in ("greeting", "exit", "invalid"):
            # H-09③：非天文分支同样未走 property_std → 补发 understand 完成事件
            bus.emit(task_id, "stage_completed", stage_id="understand", status="cancelled", duration=0)
        # P0-1：task_completed 不再由 runner 发出——迁移到 executor._finish 在
        # state_json/status 落库之后发（此前 runner 先发导致前端 loadTasks 拿到
        # running 列表、右侧面板/结果表格停在全 0 的时序竞态）。
        # M-12 保留：LLM 总结仍异步生成（慢/超时 LLM 不阻塞执行线程与排队任务），
        # 由 _summarize 线程在 task_completed 之后补发 ai message。
        if on_final_summary:
            def _summarize() -> None:
                try:
                    summary = on_final_summary(task_id, result)
                except Exception as exc:
                    logger.warning("[Runner] 总结生成失败，降级: %s", exc)
                    summary = "任务完成"
                bus.message(task_id, "ai", summary)
            threading.Thread(
                target=_summarize, daemon=True, name=f"summary-{task_id[:8]}",
            ).start()

    return result
