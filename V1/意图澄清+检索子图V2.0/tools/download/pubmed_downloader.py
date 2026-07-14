"""
PubMed/PMC下载器

支持从PubMed Central下载多种格式的论文
"""

import requests
import logging
import os
from typing import Optional, Dict
from models.paper_metadata import PaperMetadata

logger = logging.getLogger(__name__)


def download_from_pubmed(
    paper: PaperMetadata,
    output_dir: str,
    timeout: int = 60
) -> Dict:
    """
    从PubMed/PMC下载论文

    下载优先级:
    1. PMC PDF (paper.pubmed_download_url)
    2. PMC PDF (通过PMCID构建)
    3. PMC XML (备选格式)
    4. PMC TXT (最后备选)

    Args:
        paper: 论文元数据
        output_dir: 输出目录
        timeout: 下载超时（秒）

    Returns:
        下载结果字典 {
            "success": bool,
            "local_path": str,
            "file_size": int,
            "format": str,
            "source": str,
            "error": str (if failed)
        }
    """
    logger.info(f"[PubMed Download] Attempting to download PMID {paper.pmid}")

    # 准备输出文件名
    safe_filename = _generate_safe_filename(paper)

    # 策略1: 使用已有的PMC链接
    if paper.pubmed_download_url:
        logger.info(f"[PubMed Download] Trying existing PMC link")
        result = _download_pmc_pdf(
            paper.pubmed_download_url,
            output_dir,
            safe_filename,
            timeout
        )
        if result["success"]:
            return result

    # 策略2: 通过PMCID构建PMC PDF链接
    if paper.pmcid:
        logger.info(f"[PubMed Download] Trying PMC PDF via PMCID")
        pmc_pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{paper.pmcid}/pdf/"
        result = _download_pmc_pdf(
            pmc_pdf_url,
            output_dir,
            safe_filename,
            timeout
        )
        if result["success"]:
            return result

        # 策略3: 尝试PMC XML
        logger.info(f"[PubMed Download] PDF failed, trying PMC XML")
        pmc_xml_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{paper.pmcid}/?report=xml"
        result = _download_pmc_xml(
            pmc_xml_url,
            output_dir,
            safe_filename,
            timeout
        )
        if result["success"]:
            return result

    # 所有策略失败
    error_msg = "No PMC link or PMCID available"
    logger.warning(f"[PubMed Download] PMID {paper.pmid}: {error_msg}")
    return {
        "success": False,
        "error": error_msg
    }


def _download_pmc_pdf(
    url: str,
    output_dir: str,
    filename: str,
    timeout: int
) -> Dict:
    """下载PMC PDF"""
    try:
        logger.debug(f"[PubMed Download] Downloading PDF from {url[:80]}...")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        # 检查是否真的是PDF
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and "application/octet-stream" not in content_type.lower():
            logger.warning(f"[PubMed Download] Content-Type is not PDF: {content_type}")
            return {"success": False, "error": f"Not a PDF: {content_type}"}

        # 保存文件
        output_path = os.path.join(output_dir, f"{filename}.pdf")
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = os.path.getsize(output_path)

        # 验证文件大小
        if file_size < 10 * 1024:  # 小于10KB
            logger.warning(f"[PubMed Download] File too small: {file_size} bytes")
            os.remove(output_path)
            return {"success": False, "error": f"File too small: {file_size} bytes"}

        logger.info(f"[PubMed Download] Successfully downloaded PDF: {file_size} bytes")

        return {
            "success": True,
            "local_path": output_path,
            "file_size": file_size,
            "format": "pdf",
            "source": "pmc_pdf"
        }

    except requests.Timeout:
        logger.warning(f"[PubMed Download] PDF download timeout from {url[:80]}")
        return {"success": False, "error": "Timeout"}
    except requests.RequestException as e:
        logger.warning(f"[PubMed Download] PDF download failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[PubMed Download] Unexpected error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _download_pmc_xml(
    url: str,
    output_dir: str,
    filename: str,
    timeout: int
) -> Dict:
    """下载PMC XML"""
    try:
        logger.debug(f"[PubMed Download] Downloading XML from {url[:80]}...")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        # 保存文件
        output_path = os.path.join(output_dir, f"{filename}.xml")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(response.text)

        file_size = os.path.getsize(output_path)

        # 验证文件大小
        if file_size < 1024:  # 小于1KB
            logger.warning(f"[PubMed Download] XML too small: {file_size} bytes")
            os.remove(output_path)
            return {"success": False, "error": f"XML too small: {file_size} bytes"}

        logger.info(f"[PubMed Download] Successfully downloaded XML: {file_size} bytes")

        return {
            "success": True,
            "local_path": output_path,
            "file_size": file_size,
            "format": "xml",
            "source": "pmc_xml"
        }

    except requests.Timeout:
        logger.warning(f"[PubMed Download] XML download timeout from {url[:80]}")
        return {"success": False, "error": "Timeout"}
    except requests.RequestException as e:
        logger.warning(f"[PubMed Download] XML download failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[PubMed Download] Unexpected error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def _generate_safe_filename(paper: PaperMetadata) -> str:
    """生成安全的文件名"""
    # 使用PMID作为主要标识
    if paper.pmid:
        base_name = f"PMID_{paper.pmid}"
    else:
        # 备选：使用ID的一部分
        base_name = paper.id.replace(":", "_").replace("/", "_")[:50]

    # 添加年份（如果有）
    if paper.year:
        base_name += f"_{paper.year}"

    # 移除不安全字符
    safe_name = "".join(c if c.isalnum() or c in ['_', '-'] else '_' for c in base_name)

    return safe_name
