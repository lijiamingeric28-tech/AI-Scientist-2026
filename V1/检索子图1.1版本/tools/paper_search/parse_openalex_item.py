"""
解析OpenAlex API返回的单条记录
"""

from typing import Dict, Any, Optional
import logging
from models.paper_metadata import PaperMetadata
from tools.paper_search.reconstruct_abstract import reconstruct_abstract

logger = logging.getLogger(__name__)


def parse_openalex_item(item: Dict[str, Any]) -> PaperMetadata:
    """
    解析OpenAlex API返回的单条记录

    Args:
        item: OpenAlex API返回的JSON对象

    Returns:
        PaperMetadata对象

    OpenAlex API字段映射：
        - id: item["id"]（如"https://openalex.org/W2741809807"）
        - doi: item.get("doi")
        - title: item.get("title")
        - abstract: item.get("abstract_inverted_index") 需要反转
        - authors: item.get("authorships")
        - year: item.get("publication_year")
        - citation_count: item.get("cited_by_count")
        - journal: item.get("primary_location", {}).get("source", {}).get("display_name")
        - is_oa: item.get("open_access", {}).get("is_oa")
        - oa_url: item.get("open_access", {}).get("oa_url")
        - pdf_url: item.get("primary_location", {}).get("pdf_url")
    """
    # 提取OpenAlex ID
    openalex_id = item["id"].split("/")[-1]

    # 提取DOI
    doi = item.get("doi")
    if doi:
        doi = doi.replace("https://doi.org/", "")

    # 提取标题
    title = item.get("title", "Untitled")

    # 提取摘要
    abstract = reconstruct_abstract(item.get("abstract_inverted_index"))

    # 提取作者
    authors = []
    for authorship in item.get("authorships", []):
        author_name = authorship.get("author", {}).get("display_name")
        if author_name:
            authors.append(author_name)

    # 提取年份
    year = item.get("publication_year", 0)

    # 提取引用数
    citation_count = item.get("cited_by_count", 0)

    # 提取期刊
    journal = item.get("primary_location", {}).get("source", {}).get("display_name")

    # 提取开放获取信息
    open_access = item.get("open_access", {})
    is_oa = open_access.get("is_oa", False)
    oa_url = open_access.get("oa_url")

    # 提取PDF链接
    pdf_url = item.get("primary_location", {}).get("pdf_url")

    # 提取相关性得分
    relevance_score = item.get("relevance_score")

    # 提取概念标签
    concepts = [c.get("display_name") for c in item.get("concepts", [])[:5]]

    # 提取主题
    primary_topic = item.get("primary_topic", {}).get("display_name") if item.get("primary_topic") else None

    return PaperMetadata(
        id=openalex_id,
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        citation_count=citation_count,
        journal=journal,
        is_oa=is_oa,
        oa_url=oa_url,
        pdf_url=pdf_url,
        relevance_score=relevance_score,
        concepts=concepts,
        primary_topic=primary_topic
    )
