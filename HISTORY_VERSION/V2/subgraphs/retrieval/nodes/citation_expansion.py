"""
Agent D: Citation_Expansion_Agent

通过引用链扩展候选论文池（受ENABLE_PUBMED全局开关控制）
"""

import logging
from subgraphs.retrieval.state import RetrievalState
from subgraphs.retrieval.tools.citation_expansion import (
    select_seed_papers,
    get_cited_by_papers,
    get_references,
    parse_citation_item,
    pmid_to_doi,
    doi_to_openalex_id
)
from config.constants import PUBMED_EMAIL, PUBMED_API_KEY, ENABLE_PUBMED

logger = logging.getLogger(__name__)


def citation_expansion_agent(state: RetrievalState) -> RetrievalState:
    """
    Agent D: Citation_Expansion_Agent

    通过引用链扩展候选论文池
    """
    print("\n" + "="*80)
    print("[LINK] [检索子图 - Agent D] 引用链扩展开始")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent D] Citation_Expansion_Agent started")

    # 读取输入
    papers = state.get("papers", [])

    # 🔒 全局开关检查 - 如果PubMed禁用，不使用PubMed论文作为种子
    if ENABLE_PUBMED:
        pubmed_papers = state.get("pubmed_papers", [])
        logger.info(f"PubMed papers (ENABLED): {len(pubmed_papers)}")
    else:
        pubmed_papers = []
        logger.info(f"PubMed papers (DISABLED by global config): skipping as seeds")

    # 合并两个来源的论文
    all_papers = papers + pubmed_papers

    # 输入校验
    if not all_papers:
        print("\n[!]  输入论文列表为空，跳过引用扩展")
        logger.warning("papers and pubmed_papers are both empty, skipping citation expansion")
        state["citation_papers"] = []

        print("\n[OK] [Agent D] 引用链扩展完成 - 跳过")
        print("="*80 + "\n")
        return state

    print(f"\n>>> 收到 {len(all_papers)} 篇初始论文")
    print(f"    - OpenAlex: {len(papers)} 篇")
    print(f"    - PubMed: {len(pubmed_papers)} 篇")
    logger.info(f"Received {len(papers)} OpenAlex papers + {len(pubmed_papers)} PubMed papers")

    # ===== Node 1: Seed Selection =====
    print(f"\n[步骤 1/2] 选择种子论文")
    logger.info("[Node 1] Selecting seed papers from both sources")

    # 分别从两个来源选择种子
    TOP_N_PER_SOURCE = 5

    # 从OpenAlex选择Top 5
    openalex_papers = [p for p in all_papers if p.source_db == "openalex"]
    openalex_seeds = select_seed_papers(openalex_papers, top_n=TOP_N_PER_SOURCE)
    print(f"  [+] OpenAlex种子: {len(openalex_seeds)} 篇")
    for idx, paper in enumerate(openalex_seeds, 1):
        print(f"     [{idx}] {paper.title[:50]}... (引用数: {paper.citation_count})")
        logger.debug(f"  OpenAlex Seed {idx}: {paper.id} | citations={paper.citation_count}")

    # 从PubMed选择Top 5
    pubmed_papers_list = [p for p in all_papers if p.source_db == "pubmed"]
    pubmed_seeds = select_seed_papers(pubmed_papers_list, top_n=TOP_N_PER_SOURCE)
    print(f"  [+] PubMed种子: {len(pubmed_seeds)} 篇")
    for idx, paper in enumerate(pubmed_seeds, 1):
        print(f"     [{idx}] {paper.title[:50]}... (引用数: {paper.citation_count})")
        logger.debug(f"  PubMed Seed {idx}: PMID {paper.pmid} | citations={paper.citation_count}")

    # 合并两边的种子
    seed_papers = openalex_seeds + pubmed_seeds

    print(f"\n  [TOTAL] 总共选择了 {len(seed_papers)} 篇种子论文 (OpenAlex: {len(openalex_seeds)}, PubMed: {len(pubmed_seeds)})")
    logger.info(f"Selected {len(seed_papers)} total seed papers ({len(openalex_seeds)} OpenAlex + {len(pubmed_seeds)} PubMed)")

    # ===== Node 2: Citation Expansion =====
    print(f"\n[步骤 2/2] 执行引用链扩展")
    logger.info("[Node 2] Starting citation expansion")

    citation_papers = []

    for seed_idx, seed in enumerate(seed_papers, 1):
        source = seed.source_db or "unknown"
        print(f"\n  [SEED] 种子 {seed_idx}/{len(seed_papers)}: {seed.title[:40]}... (来源: {source})")
        logger.info(f"[Seed {seed_idx}/{len(seed_papers)}] Processing {seed.id} (source={source})")

        # 获取OpenAlex ID（用于引用扩展）
        openalex_id = None

        if seed.source_db == "openalex":
            # OpenAlex论文，直接使用ID
            openalex_id = seed.id
            logger.debug(f"  Using OpenAlex ID directly: {openalex_id}")

        elif seed.source_db == "pubmed":
            # PubMed论文，需要转换：PMID -> DOI -> OpenAlex ID
            print(f"     [CONVERT] PubMed论文，转换为OpenAlex ID...")
            logger.info(f"  Converting PubMed paper {seed.pmid} to OpenAlex ID")

            # Step 1: 获取DOI
            doi = seed.doi
            if not doi:
                print(f"        [API] PMID -> DOI...")
                doi = pmid_to_doi(seed.pmid, email=PUBMED_EMAIL, api_key=PUBMED_API_KEY)

            if doi:
                print(f"        [OK] DOI: {doi}")
                logger.info(f"  Got DOI: {doi}")

                # Step 2: DOI转OpenAlex ID
                print(f"        [API] DOI -> OpenAlex ID...")
                openalex_id = doi_to_openalex_id(doi, email=PUBMED_EMAIL)

                if openalex_id:
                    print(f"        [OK] OpenAlex ID: {openalex_id}")
                    logger.info(f"  Converted to OpenAlex ID: {openalex_id}")
                else:
                    print(f"        [!] DOI转换失败，跳过此种子")
                    logger.warning(f"  Failed to convert DOI {doi} to OpenAlex ID")
            else:
                print(f"        [!] 无法获取DOI，跳过此种子")
                logger.warning(f"  Failed to get DOI for PMID {seed.pmid}")

        # 如果没有OpenAlex ID，跳过此种子
        if not openalex_id:
            print(f"     [!] 无法获取OpenAlex ID，跳过引用扩展")
            logger.warning(f"  No OpenAlex ID available, skipping citation expansion for seed {seed_idx}")
            continue

        # 前向引用（cited_by）
        print(f"     [UP]  获取前向引用（谁引用了它）...")
        logger.debug(f"  Fetching cited_by papers for {openalex_id}...")
        try:
            cited_by_items = get_cited_by_papers(openalex_id, max_results=10)
            print(f"        [+] 找到 {len(cited_by_items)} 篇前向引用")
            logger.info(f"  Found {len(cited_by_items)} cited_by papers")

            for item in cited_by_items:
                paper = parse_citation_item(item)
                if paper:
                    citation_papers.append(paper)

        except Exception as e:
            print(f"        [X] 前向引用获取失败: {e}")
            logger.warning(f"  Failed to get cited_by papers: {e}")

        # 后向引用（references）
        print(f"     [DOWN]  获取后向引用（它引用了谁）...")
        logger.debug(f"  Fetching references for {openalex_id}...")
        try:
            ref_items = get_references(openalex_id, max_results=10)
            print(f"        [+] 找到 {len(ref_items)} 篇后向引用")
            logger.info(f"  Found {len(ref_items)} references")

            for item in ref_items:
                paper = parse_citation_item(item)
                if paper:
                    citation_papers.append(paper)

        except Exception as e:
            print(f"        [X] 后向引用获取失败: {e}")
            logger.warning(f"  Failed to get references: {e}")

    # 写入输出
    state["citation_papers"] = citation_papers

    print(f"\n[OK] [Agent D] 引用链扩展完成 - 新增 {len(citation_papers)} 篇候选论文")
    print("="*80 + "\n")

    logger.info(f"Citation expansion completed: {len(citation_papers)} papers added")
    logger.info("[Agent D] Citation_Expansion_Agent completed")
    logger.info("=" * 50)

    return state
