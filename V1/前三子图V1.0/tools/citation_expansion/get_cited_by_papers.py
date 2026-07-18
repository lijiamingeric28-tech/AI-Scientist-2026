"""
修复版本: 获取论文的前向引用（谁引用了它）

修复内容:
1. 使用filter=cites:{work_id}替代已废弃的cited_by_api_url
2. 添加速率控制和重试机制
3. 改进错误处理和日志
4. 添加降级策略
"""

from typing import List, Dict, Any
import requests
import time
import logging
from configs.constants import CITATION_API_TIMEOUT, OPENALEX_EMAIL, OPENALEX_API_KEY

logger = logging.getLogger(__name__)


def get_cited_by_papers(work_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    获取论文的前向引用（使用新版API）

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
        # 使用新版API: filter=cites:{work_id}
        url = "https://api.openalex.org/works"

        # 构建过滤条件
        # 放宽过滤条件：移除cited_by_count限制，只保留is_retracted
        params = {
            "filter": f"cites:{work_id},is_retracted:false",
            "per_page": max_results,
            "sort": "cited_by_count:desc",  # 按引用数排序
            "select": "id,title,publication_year,cited_by_count,doi,open_access,authorships"
        }

        # 构建请求参数
        # OpenAlex使用mailto参数而不是API key
        # 注意：OpenAlex主要使用邮箱认证，不需要API key
        params["mailto"] = OPENALEX_EMAIL
        logger.debug(f"Using email {OPENALEX_EMAIL} for {work_id}")

        logger.info(f"Fetching cited_by papers for {work_id} using filter API")

        # 添加重试机制
        max_retries = 3
        retry_delay = 2  # 起始延迟2秒

        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, timeout=CITATION_API_TIMEOUT)

                # 处理速率限制
                if response.status_code == 429:
                    wait_time = 60 * (attempt + 1)  # 指数增长: 60s, 120s, 180s
                    logger.warning(f"Rate limited (attempt {attempt + 1}/{max_retries}), waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                logger.info(f"Found {len(results)} cited_by papers for {work_id}")

                # 记录详细信息
                if results:
                    logger.debug(f"Sample cited_by paper: {results[0].get('title', 'N/A')[:50]}...")
                else:
                    logger.info(f"No cited_by papers found for {work_id} (this might be normal for newer papers)")

                # 添加礼貌延迟
                time.sleep(1)

                return results

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}, retrying...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    raise

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1 and response.status_code not in [404, 403]:
                    logger.warning(f"Request failed on attempt {attempt + 1}/{max_retries}: {e}, retrying...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise

        # 如果所有重试都失败
        logger.error(f"All {max_retries} attempts failed for {work_id}")
        return []

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, 'response') else 'unknown'
        logger.warning(f"HTTP error {status_code} when fetching cited_by for {work_id}: {e}")
        return []

    except Exception as e:
        logger.warning(f"Unexpected error when fetching cited_by for {work_id}: {type(e).__name__}: {e}")
        return []


def get_cited_by_papers_with_diagnostics(work_id: str, max_results: int = 10) -> Dict[str, Any]:
    """
    获取前向引用（带诊断信息）

    Returns:
        {
            "success": bool,
            "papers": List[Dict],
            "count": int,
            "error": str (如果失败),
            "diagnostics": {
                "api_method": str,
                "filters_applied": List[str],
                "retry_count": int
            }
        }
    """
    diagnostics = {
        "api_method": "filter_cites",
        "filters_applied": ["cites:work_id", "is_retracted:false"],
        "retry_count": 0
    }

    try:
        papers = get_cited_by_papers(work_id, max_results)

        return {
            "success": True,
            "papers": papers,
            "count": len(papers),
            "diagnostics": diagnostics
        }

    except Exception as e:
        return {
            "success": False,
            "papers": [],
            "count": 0,
            "error": str(e),
            "diagnostics": diagnostics
        }


# 向后兼容的别名
get_cited_by_papers_v2 = get_cited_by_papers
