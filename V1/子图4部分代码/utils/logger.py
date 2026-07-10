"""
logger.py

统一日志配置。所有模块通过 `get_logger(__name__)` 获取 logger 实例。
"""

from __future__ import annotations

import logging
import sys
from typing import Optional


# 全局日志级别（可通过环境变量覆盖）
_DEFAULT_LEVEL = logging.INFO

# 日志格式
_FORMAT = (
    "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = _DEFAULT_LEVEL,
    log_file: Optional[str] = None,
) -> None:
    """
    初始化全局日志配置。

    Args:
        level: 日志级别。
        log_file: 可选的文件路径，同时输出到文件。
    """
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=_FORMAT,
        datefmt=_DATE_FORMAT,
        handlers=handlers,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 logger。

    Args:
        name: 通常使用 __name__。

    Returns:
        logging.Logger 实例。
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # 避免重复添加 handler
        logger.setLevel(_DEFAULT_LEVEL)
    return logger
