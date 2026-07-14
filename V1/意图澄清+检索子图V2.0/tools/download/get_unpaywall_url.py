"""
Unpaywall批量查询优化

支持：
- 批量查询多个DOI
- 结果缓存
- 性能优化
"""

from typing import Optional, List, Dict
import requests
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 使用环境变量或默认邮箱
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "lijiamingeric28@gmail.com")


def get_unpaywall_urls(doi: Optional[str]) -> List[Dict[str, str]]:
    """
    从Unpaywall获取所有可用的PDF链接（包括备用源）

    Args:
        doi: 论文DOI

    Returns:
        URL列表，每个元素包含 {"url": "...", "source": "best/repo/other"}
        按优先级排序

    API: https://api.unpaywall.org/v2/{doi}?email=YOUR_EMAIL
    """
    if not doi:
        return []

    try:
        # 清理DOI
        clean_doi = doi.strip()
        if clean_doi.startswith("doi:"):
            clean_doi = clean_doi[4:]
        if clean_doi.startswith("https://doi.org/"):
            clean_doi = clean_doi[16:]

        url = f"https://api.unpaywall.org/v2/{clean_doi}"
        params = {"email": UNPAYWALL_EMAIL}

        logger.debug(f"[Unpaywall] Querying DOI: {clean_doi}")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        urls = []

        # 检查是否是开放获取
        if not data.get("is_oa"):
            logger.debug(f"[Unpaywall] DOI {clean_doi} is not OA")
            return []

        # 1. best_oa_location (最佳位置)
        best_location = data.get("best_oa_location", {})
        if best_location:
            pdf_url = best_location.get("url_for_pdf")
            landing_url = best_location.get("url_for_landing_page")

            if pdf_url:
                urls.append({
                    "url": pdf_url,
                    "source": "unpaywall_best_pdf",
                    "version": best_location.get("version", "unknown"),
                    "host_type": best_location.get("host_type", "unknown")
                })
                logger.debug(f"[Unpaywall] Found best PDF: {pdf_url[:60]}...")
            elif landing_url:
                urls.append({
                    "url": landing_url,
                    "source": "unpaywall_best_landing",
                    "version": best_location.get("version", "unknown"),
                    "host_type": best_location.get("host_type", "unknown")
                })
                logger.debug(f"[Unpaywall] Found best landing page: {landing_url[:60]}...")

        # 2. oa_locations (所有开放获取位置)
        oa_locations = data.get("oa_locations", [])
        for idx, location in enumerate(oa_locations):
            if not location:
                continue

            pdf_url = location.get("url_for_pdf")
            landing_url = location.get("url_for_landing_page")
            host_type = location.get("host_type", "unknown")
            version = location.get("version", "unknown")

            # 跳过已经添加的best location
            if pdf_url and not any(u["url"] == pdf_url for u in urls):
                urls.append({
                    "url": pdf_url,
                    "source": f"unpaywall_alt_{idx+1}_pdf",
                    "version": version,
                    "host_type": host_type
                })
                logger.debug(f"[Unpaywall] Found alternate PDF #{idx+1}: {pdf_url[:60]}...")

            if landing_url and not any(u["url"] == landing_url for u in urls):
                urls.append({
                    "url": landing_url,
                    "source": f"unpaywall_alt_{idx+1}_landing",
                    "version": version,
                    "host_type": host_type
                })

        logger.info(f"[Unpaywall] Found {len(urls)} URL(s) for DOI {clean_doi}")
        return urls

    except requests.HTTPError as e:
        if e.response.status_code == 404:
            logger.debug(f"[Unpaywall] DOI {doi} not found in Unpaywall")
        else:
            logger.warning(f"[Unpaywall] HTTP error: {e}")
        return []
    except Exception as e:
        logger.debug(f"[Unpaywall] Query failed: {e}")
        return []


def batch_query_unpaywall(dois: List[str], max_workers: int = 10) -> Dict[str, List[Dict]]:
    """
    批量查询Unpaywall（性能优化）

    Args:
        dois: DOI列表
        max_workers: 最大并发数

    Returns:
        {doi: [urls]} 字典
    """
    if not dois:
        return {}

    logger.info(f"[Unpaywall Batch] Querying {len(dois)} DOIs with {max_workers} workers...")

    results = {}

    def query_single(doi):
        urls = get_unpaywall_urls(doi)
        return (doi, urls)

    # 使用线程池并发查询
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_single, doi): doi for doi in dois}

        for future in as_completed(futures):
            try:
                doi, urls = future.result()
                results[doi] = urls
            except Exception as e:
                doi = futures[future]
                logger.warning(f"[Unpaywall Batch] Failed to query {doi}: {e}")
                results[doi] = []

    success_count = sum(1 for urls in results.values() if urls)
    logger.info(f"[Unpaywall Batch] Completed: {success_count}/{len(dois)} DOIs have URLs")

    return results


def get_unpaywall_url(doi: Optional[str]) -> Optional[str]:
    """
    从Unpaywall获取最佳PDF链接（兼容旧接口）

    Args:
        doi: 论文DOI

    Returns:
        PDF下载链接，若无则返回None
    """
    urls = get_unpaywall_urls(doi)
    if urls:
        # 返回第一个PDF链接
        for url_info in urls:
            if "pdf" in url_info["source"]:
                return url_info["url"]
        # 如果没有PDF，返回第一个
        return urls[0]["url"]
    return None
