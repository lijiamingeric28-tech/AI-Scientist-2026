"""结果汇总节点"""

import logging
from datetime import datetime

from ..state import RetrievalState

logger = logging.getLogger(__name__)


def result_aggregator(state: RetrievalState) -> RetrievalState:
    """
    结果汇总节点

    步骤：
    1. 汇总 SIMBAD 解析结果
    2. 汇总数据库查询结果
    3. 汇总论文检索结果
    4. 构建最终输出
    5. 记录统计信息

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    query_id = state["query_id"]
    target_entity = state["target_entity"]

    logger.info(f"[Result Aggregator] Query ID: {query_id}")
    logger.info("[Result Aggregator] Aggregating results...")

    # Step 1: 构建 SIMBAD 解析结果（已在 state 中）
    simbad_resolution = {
        "status": state.get("simbad_status", "failed"),
        "main_id": state.get("simbad_main_id"),
        "aliases": state.get("simbad_aliases", []),
        "object_type": state.get("simbad_object_type"),
        "coordinates": state.get("simbad_coordinates"),
        "resolved_at": state.get("simbad_resolved_at")
    }

    # Step 2: 构建数据库查询结果
    successful = state.get("successful_catalogs", []) or []
    failed = state.get("failed_catalogs", []) or []
    database_results = {
        "total_catalogs_queried": len(successful) + len(failed),
        "successful_catalogs": list(successful),
        "failed_catalogs": list(failed),
        "sources": state.get("database_sources", []),
        "records": state.get("database_records", [])
    }

    # Step 3: 构建论文检索结果
    # Phase 2 统一后子图 state 键为 download_paths（原 downloaded_papers）
    downloaded = state.get("download_paths", [])
    paper_results = {
        "total_papers_found": state.get("ads_total_found", 0),
        "downloaded_papers": len(downloaded),
        "failed_downloads": len(state.get("failed_downloads", [])),
        "search_metadata": {
            "search_query": state.get("ads_query_string"),
            "ads_query_string": state.get("ads_query_string"),
            "search_timestamp": datetime.now().isoformat()
        },
        "sources": state.get("paper_sources", []),
        "download_paths": downloaded
    }

    # Step 4: 记录完成时间
    state["retrieval_timestamp"] = datetime.now().isoformat()

    # Step 5: 打印统计信息
    # Step 5: 补充材料统计
    supp_sources = state.get("supplementary_sources", []) or []
    supp_records = state.get("supplementary_records", []) or []

    logger.info("[Result Aggregator] Completed!")
    logger.info("[Result Aggregator] === Summary ===")
    logger.info(f"[Result Aggregator]   SIMBAD: {simbad_resolution['status']}")
    logger.info(f"[Result Aggregator]   Database sources: {len(database_results['sources'])}")
    logger.info(f"[Result Aggregator]   Database records: {len(database_results['records'])}")
    logger.info(f"[Result Aggregator]   Papers found: {paper_results['total_papers_found']}")
    logger.info(f"[Result Aggregator]   Papers downloaded: {paper_results['downloaded_papers']}")
    logger.info(f"[Result Aggregator]   Supplementary tables: {len(supp_sources)}")
    logger.info(f"[Result Aggregator]   Supplementary records: {len(supp_records)}")

    # 打印错误日志摘要
    error_log = state.get("error_log", [])
    if error_log:
        logger.warning(f"[Result Aggregator]   Errors: {len(error_log)}")
        for error in error_log:
            logger.warning(f"[Result Aggregator]     - {error['node']}: {error['error']}")

    # 只返回更新的字段
    return {
        "retrieval_timestamp": state.get("retrieval_timestamp"),
        "supplementary_sources": supp_sources,
        "supplementary_records": supp_records,
    }
