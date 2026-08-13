"""
logger.py — 统一日志工厂（Phase 4d 收敛）

原实现带 force=True 重置 handler 的 setup_logging，会覆盖入口配置。
现 re-export 统一工厂（astroquery_ai/logger.py），保持
`from ...utils.logger import get_logger` 调用方式不变。
"""

from astroquery_ai.logger import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging"]
