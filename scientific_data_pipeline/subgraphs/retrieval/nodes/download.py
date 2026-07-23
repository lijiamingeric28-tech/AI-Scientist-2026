"""
Agent C: 并发下载Agent（高性能版）

性能优化：
1. 多线程并发下载（5个并发）
2. Unpaywall批量查询（提前获取所有URL）
3. 移除Cookie预热（减少50%请求）
4. 优化重试策略
5. PubMed支路受全局开关控制（ENABLE_PUBMED）
"""

import os
import logging
from typing import List
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from subgraphs.retrieval.state import RetrievalState
from subgraphs.retrieval.tools.download.download_with_waterfall import download_with_waterfall
from subgraphs.retrieval.tools.download.get_unpaywall_url import batch_query_unpaywall
from config.constants import ENABLE_PUBMED

# 默认下载目录
DEFAULT_PAPERS_DIR = "./data/papers"

logger = logging.getLogger(__name__)


def download_agent_sync(state: RetrievalState) -> RetrievalState:
    """
    Agent C: Paper_Download_Agent (高性能并发版)

    性能优化：
    - 多线程并发下载
    - Unpaywall批量查询
    - 移除Cookie预热
    """
    print("\n" + "="*80)
    print("[DOWNLOAD] [检索子图 - Agent C] 论文下载开始（高性能版）")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent C] High-performance download agent started")

    # ========== 读取输入 ==========
    filtered_papers = state.get("filtered_papers", [])

    if not filtered_papers:
        print("\n[!]  filtered_papers为空，无需下载")
        logger.warning("filtered_papers is empty, skipping download")

        print("\n[OK] [Agent C] 下载完成 - 无需下载")
        print("="*80 + "\n")
        return state

    print(f"\n>>> 收到 {len(filtered_papers)} 篇论文待下载")
    logger.info(f"Received {len(filtered_papers)} papers to download")

    # 统计PubMed论文数量
    pubmed_count = sum(1 for p in filtered_papers if p.source_db == "pubmed")
    openalex_count = len(filtered_papers) - pubmed_count

    print(f"    - OpenAlex: {openalex_count} 篇")
    print(f"    - PubMed: {pubmed_count} 篇")

    if not ENABLE_PUBMED and pubmed_count > 0:
        print(f"    [!] PubMed功能已禁用，将跳过 {pubmed_count} 篇PubMed论文")
        logger.info(f"PubMed disabled: will skip {pubmed_count} PubMed papers")

    # 准备下载目录
    download_dir = DEFAULT_PAPERS_DIR
    os.makedirs(download_dir, exist_ok=True)
    logger.info(f"Download directory: {download_dir}")

    # 🚀 性能优化1: Unpaywall批量查询（提前获取所有URL）
    print(f"\n[BATCH] 批量查询Unpaywall...")
    logger.info("Starting Unpaywall batch query...")

    unpaywall_cache = {}

    # 提取所有有DOI的论文
    papers_with_doi = [p for p in filtered_papers if p.doi]

    if papers_with_doi:
        print(f"[API] 批量查询Unpaywall: {len(papers_with_doi)} 个DOI...")
        logger.info(f"Batch querying Unpaywall for {len(papers_with_doi)} DOIs...")

        unpaywall_cache = batch_query_unpaywall([p.doi for p in papers_with_doi])
        success_count = sum(1 for urls in unpaywall_cache.values() if urls)

        print(f"[OK] Unpaywall查询完成: {success_count}/{len(papers_with_doi)} 个DOI有URL")
        logger.info(f"Unpaywall batch query completed: {success_count}/{len(papers_with_doi)} DOIs have URLs")
        logger.info(f"Unpaywall cache size: {len(unpaywall_cache)} entries")
    else:
        logger.info("No papers with DOI, skipping Unpaywall batch query")

    # 🚀 性能优化2: 多线程并发下载
    max_workers = min(5, len(filtered_papers))  # 最多5个并发
    print(f"[*] 使用 {max_workers} 个并发线程下载")
    logger.info(f"Using {max_workers} concurrent workers for download")
    logger.info(f"Total papers to process: {len(filtered_papers)}")

    def download_single_paper(paper):
        """下载单篇论文的函数"""
        paper_log_prefix = f"[{paper.id}]"

        try:
            # 🔒 全局开关检查 - 跳过PubMed论文（如果PubMed已禁用）
            if not ENABLE_PUBMED and paper.source_db == "pubmed":
                logger.info(f"{paper_log_prefix} Skipping PubMed paper (ENABLE_PUBMED=False)")
                paper.download_status = "skipped"
                paper.download_error = "PubMed disabled by global config"
                return paper

            logger.debug(f"{paper_log_prefix} Starting download attempt")
            logger.debug(f"{paper_log_prefix} DOI: {paper.doi}")
            logger.debug(f"{paper_log_prefix} Source DB: {paper.source_db}")

            # 使用Waterfall策略（传入Unpaywall缓存）
            result = download_with_waterfall(
                paper,
                download_dir,
                unpaywall_cache=unpaywall_cache
            )

            # 更新论文状态
            if result["success"]:
                paper.download_status = "success"
                paper.local_path = result["local_path"]
                paper.download_source = result.get("source")
                paper.file_size = result.get("file_size")
                logger.info(f"{paper_log_prefix} SUCCESS - Source: {result.get('source')}, Size: {result.get('file_size')} bytes")
            else:
                paper.download_status = "failed"
                paper.download_error = result.get("error")
                logger.warning(f"{paper_log_prefix} FAILED - Error: {result.get('error')}")

            return paper

        except Exception as e:
            paper.download_status = "failed"
            paper.download_error = str(e)
            logger.error(f"{paper_log_prefix} EXCEPTION during download: {e}", exc_info=True)
            return paper

    # 使用线程池并发下载
    print(f"\n[START] 开始并发下载...")
    logger.info("Starting concurrent download with ThreadPoolExecutor...")

    completed_papers = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有下载任务
        future_to_paper = {executor.submit(download_single_paper, paper): paper for paper in filtered_papers}
        logger.info(f"Submitted {len(future_to_paper)} download tasks")

        # 显示进度条并收集结果
        with tqdm(total=len(filtered_papers), desc="下载进度", unit="篇", ncols=80) as pbar:
            for future in as_completed(future_to_paper):
                paper = future.result()
                completed_papers.append(paper)
                pbar.update(1)

    logger.info(f"All download tasks completed. Total: {len(completed_papers)}")

    # 更新state（保持原顺序）
    paper_dict = {p.id: p for p in completed_papers}
    state["filtered_papers"] = [paper_dict.get(p.id, p) for p in filtered_papers]

    # 统计结果
    success_count = sum(1 for p in completed_papers if p.download_status == "success")
    skipped_count = sum(1 for p in completed_papers if p.download_status == "skipped")
    failed_count = sum(1 for p in completed_papers if p.download_status == "failed")

    print(f"\n[STAT] 下载统计:")
    print(f"  [OK] 成功: {success_count} 篇")
    print(f"  [SKIP] 跳过: {skipped_count} 篇")
    print(f"  [X] 失败: {failed_count} 篇")

    logger.info("="*50)
    logger.info("[Agent C] Download Summary:")
    logger.info(f"  Success: {success_count}/{len(completed_papers)} ({success_count/len(completed_papers)*100:.1f}%)")
    logger.info(f"  Skipped: {skipped_count}/{len(completed_papers)} ({skipped_count/len(completed_papers)*100:.1f}%)")
    logger.info(f"  Failed: {failed_count}/{len(completed_papers)} ({failed_count/len(completed_papers)*100:.1f}%)")

    # 统计下载来源
    if success_count > 0:
        source_dist = {}
        for p in completed_papers:
            if p.download_status == "success" and p.download_source:
                source_dist[p.download_source] = source_dist.get(p.download_source, 0) + 1

        logger.info("Download source distribution:")
        for source, count in sorted(source_dist.items(), key=lambda x: -x[1]):
            logger.info(f"  {source}: {count} ({count/success_count*100:.1f}%)")

    logger.info("="*50)

    # 显示成功下载的论文
    if success_count > 0:
        print(f"\n[DOC] 成功下载的论文(前3篇):")
        success_papers = [p for p in completed_papers if p.download_status == "success"][:3]
        for idx, paper in enumerate(success_papers, 1):
            print(f"  [{idx}] {paper.title[:50].encode('ascii', errors='ignore').decode('ascii')}...")
            print(f"      来源: {paper.download_source} | 大小: {paper.file_size/1024:.1f} KB")

    print(f"\n[OK] [Agent C] 并发下载完成")
    print("="*80 + "\n")

    logger.info("[Agent C] High-performance download agent completed")

    return state
