"""Logger — 统一日志工厂（Phase 4d 收敛）

原实现按 logger 名添加 console + file handler，与 root basicConfig 并存
导致重复/缺失输出。现 re-export 统一工厂（astroquery_ai/logger.py），
保持 `from ..utils.logger import get_logger` 调用方式不变。
"""

from astroquery_ai.logger import get_logger

__all__ = ["get_logger"]
