"""
检查文件是否已存在且有效（断点续传）
"""

import os
import logging
from subgraphs.retrieval.tools.download.validate_pdf_file import validate_pdf_file

logger = logging.getLogger(__name__)


def check_existing_file(file_path: str) -> bool:
    """
    检查文件是否已存在且有效

    Args:
        file_path: 文件路径

    Returns:
        是否可跳过下载
    """
    if not os.path.exists(file_path):
        return False

    is_valid = validate_pdf_file(file_path)

    if is_valid:
        logger.debug(f"File already exists and is valid: {file_path}")

    return is_valid
