"""
从CORE API获取PDF下载链接
"""

from typing import Optional
import requests
import logging
from config.constants import CORE_API_KEY

logger = logging.getLogger(__name__)


def get_core_url(doi: Optional[str]) -> Optional[str]:
    """
    从CORE获取PDF链接

    Args:
        doi: 论文DOI

    Returns:
        PDF下载链接，若无则返回None

    API: https://api.core.ac.uk/v3/search/works?q=doi:{doi}
    """
    if not doi or not CORE_API_KEY:
        return None

    try:
        url = "https://api.core.ac.uk/v3/search/works"
        params = {
            "q": f"doi:{doi}",
            "apiKey": CORE_API_KEY
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if results:
            download_url = results[0].get("downloadUrl")
            if download_url:
                logger.debug(f"Found CORE URL for {doi}")
                return download_url

        return None

    except Exception as e:
        logger.debug(f"CORE query failed: {e}")
        return None
