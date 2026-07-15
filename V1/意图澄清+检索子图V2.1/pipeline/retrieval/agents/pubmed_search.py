"""
Agent B2: PubMed_Search_Agent

调用PubMed API检索医学文献（受ENABLE_PUBMED全局开关控制）
"""

import logging
from state.retrieval_state import RetrievalState
from configs.constants import ENABLE_PUBMED
from tools.pubmed_search import search_pubmed, fetch_paper_details, get_pmc_links, parse_pubmed_metadata
from configs.constants import PUBMED_EMAIL, PUBMED_API_KEY

logger = logging.getLogger(__name__)


class StateValidationError(Exception):
    """State验证错误"""
    pass


def pubmed_search_agent(state: RetrievalState) -> RetrievalState:
    """
    Agent B2: PubMed_Search_Agent

    调用PubMed API检索文献（受ENABLE_PUBMED全局开关控制）
    """
    # 🔒 全局开关检查
    if not ENABLE_PUBMED:
        print("\n" + "="*80)
        print("[PUBMED] [检索子图 - Agent B2] PubMed检索已禁用（ENABLE_PUBMED=False）")
        print("="*80)
        logger.info("[Agent B2] PubMed search DISABLED by global config")
        state["pubmed_papers"] = []
        print("\n[LOCKED] PubMed功能已在配置中禁用 (configs/constants.py)")
        print("="*80 + "\n")
        return state

    print("\n" + "="*80)
    print("[PUBMED] [检索子图 - Agent B2] PubMed文献检索开始")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent B2] PubMed_Search_Agent started")

    # ========== Step 1: 验证输入 ==========
    expanded_queries = state.get("expanded_queries")
    if not expanded_queries or "pubmed" not in expanded_queries:
        logger.warning("expanded_queries is empty or missing 'pubmed' field, skipping PubMed search")
        print("\n[!] expanded_queries中没有pubmed字段，跳过PubMed检索")
        print("="*80 + "\n")
        state["pubmed_papers"] = []
        return state

    pubmed_query_params = expanded_queries["pubmed"]
    search_query = pubmed_query_params.get("search")
    filters = pubmed_query_params.get("filters", {})

    if not search_query:
        raise StateValidationError("pubmed.search is empty")

    print(f"\n>>> 输入:")
    print(f"  - PubMed查询: {search_query[:80]}...")
    print(f"  - 过滤条件: {filters}")

    logger.info(f"PubMed search query: {search_query}")
    logger.info(f"Filters: {filters}")

    # ========== Step 2: 调用PubMed API ==========
    print(f"\n>>> 步骤1: 调用PubMed ESearch API...")

    try:
        # Step 2.1: 搜索获取PMID列表
        pmids = search_pubmed(
            query=search_query,
            filters=filters,
            email=PUBMED_EMAIL,
            api_key=PUBMED_API_KEY
        )

        print(f"  [+] 找到 {len(pmids)} 篇论文的PMID")
        logger.info(f"Retrieved {len(pmids)} PMIDs from PubMed")

        if not pmids:
            print("\n[!] PubMed检索无结果")
            print("="*80 + "\n")
            state["pubmed_papers"] = []
            return state

    except Exception as e:
        print(f"  [X] PubMed ESearch调用失败: {e}")
        logger.error(f"PubMed ESearch call failed: {e}")
        state["pubmed_papers"] = []
        return state

    # ========== Step 3: 获取论文详情 ==========
    print(f"\n>>> 步骤2: 获取论文元数据...")

    try:
        # Step 3.1: 批量获取元数据
        summaries = fetch_paper_details(
            pmids=pmids,
            email=PUBMED_EMAIL,
            api_key=PUBMED_API_KEY
        )

        print(f"  [+] 成功获取 {len(summaries)} 篇论文的元数据")
        logger.info(f"Fetched {len(summaries)} paper details")

    except Exception as e:
        print(f"  [X] 获取元数据失败: {e}")
        logger.error(f"Failed to fetch paper details: {e}")
        state["pubmed_papers"] = []
        return state

    # ========== Step 4: 获取PMC下载链接 ==========
    print(f"\n>>> 步骤3: 获取PMC全文链接...")

    try:
        pmc_links = get_pmc_links(
            pmids=pmids,
            email=PUBMED_EMAIL,
            api_key=PUBMED_API_KEY
        )

        print(f"  [+] 找到 {len(pmc_links)} 篇论文的PMC链接 ({len(pmc_links)/len(pmids)*100:.1f}%)")
        logger.info(f"Retrieved {len(pmc_links)} PMC links")

    except Exception as e:
        print(f"  [!] 获取PMC链接失败: {e}，继续处理")
        logger.warning(f"Failed to get PMC links: {e}")
        pmc_links = {}

    # ========== Step 5: 转换为PaperMetadata ==========
    print(f"\n>>> 步骤4: 转换为PaperMetadata格式...")

    papers = []
    for summary in summaries:
        pmid = summary.get("uid")
        pmc_url = pmc_links.get(pmid)

        paper = parse_pubmed_metadata(summary, pmc_url)
        if paper:
            papers.append(paper)

    print(f"  [+] 成功解析 {len(papers)} 篇论文")

    if papers:
        print(f"\n  [DOC] 前3篇PubMed论文预览:")
        for idx, paper in enumerate(papers[:3], 1):
            # 安全处理可能包含特殊字符的标题
            try:
                # 移除所有非ASCII字符
                title_safe = ''.join(c if ord(c) < 128 else '?' for c in paper.title[:60])
                print(f"     [{idx}] {title_safe}...")
            except Exception as e:
                print(f"     [{idx}] [Title contains special characters]")

            print(f"         PMID: {paper.pmid} | Year: {paper.year} | Citations: {paper.citation_count}")
            if paper.pubmed_download_url:
                print(f"         PMC: Yes")

    logger.info(f"Converted {len(papers)} papers to PaperMetadata")

    # ========== Step 6: 写入State ==========
    state["pubmed_papers"] = papers

    print(f"\n[OK] [Agent B2] PubMed文献检索完成 - 共 {len(papers)} 篇")
    print("="*80 + "\n")

    logger.info("[Agent B2] PubMed_Search_Agent completed")
    logger.info("=" * 50)

    return state
