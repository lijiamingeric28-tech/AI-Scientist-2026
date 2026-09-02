"""
检索子图的Graph定义 (V2.0 - PubMed集成)
"""

from langgraph.graph import StateGraph, END
from subgraphs.retrieval.state import RetrievalState
from subgraphs.retrieval.nodes import (
    expand_query_agent,
    paper_search_agent,
    pubmed_search_agent,
    citation_expansion_agent,
    filter_rank_agent,
    download_agent_sync
)


def create_retrieval_graph(enable_citation_expansion=True):
    """
    创建检索子图的Graph (V2.0 - 双源检索)

    流程：
    expand_query → search_openalex → search_pubmed →
    [expand_citations] → filter_rank → download_papers

    Args:
        enable_citation_expansion: 是否启用引用扩展（默认True）

    Returns:
        编译后的Graph对象
    """
    # 创建Graph
    graph = StateGraph(RetrievalState)

    # 添加Node
    graph.add_node("expand_query", expand_query_agent)
    graph.add_node("search_openalex", paper_search_agent)  # 重命名以明确来源
    graph.add_node("search_pubmed", pubmed_search_agent)    # 新增PubMed检索
    graph.add_node("filter_rank", filter_rank_agent)
    graph.add_node("download_papers", download_agent_sync)

    # 添加Edge（顺序执行）
    graph.set_entry_point("expand_query")
    graph.add_edge("expand_query", "search_openalex")
    graph.add_edge("search_openalex", "search_pubmed")     # OpenAlex → PubMed

    if enable_citation_expansion:
        # 启用引用扩展
        graph.add_node("expand_citations", citation_expansion_agent)
        graph.add_edge("search_pubmed", "expand_citations")
        graph.add_edge("expand_citations", "filter_rank")
    else:
        # 跳过引用扩展
        graph.add_edge("search_pubmed", "filter_rank")

    graph.add_edge("filter_rank", "download_papers")
    graph.add_edge("download_papers", END)

    # 编译Graph
    return graph.compile()
