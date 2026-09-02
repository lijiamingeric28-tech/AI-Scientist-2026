"""
获取论文的后向引用（它引用了谁）
"""

from typing import List, Dict, Any
import requests
import time
import logging
from configs.constants import CITATION_API_TIMEOUT, OPENALEX_EMAIL, OPENALEX_API_KEY

logger = logging.getLogger(__name__)


def get_references(work_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    获取论文的后向引用

    Args:
        work_id: OpenAlex论文ID
        max_results: 最多返回多少篇参考文献，默认10

    Returns:
        参考文献的元数据列表（OpenAlex API格式）

    Raises:
        TimeoutError: API调用超时
        requests.HTTPError: API返回错误

    Fallback:
        如果失败，返回空列表[]
    """
    try:
        # 获取referenced_works字段
        work_url = f"https://api.openalex.org/works/{work_id}"
        params = {
            "select": "referenced_works"
        }

        # 构建请求头
        headers = {}
        if OPENALEX_API_KEY:
            headers["Authorization"] = f"Bearer {OPENALEX_API_KEY}"
        else:
            params["mailto"] = OPENALEX_EMAIL

        logger.debug(f"Getting referenced_works for {work_id}")

        response = requests.get(work_url, params=params, headers=headers, timeout=CITATION_API_TIMEOUT)
        response.raise_for_status()

        data = response.json()
        referenced_work_ids = data.get("referenced_works", [])

        if not referenced_work_ids:
            logger.debug(f"No referenced_works for {work_id}")
            return []

        # 取前max_results个
        selected_ids = referenced_work_ids[:max_results]

        # 使用OpenAlex的filter参数批量查询
        filter_ids = "|".join([id.split("/")[-1] for id in selected_ids])

        search_url = "https://api.openalex.org/works"
        params = {
            "filter": f"openalex:{filter_ids},is_retracted:false,cited_by_count:>=3",
            "per_page": max_results,
            "sort": "cited_by_count:desc"
        }

        # 构建请求头
        headers = {}
        if OPENALEX_API_KEY:
            headers["Authorization"] = f"Bearer {OPENALEX_API_KEY}"
        else:
            params["mailto"] = OPENALEX_EMAIL

        logger.debug(f"Fetching {len(selected_ids)} references")

        response = requests.get(search_url, params=params, headers=headers, timeout=CITATION_API_TIMEOUT)

        # 处理速率限制
        if response.status_code == 429:
            logger.warning("Rate limited, waiting 60s...")
            time.sleep(60)
            response = requests.get(search_url, params=params, headers=headers, timeout=CITATION_API_TIMEOUT)

        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        logger.info(f"Found {len(results)} references for {work_id}")

        return results

    except Exception as e:
        logger.warning(f"Failed to get references for {work_id}: {e}")
        return []
