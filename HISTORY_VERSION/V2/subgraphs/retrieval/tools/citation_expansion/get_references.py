"""
修复版本: 获取论文的后向引用（它引用了谁）

修复内容:
1. 保持referenced_works方式（已验证可用）
2. 优化批量查询效率
3. 添加速率控制和重试
4. 改进错误处理和日志
"""

from typing import List, Dict, Any
import requests
import time
import logging
from config.constants import CITATION_API_TIMEOUT, OPENALEX_EMAIL, OPENALEX_API_KEY

logger = logging.getLogger(__name__)


def get_references(work_id: str, max_results: int = 10) -> list[dict[str, Any]]:
    """
    获取论文的后向引用（优化版本）

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
        # Step 1: 获取referenced_works字段
        work_url = f"https://api.openalex.org/works/{work_id}"
        params = {
            "select": "referenced_works"
        }

        # 构建请求参数
        # OpenAlex使用mailto参数
        params["mailto"] = OPENALEX_EMAIL
        logger.debug(f"Using email {OPENALEX_EMAIL} for {work_id}")

        logger.info(f"Fetching referenced_works for {work_id}")

        response = requests.get(work_url, params=params, timeout=CITATION_API_TIMEOUT)
        response.raise_for_status()

        data = response.json()
        referenced_work_ids = data.get("referenced_works", [])

        if not referenced_work_ids:
            logger.info(f"No referenced_works for {work_id}")
            return []

        logger.info(f"Found {len(referenced_work_ids)} references for {work_id}")

        # 添加礼貌延迟
        time.sleep(1)

        # Step 2: 批量查询参考文献详情
        # 取前max_results个
        selected_ids = referenced_work_ids[:max_results]

        # 提取work ID（移除URL前缀）
        clean_ids = [work_id.split("/")[-1] for work_id in selected_ids]

        # 使用OpenAlex的filter参数批量查询
        filter_ids = "|".join(clean_ids)

        search_url = "https://api.openalex.org/works"
        search_params = {
            "filter": f"openalex:{filter_ids},is_retracted:false",  # 放宽条件，移除cited_by_count限制
            "per_page": max_results,
            "sort": "cited_by_count:desc",
            "select": "id,title,publication_year,cited_by_count,doi,open_access,authorships"
        }

        # 构建请求参数
        # OpenAlex使用mailto参数
        search_params["mailto"] = OPENALEX_EMAIL

        logger.debug(f"Fetching details for {len(selected_ids)} references")

        # 添加重试机制
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                response = requests.get(search_url, params=search_params, timeout=CITATION_API_TIMEOUT)

                # 处理速率限制
                if response.status_code == 429:
                    wait_time = 60 * (attempt + 1)
                    logger.warning(f"Rate limited (attempt {attempt + 1}/{max_retries}), waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                logger.info(f"Successfully fetched {len(results)} references for {work_id}")

                # 记录详细信息
                if results:
                    logger.debug(f"Sample reference: {results[0].get('title', 'N/A')[:50]}...")
                else:
                    logger.warning(f"No reference details retrieved for {work_id} (filter might be too strict)")

                # 添加礼貌延迟
                time.sleep(1)

                return results

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}, retrying...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
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
        logger.warning(f"HTTP error {status_code} when fetching references for {work_id}: {e}")
        return []

    except Exception as e:
        logger.warning(f"Unexpected error when fetching references for {work_id}: {type(e).__name__}: {e}")
        return []


def get_references_with_diagnostics(work_id: str, max_results: int = 10) -> dict[str, Any]:
    """
    获取后向引用（带诊断信息）

    Returns:
        {
            "success": bool,
            "papers": list[Dict],
            "count": int,
            "error": str (如果失败),
            "diagnostics": {
                "api_method": str,
                "total_references": int,
                "selected_count": int,
                "filters_applied": list[str]
            }
        }
    """
    diagnostics = {
        "api_method": "referenced_works",
        "total_references": 0,
        "selected_count": 0,
        "filters_applied": ["is_retracted:false"]
    }

    try:
        papers = get_references(work_id, max_results)

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
get_references_v2 = get_references
