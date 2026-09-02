"""
使用Waterfall策略从多个源依次尝试下载（改进版，支持Unpaywall多源和Nature scraper）
"""

import os
import logging
from typing import Dict, Any
from urllib.parse import urlparse
from shared.models.paper_metadata import PaperMetadata
from subgraphs.retrieval.tools.download.download_from_url import download_from_url
from subgraphs.retrieval.tools.download.get_unpaywall_url import get_unpaywall_urls
from subgraphs.retrieval.tools.download.get_core_url import get_core_url
from subgraphs.retrieval.tools.download.nature_scraper import download_from_nature

logger = logging.getLogger(__name__)


def download_with_waterfall(paper: PaperMetadata, save_dir: str, unpaywall_cache: Dict = None) -> dict[str, Any]:
    """
    使用Waterfall策略下载论文（改进版）

    Args:
        paper: 论文元数据
        save_dir: 保存目录
        unpaywall_cache: Unpaywall URL缓存（可选）

    Returns:
        {
            "success": True/False,
            "local_path": "./data/papers/W123.pdf",
            "source": "pdf_url",  # 成功的源
            "file_size": 2048576,
            "error": None
        }

    Waterfall顺序（改进）:
        1. pdf_url（OpenAlex直接PDF链接）
        2. oa_url（OpenAlex开放获取链接）
        3. unpaywall_best_pdf（Unpaywall最佳PDF）
        4. unpaywall_alt_*_pdf（Unpaywall备用PDF）
        5. unpaywall_*_landing（Unpaywall着陆页）
        6. nature_scraper（自动检测）
        7. core（CORE API）
    """
    logger.info(f"[Waterfall] Starting download for {paper.id}")
    logger.debug(f"[Waterfall] Paper title: {paper.title[:100]}")
    logger.debug(f"[Waterfall] DOI: {paper.doi}")
    logger.debug(f"[Waterfall] Source DB: {paper.source_db}")

    # 生成保存路径
    safe_id = paper.id.replace("/", "_").replace(":", "_")
    save_path = os.path.join(save_dir, f"{safe_id}.pdf")

    # 构建源列表
    sources = []

    # 1. OpenAlex直接链接
    if paper.pdf_url:
        sources.append(("pdf_url", paper.pdf_url))

    if paper.oa_url:
        sources.append(("oa_url", paper.oa_url))

    # 2. Unpaywall多源（优化：使用缓存）
    if paper.doi:
        # 优先使用缓存
        if unpaywall_cache and paper.doi in unpaywall_cache:
            unpaywall_urls = unpaywall_cache[paper.doi]
            logger.debug(f"[Waterfall] Using cached Unpaywall results for {paper.doi}")
        else:
            logger.debug(f"[Waterfall] Querying Unpaywall for DOI: {paper.doi}")
            unpaywall_urls = get_unpaywall_urls(paper.doi)

        if unpaywall_urls:
            logger.info(f"[Waterfall] Unpaywall returned {len(unpaywall_urls)} URL(s)")
            for url_info in unpaywall_urls:
                sources.append((url_info["source"], url_info["url"]))
        else:
            logger.debug(f"[Waterfall] No Unpaywall URLs for DOI: {paper.doi}")

    # 3. CORE API
    if paper.doi:
        core_url = get_core_url(paper.doi) if paper.doi else None
        if core_url:
            sources.append(("core", core_url))

    # 依次尝试每个源
    logger.info(f"[Waterfall] Total sources to try: {len(sources)}")

    for idx, (source_name, url) in enumerate(sources, 1):
        if not url:
            continue

        logger.info(f"[Waterfall] [{idx}/{len(sources)}] Trying {source_name}: {url[:80]}...")

        # 检查是否是Nature.com链接，使用专用scraper
        if 'nature.com' in url.lower():
            logger.info(f"[Waterfall] Detected Nature.com, using nature_scraper")
            result = download_from_nature(url, save_path)

            if result["success"]:
                logger.info(f"[Waterfall] SUCCESS from nature_scraper: {paper.id}")
                logger.info(f"[Waterfall] File size: {result['file_size']} bytes")
                return {
                    "success": True,
                    "local_path": save_path,
                    "source": "nature_scraper",
                    "file_size": result["file_size"],
                    "error": None
                }
            else:
                logger.debug(f"[Waterfall] Nature scraper failed: {result.get('error', 'Unknown')}, trying standard download")
                # Nature scraper失败，尝试标准下载
                result = download_from_url(url, save_path)
        else:
            # 非Nature链接，使用标准下载
            result = download_from_url(url, save_path)

        if result["success"]:
            logger.info(f"[Waterfall] SUCCESS from {source_name}: {paper.id}")
            logger.info(f"[Waterfall] File size: {result['file_size']} bytes")
            return {
                "success": True,
                "local_path": save_path,
                "source": source_name,
                "file_size": result["file_size"],
                "error": None
            }
        else:
            logger.debug(f"[Waterfall] Failed from {source_name}: {result.get('error', 'Unknown')}")

    # 所有源都失败
    logger.warning(f"[Waterfall] All {len(sources)} sources failed for {paper.id}")
    return {
        "success": False,
        "local_path": None,
        "source": None,
        "file_size": None,
        "error": f"All sources failed ({len(sources)} tried)"
    }
