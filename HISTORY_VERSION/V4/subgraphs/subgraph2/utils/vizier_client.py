"""VizieR 共享客户端——多镜像 fallback + 快速失败

背景（2026-08 调研）：CDS/VizieR 服务间歇性高负载（SIMBAD TAP 与
vizier.cfa.harvard.edu 均出现 30s read timeout）。官方镜像轮询可避开单点故障。

镜像优先级：
1. vizier.cfa.harvard.edu   （美国哈佛，当前默认，负载高）
2. vizier.nao.ac.jp         （日本国立天文台，亚洲区稳定）
3. vizier.ast.cam.ac.uk     （英国剑桥）
4. vizier.u-strasbg.fr      （法国主站）

设计：
- 每次查询携带 fallback 镜像列表，当前镜像 ReadTimeout/连接失败 → 切下一个
- 单次超时 10s（原 30s），避免最坏 N×30s 死等
- 连续失败计数（熔断）：一次查询内超过镜像数 × 尝试次数后抛异常，由调用方降级
"""

import logging
from typing import Callable, List

from astroquery.vizier import Vizier

logger = logging.getLogger(__name__)

# 官方镜像（按优先级排序）
VIZIER_MIRRORS: List[str] = [
    "vizier.cfa.harvard.edu",
    "vizier.nao.ac.jp",
    "vizier.ast.cam.ac.uk",
    "vizier.u-strasbg.fr",
]

# 单次查询超时（秒）——原 30s 太长，镜像切换本身比死等更快
DEFAULT_TIMEOUT = 10

# 每个镜像上单次查询的尝试次数（瞬时抖动重试）
ATTEMPTS_PER_MIRROR = 1


def create_vizier(mirror: str = None, row_limit: int = 10, timeout: int = DEFAULT_TIMEOUT) -> Vizier:
    """创建指向指定镜像的 Vizier 实例"""
    v = Vizier(columns=['**'], row_limit=row_limit, timeout=timeout)
    v.VIZIER_SERVER = mirror or VIZIER_MIRRORS[0]
    return v


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否可通过切换镜像重试（超时/连接错误/服务端 5xx/限流 429）"""
    import socket
    from requests.exceptions import ConnectionError, HTTPError, ReadTimeout
    if isinstance(exc, (ReadTimeout, ConnectionError, socket.timeout)):
        return True
    # M-23: astroquery 对非 2xx 响应 raise_for_status 抛 HTTPError——
    # CDS/VizieR 间歇性高负载最典型表现是 502/503/504 快速返回，应切换镜像重试；
    # 4xx（语法错误/表不存在）直接抛出，切换镜像无意义
    if isinstance(exc, HTTPError):
        resp = getattr(exc, "response", None)
        status = resp.status_code if resp is not None else None
        if status is not None and (status >= 500 or status == 429):
            return True
    name = type(exc).__name__.lower()
    return 'timeout' in name or 'connection' in name or 'econn' in name


def query_with_fallback(
    query_func: Callable[[Vizier], object],
    row_limit: int = 10,
    timeout: int = DEFAULT_TIMEOUT,
    mirrors: List[str] = None,
) -> object:
    """
    带镜像 fallback 的 VizieR 查询。

    Args:
        query_func: 接收 Vizier 实例并执行查询的可调用对象
        row_limit: 行数上限（透传给 create_vizier）
        timeout: 单次超时秒数
        mirrors: 镜像列表（默认 VIZIER_MIRRORS）

    Returns:
        query_func 的返回结果

    Raises:
        所有镜像都失败时抛出最后一个异常
    """
    mirrors = mirrors or VIZIER_MIRRORS
    last_exc = None

    for mirror in mirrors:
        for attempt in range(1, ATTEMPTS_PER_MIRROR + 1):
            try:
                v = create_vizier(mirror, row_limit=row_limit, timeout=timeout)
                result = query_func(v)
                # 切换回默认镜像（若当前不是），避免长时间占用非默认镜像
                return result
            except Exception as e:
                last_exc = e
                if _is_retryable(e):
                    logger.warning(
                        f"[VizieR] {mirror} 查询失败 (attempt {attempt}): {e} → 切换镜像"
                    )
                    break  # 尝试下一个镜像
                # 非可重试错误（语法错误等）直接抛出，切换镜像无意义
                raise

    logger.error(f"[VizieR] 全部镜像失败 ({len(mirrors)} 个): {last_exc}")
    raise last_exc
