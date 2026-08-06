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
from typing import Dict, Literal

from langgraph.graph import END, START, StateGraph

from .adapters import (
    clarification_node,
    extraction_node,
    property_standardization_adapter,
    retrieval_node,
    skip_extraction_node,
)
from .aggregator import final_aggregator
from .quality_adapter import quality_node
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

def create_main_graph():
    """构建并编译主图"""
    graph = StateGraph(MainGraphState)

    graph.add_node("clarification", clarification_node)
    graph.add_node("property_std", property_standardization_adapter)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("skip_extraction", skip_extraction_node)
    graph.add_node("aggregation", final_aggregator)
    graph.add_node("quality", quality_node)

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
    graph.add_edge("aggregation", "quality")
    graph.add_edge("quality", END)

    compiled = graph.compile()
    logger.info("[Main Graph] 编译完成")
    return compiled


def run_pipeline(
    user_query: str,
    extra_pdfs=None,
    query_id: str = None,
    recursion_limit: int = 50,
) -> Dict:
    """
    端到端执行一次完整查询。

    Args:
        user_query: 用户自然语言问题
        extra_pdfs: 手动上传的 PDF 绝对路径列表（可选）
        query_id: 查询 ID，不传则自动生成 UUID
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

    app = create_main_graph()
    final_state = app.invoke(initial, config={"recursion_limit": recursion_limit})

    logger.info("[Pipeline] 结束 query_id=%s", qid)
    return final_state
