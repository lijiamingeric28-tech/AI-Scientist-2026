"""
使用Waterfall策略从多个源依次尝试下载
"""

import os
import logging
from typing import Dict, Any
from models.paper_metadata import PaperMetadata
from tools.download.download_from_url import download_from_url
from tools.download.get_unpaywall_url import get_unpaywall_url
from tools.download.get_core_url import get_core_url

logger = logging.getLogger(__name__)


def download_with_waterfall(paper: PaperMetadata, save_dir: str) -> Dict[str, Any]:
    """
    使用Waterfall策略下载论文

    Args:
        paper: 论文元数据
        save_dir: 保存目录

    Returns:
        {
            "success": True/False,
            "local_path": "./data/papers/W123.pdf",
            "source": "pdf_url",  # 成功的源
            "file_size": 2048576,
            "error": None
        }

    Waterfall顺序:
        1. pdf_url（OpenAlex直接PDF链接）
        2. oa_url（OpenAlex开放获取链接）
        3. unpaywall（Unpaywall API）
        4. core（CORE API）
    """

    save_path = os.path.join(save_dir, f"{paper.id}.pdf")

    # 定义所有源
    sources = [
        ("pdf_url", paper.pdf_url),
        ("oa_url", paper.oa_url),
        ("unpaywall", get_unpaywall_url(paper.doi) if paper.doi else None),
        ("core", get_core_url(paper.doi) if paper.doi else None)
    ]

    for source_name, url in sources:
        if not url:
            continue

        logger.debug(f"Trying {source_name}: {url[:60]}...")

        result = download_from_url(url, save_path)

        if result["success"]:
            logger.info(f"Downloaded from {source_name}: {paper.id}")
            return {
                "success": True,
                "local_path": save_path,
                "source": source_name,
                "file_size": result["file_size"],
                "error": None
            }
        else:
            logger.debug(f"Failed from {source_name}: {result['error']}")

    # 所有源都失败
    return {
        "success": False,
        "local_path": None,
        "source": None,
        "file_size": None,
        "error": "All sources failed"
    }
