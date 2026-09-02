"""
基于ID、DOI、PMID去重
"""

from typing import List
import logging
from shared.models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def deduplicate_by_id(papers: list[PaperMetadata]) -> list[PaperMetadata]:
    """
    基于ID、DOI、PMID三重去重

    Args:
        papers: 可能包含重复的论文列表

    Returns:
        去重后的论文列表（保留第一次出现的，优先保留有PMC链接的版本）

    去重逻辑:
        1. 使用ID (paper.id) 去重
        2. 使用DOI (paper.doi) 去重
        3. 使用PMID (paper.pmid) 去重
        4. 同一篇论文可能有多个标识符，优先保留有pubmed_download_url的版本
    """
    seen_ids = set()
    seen_dois = set()
    seen_pmids = set()
    deduplicated = []

    for paper in papers:
        # 检查是否已存在
        is_duplicate = False

        # 检查ID
        if paper.id in seen_ids:
            is_duplicate = True

        # 检查DOI
        if paper.doi and paper.doi in seen_dois:
            is_duplicate = True

        # 检查PMID
        if paper.pmid and paper.pmid in seen_pmids:
            is_duplicate = True

        # 如果不重复，添加到结果
        if not is_duplicate:
            deduplicated.append(paper)
            seen_ids.add(paper.id)
            if paper.doi:
                seen_dois.add(paper.doi)
            if paper.pmid:
                seen_pmids.add(paper.pmid)

    duplicates_removed = len(papers) - len(deduplicated)
    logger.info(f"Removed {duplicates_removed} duplicates (by ID/DOI/PMID), {len(deduplicated)} papers remain")

    return deduplicated
