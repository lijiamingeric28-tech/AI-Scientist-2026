"""
使用Waterfall策略从多个源依次尝试下载
"""

import os
import logging
from typing import Dict, Any
from urllib.parse import urlparse, urlunparse
from models.paper_metadata import PaperMetadata
from tools.download.download_from_url import download_from_url
from tools.download.get_core_url import get_core_url

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    规范化URL（去除参数、锚点）

    用于URL去重，避免下载相同的资源
    """
    try:
        parsed = urlparse(url)
        # 去除query和fragment
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            '',  # params
            '',  # query
            ''   # fragment
        ))
        return normalized.lower()  # 转小写
    except:
        return url.lower()


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
        2. oa_url（OpenAlex开放获取链接，数据来自Unpaywall）
        3. core（CORE API）

    注: Unpaywall已移除，因为其数据已包含在oa_url中
    """

    save_path = os.path.join(save_dir, f"{paper.id}.pdf")

    # URL去重集合
    tried_urls = set()

    # 定义所有源
    sources = [
        ("pdf_url", paper.pdf_url),
        ("oa_url", paper.oa_url),
        ("core", get_core_url(paper.doi) if paper.doi else None)
    ]

    for source_name, url in sources:
        if not url:
            continue

        # URL去重检查
        normalized = normalize_url(url)
        if normalized in tried_urls:
            logger.debug(f"Skipping duplicate URL: {source_name} ({url[:60]})")
            continue

        tried_urls.add(normalized)

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
