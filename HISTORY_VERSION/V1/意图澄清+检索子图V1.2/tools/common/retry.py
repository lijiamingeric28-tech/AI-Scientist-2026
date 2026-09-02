"""
重试装饰器

用于API调用和LLM调用的自动重试
"""

from functools import wraps
import time
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


def retry_on_failure(
    max_attempts: int = 2,
    timeout: int = 30,
    backoff_factor: float = 2.0
):
    """
    重试装饰器

    Args:
        max_attempts: 最大尝试次数
        timeout: 单次调用超时（秒）
        backoff_factor: 退避因子（每次重试等待时间翻倍）

    Usage:
        @retry_on_failure(max_attempts=3, timeout=10)
        def some_function():
            # 可能失败的操作
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    logger.debug(f"Attempt {attempt}/{max_attempts}: {func.__name__}")
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e
                    logger.warning(f"Attempt {attempt} failed: {e}")

                    if attempt < max_attempts:
                        wait_time = backoff_factor ** (attempt - 1)
                        logger.debug(f"Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_attempts} attempts failed")

            # 所有尝试都失败，抛出最后一个异常
            raise last_exception

        return wrapper
    return decorator
