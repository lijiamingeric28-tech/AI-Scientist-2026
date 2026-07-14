"""
Nature.com专用下载器（基于GitHub spider-rs示例）

参考: https://github.com/spider-rs/web-scraping-examples/blob/main/science-research/nature-scraper.ts
"""

import requests
import logging
from typing import Optional, Dict
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def download_from_nature(url: str, output_path: str, timeout: int = 60) -> Dict:
    """
    从Nature.com下载PDF

    Nature特殊处理：
    1. 访问文章页面获取PDF链接
    2. 添加特殊headers模拟浏览器
    3. 处理重定向

    Args:
        url: Nature文章URL
        output_path: 输出路径
        timeout: 超时时间

    Returns:
        {"success": bool, "local_path": str, "error": str}
    """
    logger.info(f"[Nature] Attempting to download from Nature.com")

    try:
        # Nature特殊的headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }

        # 步骤1: 访问文章页面
        logger.debug(f"[Nature] Step 1: Fetching article page: {url[:80]}")
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()

        # 步骤2: 查找PDF链接
        soup = BeautifulSoup(response.text, 'html.parser')

        # 方法1: 查找直接的PDF链接
        pdf_link = None

        # 常见的Nature PDF链接模式
        patterns = [
            'a[href*="/articles/"][href$=".pdf"]',
            'a[data-track-action="download pdf"]',
            'a[data-test="pdf-link"]',
            'a.c-pdf-download__link',
            'a[href*="/content/pdf/"]'
        ]

        for pattern in patterns:
            link = soup.select_one(pattern)
            if link and link.get('href'):
                pdf_link = link.get('href')
                logger.debug(f"[Nature] Found PDF link with pattern '{pattern}': {pdf_link[:60]}")
                break

        # 方法2: 从URL构造PDF链接
        if not pdf_link and '/articles/' in url:
            # 例如: https://www.nature.com/articles/s41586-020-2012-7
            # 转换为: https://www.nature.com/articles/s41586-020-2012-7.pdf
            if not url.endswith('.pdf'):
                pdf_link = url.rstrip('/') + '.pdf'
                logger.debug(f"[Nature] Constructed PDF link from URL: {pdf_link[:60]}")

        if not pdf_link:
            logger.warning(f"[Nature] No PDF link found in article page")
            return {"success": False, "error": "No PDF link found"}

        # 处理相对链接
        if pdf_link.startswith('/'):
            pdf_link = 'https://www.nature.com' + pdf_link
        elif not pdf_link.startswith('http'):
            pdf_link = 'https://www.nature.com/' + pdf_link.lstrip('/')

        # 步骤3: 下载PDF
        logger.info(f"[Nature] Step 2: Downloading PDF from: {pdf_link[:80]}")
        pdf_response = requests.get(pdf_link, headers=headers, timeout=timeout, stream=True)
        pdf_response.raise_for_status()

        # 检查content-type
        content_type = pdf_response.headers.get('Content-Type', '')
        if 'pdf' not in content_type.lower() and 'application/octet-stream' not in content_type.lower():
            logger.warning(f"[Nature] Unexpected content type: {content_type}")
            # 继续尝试，因为有些服务器返回错误的content-type

        # 保存文件
        with open(output_path, 'wb') as f:
            for chunk in pdf_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        import os
        file_size = os.path.getsize(output_path)

        # 验证文件大小
        if file_size < 10 * 1024:  # 小于10KB
            logger.warning(f"[Nature] Downloaded file too small: {file_size} bytes")
            os.remove(output_path)
            return {"success": False, "error": f"File too small: {file_size} bytes"}

        # 验证是否是PDF
        with open(output_path, 'rb') as f:
            header = f.read(4)
            if header != b'%PDF':
                logger.warning(f"[Nature] Downloaded file is not a PDF")
                os.remove(output_path)
                return {"success": False, "error": "Not a valid PDF file"}

        logger.info(f"[Nature] Successfully downloaded PDF: {file_size} bytes")
        return {
            "success": True,
            "local_path": output_path,
            "file_size": file_size,
            "source": "nature_scraper",
            "error": None
        }

    except requests.Timeout:
        logger.warning(f"[Nature] Download timeout")
        return {"success": False, "error": "Timeout"}
    except requests.HTTPError as e:
        logger.warning(f"[Nature] HTTP error: {e}")
        return {"success": False, "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error(f"[Nature] Unexpected error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
