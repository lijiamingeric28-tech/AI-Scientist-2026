"""
Agent B: Paper_Search_Agent

调用OpenAlex API搜索学术文献
"""

import logging
from subgraphs.retrieval.state import RetrievalState
from subgraphs.retrieval.tools.paper_search import call_openalex_api

logger = logging.getLogger(__name__)


class StateValidationError(Exception):
    """State验证错误"""
    pass


def paper_search_agent(state: RetrievalState) -> RetrievalState:
    """
    Agent B: Paper_Search_Agent

    调用OpenAlex API搜索文献
    """
    print("\n" + "="*80)
    print("[BOOKS] [检索子图 - Agent B] 文献搜索开始")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent B] Paper_Search_Agent started")

    # ========== Step 1: 验证输入 ==========
    expanded_queries = state.get("expanded_queries")
    if not expanded_queries or "openalex" not in expanded_queries:
        raise StateValidationError(
            "expanded_queries is empty or missing 'openalex' field"
        )

    openalex_params = expanded_queries["openalex"]
    search = openalex_params.get("search")
    filter_dict = openalex_params.get("filter", {})
    per_page = openalex_params.get("per_page", 50)

    print(f"\n>>> API调用参数:")
    print(f"  - 搜索查询: {search[:80]}..." if len(search) > 80 else f"  - 搜索查询: {search}")
    print(f"  - 过滤条件: {filter_dict}")
    print(f"  - 返回数量: {per_page} 篇")

    logger.info(f"Search query: {search}")
    logger.info(f"Filter: {filter_dict}")
    logger.info(f"Per page: {per_page}")

    # ========== Step 2: 调用OpenAlex API ==========
    print(f"\n[WWW] 调用OpenAlex API...")

    try:
        papers = call_openalex_api(search, filter_dict, per_page)

        print(f"  [+] 成功检索到 {len(papers)} 篇论文")

        if papers:
            print(f"\n  [DOC] 前3篇论文预览:")
            for idx, paper in enumerate(papers[:3], 1):
                print(f"     [{idx}] {paper.title[:60]}...")
                print(f"         引用数: {paper.citation_count} | 年份: {paper.year}")

        logger.info(f"Retrieved {len(papers)} papers from OpenAlex")

    except Exception as e:
        print(f"  [X] API调用失败: {e}")
        logger.error(f"OpenAlex API call failed: {e}")
        papers = []

    # ========== Step 3: 写入State ==========
    state["papers"] = papers

    print(f"\n[OK] [Agent B] 文献搜索完成 - 共 {len(papers)} 篇")
    print("="*80 + "\n")

    logger.info("[Agent B] Paper_Search_Agent completed")
    logger.info("=" * 50)

    return state
