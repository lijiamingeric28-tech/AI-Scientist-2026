"""
验证下载的文件是否为有效PDF
"""

import os
import logging
from configs.constants import MIN_FILE_SIZE, MAX_FILE_SIZE

logger = logging.getLogger(__name__)


def validate_pdf_file(file_path: str) -> bool:
    """
    验证PDF文件有效性

    Args:
        file_path: 文件路径

    Returns:
        是否有效（检查大小和PDF魔数）
    """
    try:
        if not os.path.exists(file_path):
            return False

        file_size = os.path.getsize(file_path)

        # 检查大小范围 (PDF应该至少10KB)
        if not (MIN_FILE_SIZE < file_size < MAX_FILE_SIZE):
            logger.warning(f"File size out of range: {file_size} bytes")
            return False

        # 检查PDF魔数 (文件必须以 %PDF- 开头)
        with open(file_path, 'rb') as f:
            header = f.read(5)
            if header != b'%PDF-':
                logger.warning(f"Invalid PDF header: {header[:20]}")
                return False

        # 检查PDF结束标记 (文件应该包含 %%EOF)
        with open(file_path, 'rb') as f:
            # 读取最后1KB
            f.seek(-min(1024, file_size), 2)
            tail = f.read()
            if b'%%EOF' not in tail:
                logger.warning(f"Missing PDF EOF marker")
                return False

        return True

    except Exception as e:
        logger.warning(f"Failed to validate file: {e}")
        return False
