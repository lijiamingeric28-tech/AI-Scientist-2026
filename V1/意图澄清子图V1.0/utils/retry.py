"""
重试装饰器
"""
import time
import functools
from typing import Callable, Type, Tuple
import logging

logger = logging.getLogger(__name__)


def retry_on_failure(
    max_attempts: int = 2,
    timeout: int = 30,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    backoff: float = 0.0
) -> Callable:
    """
    重试装饰器

    Args:
        max_attempts: 最大尝试次数（包含首次）
        timeout: 单次调用超时时间（秒）
        exceptions: 需要重试的异常类型
        backoff: 重试间隔（秒），0表示立即重试

    Returns:
        装饰器函数

    Example:
        @retry_on_failure(max_attempts=2, timeout=30)
        def generate_schema(query: str) -> dict:
            return call_llm_structured(...)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    logger.debug(f"[{func.__name__}] Attempt {attempt}/{max_attempts}")

                    # 执行函数
                    result = func(*args, **kwargs)

                    if attempt > 1:
                        logger.info(f"[{func.__name__}] Succeeded on attempt {attempt}")

                    return result

                except exceptions as e:
                    last_exception = e
                    logger.warning(
                        f"[{func.__name__}] Attempt {attempt}/{max_attempts} failed: {e}"
                    )

                    # 如果还有重试机会，等待后重试
                    if attempt < max_attempts:
                        if backoff > 0:
                            logger.debug(f"Waiting {backoff}s before retry...")
                            time.sleep(backoff)
                    else:
                        # 最后一次失败，抛出异常
                        logger.error(
                            f"[{func.__name__}] All {max_attempts} attempts failed"
                        )
                        raise last_exception

            # 理论上不会到这里
            raise last_exception

        return wrapper
    return decorator
