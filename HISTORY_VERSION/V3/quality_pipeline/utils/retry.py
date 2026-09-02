"""
retry.py

重试装饰器，支持最大重试次数、间隔、指数退避。
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

from ..utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_failure(
    max_retries: int = 3,
    delay_seconds: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    装饰器：函数执行失败时自动重试。

    Args:
        max_retries: 最大重试次数（不含首次执行）。
        delay_seconds: 首次重试前的等待秒数。
        backoff_factor: 指数退避因子。第 n 次重试延迟 = delay * backoff^(n-1)。
        exceptions: 需要重试的异常类型元组。

    Returns:
        装饰后的函数。

    Usage:
        @retry_on_failure(max_retries=3, delay_seconds=1.0)
        def unstable_func():
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait = delay_seconds * (backoff_factor ** attempt)
                        logger.warning(
                            "[%s] 执行失败 (attempt %d/%d): %s。%s 秒后重试...",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            e,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "[%s] 已达最大重试次数 (%d)，最终失败: %s",
                            func.__name__,
                            max_retries,
                            e,
                        )

            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
