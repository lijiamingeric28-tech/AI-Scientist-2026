"""
检索子图的Graph定义 (V2.0 - PubMed集成)
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
from pipeline.retrieval.agents.pubmed_search import pubmed_search_agent


def create_retrieval_graph():
    """
    创建检索子图的Graph (V2.0 - 双源检索)

    流程：
    expand_query → search_openalex → search_pubmed →
    expand_citations → filter_rank → download_papers

    Returns:
        编译后的Graph对象
    """
    # 创建Graph
    graph = StateGraph(RetrievalState)

    # 添加Node
    graph.add_node("expand_query", expand_query_agent)
    graph.add_node("search_openalex", paper_search_agent)  # 重命名以明确来源
    graph.add_node("search_pubmed", pubmed_search_agent)    # 新增PubMed检索
    graph.add_node("expand_citations", citation_expansion_agent)
    graph.add_node("filter_rank", filter_rank_agent)
    graph.add_node("download_papers", download_agent_sync)

    # 添加Edge（顺序执行）
    graph.set_entry_point("expand_query")
    graph.add_edge("expand_query", "search_openalex")
    graph.add_edge("search_openalex", "search_pubmed")     # OpenAlex → PubMed
    graph.add_edge("search_pubmed", "expand_citations")    # PubMed → 引用扩展
    graph.add_edge("expand_citations", "filter_rank")
    graph.add_edge("filter_rank", "download_papers")
    graph.add_edge("download_papers", END)

    # 编译Graph
    return graph.compile()
