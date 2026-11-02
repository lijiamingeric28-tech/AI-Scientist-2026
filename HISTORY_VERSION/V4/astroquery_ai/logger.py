"""统一日志工厂（Phase 4d 收敛）

历史：三套并行日志系统互相打架——
  1. run.py 的 basicConfig（入口配置）
  2. quality_pipeline/utils/logger.py 的 setup_logging(force=True)（重置所有 handler）
  3. subgraph3/utils/logger.py 按 logger 名添加 console + file handler（重复输出）

现在：唯一工厂 + 幂等入口配置。
- get_logger(name)：纯 logging.getLogger，不附加 handler（避免重复输出）
- setup_logging()：入口调用一次，幂等（重复调用不重置已有 handler）
"""

import logging
import sys
from typing import Optional

# 默认格式（与 run.py 历史一致）
_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT = "%H:%M:%S"

# 第三方库降噪名单（入口配置时统一处理）
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "PIL", "openai")


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 logger（不附加 handler，交由入口 basicConfig 统一输出）。"""
    return logging.getLogger(name)


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    verbose: bool = False,
) -> None:
    """
    初始化全局日志配置（幂等——重复调用不重置已有 handler）。

    Args:
        level: 日志级别。
        log_file: 可选的文件路径，同时输出到文件。
        verbose: 是否输出 DEBUG 日志。
    """
    if verbose:
        level = logging.DEBUG

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=_DEFAULT_FORMAT,
        datefmt=_DEFAULT_DATE_FORMAT,
        handlers=handlers,
    )

    # 第三方库降噪
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
