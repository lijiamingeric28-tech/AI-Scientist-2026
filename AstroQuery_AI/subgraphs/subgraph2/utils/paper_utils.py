"""论文检索辅助函数"""

import logging
import math
import re
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

# 匹配 arXiv ID 的两种形式：
#   新式: arXiv:2301.12345
#   旧式: arXiv:astro-ph/9802121
# 必须排除 10.48550/arXiv.xxx 这种 DOI 形式（ADS 的 identifier 里两者都有）
_ARXIV_ID_PATTERN = re.compile(r'^arXiv:([0-9]{4}\.[0-9]{4,5}|[a-z-]+(\.[A-Z]{2})?/[0-9]{7})$')


def extract_arxiv_id(identifiers) -> str:
    """
    从 ADS 返回的 identifier 列表中提取 arXiv ID

    Args:
        identifiers: ADS 返回的 identifier 列表（可能是 list 或 None）

    Returns:
        arXiv ID 字符串，如 "2301.12345" 或 "astro-ph/9802121"；
        提取不到返回 None
    """
    if not identifiers:
        return None

    for ident in identifiers:
        m = _ARXIV_ID_PATTERN.match(str(ident).strip())
        if m:
            return m.group(1)

    return None


def calculate_retrieval_priority(
    score: float,
    citation_count: int,
    year: int,
    max_score: float = 1000,
    max_citations: int = 1000
) -> float:
    """
    计算论文的检索优先级（0-1）

    公式：
    priority = 0.5 * normalized_score + 0.3 * normalized_citations + 0.2 * time_factor

    Args:
        score: ADS 相关性分数
        citation_count: 被引量
        year: 发表年份
        max_score: 最大分数（用于归一化）
        max_citations: 最大被引量（用于归一化）

    Returns:
        优先级分数（0-1）
    """
    # 归一化 score
    normalized_score = min(score / max_score, 1.0) if max_score > 0 else 0.0

    # 归一化被引量
    normalized_citations = min(citation_count / max_citations, 1.0) if max_citations > 0 else 0.0

    # 时间衰减因子（近期论文权重更高）
    # L-07: current_year 动态取当前年份，不再硬编码——跨年后衰减因子失真
    current_year = datetime.now().year
    age = current_year - year if year else 0
    age = max(age, 0)  # L-07: 未来年份（时钟/数据误差）钳制为 0，避免 time_factor 反超 1
    time_factor = 1.0 / (1.0 + 0.05 * age)  # 每年衰减 5%

    # 加权综合
    priority = (
        0.5 * normalized_score +
        0.3 * normalized_citations +
        0.2 * time_factor
    )

    return min(priority, 1.0)


def extract_paper_metadata(paper, search_rank: int, search_query: str) -> dict:
    """
    从 ADS 结果中提取论文元数据

    Args:
        paper: ADS 搜索结果对象
        search_rank: 搜索结果中的排名
        search_query: 搜索查询字符串

    Returns:
        论文元数据字典
    """
    # 提取基础字段
    bibcode = paper.bibcode if hasattr(paper, 'bibcode') else None
    doi = paper.doi[0] if hasattr(paper, 'doi') and paper.doi else None
    title = paper.title[0] if hasattr(paper, 'title') and paper.title else "Untitled"
    authors = paper.author if hasattr(paper, 'author') and paper.author else []
    # year 治本 fix (2026-08-11 真实链路暴露): ADS paper.year 是 str ('2001'),
    # 直接透传会让 quality 管线 statistical_conflict 的 year_a - year_b 崩 TypeError。
    # 统一转 int, 解析失败置 None (不参与时间差异判定)。
    _year = paper.year if hasattr(paper, 'year') else None
    year = None
    if _year is not None:
        try:
            year = int(_year)
        except (ValueError, TypeError):
            logger.warning(f"[extract_paper_metadata] year 非数值, 置 None: {_year!r}")
            year = None
    journal = paper.pub if hasattr(paper, 'pub') else None
    abstract = paper.abstract if hasattr(paper, 'abstract') else None

    # 提取 keyword
    keywords = []
    if hasattr(paper, 'keyword') and paper.keyword:
        keywords = paper.keyword

    # 提取被引量
    citation_count = 0
    if hasattr(paper, 'citation_count') and paper.citation_count:
        try:
            citation_count = int(paper.citation_count)
        except (ValueError, TypeError):
            citation_count = 0

    # 提取 arXiv ID 和 esources（用于下载链路，见 P0）
    arxiv_id = extract_arxiv_id(getattr(paper, 'identifier', None))
    esources = getattr(paper, 'esources', None) or []

    # R2-2: 提取 score —— 优先真实 ADS 相关性分（fl 已请求 'score' 字段）；
    # 缺失/异常时回退被引量（次级替代，score_source 标记区分）。
    score = None
    score_source = "ads"
    if hasattr(paper, "score") and getattr(paper, "score", None) is not None:
        try:
            score = float(paper.score)
        except (ValueError, TypeError):
            score = None
    if score is None or not math.isfinite(score) or score <= 0:
        score = citation_count
        score_source = "citation_fallback"

    # 计算 retrieval_priority。
    # 注意：真实 ADS score 的量纲不定（批内相对值），此处 max_score=1000 是
    # 占位估算；ads_search 拿到整批结果后会按批内最大值重算（见 ads_search.py）。
    priority = calculate_retrieval_priority(
        score=score,
        citation_count=citation_count,
        year=int(year) if year else 2020,
        max_score=1000,
        max_citations=1000
    )

    metadata = {
        "bibcode": bibcode,
        "doi": doi,
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "abstract": abstract,
        "keywords": keywords,
        "citation_count": citation_count,
        "score": score,
        "score_source": score_source,
        "retrieval_priority": priority,
        "search_query": search_query,
        "search_rank": search_rank,
        "arxiv_id": arxiv_id,
        "esources": esources
    }

    logger.debug(f"[extract_paper_metadata] 提取论文元数据: {bibcode}, priority={priority:.4f}")

    return metadata
