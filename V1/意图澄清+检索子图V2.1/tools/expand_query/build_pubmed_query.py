"""
构建PubMed API查询参数

将扩展后的实体和属性转换为PubMed查询语法
"""

from typing import List, Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def build_pubmed_query(
    expanded_entities: List[str],
    expanded_properties: List[str],
    conditions: Dict[str, str]
) -> Dict[str, Any]:
    """
    构建PubMed API查询参数

    Args:
        expanded_entities: 扩展后的实体列表
        expanded_properties: 扩展后的属性列表
        conditions: 条件字典

    Returns:
        PubMed查询参数字典
    """
    logger.info("Building PubMed query parameters")

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

    # 如果过滤后为空，使用默认医学词汇
    if not filtered_entities:
        logger.warning("No English entities after filtering, using medical defaults")
        filtered_entities = ["medical", "clinical"]

    if not filtered_properties:
        logger.warning("No English properties after filtering, using medical defaults")
        filtered_properties = ["treatment", "therapy", "outcome"]

    # 构建PubMed查询字符串
    # PubMed语法: term[Field] AND term[Field]
    # 支持的字段: Title, Abstract, Title/Abstract, MeSH Terms, etc.

    # 实体查询 (在标题或摘要中)
    entities_parts = [f"{entity}[Title/Abstract]" for entity in filtered_entities]
    entities_query = " OR ".join(entities_parts)

    # 属性查询 (在标题或摘要中)
    properties_parts = [f"{prop}[Title/Abstract]" for prop in filtered_properties]
    properties_query = " OR ".join(properties_parts)

    # 组合实体和属性查询
    search_query = f"({entities_query}) AND ({properties_query})"

    logger.info(f"Built PubMed search query: {search_query[:100]}...")

    # 构建过滤条件
    filters = {
        "publication_date": _build_pubmed_date_range(conditions),
        "retmax": 50,  # 最大返回数量
        "sort": "relevance"  # 按相关性排序
    }

    # 返回查询参数
    query_params = {
        "search": search_query,
        "filters": filters
    }

    logger.debug(f"Complete PubMed query params: {query_params}")

    return query_params


def _build_pubmed_date_range(conditions: Dict[str, str]) -> str:
    """
    构建PubMed日期范围

    PubMed日期格式: YYYY:YYYY 或 YYYY/MM/DD:YYYY/MM/DD

    Args:
        conditions: 条件字典

    Returns:
        日期范围字符串，如"2015:2025"
    """
    # 查找年份条件
    year_condition = None

    for key, value in conditions.items():
        if "year" in key.lower() or "年" in key:
            year_condition = value
            break

    # 如果有明确的年份范围 (格式: 2015-2025)
    if year_condition and "-" in str(year_condition):
        # 转换为PubMed格式: 2015:2025
        start_year, end_year = year_condition.split("-")
        pubmed_range = f"{start_year.strip()}:{end_year.strip()}"
        logger.debug(f"Using specified date range: {pubmed_range}")
        return pubmed_range

    # 默认：最近10年 (PubMed医学文献更注重时效性)
    current_year = datetime.now().year
    start_year = current_year - 10
    default_range = f"{start_year}:{current_year}"

    logger.debug(f"Using default PubMed date range: {default_range}")

    return default_range
