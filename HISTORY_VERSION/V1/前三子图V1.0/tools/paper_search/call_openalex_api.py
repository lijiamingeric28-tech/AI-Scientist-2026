"""
调用OpenAlex API搜索文献
"""

from typing import List, Dict, Any
import requests
import time
import logging
from models.paper_metadata import PaperMetadata
from tools.paper_search.parse_openalex_item import parse_openalex_item
from configs.constants import OPENALEX_BASE_URL, OPENALEX_TIMEOUT, OPENALEX_EMAIL, OPENALEX_API_KEY

logger = logging.getLogger(__name__)


def call_openalex_api(
    search: str,
    filter_dict: Dict[str, Any],
    per_page: int = 50,
    max_attempts: int = 2
) -> List[PaperMetadata]:
    """
    调用OpenAlex API搜索文献（带重试机制）

    Args:
        search: 布尔检索式
        filter_dict: 过滤条件字典
        per_page: 每页结果数
        max_attempts: 最大尝试次数

    Returns:
        论文元数据列表

    Raises:
        requests.RequestException: API调用失败
    """
    for attempt in range(max_attempts):
        try:
            # 构建filter字符串
            filter_str = _build_filter_string(filter_dict)

            # 构建请求参数
            params = {
                "search": search,
                "filter": filter_str,
                "per_page": per_page,
                "sort": "cited_by_count:desc"
            }

            # 构建请求头
            headers = {}

            # 使用API密钥和邮箱参数
            # OpenAlex使用api_key参数而不是Bearer token
            if OPENALEX_API_KEY:
                params["api_key"] = OPENALEX_API_KEY
                logger.debug(f"Using OpenAlex API Key: {OPENALEX_API_KEY[:10]}...")

            params["mailto"] = OPENALEX_EMAIL
            logger.debug(f"Using OpenAlex email: {OPENALEX_EMAIL}")

            logger.info(f"Calling OpenAlex API (attempt {attempt+1}/{max_attempts})")
            logger.debug(f"URL: {OPENALEX_BASE_URL}")
            logger.debug(f"Params: {params}")

            # 发送请求
            response = requests.get(OPENALEX_BASE_URL, params=params, headers=headers, timeout=OPENALEX_TIMEOUT)

            # 处理速率限制
            if response.status_code == 429:
                logger.warning("Rate limited by OpenAlex, waiting 60s...")
                time.sleep(60)
                continue

            # 处理服务器错误
            if response.status_code in [500, 503]:
                logger.warning(f"Server error {response.status_code}, retrying...")
                time.sleep(2)
                continue

            response.raise_for_status()

            # 解析返回
            data = response.json()
            results = data.get("results", [])

            if not results:
                logger.warning("OpenAlex returned 0 results")
                return []

            # 转换为PaperMetadata
            papers = []
            for item in results:
                try:
                    paper = parse_openalex_item(item)
                    papers.append(paper)
                except Exception as e:
                    logger.warning(f"Failed to parse item: {e}")
                    continue

            logger.info(f"Successfully parsed {len(papers)} papers")
            return papers

        except requests.Timeout:
            logger.warning(f"Request timeout (attempt {attempt+1}/{max_attempts})")
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            else:
                logger.error("Max retries reached, returning empty list")
                return []

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            else:
                logger.error("Max retries reached, returning empty list")
                return []

    return []


def _build_filter_string(filter_dict: Dict[str, Any]) -> str:
    """
    构建OpenAlex filter字符串

    Args:
        filter_dict: 过滤条件字典

    Returns:
        filter字符串
    """
    filters = []

    # 强制条件
    filters.append("is_retracted:false")

    # 来自Agent A的条件
    if "publication_year" in filter_dict:
        filters.append(f"publication_year:{filter_dict['publication_year']}")

    if "cited_by_count" in filter_dict:
        filters.append(f"cited_by_count:{filter_dict['cited_by_count']}")

    # 学科过滤（新的Topics系统）
    # 优先级: topics.id (最精确) > topics.subfield.id > topics.field.id
    if "topics.id" in filter_dict:
        filters.append(f"topics.id:{filter_dict['topics.id']}")
    elif "topics.subfield.id" in filter_dict:
        filters.append(f"topics.subfield.id:{filter_dict['topics.subfield.id']}")
    elif "topics.field.id" in filter_dict:
        filters.append(f"topics.field.id:{filter_dict['topics.field.id']}")

    filter_str = ",".join(filters)
    logger.debug(f"Built filter string: {filter_str}")
    return filter_str
