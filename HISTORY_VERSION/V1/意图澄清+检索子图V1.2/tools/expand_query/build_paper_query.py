"""
构建OpenAlex API查询参数
"""

from typing import List, Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def build_paper_query(
    expanded_entities: List[str],
    expanded_properties: List[str],
    conditions: Dict[str, str]
) -> Dict[str, Any]:
    """
    构建OpenAlex API查询参数

    Args:
        expanded_entities: 扩展后的实体列表
        expanded_properties: 扩展后的属性列表
        conditions: 条件字典

    Returns:
        API查询参数字典
    """
    logger.info("Building API query parameters")

    # 过滤掉中文词汇，只保留英文
    def filter_english_terms(terms: List[str]) -> List[str]:
        """只保留英文和数字字符的词汇"""
        english_terms = []
        for term in terms:
            # 检查是否主要是ASCII字符
            if all(ord(c) < 128 or c in ['-', '_', ' '] for c in term):
                english_terms.append(term)
            else:
                logger.debug(f"Filtered out non-English term: {term}")
        return english_terms

    # 过滤实体和属性
    filtered_entities = filter_english_terms(expanded_entities)
    filtered_properties = filter_english_terms(expanded_properties)

    # 如果过滤后为空，使用默认英文词汇
    if not filtered_entities:
        logger.warning("No English entities after filtering, using defaults")
        filtered_entities = ["material", "alloy"]

    if not filtered_properties:
        logger.warning("No English properties after filtering, using defaults")
        filtered_properties = ["mechanical properties", "strength"]

    # 构建布尔检索式
    entities_query = " OR ".join(filtered_entities)
    properties_query = " OR ".join(filtered_properties)

    # 组合实体和属性查询
    search_query = f"({entities_query}) AND ({properties_query})"

    # 处理高温条件
    if "温度" in conditions or "temperature" in conditions.values():
        temp_terms = ["high temperature", "elevated temperature"]
        search_query += f" AND ({' OR '.join(temp_terms)})"

    logger.info(f"Built search query: {search_query[:100]}...")

    # 构建过滤条件
    filter_dict = {
        "publication_year": _build_year_range(conditions),
        "cited_by_count": ">4"  # OpenAlex要求用>而不是>=
    }

    # 返回查询参数
    query_params = {
        "openalex": {
            "search": search_query,
            "filter": filter_dict,
            "per_page": 50
        },
        "semantic_scholar": {
            "query": search_query,
            "limit": 50
        }
    }

    logger.debug(f"Complete query params: {query_params}")

    return query_params


def _build_year_range(conditions: Dict[str, str]) -> str:
    """
    构建年份范围

    Args:
        conditions: 条件字典

    Returns:
        年份范围字符串，如"2015-2025"
    """
    # 查找年份条件
    year_condition = None

    for key, value in conditions.items():
        if "year" in key.lower() or "年" in key:
            year_condition = value
            break

    # 如果有明确的年份范围
    if year_condition and "-" in str(year_condition):
        return year_condition

    # 默认：最近50年
    current_year = datetime.now().year
    start_year = current_year - 50
    default_range = f"{start_year}-{current_year}"

    logger.debug(f"Using default year range: {default_range}")

    return default_range
