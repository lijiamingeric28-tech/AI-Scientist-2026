"""
DOI转换工具

提供PMID和DOI之间的转换功能
"""

import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# API配置
PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ID_CONVERTER_API = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
OPENALEX_API = "https://api.openalex.org"


def pmid_to_doi(pmid: str, email: str = "your_email@example.com", api_key: Optional[str] = None) -> Optional[str]:
    """
    PMID转DOI

    策略:
    1. 调用NCBI ID Converter API
    2. 如果失败，尝试从PubMed EFetch获取

    Args:
        pmid: PubMed ID
        email: 邮箱地址（NCBI要求）
        api_key: API Key（可选）

    Returns:
        DOI字符串，失败返回None
    """
    logger.info(f"[DOI Converter] Converting PMID {pmid} to DOI")

    # 方法1: 使用ID Converter API
    try:
        params = {
            "ids": pmid,
            "format": "json"
        }

        response = requests.get(ID_CONVERTER_API, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if "records" in data and len(data["records"]) > 0:
            record = data["records"][0]
            doi = record.get("doi")

            if doi:
                logger.info(f"[DOI Converter] PMID {pmid} -> DOI {doi} (via ID Converter)")
                return doi

        logger.debug(f"[DOI Converter] ID Converter returned no DOI for PMID {pmid}")

    except requests.RequestException as e:
        logger.warning(f"[DOI Converter] ID Converter API failed for PMID {pmid}: {e}")
    except Exception as e:
        logger.warning(f"[DOI Converter] Unexpected error in ID Converter for PMID {pmid}: {e}")

    # 方法2: 使用PubMed EFetch
    try:
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml",
            "email": email
        }

        if api_key:
            params["api_key"] = api_key

        url = f"{PUBMED_BASE_URL}/efetch.fcgi"
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        # 从XML中提取DOI
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.content)

        # 查找ArticleId[@IdType="doi"]
        for article_id in root.findall(".//ArticleId"):
            if article_id.get("IdType") == "doi":
                doi = article_id.text
                if doi:
                    logger.info(f"[DOI Converter] PMID {pmid} -> DOI {doi} (via EFetch)")
                    return doi

        logger.debug(f"[DOI Converter] EFetch returned no DOI for PMID {pmid}")

    except requests.RequestException as e:
        logger.warning(f"[DOI Converter] EFetch API failed for PMID {pmid}: {e}")
    except Exception as e:
        logger.warning(f"[DOI Converter] Unexpected error in EFetch for PMID {pmid}: {e}")

    logger.warning(f"[DOI Converter] Failed to convert PMID {pmid} to DOI")
    return None


def doi_to_openalex_id(doi: str, email: str = "your_email@example.com") -> Optional[str]:
    """
    DOI转OpenAlex ID

    Args:
        doi: DOI字符串
        email: 邮箱地址（OpenAlex礼貌参数）

    Returns:
        OpenAlex ID（格式：W1234567890），失败返回None
    """
    logger.info(f"[DOI Converter] Converting DOI {doi} to OpenAlex ID")

    try:
        # 清理DOI（移除可能的前缀）
        clean_doi = doi.strip()
        if clean_doi.startswith("doi:"):
            clean_doi = clean_doi[4:]
        if clean_doi.startswith("https://doi.org/"):
            clean_doi = clean_doi[16:]
        if clean_doi.startswith("http://doi.org/"):
            clean_doi = clean_doi[15:]

        # 调用OpenAlex API
        url = f"{OPENALEX_API}/works/doi:{clean_doi}"
        headers = {
            "User-Agent": f"mailto:{email}"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        openalex_id = data.get("id")

        if openalex_id:
            # 提取ID部分（从完整URL中）
            if "/" in openalex_id:
                openalex_id = openalex_id.split("/")[-1]

            logger.info(f"[DOI Converter] DOI {doi} -> OpenAlex ID {openalex_id}")
            return openalex_id

        logger.warning(f"[DOI Converter] OpenAlex returned no ID for DOI {doi}")
        return None

    except requests.RequestException as e:
        logger.warning(f"[DOI Converter] OpenAlex API failed for DOI {doi}: {e}")
        return None
    except Exception as e:
        logger.error(f"[DOI Converter] Unexpected error converting DOI {doi}: {e}", exc_info=True)
        return None
