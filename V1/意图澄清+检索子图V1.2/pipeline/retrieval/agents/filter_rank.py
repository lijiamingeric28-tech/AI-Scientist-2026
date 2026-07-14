"""
Agent E: Paper_Filter_Rank_Agent

合并、去重、过滤、排序论文列表
"""

import logging
from state.retrieval_state import RetrievalState
from tools.filter_rank import (
    merge_papers,
    deduplicate_by_id,
    filter_papers,
    calculate_score,
    rank_and_select_top
)
from configs.constants import OUTPUT_TOP_N

logger = logging.getLogger(__name__)


def filter_rank_agent(state: RetrievalState) -> RetrievalState:
    """
    Agent E: Paper_Filter_Rank_Agent

    合并、去重、过滤、排序论文列表
    """
    print("\n" + "="*80)
    print("[*] [检索子图 - Agent E] 过滤排序开始")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent E] Paper_Filter_Rank_Agent started")

    # 读取输入
    papers = state.get("papers", [])
    citation_papers = state.get("citation_papers", [])

    print(f"\n>>> 收到论文:")
    print(f"  - Agent B搜索结果: {len(papers)} 篇")
    print(f"  - Agent D引用扩展: {len(citation_papers)} 篇")

    logger.info(f"papers: {len(papers)}, citation_papers: {len(citation_papers)}")

    # 输入校验
    if not papers and not citation_papers:
        print("\n[!]  输入论文列表都为空，返回空列表")
        logger.warning("Both papers and citation_papers are empty")
        state["filtered_papers"] = []

        print("\n[OK] [Agent E] 过滤排序完成 - 无结果")
        print("="*80 + "\n")
        return state

    # ===== Node 1: Merge =====
    print(f"\n[步骤 1/5] 合并论文列表")
    logger.info("[Node 1] Merging paper lists")

    merged = merge_papers(papers, citation_papers)
    print(f"  [+] 合并后: {len(merged)} 篇")
    logger.info(f"Merged: {len(merged)} papers")

    # ===== Node 2: Deduplicate =====
    print(f"\n[步骤 2/5] 基于ID去重")
    logger.info("[Node 2] Deduplicating by ID")

    deduped = deduplicate_by_id(merged)
    removed = len(merged) - len(deduped)
    print(f"  [+] 去重后: {len(deduped)} 篇 (移除 {removed} 篇重复)")
    logger.info(f"Deduplicated: {len(deduped)} papers (removed {removed} duplicates)")

    # ===== Node 3: Filter =====
    print(f"\n[步骤 3/5] 应用过滤条件")
    logger.info("[Node 3] Filtering papers")

    intent_params = state.get("intent_params")
    conditions = intent_params.conditions if intent_params else {}

    filtered = filter_papers(deduped, conditions)
    removed = len(deduped) - len(filtered)
    print(f"  [+] 过滤后: {len(filtered)} 篇 (移除 {removed} 篇)")
    logger.info(f"Filtered: {len(filtered)} papers (removed {removed} papers)")

    if not filtered:
        print("\n[!]  过滤后无剩余论文，返回空列表")
        logger.warning("filtered_papers is empty")
        state["filtered_papers"] = []

        print("\n[OK] [Agent E] 过滤排序完成 - 无结果")
        print("="*80 + "\n")
        return state

    # ===== Node 4: Calculate Score =====
    print(f"\n[步骤 4/5] 计算综合评分")
    logger.info("[Node 4] Calculating scores")

    current_year = 2026
    for paper in filtered:
        paper.score = calculate_score(paper, current_year)

    print(f"  [+] 完成评分 (引用40% + 时效30% + 相关性30%)")
    logger.info("Scores calculated")

    # ===== Node 5: Rank and Select Top =====
    print(f"\n[步骤 5/5] 排序并选择论文")
    logger.info("[Node 5] Ranking and selecting top papers")

    # 使用配置文件中的OUTPUT_TOP_N（None表示选择全部）
    ranked = rank_and_select_top(filtered, top_n=OUTPUT_TOP_N)

    if OUTPUT_TOP_N is None:
        print(f"  [+] 选择所有 {len(ranked)} 篇论文（OUTPUT_TOP_N=None，下载全部）")
    else:
        print(f"  [+] 选择Top {OUTPUT_TOP_N}篇论文")

    print(f"\n  [STAT] 评分排名前5:")
    for idx, paper in enumerate(ranked[:5], 1):
        print(f"     [{idx}] {paper.title[:50]}...")
        print(f"         分数: {paper.score:.2f} | 引用数: {paper.citation_count} | 年份: {paper.year}")

    logger.info(f"Selected {len(ranked)} papers (OUTPUT_TOP_N={OUTPUT_TOP_N})")
    for idx, paper in enumerate(ranked[:5], 1):
        logger.debug(f"  Rank {idx}: {paper.id} | score={paper.score:.2f} | citations={paper.citation_count}")

    # 写入输出
    state["filtered_papers"] = ranked

    print(f"\n[OK] [Agent E] 过滤排序完成 - 输出 {len(ranked)} 篇论文")
    print("="*80 + "\n")

    logger.info("[Agent E] Paper_Filter_Rank_Agent completed")
    logger.info("=" * 50)

    return state
