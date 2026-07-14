"""
检索子图的Graph定义
"""

from langgraph.graph import StateGraph, END
from state.retrieval_state import RetrievalState
from pipeline.retrieval.agents import (
    expand_query_agent,
    paper_search_agent,
    citation_expansion_agent,
    filter_rank_agent,
    download_agent_sync
)


def create_retrieval_graph():
    """
    创建检索子图的Graph

    Returns:
        编译后的Graph对象
    """
    # 创建Graph
    graph = StateGraph(RetrievalState)

    # 添加Node
    graph.add_node("expand_query", expand_query_agent)
    graph.add_node("search_papers", paper_search_agent)
    graph.add_node("expand_citations", citation_expansion_agent)
    graph.add_node("filter_rank", filter_rank_agent)
    graph.add_node("download_papers", download_agent_sync)

    # 添加Edge（线性流程）
    graph.set_entry_point("expand_query")
    graph.add_edge("expand_query", "search_papers")
    graph.add_edge("search_papers", "expand_citations")
    graph.add_edge("expand_citations", "filter_rank")
    graph.add_edge("filter_rank", "download_papers")
    graph.add_edge("download_papers", END)

    # 编译Graph
    return graph.compile()
