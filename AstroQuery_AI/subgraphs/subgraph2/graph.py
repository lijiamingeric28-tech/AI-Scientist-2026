"""LangGraph 图构建模块

B2 收敛后：取消 simbad_resolver 节点，START 直接进入 database_query 和
build_ads_query→ads_search 并行。simbad_* 字段由 adapters 从 P1 的 simbad_info
预填充，子图2 不再做二次 SIMBAD 查询。
"""

import logging
from langgraph.graph import StateGraph, END, START

from astroquery_ai.config import get_settings
from .state import RetrievalState
from .nodes import (
    database_query,
    build_ads_query,
    ads_search,
    unpaywall_query,
    pdf_download,
    supplementary_query,
    result_aggregator
)

logger = logging.getLogger(__name__)


def create_retrieval_subgraph(checkpointer=None) -> StateGraph:
    """
    创建并行检索子图（B2 收敛版——无 simbad_resolver 入口）。
    Phase 4c: checkpointer 可选（HITL interrupt 支持）。

    流程：
      START → [database_query, build_ads_query] 并行
         database_query → result_aggregator
         build_ads_query → ads_search → unpaywall_query → pdf_download
             → supplementary_query → result_aggregator
      result_aggregator → END

    Returns:
        StateGraph: 编译后的图对象
    """
    logger.info("Creating Retrieval Subgraph")

    graph = StateGraph(RetrievalState)

    graph.add_node("database_query", database_query)
    graph.add_node("build_ads_query", build_ads_query)
    graph.add_node("ads_search", ads_search)
    graph.add_node("unpaywall_query", unpaywall_query)
    graph.add_node("pdf_download", pdf_download)
    graph.add_node("supplementary_query", supplementary_query)
    graph.add_node("result_aggregator", result_aggregator)

    # START → 两路并行（P18 消融：PAPER_CHAIN_ENABLED=false 时只走数据库路；
    # 不要用"空返回 build_ads_query"——ads_search 有仅天体名回退查询，会实际查 ADS）
    graph.add_edge(START, "database_query")
    if get_settings().paper_chain_enabled:
        graph.add_edge(START, "build_ads_query")

        # 论文链
        graph.add_edge("build_ads_query", "ads_search")
        graph.add_edge("ads_search", "unpaywall_query")
        graph.add_edge("unpaywall_query", "pdf_download")
        graph.add_edge("pdf_download", "supplementary_query")
        graph.add_edge("supplementary_query", "result_aggregator")
    else:
        graph.add_edge(START, "result_aggregator")

    # 数据库路
    graph.add_edge("database_query", "result_aggregator")

    # 汇合 → 结束
    graph.add_edge("result_aggregator", END)

    compiled_graph = graph.compile(checkpointer=checkpointer)
    logger.info("Retrieval Subgraph created successfully!")
    return compiled_graph
