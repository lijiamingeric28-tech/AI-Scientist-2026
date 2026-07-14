"""
获取论文的前向引用（谁引用了它）
"""

from typing import List, Dict, Any
import requests
import time
import logging
from configs.constants import CITATION_API_TIMEOUT, OPENALEX_EMAIL, OPENALEX_API_KEY

logger = logging.getLogger(__name__)


def get_cited_by_papers(work_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    获取论文的前向引用

    Args:
        work_id: OpenAlex论文ID，如"W2741809807"
        max_results: 最多返回多少篇引用论文，默认10

    Returns:
        引用论文的元数据列表（OpenAlex API格式）

    Raises:
        TimeoutError: API调用超时
        requests.HTTPError: API返回错误

    Fallback:
        如果失败，返回空列表[]
    """
    try:
        # Step 1: 获取cited_by_api_url
        work_url = f"https://api.openalex.org/works/{work_id}"
        params = {
            "select": "cited_by_api_url"
        }

        # 构建请求头
        headers = {}
        if OPENALEX_API_KEY:
            headers["Authorization"] = f"Bearer {OPENALEX_API_KEY}"
        else:
            params["mailto"] = OPENALEX_EMAIL

        logger.debug(f"Getting cited_by_api_url for {work_id}")

        response = requests.get(work_url, params=params, headers=headers, timeout=CITATION_API_TIMEOUT)
        response.raise_for_status()

        data = response.json()
        cited_by_url = data.get("cited_by_api_url")

        if not cited_by_url:
            logger.debug(f"No cited_by_api_url for {work_id}")
            return []

        # Step 2: 获取引用论文列表
        params = {
            "per_page": max_results,
            "sort": "cited_by_count:desc",
            "filter": "is_retracted:false,cited_by_count:>=3"
        }

        # 构建请求头
        headers = {}
        if OPENALEX_API_KEY:
            headers["Authorization"] = f"Bearer {OPENALEX_API_KEY}"
        else:
            params["mailto"] = OPENALEX_EMAIL

        logger.debug(f"Fetching cited_by papers from {cited_by_url}")

        response = requests.get(cited_by_url, params=params, headers=headers, timeout=CITATION_API_TIMEOUT)

        # 处理速率限制
        if response.status_code == 429:
            logger.warning("Rate limited, waiting 60s...")
            time.sleep(60)
            response = requests.get(cited_by_url, params=params, headers=headers, timeout=CITATION_API_TIMEOUT)

        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        logger.info(f"Found {len(results)} cited_by papers for {work_id}")

        return results

    except Exception as e:
        logger.warning(f"Failed to get cited_by papers for {work_id}: {e}")
        return []
