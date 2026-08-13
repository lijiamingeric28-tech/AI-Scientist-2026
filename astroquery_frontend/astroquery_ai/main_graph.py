"""主图装配

拓扑
----
                       ┌──────────────┐
    START ──────────► │ clarification │
                       └──────┬───────┘
                              │ route_after_clarification
                  ┌───────────┴───────────┐
                  │                       │
          (可继续) ▼               (取消/无效) ▼
     ┌────────────────────┐               │
     │ property_std (P1)  │               │
     └──────┬─────────────┘               │
            │ (无条件)                    │
            ▼                            │
       ┌───────────┐                     │
       │ retrieval │                     │
       └─────┬─────┘                     │
             │ route_after_retrieval     │
   ┌─────────┴─────────┐                 │
(有PDF)▼           (无PDF)▼                 │
┌────────────┐   ┌─────────────────┐      │
│ extraction │   │ skip_extraction │      │
└──────┬─────┘   └────────┬────────┘      │
      └──────────┬───────┘               │
                 ▼                       │
           ┌─────────────┐ ◄─────────────┘
           │ aggregation │
           └──────┬──────┘
                  ▼
                 END

两处对设计文档的有意偏离（已与用户确认）
-------------------------------------
1. route_after_clarification 在用户取消/非天文查询时走 **aggregation**
   而非 END。设计文档写 END，但那样无法兑现"永远输出 JSON"的约定 ——
   下游会收到空响应而不是一个 records 为空的合法结构。

2. route_after_retrieval 额外判断 **extra_pdfs**。设计文档只看
   paper_results.download_paths，但当 Node 2 零下载而用户手动传了 PDF 时，
   那样会错误跳过 Node 3。
"""

import logging
import uuid
from typing import Dict, List, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .adapters import (
    clarification_node,
    extraction_node,
    property_standardization_adapter,
    retrieval_node,
    skip_extraction_node,
)
from .aggregator import final_aggregator
from .quality_adapter import quality_finalize_node, quality_node
from .state import MainGraphState

logger = logging.getLogger(__name__)


class _CancelledError(Exception):
    """节点边界取消信号（H-08①）：wrap 检查 should_cancel 时抛出，web_runner 捕获终止任务。

    定义在本模块而非 web_runner：wrap 需要抛出而 web_runner 已 import 本模块，
    反向 import 会成环；web_runner 从本模块复用此类。
    """


# ══════════════════════════════════════════════════════════════
# 路由函数
# ══════════════════════════════════════════════════════════════

def route_after_clarification(
    state: MainGraphState,
) -> Literal["property_std", "aggregation"]:
    """
    澄清后路由。

    终止条件（直接出空结果）：
    - 用户取消 / 检测到退出意图 -> clarification_status == "cancelled"
    - 非天文查询 -> query_type in ("greeting", "exit", "invalid")
    - 没拿到 target_entity -> 检索无从下手

    正常流程：进入 P1 性质标准化
    """
    status = state.get("clarification_status", "confirmed")
    query_type = state.get("query_type", "astronomical")
    entity = state.get("target_entity")

    if status == "cancelled":
        logger.info("[Router-1] 用户取消，跳到最终聚合")
        return "aggregation"

    if query_type in ("greeting", "exit", "invalid"):
        logger.info("[Router-1] 非天文查询 (%s)，跳到最终聚合", query_type)
        return "aggregation"

    if not entity:
        logger.warning("[Router-1] 无 target_entity，跳到最终聚合")
        return "aggregation"

    logger.info("[Router-1] 进入性质标准化 entity=%s", entity)
    return "property_std"


def route_after_retrieval(
    state: MainGraphState,
) -> Literal["extraction", "skip_extraction"]:
    """
    检索后路由。

    只要有任一来源的 PDF（自动下载 或 用户手动上传）就进 Node 3。
    """
    paper_results = state.get("paper_results") or {}
    downloaded = paper_results.get("download_paths", []) or []
    extra = state.get("extra_pdfs", []) or []

    if downloaded or extra:
        logger.info(
            "[Router-2] 进入提取 auto=%d manual=%d", len(downloaded), len(extra)
        )
        return "extraction"

    logger.info("[Router-2] 无 PDF，跳过提取")
    return "skip_extraction"


# ══════════════════════════════════════════════════════════════
# 图装配
# ══════════════════════════════════════════════════════════════

# Phase 3: 编译缓存 — 图结构是静态的, 每次调用重新编译纯属浪费
_compiled_graph = None


def create_main_graph(checkpointer=None, event_cb=None, should_cancel=None):
    """构建并编译主图（编译一次, 后续复用缓存实例）。

    Phase 4c: 支持可选 checkpointer —— HITL（interrupt）需要 checkpointer，
    带 checkpointer 的实例不缓存（每次独立，thread_id 隔离会话）。

    Phase 5 (web): 可选 event_cb(stage_event) —— 节点级阶段事件包装
    （stage_started/stage_completed，前端 7 卡映射）。
    默认 None 时行为完全不变（CLI / 离线测试零影响）。

    H-08①: 可选 should_cancel() —— 节点进入/退出边界检查，为真抛 _CancelledError，
    使 executor 的 cancel 能终止执行中的图（非澄清阶段也生效）。
    H-09④: 同图实例内对已 start 未 completed 的 stage 去重（抑制澄清重入的重复
    stage_started，DP-06 started=2/completed=1 实证）。
    """
    global _compiled_graph
    if checkpointer is None and _compiled_graph is not None:
        return _compiled_graph

    # 本图实例共享：已发 stage_started 但尚未 stage_completed 的 stage_id
    _active_stages: set = set()

    def wrap(stage_id: str, name: str, mode: str, fn):
        """包装节点：按前端阶段映射发 stage 事件（start/end/both）+ 取消边界检查。"""
        import time as _time

        def wrapped(*args, **kwargs):
            if should_cancel is not None and should_cancel():
                raise _CancelledError()
            if event_cb and mode in ("start", "both") and stage_id not in _active_stages:
                _active_stages.add(stage_id)
                event_cb("stage_started", stage_id=stage_id, name=name)
            t0 = _time.time()
            try:
                return fn(*args, **kwargs)
            finally:
                if should_cancel is not None and should_cancel():
                    raise _CancelledError()
                if event_cb and mode in ("end", "both"):
                    status = "skipped" if stage_id == "extraction" and fn is skip_extraction_node else "completed"
                    _active_stages.discard(stage_id)
                    payload = dict(stage_id=stage_id, duration=_time.time() - t0, status=status)
                    # 2026-08-14：卡 1 完成态实时数据——stage_completed(understand)
                    # 携带 target_entity/simbad_info/property_spec，前端运行中即渲染
                    # 标准性质（此前前端只在 openTask 快照恢复时从 /state 建 output，
                    # 运行中不显示、需刷新才出现）
                    if stage_id == "understand" and args and isinstance(args[0], dict):
                        _st = args[0]
                        payload["target_entity"] = _st.get("target_entity")
                        payload["simbad_info"] = _st.get("simbad_info")
                        payload["property_spec"] = _st.get("property_spec")
                    event_cb("stage_completed", **payload)
        return wrapped

    # 前端阶段映射：clarification+property_std → 任务理解；quality_finalize → 任务完成
    _NODES = {
        "clarification": ("understand", "任务理解", "start", clarification_node),
        "property_std": ("understand", "任务理解", "end", property_standardization_adapter),
        "retrieval": ("retrieval", "数据检索", "both", retrieval_node),
        "extraction": ("extraction", "数据提取", "both", extraction_node),
        "skip_extraction": ("extraction", "数据提取", "both", skip_extraction_node),
        "quality": ("quality_check", "质量检查", "both", quality_node),
        "quality_finalize": ("done", "任务完成", "end", quality_finalize_node),
    }

    graph = StateGraph(MainGraphState)

    for node_id, (stage_id, name, mode, fn) in _NODES.items():
        graph.add_node(node_id, wrap(stage_id, name, mode, fn) if event_cb else fn)
    graph.add_node("aggregation", final_aggregator)

    graph.add_edge(START, "clarification")

    graph.add_conditional_edges(
        "clarification",
        route_after_clarification,
        {"property_std": "property_std", "aggregation": "aggregation"},
    )

    graph.add_edge("property_std", "retrieval")

    graph.add_conditional_edges(
        "retrieval",
        route_after_retrieval,
        {"extraction": "extraction", "skip_extraction": "skip_extraction"},
    )

    graph.add_edge("extraction", "aggregation")
    graph.add_edge("skip_extraction", "aggregation")
    # Phase 4: quality → quality_finalize → END（修复质量结果不进 final_output 的断链）
    graph.add_edge("aggregation", "quality")
    graph.add_edge("quality", "quality_finalize")
    graph.add_edge("quality_finalize", END)

    compiled = graph.compile(checkpointer=checkpointer)
    if checkpointer is None:
        _compiled_graph = compiled
    logger.info("[Main Graph] 编译完成")
    return compiled


def _prompt_for_interrupt(payloads: List[Dict]) -> str:
    """CLI 端渲染 interrupt payload 并读取用户输入（HITL 交互）。

    前端对接时可用同样的 payload 结构自行渲染 UI，
    恢复时通过 Command(resume=answer) 传回答案。
    """
    for p in payloads:
        if not isinstance(p, dict):
            continue
        text = p.get("text") or p.get("question") or ""
        print(text)
    return input().strip()


def run_pipeline(
    user_query: str,
    extra_pdfs=None,
    query_id: str = None,
    recursion_limit: int = 50,
) -> Dict:
    """
    端到端执行一次完整查询（支持 HITL interrupt 循环）。

    Phase 4c: 节点内 input() 已改为 LangGraph interrupt()。
    本函数用 MemorySaver + thread_id 执行图：
      - 遇到 interrupt（state 出现 __interrupt__ 键）→ CLI 渲染 payload 读输入
      - Command(resume=answer) 恢复图执行
    前端可直接调用 create_main_graph(checkpointer=...) 自行处理 interrupt。

    Args:
        user_query: 用户自然语言问题
        extra_pdfs: 手动上传的 PDF 绝对路径列表（可选）
        query_id: 查询 ID，不传则自动生成 UUID（也是 HITL thread_id）
        recursion_limit: LangGraph 递归上限

    Returns:
        主图最终状态。final_output 键即下游消费的结构。
    """
    qid = query_id or str(uuid.uuid4())

    initial: Dict = {
        "user_query": user_query,
        "query_id": qid,
        "extra_pdfs": list(extra_pdfs or []),
        "error_log": [],
    }

    logger.info("[Pipeline] 启动 query_id=%s query=%r", qid, user_query)

    checkpointer = MemorySaver()
    app = create_main_graph(checkpointer=checkpointer)
    config = {
        # thread_id 隔离会话；checkpointer 供方式B 子图共享（HITL 持久化）
        "configurable": {"thread_id": qid, "checkpointer": checkpointer},
        "recursion_limit": recursion_limit,
    }

    result = app.invoke(initial, config)
    while isinstance(result, dict) and result.get("__interrupt__"):
        payloads = result["__interrupt__"]
        try:
            answer = _prompt_for_interrupt(payloads)
        except EOFError:
            # L-03 fix: stdin 关闭（如 `astroquery-ai ... < /dev/null`）时
            # input() 抛 EOFError —— 视为用户取消，返回当前 state，
            # 遵守"永远出 JSON"约定，不向调用方抛栈
            logger.warning("[Pipeline] 输入流关闭（EOF），按取消处理")
            return result
        result = app.invoke(Command(resume=answer), config)

    logger.info("[Pipeline] 结束 query_id=%s", qid)
    return result
