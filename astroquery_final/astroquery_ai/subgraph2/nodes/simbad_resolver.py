"""SIMBAD 名称解析节点"""

import time
import logging
from datetime import datetime
from astroquery.simbad import Simbad

from ..state import RetrievalState
from ..config import config

logger = logging.getLogger(__name__)


def simbad_resolver(state: RetrievalState) -> RetrievalState:
    """
    SIMBAD 名称解析节点

    步骤：
    1. 配置 SIMBAD 查询引擎
    2. 执行查询（带重试机制）
    3. 解析结果（主ID、别名、类型、坐标）
    4. 更新状态

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    target_entity = state["target_entity"]
    query_id = state["query_id"]

    logger.info(f"[SIMBAD Resolver] Query ID: {query_id}")
    logger.info(f"[SIMBAD Resolver] Target: {target_entity}")

    # Step 1: 配置 SIMBAD 引擎（简化，只请求必要字段）
    simbad_engine = Simbad()
    # 只添加别名和类型，避免过多字段导致查询失败
    simbad_engine.add_votable_fields('ids', 'otype')

    # 设置超时
    simbad_engine.TIMEOUT = config.retrieval['simbad']['timeout']

    # Step 2: 执行查询（带重试）
    simbad_res = None
    max_retries = config.retrieval['simbad']['max_retries']
    retry_backoff = config.retrieval['simbad']['retry_backoff']

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[SIMBAD Resolver] Attempt {attempt}/{max_retries}")
            simbad_res = simbad_engine.query_object(target_entity)

            if simbad_res is not None:
                logger.info(f"[SIMBAD Resolver] Query successful")
                break

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"[SIMBAD Resolver] Attempt {attempt} failed: {error_msg}")

            if attempt < max_retries:
                wait_time = attempt * retry_backoff  # 退避等待
                logger.info(f"[SIMBAD Resolver] Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                # 3次重试全部失败
                logger.error(f"[SIMBAD Resolver] All {max_retries} attempts failed")
                # 只返回本节点更新的字段：error_log 是 Annotated[list, add]，
                # 返回整个 state 会把已累积的条目重复累加一次。
                return {
                    "simbad_status": "failed",
                    "error_log": [{
                        "node": "simbad_resolver",
                        "error": f"SIMBAD query failed after {max_retries} attempts: {error_msg}",
                        "timestamp": datetime.now().isoformat()
                    }]
                }

    # Step 3: 解析结果
    if simbad_res is None or len(simbad_res) == 0:
        logger.error(f"[SIMBAD Resolver] No results found for {target_entity}")
        return {
            "simbad_status": "failed",
            "error_log": [{
                "node": "simbad_resolver",
                "error": f"No SIMBAD results for '{target_entity}'",
                "timestamp": datetime.now().isoformat()
            }]
        }

    row = simbad_res[0]

    # 提取别名 - 字段名是小写的 'ids'
    aliases = []
    if 'ids' in row.colnames and row['ids']:
        # ids字段包含用 | 分隔的别名列表
        ids_str = str(row['ids'])
        if ids_str and ids_str.lower() not in ('nan', '--', 'none'):
            aliases = [alias.strip() for alias in ids_str.split('|') if alias.strip()]

    # 提取主ID - 字段名是小写的 'main_id'
    main_id = str(row['main_id']).strip() if 'main_id' in row.colnames else None

    # 提取天体类型 - 字段名是小写的 'otype'
    object_type = str(row['otype']).strip() if 'otype' in row.colnames else None

    # 提取坐标 - 字段名是小写的 'ra', 'dec'
    coordinates = None
    if 'ra' in row.colnames and 'dec' in row.colnames:
        try:
            coordinates = {
                "ra": float(row['ra']),
                "dec": float(row['dec']),
                "frame": "ICRS",
                "epoch": "J2000"
            }
        except (ValueError, TypeError) as e:
            logger.warning(f"[SIMBAD Resolver] Failed to parse coordinates: {e}")

    # Step 4: 更新状态
    state["simbad_status"] = "success"
    state["simbad_main_id"] = main_id
    state["simbad_aliases"] = aliases
    state["simbad_object_type"] = object_type
    state["simbad_coordinates"] = coordinates
    state["simbad_resolved_at"] = datetime.now().isoformat()

    logger.info(f"[SIMBAD Resolver] Success!")
    logger.info(f"[SIMBAD Resolver]   Main ID: {main_id}")
    logger.info(f"[SIMBAD Resolver]   Type: {object_type}")
    logger.info(f"[SIMBAD Resolver]   Aliases: {len(aliases)} found")

    # 只返回更新的字段
    return {
        "simbad_status": state.get("simbad_status"),
        "simbad_main_id": state.get("simbad_main_id"),
        "simbad_aliases": state.get("simbad_aliases", []),
        "simbad_object_type": state.get("simbad_object_type"),
        "simbad_coordinates": state.get("simbad_coordinates"),
        "simbad_resolved_at": state.get("simbad_resolved_at")
    }
