"""
Agent D: Citation_Expansion_Agent

通过引用链扩展候选论文池
"""

import logging
from state.retrieval_state import RetrievalState
from tools.citation_expansion import (
    select_seed_papers,
    get_cited_by_papers,
    get_references,
    parse_citation_item
)

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

    # 输入校验
    if not papers:
        print("\n[!]  输入论文列表为空，跳过引用扩展")
        logger.warning("papers is empty, skipping citation expansion")
        state["citation_papers"] = []

        print("\n[OK] [Agent D] 引用链扩展完成 - 跳过")
        print("="*80 + "\n")
        return state

    print(f"\n>>> 收到 {len(papers)} 篇初始论文")
    logger.info(f"Received {len(papers)} papers from Agent B")

    # ===== Node 1: Seed Selection =====
    print(f"\n[步骤 1/2] 选择种子论文")
    logger.info("[Node 1] Selecting seed papers")

    TOP_N = 5
    seed_papers = select_seed_papers(papers, top_n=TOP_N)

    print(f"  [+] 选择了 {len(seed_papers)} 篇种子论文:")
    for idx, paper in enumerate(seed_papers, 1):
        print(f"     [{idx}] {paper.title[:50]}... (引用数: {paper.citation_count})")

    logger.info(f"Selected {len(seed_papers)} seed papers")
    for idx, paper in enumerate(seed_papers, 1):
        logger.debug(f"  Seed {idx}: {paper.id} | {paper.title[:50]}... | citations={paper.citation_count}")

    # ===== Node 2: Citation Expansion =====
    print(f"\n[步骤 2/2] 执行引用链扩展")
    logger.info("[Node 2] Starting citation expansion")

    citation_papers = []

    for seed_idx, seed in enumerate(seed_papers, 1):
        print(f"\n  [SEED] 种子 {seed_idx}/{len(seed_papers)}: {seed.title[:40]}...")
        logger.info(f"[Seed {seed_idx}/{len(seed_papers)}] Processing {seed.id}")

        # 前向引用（cited_by）
        print(f"     [UP]  获取前向引用（谁引用了它）...")
        logger.debug(f"  Fetching cited_by papers...")
        try:
            cited_by_items = get_cited_by_papers(seed.id, max_results=10)
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
        logger.debug(f"  Fetching references...")
        try:
            ref_items = get_references(seed.id, max_results=10)
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
