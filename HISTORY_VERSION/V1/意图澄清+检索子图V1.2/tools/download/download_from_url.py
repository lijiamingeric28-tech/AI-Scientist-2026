"""
增强下载函数 - HTML Fallback支持 + 连接池
从HTML页面中提取真实PDF链接
"""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
import time
import random
import re
from typing import Dict, Any
from configs.constants import DOWNLOAD_TIMEOUT, DOWNLOAD_CONNECTION_POOL_SIZE
from tools.download.validate_pdf_file import validate_pdf_file

logger = logging.getLogger(__name__)


# 全局Session（连接池）
_session = None


def get_session():
    """获取带连接池的全局Session"""
    global _session

    if _session is None:
        _session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=0,  # 我们自己处理重试
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"]
        )

        # 配置HTTP适配器（连接池）
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=DOWNLOAD_CONNECTION_POOL_SIZE,   # 连接池大小
            pool_maxsize=DOWNLOAD_CONNECTION_POOL_SIZE,       # 最大连接数
            pool_block=False
        )

        _session.mount("http://", adapter)
        _session.mount("https://", adapter)

        logger.info(f"HTTP connection pool initialized (size={DOWNLOAD_CONNECTION_POOL_SIZE})")

    return _session


def get_browser_headers() -> dict:
    """获取真实浏览器请求头"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    ]

    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://scholar.google.com/'
    }

    return headers


def extract_pdf_links_from_html(html_content: str, base_url: str) -> list:
    """
    从HTML中提取可能的PDF链接

    策略:
    1. 查找明确的PDF链接 (href包含.pdf)
    2. 查找下载按钮的链接
    3. 查找meta标签中的PDF链接
    """
    pdf_links = []

    try:
        from urllib.parse import urljoin

        # 策略1: 查找所有.pdf链接
        pdf_pattern = re.compile(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', re.IGNORECASE)
        matches = pdf_pattern.findall(html_content)

        for match in matches:
            full_url = urljoin(base_url, match)
            if full_url not in pdf_links:
                pdf_links.append(full_url)

        # 策略2: 查找常见的下载链接模式
        download_patterns = [
            r'href=["\']([^"\']*download[^"\']*)["\']',
            r'href=["\']([^"\']*fulltext[^"\']*)["\']',
            r'href=["\']([^"\']*content/pdf[^"\']*)["\']',
            r'data-article-pdf=["\']([^"\']*)["\']',
        ]

        for pattern in download_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                full_url = urljoin(base_url, match)
                if '.pdf' in full_url.lower() or 'download' in full_url.lower():
                    if full_url not in pdf_links:
                        pdf_links.append(full_url)

        # 策略3: 查找meta标签
        meta_pattern = re.compile(r'<meta[^>]*citation_pdf_url[^>]*content=["\']([^"\']*)["\']', re.IGNORECASE)
        matches = meta_pattern.findall(html_content)
        for match in matches:
            full_url = urljoin(base_url, match)
            if full_url not in pdf_links:
                pdf_links.append(full_url)

        logger.debug(f"Extracted {len(pdf_links)} potential PDF links from HTML")

    except Exception as e:
        logger.debug(f"Failed to extract PDF links: {e}")

    return pdf_links


def download_from_url(url: str, save_path: str, timeout: int = DOWNLOAD_TIMEOUT, retry_count: int = 3) -> Dict[str, Any]:
    """
    从URL下载文件（增强版 + HTML Fallback + 连接池）

    新增功能:
    - 如果返回HTML，尝试从HTML中提取真实PDF链接
    - 对提取的链接逐个尝试下载
    - 使用全局连接池提高性能
    """

    # 使用全局连接池Session
    session = get_session()

    # Cookie预热
    try:
        article_url = url.replace('.pdf', '').replace('/pdf', '')
        if article_url != url and 'http' in article_url:
            logger.debug(f"Cookie warmup: {article_url[:80]}")
            warmup_headers = get_browser_headers()
            session.get(article_url, headers=warmup_headers, timeout=10, allow_redirects=True)
            time.sleep(1)
    except Exception as e:
        logger.debug(f"Cookie warmup failed: {e}")

    for attempt in range(retry_count):
        try:
            headers = get_browser_headers()

            logger.debug(f"Attempt {attempt + 1}/{retry_count}: Downloading {url[:80]}...")

            response = session.get(
                url,
                headers=headers,
                timeout=timeout,
                stream=False,  # 改为False，先读取全部内容
                allow_redirects=True,
                verify=True
            )

            response.raise_for_status()

            # 检查Content-Type
            content_type = response.headers.get('Content-Type', '').lower()
            logger.debug(f"Content-Type: {content_type}")

            content = response.content

            # 检查是否为PDF
            if content.startswith(b'%PDF-'):
                logger.debug("Direct PDF download successful")

                # 保存文件
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(content)

                file_size = os.path.getsize(save_path)

                # 验证PDF
                if validate_pdf_file(save_path):
                    return {
                        "success": True,
                        "file_size": file_size,
                        "error": None
                    }
                else:
                    logger.warning("PDF validation failed")
                    os.remove(save_path)
                    if attempt == retry_count - 1:
                        return {
                            "success": False,
                            "file_size": 0,
                            "error": "Invalid PDF file"
                        }
                    time.sleep(2 ** attempt)
                    continue

            # 🔥 新功能: HTML Fallback
            elif content.startswith(b'<!DOCTYPE') or content.startswith(b'<html') or 'text/html' in content_type:
                logger.info("Received HTML page - trying HTML Fallback")

                try:
                    html_content = content.decode('utf-8', errors='ignore')
                except:
                    html_content = content.decode('latin-1', errors='ignore')

                # 从HTML中提取PDF链接
                pdf_links = extract_pdf_links_from_html(html_content, response.url)

                if not pdf_links:
                    logger.warning("No PDF links found in HTML")
                    if attempt == retry_count - 1:
                        return {
                            "success": False,
                            "file_size": 0,
                            "error": "HTML page, no PDF links found"
                        }
                    time.sleep(2 ** attempt)
                    continue

                # 尝试下载提取的PDF链接
                logger.info(f"Found {len(pdf_links)} potential PDF links, trying...")

                for i, pdf_link in enumerate(pdf_links[:3], 1):  # 只尝试前3个
                    logger.debug(f"Trying extracted link {i}: {pdf_link[:80]}")

                    try:
                        pdf_response = session.get(
                            pdf_link,
                            headers=headers,
                            timeout=timeout,
                            allow_redirects=True
                        )

                        if pdf_response.status_code == 200:
                            pdf_content = pdf_response.content

                            if pdf_content.startswith(b'%PDF-'):
                                logger.info(f"Successfully downloaded PDF from extracted link {i}")

                                # 保存
                                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                                with open(save_path, 'wb') as f:
                                    f.write(pdf_content)

                                file_size = os.path.getsize(save_path)

                                # 验证
                                if validate_pdf_file(save_path):
                                    return {
                                        "success": True,
                                        "file_size": file_size,
                                        "error": None
                                    }
                                else:
                                    os.remove(save_path)

                    except Exception as e:
                        logger.debug(f"Extracted link {i} failed: {e}")
                        continue

                logger.warning("All extracted PDF links failed")
                if attempt == retry_count - 1:
                    return {
                        "success": False,
                        "file_size": 0,
                        "error": "HTML Fallback failed"
                    }

                time.sleep(2 ** attempt)
                continue

            else:
                logger.warning(f"Unknown content type: {content_type}")
                if attempt == retry_count - 1:
                    return {
                        "success": False,
                        "file_size": 0,
                        "error": f"Unknown content type: {content_type}"
                    }
                time.sleep(2 ** attempt)
                continue

        except requests.Timeout:
            logger.warning(f"Timeout (attempt {attempt + 1})")
            if attempt < retry_count - 1:
                time.sleep(2 ** attempt)
                continue
            return {
                "success": False,
                "file_size": 0,
                "error": "Timeout"
            }

        except requests.HTTPError as e:
            status_code = e.response.status_code
            logger.warning(f"HTTP {status_code} (attempt {attempt + 1})")

            # 403/404/401 不重试
            if status_code in [403, 404, 401]:
                return {
                    "success": False,
                    "file_size": 0,
                    "error": f"HTTP {status_code}"
                }

            # 其他错误码重试
            if attempt < retry_count - 1:
                wait_time = 5 * (2 ** attempt)  # 5s, 10s, 20s
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            return {
                "success": False,
                "file_size": 0,
                "error": f"HTTP {status_code}"
            }

        except Exception as e:
            logger.warning(f"Error (attempt {attempt + 1}): {e}")
            if attempt < retry_count - 1:
                time.sleep(2 ** attempt)
                continue
            return {
                "success": False,
                "file_size": 0,
                "error": str(e)
            }

    return {
        "success": False,
        "file_size": 0,
        "error": "All retry attempts failed"
    }
