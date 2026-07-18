"""
PubMed API客户端

使用NCBI Entrez E-utilities API进行文献检索
"""

import requests
import time
import logging
from typing import List, Dict, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# API配置
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
REQUEST_DELAY = 0.34  # 无API Key限速：3次/秒


def search_pubmed(
    query: str,
    filters: Dict,
    email: str = "your_email@example.com",
    api_key: Optional[str] = None
) -> List[str]:
    """
    使用ESearch API搜索PubMed，返回PMID列表

    Args:
        query: PubMed查询字符串
        filters: 过滤条件字典，包含publication_date, retmax等
        email: 邮箱地址（NCBI要求）
        api_key: API Key（可选，可提高限速到10次/秒）

    Returns:
        PMID列表
    """
    logger.info(f"[PubMed ESearch] Starting search with query: {query[:100]}...")
    logger.debug(f"[PubMed ESearch] Full query: {query}")
    logger.debug(f"[PubMed ESearch] Filters: {filters}")

    # 构建请求参数
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": filters.get("retmax", 50),
        "retmode": "xml",
        "sort": filters.get("sort", "relevance"),
        "email": email
    }

    # 添加日期过滤
    if "publication_date" in filters:
        date_range = filters["publication_date"]
        # 格式: 2015:2025 -> mindate=2015&maxdate=2025
        if ":" in date_range:
            start, end = date_range.split(":")
            params["mindate"] = start.strip()
            params["maxdate"] = end.strip()
            params["datetype"] = "pdat"  # Publication Date

    if api_key:
        params["api_key"] = api_key

    try:
        # 调用ESearch API
        url = f"{PUBMED_BASE_URL}/esearch.fcgi"
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        # 解析XML响应
        root = ET.fromstring(response.content)

        # 提取PMID列表
        pmids = []
        id_list = root.find("IdList")
        if id_list is not None:
            for id_elem in id_list.findall("Id"):
                pmids.append(id_elem.text)

        count = root.findtext("Count", "0")
        logger.info(f"[PubMed ESearch] Found {count} total papers in PubMed")
        logger.info(f"[PubMed ESearch] Returning {len(pmids)} PMIDs (retmax={filters.get('retmax', 50)})")
        if pmids:
            logger.debug(f"[PubMed ESearch] First 5 PMIDs: {pmids[:5]}")

        # API限速
        time.sleep(REQUEST_DELAY)

        return pmids

    except requests.RequestException as e:
        logger.error(f"[PubMed ESearch] API request failed: {e}", exc_info=True)
        return []
    except ET.ParseError as e:
        logger.error(f"[PubMed ESearch] Failed to parse XML response: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"[PubMed ESearch] Unexpected error: {e}", exc_info=True)
        return []


def fetch_paper_details(
    pmids: List[str],
    email: str = "your_email@example.com",
    api_key: Optional[str] = None,
    batch_size: int = 200
) -> List[Dict]:
    """
    使用ESummary API批量获取论文元数据

    Args:
        pmids: PMID列表
        email: 邮箱地址
        api_key: API Key（可选）
        batch_size: 每批处理数量（ESummary最大支持500）

    Returns:
        论文元数据字典列表
    """
    logger.info(f"[PubMed ESummary] Fetching details for {len(pmids)} PMIDs")
    logger.debug(f"[PubMed ESummary] Batch size: {batch_size}")

    if not pmids:
        return []

    all_summaries = []

    # 分批处理
    for i in range(0, len(pmids), batch_size):
        batch_pmids = pmids[i:i + batch_size]
        batch_num = i//batch_size + 1
        total_batches = (len(pmids) + batch_size - 1) // batch_size
        logger.info(f"[PubMed ESummary] Processing batch {batch_num}/{total_batches}: {len(batch_pmids)} PMIDs")
        logger.debug(f"[PubMed ESummary] Batch PMIDs: {batch_pmids[:5]}...")

        # 构建请求参数
        params = {
            "db": "pubmed",
            "id": ",".join(batch_pmids),
            "retmode": "xml",
            "email": email
        }

        if api_key:
            params["api_key"] = api_key

        try:
            # 调用ESummary API
            url = f"{PUBMED_BASE_URL}/esummary.fcgi"
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # 解析XML响应
            root = ET.fromstring(response.content)

            # 提取每篇论文的元数据
            for doc_sum in root.findall(".//DocSum"):
                summary = _parse_doc_sum(doc_sum)
                if summary:
                    all_summaries.append(summary)

            # API限速
            time.sleep(REQUEST_DELAY)

        except requests.RequestException as e:
            logger.error(f"[PubMed ESummary] API request failed for batch {batch_num}: {e}", exc_info=True)
        except ET.ParseError as e:
            logger.error(f"[PubMed ESummary] Failed to parse XML response for batch {batch_num}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[PubMed ESummary] Unexpected error in batch {batch_num}: {e}", exc_info=True)

    logger.info(f"[PubMed ESummary] Successfully fetched {len(all_summaries)}/{len(pmids)} paper details")
    if len(all_summaries) < len(pmids):
        logger.warning(f"[PubMed ESummary] Failed to fetch {len(pmids) - len(all_summaries)} papers")
    return all_summaries


def get_pmc_links(
    pmids: List[str],
    email: str = "your_email@example.com",
    api_key: Optional[str] = None,
    batch_size: int = 200
) -> Dict[str, str]:
    """
    使用ELink API获取PMC全文链接

    Args:
        pmids: PMID列表
        email: 邮箱地址
        api_key: API Key（可选）

    Returns:
        {pmid: pmc_pdf_url}字典
    """
    logger.info(f"[PubMed ELink] Fetching PMC links for {len(pmids)} PMIDs")
    logger.debug(f"[PubMed ELink] Batch size: {batch_size}")

    if not pmids:
        return {}

    pmc_links = {}

    # ELink一次最多处理200个ID
    batch_size = 200
    for i in range(0, len(pmids), batch_size):
        batch_pmids = pmids[i:i + batch_size]

        # 构建请求参数
        params = {
            "dbfrom": "pubmed",
            "db": "pmc",
            "id": ",".join(batch_pmids),
            "linkname": "pubmed_pmc",
            "retmode": "xml",
            "email": email
        }

        if api_key:
            params["api_key"] = api_key

        try:
            # 调用ELink API
            url = f"{PUBMED_BASE_URL}/elink.fcgi"
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # 解析XML响应
            root = ET.fromstring(response.content)

            # 提取PMC ID映射
            for linkset in root.findall(".//LinkSet"):
                pmid_elem = linkset.find(".//Id")
                if pmid_elem is None:
                    continue

                pmid = pmid_elem.text

                # 查找对应的PMCID
                link_set_db = linkset.find(".//LinkSetDb")
                if link_set_db is not None:
                    pmc_id_elem = link_set_db.find(".//Link/Id")
                    if pmc_id_elem is not None:
                        pmcid = pmc_id_elem.text
                        # 构建PMC PDF链接
                        pmc_pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/"
                        pmc_links[pmid] = pmc_pdf_url
                        logger.debug(f"PMID {pmid} -> PMCID {pmcid}")

            # API限速
            time.sleep(REQUEST_DELAY)

        except requests.RequestException as e:
            logger.error(f"[PubMed ELink] API request failed for batch {batch_num}: {e}", exc_info=True)
        except ET.ParseError as e:
            logger.error(f"[PubMed ELink] Failed to parse XML response for batch {batch_num}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[PubMed ELink] Unexpected error in batch {batch_num}: {e}", exc_info=True)

    success_rate = len(pmc_links) / len(pmids) * 100 if pmids else 0
    logger.info(f"[PubMed ELink] Found {len(pmc_links)}/{len(pmids)} PMC links ({success_rate:.1f}% success rate)")
    if pmc_links:
        logger.debug(f"[PubMed ELink] Sample PMC links: {list(pmc_links.items())[:3]}")
    return pmc_links


def _parse_doc_sum(doc_sum: ET.Element) -> Optional[Dict]:
    """
    解析ESummary返回的DocSum元素

    Args:
        doc_sum: DocSum XML元素

    Returns:
        元数据字典
    """
    try:
        summary = {}

        # PMID
        uid_elem = doc_sum.find("Id")
        if uid_elem is not None:
            summary["uid"] = uid_elem.text

        # 提取各个字段
        for item in doc_sum.findall("Item"):
            name = item.get("Name")
            item_type = item.get("Type")

            if name == "Title":
                summary["title"] = item.text or ""
            elif name == "PubDate":
                summary["pubdate"] = item.text or ""
            elif name == "Source":
                summary["source"] = item.text or ""
            elif name == "AuthorList":
                authors = []
                for author in item.findall("Item"):
                    if author.text:
                        authors.append(author.text)
                summary["authors"] = authors
            elif name == "DOI":
                summary["elocationid"] = item.text
            elif name == "PmcRefCount":
                try:
                    summary["pmc_refcount"] = int(item.text or "0")
                except ValueError:
                    summary["pmc_refcount"] = 0

        return summary if "uid" in summary else None

    except Exception as e:
        logger.error(f"Failed to parse DocSum: {e}")
        return None
