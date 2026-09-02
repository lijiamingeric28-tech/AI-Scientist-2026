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


def create_main_graph(checkpointer=None):
    """构建并编译主图（编译一次, 后续复用缓存实例）。

    Phase 4c: 支持可选 checkpointer —— HITL（interrupt）需要 checkpointer，
    带 checkpointer 的实例不缓存（每次独立，thread_id 隔离会话）。
    """
    global _compiled_graph
    if checkpointer is None and _compiled_graph is not None:
        return _compiled_graph

    graph = StateGraph(MainGraphState)

    graph.add_node("clarification", clarification_node)
    graph.add_node("property_std", property_standardization_adapter)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("skip_extraction", skip_extraction_node)
    graph.add_node("aggregation", final_aggregator)
    graph.add_node("quality", quality_node)
    graph.add_node("quality_finalize", quality_finalize_node)

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
