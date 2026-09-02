"""
从Unpaywall API获取PDF下载链接
"""

from typing import Optional
import requests
import logging
from configs.constants import UNPAYWALL_EMAIL

logger = logging.getLogger(__name__)


def get_unpaywall_url(doi: Optional[str]) -> Optional[str]:
    """
    从Unpaywall获取PDF链接

    Args:
        doi: 论文DOI

    Returns:
        PDF下载链接，若无则返回None

    API: https://api.unpaywall.org/v2/{doi}?email=YOUR_EMAIL
    """
    if not doi:
        return None

    try:
        url = f"https://api.unpaywall.org/v2/{doi}"
        params = {"email": UNPAYWALL_EMAIL}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if data.get("is_oa"):
            best_location = data.get("best_oa_location", {})
            pdf_url = best_location.get("url_for_pdf")
            if pdf_url:
                logger.debug(f"Found Unpaywall URL for {doi}")
                return pdf_url

        return None

    except Exception as e:
        logger.debug(f"Unpaywall query failed: {e}")
        return None
