"""Unpaywall 批量查询节点"""

import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

from ..state import RetrievalState
from ..config import config

logger = logging.getLogger(__name__)


def get_unpaywall_urls(doi: str, email: str, timeout: int = 30) -> List[Dict]:
    """
    查询单个 DOI 的所有可用 PDF URL

    Args:
        doi: DOI 标识符
        email: Unpaywall 要求的邮箱
        timeout: 超时时间（秒）

    Returns:
        URL 列表，按优先级排序
    """
    urls = []

    try:
        api_url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
        response = requests.get(api_url, timeout=timeout)

        if response.status_code == 200:
            data = response.json()

            # 提取最佳 PDF URL
            if data.get('best_oa_location') and data['best_oa_location'].get('url_for_pdf'):
                urls.append({
                    "url": data['best_oa_location']['url_for_pdf'],
                    "source": "unpaywall_best_pdf",
                    "version": data['best_oa_location'].get('version', 'unknown'),
                    "host_type": data['best_oa_location'].get('host_type', 'unknown')
                })

            # 提取所有备用 URL
            if data.get('oa_locations'):
                for location in data['oa_locations']:
                    pdf_url = location.get('url_for_pdf')
                    if pdf_url and pdf_url not in [u['url'] for u in urls]:
                        urls.append({
                            "url": pdf_url,
                            "source": "unpaywall_alternate",
                            "version": location.get('version', 'unknown'),
                            "host_type": location.get('host_type', 'unknown')
                        })

        elif response.status_code == 404:
            logger.debug(f"[Unpaywall] DOI not found: {doi}")
        else:
            logger.warning(f"[Unpaywall] HTTP {response.status_code} for DOI: {doi}")

    except requests.Timeout:
        logger.warning(f"[Unpaywall] Timeout for DOI: {doi}")
    except Exception as e:
        logger.warning(f"[Unpaywall] Error querying DOI {doi}: {e}")

    return urls


def batch_query_unpaywall_all_urls(
    dois: List[str],
    email: str,
    max_workers: int = 10,
    timeout: int = 30
) -> Dict[str, List[Dict]]:
    """
    批量查询 Unpaywall，获取所有可用 URL（不只是最佳）

    Args:
        dois: DOI 列表
        email: Unpaywall 邮箱
        max_workers: 最大并发数
        timeout: 超时时间（秒）

    Returns:
        {doi: [{"url": "...", "source": "unpaywall_best_pdf", ...}, ...]}
    """
    if not dois:
        return {}

    logger.info(f"[Unpaywall Batch] Querying {len(dois)} DOIs with {max_workers} workers...")

    results = {}

    def query_single(doi):
        urls = get_unpaywall_urls(doi, email, timeout)
        return (doi, urls)

    # 使用线程池并发查询
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_single, doi): doi for doi in dois}

        completed = 0
        for future in as_completed(futures):
            try:
                doi, urls = future.result()
                results[doi] = urls
                completed += 1

                if urls:
                    logger.debug(f"[Unpaywall Batch] [{completed}/{len(dois)}] ✓ {doi}: {len(urls)} URLs")
                else:
                    logger.debug(f"[Unpaywall Batch] [{completed}/{len(dois)}] ✗ {doi}: No URLs")

            except Exception as e:
                doi = futures[future]
                logger.warning(f"[Unpaywall Batch] Failed to query {doi}: {e}")
                results[doi] = []
                completed += 1

    success_count = sum(1 for urls in results.values() if urls)
    logger.info(f"[Unpaywall Batch] Completed: {success_count}/{len(dois)} DOIs have URLs")

    return results


def unpaywall_query(state: RetrievalState) -> RetrievalState:
    """
    Unpaywall 批量查询节点

    步骤：
    1. 提取所有 DOI
    2. 批量查询 Unpaywall（并发 10）
    3. 保存所有可用 URL（best + alternates）
    4. 更新状态

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    papers_metadata = state.get("ads_papers_metadata", [])
    query_id = state["query_id"]

    if not papers_metadata:
        logger.info(f"[Unpaywall Query] No papers to query, skipping")
        state["unpaywall_query_status"] = "skipped"
        state["unpaywall_results"] = {}
        # 只返回更新的字段
        return {
            "unpaywall_query_status": state.get("unpaywall_query_status"),
            "unpaywall_results": state.get("unpaywall_results", {})
        }

    logger.info(f"[Unpaywall Query] Query ID: {query_id}")
    logger.info(f"[Unpaywall Query] Papers: {len(papers_metadata)}")

    state["unpaywall_query_status"] = "running"

    # Step 1: 提取 DOI
    dois = []
    for paper in papers_metadata:
        if paper.get("doi"):
            dois.append(paper["doi"])

    logger.info(f"[Unpaywall Query] DOIs found: {len(dois)}")

    if not dois:
        logger.warning(f"[Unpaywall Query] No DOIs to query")
        state["unpaywall_query_status"] = "skipped"
        state["unpaywall_results"] = {}
        # 只返回更新的字段
        return {
            "unpaywall_query_status": state.get("unpaywall_query_status"),
            "unpaywall_results": state.get("unpaywall_results", {})
        }

    # Step 2: 批量查询（并发 10）
    unpaywall_config = config.api['unpaywall']
    email = unpaywall_config['email']

    if not email:
        logger.error("[Unpaywall Query] UNPAYWALL_EMAIL not configured")
        state["unpaywall_query_status"] = "failed"
        state["unpaywall_results"] = {}
        # 只返回更新的字段
        return {
            "unpaywall_query_status": state.get("unpaywall_query_status"),
            "unpaywall_results": state.get("unpaywall_results", {})
        }

    unpaywall_results = batch_query_unpaywall_all_urls(
        dois=dois,
        email=email,
        max_workers=unpaywall_config['max_workers'],
        timeout=unpaywall_config['timeout']
    )

    # Step 3: 更新状态
    state["unpaywall_query_status"] = "completed"
    state["unpaywall_results"] = unpaywall_results

    success_count = sum(1 for urls in unpaywall_results.values() if urls)
    logger.info(f"[Unpaywall Query] Completed!")
    logger.info(f"[Unpaywall Query]   Success: {success_count}/{len(dois)} DOIs")

    # 只返回更新的字段
    return {
        "unpaywall_query_status": state.get("unpaywall_query_status"),
        "unpaywall_results": state.get("unpaywall_results", {})
    }
