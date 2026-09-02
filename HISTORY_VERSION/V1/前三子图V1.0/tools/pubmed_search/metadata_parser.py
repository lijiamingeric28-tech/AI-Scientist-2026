"""
PubMed元数据解析器

将PubMed API返回的元数据转换为PaperMetadata模型
"""

import logging
from typing import Optional, Dict
from models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def parse_pubmed_metadata(
    summary: Dict,
    pmc_url: Optional[str] = None
) -> Optional[PaperMetadata]:
    """
    将PubMed返回的元数据转换为PaperMetadata

    Args:
        summary: ESummary返回的元数据字典
        pmc_url: PMC PDF链接（可选）

    Returns:
        PaperMetadata对象，失败返回None
    """
    try:
        # 必需字段检查
        uid = summary.get("uid")
        title = summary.get("title", "").strip()

        if not uid or not title:
            logger.warning(f"[PubMed Parser] Missing required fields: uid={uid}, title={'<empty>' if not title else '<present>'}")
            return None

        logger.debug(f"[PubMed Parser] Parsing PMID {uid}: {title[:50]}...")

        # 提取年份
        year = _extract_year(summary.get("pubdate", ""))
        if not year:
            logger.warning(f"[PubMed Parser] PMID {uid}: Failed to extract year from pubdate='{summary.get('pubdate')}', using default 2020")
            year = 2020  # 默认值

        # 提取作者列表
        authors = summary.get("authors", [])
        if not authors:
            logger.debug(f"[PubMed Parser] PMID {uid}: No authors found, using 'Unknown'")
            authors = ["Unknown"]

        # 构建PaperMetadata
        paper = PaperMetadata(
            id=f"PMID:{uid}",
            pmid=uid,
            doi=summary.get("elocationid"),
            title=title,
            authors=authors,
            year=year,
            journal=summary.get("source"),
            citation_count=summary.get("pmc_refcount", 0),
            pubmed_download_url=pmc_url,
            source_db="pubmed",
            # 其他字段使用默认值
            oa_url=pmc_url,  # PMC链接也作为开放获取链接
            pdf_url=None,
            primary_topic="Medical",
            concepts=[]
        )

        logger.debug(f"[PubMed Parser] Successfully parsed PMID {uid}")
        return paper

    except Exception as e:
        uid = summary.get("uid", "unknown")
        logger.error(f"[PubMed Parser] Failed to parse PMID {uid}: {e}", exc_info=True)
        return None


def _extract_year(pubdate: str) -> Optional[int]:
    """
    从PubDate字符串提取年份

    支持格式:
    - "2023"
    - "2023 Jan"
    - "2023 Jan 15"
    - "2023/01/15"

    Args:
        pubdate: 发表日期字符串

    Returns:
        年份整数，失败返回None
    """
    if not pubdate:
        logger.debug("[PubMed Parser] Empty pubdate string")
        return None

    # 尝试提取前4个数字
    import re
    match = re.search(r'\b(19|20)\d{2}\b', pubdate)
    if match:
        year = int(match.group(0))
        logger.debug(f"[PubMed Parser] Extracted year {year} from pubdate '{pubdate}'")
        return year

    # 如果是纯数字字符串
    if pubdate.isdigit() and len(pubdate) == 4:
        year = int(pubdate)
        logger.debug(f"[PubMed Parser] Extracted year {year} from numeric pubdate '{pubdate}'")
        return year

    logger.debug(f"[PubMed Parser] Failed to extract year from pubdate '{pubdate}'")
    return None
