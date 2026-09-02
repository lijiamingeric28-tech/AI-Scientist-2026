"""
计算论文的综合分数
"""

import logging
from models.paper_metadata import PaperMetadata
from configs.constants import (
    RANK_CITATION_WEIGHT,
    RANK_RECENCY_WEIGHT,
    RANK_RELEVANCE_WEIGHT
)

logger = logging.getLogger(__name__)


def calculate_score(paper: PaperMetadata, current_year: int = 2026) -> float:
    """
    计算论文的综合分数

    Args:
        paper: 论文元数据
        current_year: 当前年份，用于计算时效性

    Returns:
        综合分数（0-100）

    分数公式:
        base_score = citation_score * 0.4 + recency_score * 0.3 + relevance_score * 0.3

        如果是PubMed论文且有PMC链接，加10%权重:
        final_score = base_score * 1.1

    各项计算:
        - citation_score: min(citation_count, 1000) / 10  (0-100)
        - recency_score: max(0, 100 - (current_year - year) * 5)  (0-100)
        - relevance_score: relevance_score * 100 if exists else 50  (0-100)
    """
    # 引用分数（归一化到0-100）
    citation_score = min(paper.citation_count, 1000) / 10

    # 时效性分数（越新越高）
    # 如果year为None，给予中等分数
    if paper.year is None:
        recency_score = 50  # 中等分数
        logger.debug(f"Paper {paper.id} has no year, using default recency score: 50")
    else:
        years_ago = current_year - paper.year
        recency_score = max(0, 100 - years_ago * 5)
        logger.debug(f"Paper {paper.id} year: {paper.year}, recency score: {recency_score:.2f}")

    # 相关性分数
    relevance_score = paper.relevance_score * 100 if paper.relevance_score else 50

    # 基础综合分数
    base_score = (
        citation_score * RANK_CITATION_WEIGHT +
        recency_score * RANK_RECENCY_WEIGHT +
        relevance_score * RANK_RELEVANCE_WEIGHT
    )

    # PubMed论文加权（有PMC链接的论文+10%）
    if paper.source_db == "pubmed" and paper.pubmed_download_url:
        final_score = base_score * 1.1
        logger.debug(f"PubMed paper {paper.pmid} boosted: {base_score:.2f} -> {final_score:.2f}")
    else:
        final_score = base_score

    return round(final_score, 2)
