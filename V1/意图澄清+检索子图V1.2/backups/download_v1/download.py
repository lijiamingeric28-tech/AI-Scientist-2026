"""
Agent C: Paper_Download_Agent

并发下载论文全文PDF
"""

import os
import logging
from state.retrieval_state import RetrievalState
from tools.download import download_with_waterfall, check_existing_file
from configs.constants import DOWNLOAD_DIR, DOWNLOAD_MAX_CONCURRENT
import asyncio

logger = logging.getLogger(__name__)


def download_agent_sync(state: RetrievalState) -> RetrievalState:
    """
    Agent C: Paper_Download_Agent (同步版本)

    并发下载论文全文PDF
    """
    print("\n" + "="*80)
    print("[DOWN]  [检索子图 - Agent C] PDF下载开始")
    print("="*80)

    logger.info("=" * 50)
    logger.info("[Agent C] Paper_Download_Agent started")

    # 检查是否使用测试专用目录
    download_dir = os.getenv('TEST_OUTPUT_PAPERS_DIR', DOWNLOAD_DIR)
    metadata_dir = os.getenv('TEST_OUTPUT_METADATA_DIR', None)

    if os.getenv('TEST_OUTPUT_PAPERS_DIR'):
        print(f"\n[INFO] 使用测试输出目录: {download_dir}")

    # 读取输入
    filtered_papers = state.get("filtered_papers", [])

    if not filtered_papers:
        print("\n[!]  输入论文列表为空，跳过下载")
        logger.warning("filtered_papers is empty")

        print("\n[OK] [Agent C] PDF下载完成 - 跳过")
        print("="*80 + "\n")
        return state

    print(f"\n>>> 收到 {len(filtered_papers)} 篇待下载论文")
    print(f"[DIR] 下载目录: {DOWNLOAD_DIR}")
    print(f"[#] 最大并发数: {DOWNLOAD_MAX_CONCURRENT}")

    logger.info(f"Received {len(filtered_papers)} papers to download")
    logger.info(f"Download directory: {DOWNLOAD_DIR}")
    logger.info(f"Max concurrent downloads: {DOWNLOAD_MAX_CONCURRENT}")

    # 运行异步下载
    try:
        asyncio.run(_download_papers_async(filtered_papers, download_dir))
    except Exception as e:
        print(f"\n[X] 下载过程出错: {e}")
        logger.error(f"Download failed: {e}", exc_info=True)

    # 统计结果
    success_count = sum(1 for p in filtered_papers if p.download_status == "success")
    skipped_count = sum(1 for p in filtered_papers if p.download_status == "skipped")
    failed_count = sum(1 for p in filtered_papers if p.download_status == "failed")

    print(f"\n[STAT] 下载统计:")
    print(f"  [OK] 成功: {success_count} 篇")
    print(f"  [SKIP]  跳过(已存在): {skipped_count} 篇")
    print(f"  [X] 失败: {failed_count} 篇")

    logger.info(f"Download summary: success={success_count}, skipped={skipped_count}, failed={failed_count}")

    # 显示成功下载的论文
    if success_count > 0:
        print(f"\n  [DOC] 成功下载的论文(前3篇):")
        success_papers = [p for p in filtered_papers if p.download_status == "success"]
        for idx, paper in enumerate(success_papers[:3], 1):
            print(f"     [{idx}] {paper.title[:50]}...")
            print(f"         来源: {paper.download_source} | 大小: {paper.file_size/1024:.1f} KB")

    # 写入输出（原地更新）
    state["filtered_papers"] = filtered_papers

    print(f"\n[OK] [Agent C] PDF下载完成")
    print("="*80 + "\n")

    logger.info("[Agent C] Paper_Download_Agent completed")
    logger.info("=" * 50)

    return state


async def _download_papers_async(papers, download_dir):
    """异步下载论文（内部函数）"""
    from asyncio import Semaphore

    semaphore = Semaphore(DOWNLOAD_MAX_CONCURRENT)

    async def download_one(paper, idx):
        """下载单篇论文"""
        async with semaphore:
            print(f"\n  [{idx}/{len(papers)}] 下载: {paper.title[:40]}...")
            logger.info(f"[{idx}/{len(papers)}] Downloading {paper.id}")

            # 检查是否已存在
            file_path = os.path.join(download_dir, f"{paper.id}.pdf")
            if check_existing_file(file_path):
                paper.local_path = file_path
                paper.download_status = "skipped"
                print(f"       [SKIP]  文件已存在，跳过")
                logger.debug(f"  {paper.id} already exists, skipped")
                return

            # 下载（在异步上下文中运行同步函数）
            try:
                result = await asyncio.to_thread(
                    download_with_waterfall,
                    paper=paper,
                    save_dir=download_dir
                )

                if result["success"]:
                    paper.local_path = result["local_path"]
                    paper.download_status = "success"
                    paper.download_source = result["source"]
                    paper.file_size = result.get("file_size", 0)
                    print(f"       [OK] 成功 (来源: {result['source']}, 大小: {result.get('file_size', 0)/1024:.1f} KB)")
                    logger.info(f"  {paper.id} downloaded successfully from {result['source']}")
                else:
                    paper.download_status = "failed"
                    print(f"       [X] 失败: {result.get('error', 'Unknown error')}")
                    logger.warning(f"  {paper.id} download failed: {result.get('error')}")

            except Exception as e:
                paper.download_status = "failed"
                print(f"       [X] 异常: {e}")
                logger.error(f"  {paper.id} download exception: {e}")

    # 创建下载任务
    tasks = [download_one(paper, idx) for idx, paper in enumerate(papers, 1)]

    # 并发执行
    await asyncio.gather(*tasks)
