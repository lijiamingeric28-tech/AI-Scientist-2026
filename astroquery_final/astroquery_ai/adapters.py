"""子图适配层

每个子图被包装成一个主图节点。包装节点承担三件事：

1. **投影输入**：从主图状态挑出子图需要的字段，按子图的键名传入
2. **映射输出**：把子图返回的扁平字段整理成主图的嵌套契约
3. **隔离失败**：子图抛异常时记录到 error_log 并返回可继续的降级状态，
   保证主图永远能走到 aggregation 出 JSON

为什么不直接 add_node(subgraph)
------------------------------
子图的状态键名与主图不一致（downloaded_papers vs download_paths，
original_query vs user_query），且子图 2 的嵌套输出结构原先只存在于它的
main.py:save_output() 里，从未进入 state。适配层把这些差异吸收掉，
使三个子图源码保持零改动。

error_log 与 add reducer
-----------------------
主图 error_log 用 Annotated[List, add]。包装节点只返回**本次新增**的条目，
不回传子图内部已累积的全量列表，否则 add 会重复累加。
"""

import logging
import time
from datetime import datetime
from typing import Dict, List

from .property_standardization import property_standardization_node
from .state import MainGraphState
from .subgraph1.graph import create_intent_clarification_subgraph
from .subgraph2.graph import create_retrieval_subgraph
from .subgraph3.graph import create_extraction_subgraph

logger = logging.getLogger(__name__)


_stage_times: Dict[str, float] = {}

def _timed(stage: str, start: float) -> None:
    """记录阶段耗时到全局字典中。"""
    elapsed = time.time() - start
    _stage_times[stage] = elapsed
    logger.info(f"[TIMER] {stage}: {elapsed:.1f}s")

def _err(node: str, exc: Exception) -> Dict:
    """构造一条标准错误日志"""
    return {
        "node": node,
        "error": f"{type(exc).__name__}: {exc}",
        "timestamp": datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════
# Node 1: 意图澄清
# ══════════════════════════════════════════════════════════════

def clarification_node(state: MainGraphState) -> Dict:
    """
    调用子图 1，把 user_query 澄清成结构化检索参数。

    输入投影：user_query -> original_query
    输出映射：target_entity / requested_properties / user_confirmed 等平铺上浮
    """
    t0 = time.time()
    logger.info("[Node 1] 意图澄清开始 query_id=%s", state.get("query_id"))

    # 如果 upstream 已注入澄清结果（如程序化调用），跳过交互子图
    if state.get("target_entity") and state.get("clarification_status") == "confirmed":
        logger.info("[Node 1] 已有 target_entity + confirmed，跳过澄清子图")
        return {
            "target_entity": state["target_entity"],
            "requested_properties": state.get("requested_properties", []),
            "entity_type_hint": state.get("entity_type_hint", "unknown"),
            "user_confirmed": True,
            "clarification_status": "confirmed",
            "query_type": state.get("query_type", "astronomical"),
            "conversation_history": state.get("conversation_history", []),
        }

    sub_input = {
        "original_query": state["user_query"],
        "query_id": state.get("query_id", ""),
    }

    try:
        subgraph = create_intent_clarification_subgraph()
        result = subgraph.invoke(sub_input)
    except Exception as exc:
        logger.exception("[Node 1] 子图执行失败")
        return {
            "user_confirmed": False,
            "clarification_status": "failed",
            "query_type": "astronomical",
            "target_entity": None,
            "requested_properties": [],
            "error_log": [_err("clarification_node", exc)],
        }

    out = {
        "target_entity": result.get("target_entity"),
        "requested_properties": result.get("requested_properties", []),
        "entity_type_hint": result.get("entity_type_hint", "unknown"),
        "user_confirmed": result.get("user_confirmed", False),
        "clarification_status": result.get("clarification_status", "confirmed"),
        "query_type": result.get("query_type", "astronomical"),
        "conversation_history": result.get("conversation_history", []),
    }

    logger.info(
        "[Node 1] 完成 entity=%s properties=%s status=%s",
        out["target_entity"], out["requested_properties"], out["clarification_status"],
    )
    return out


# ══════════════════════════════════════════════════════════════
# P1: 性质标准化（SIMBAD + RAG + LLM）
# ══════════════════════════════════════════════════════════════

def property_standardization_adapter(state: MainGraphState) -> Dict:
    """
    P1 适配器：调用性质标准化节点

    输入：target_entity, user_query, requested_properties
    输出：simbad_info, property_spec, target_schema
    """
    logger.info("[P1 Adapter] 性质标准化开始")

    try:
        result = property_standardization_node(state)
    except Exception as exc:
        logger.exception("[P1 Adapter] 执行失败")
        return {
            "error_log": [_err("property_standardization", exc)],
        }

    # 错误检查
    if "error_log" in result:
        logger.warning("[P1 Adapter] 性质标准化失败，返回错误")
        return result

    logger.info(
        "[P1 Adapter] 完成 main_id=%s otype=%s properties=%d",
        result.get("simbad_info", {}).get("main_id", "?"),
        result.get("simbad_info", {}).get("otype", "?"),
        len(result.get("property_spec", []))
    )

    return result


# ══════════════════════════════════════════════════════════════
# Node 2: 并行检索
# ══════════════════════════════════════════════════════════════

def _empty_retrieval() -> Dict:
    """检索失败时的空壳结构，保证下游键存在"""
    return {
        "database_results": {
            "total_catalogs_queried": 0,
            "successful_catalogs": [],
            "failed_catalogs": [],
            "sources": [],
            "records": [],
        },
        "paper_results": {
            "total_papers_found": 0,
            "downloaded_papers": 0,
            "failed_downloads": 0,
            "search_metadata": {},
            "sources": [],
            "download_paths": [],
        },
        "simbad_info": {"status": "failed", "main_id": None, "aliases": []},
        "retrieval_timestamp": datetime.now().isoformat(),
    }


def retrieval_node(state: MainGraphState) -> Dict:
    """
    调用子图 2，并把它的扁平状态组装成主图的嵌套契约。

    这里承接了原 subgraph2/main.py:save_output() 的组装逻辑 —— 子图的
    result_aggregator 只返回 retrieval_timestamp，嵌套结构必须在此重建。

    关键改名：downloaded_papers(list) -> paper_results.download_paths
              以对齐子图 3 的输入契约。
    """
    logger.info("[Node 2] 并行检索开始 entity=%s", state.get("target_entity"))

    # 从 P1 的 simbad_info 构建子图 2 所需的 simbad_* 字段
    # （原来由 simbad_resolver 二次查询产出，B2 收敛后直接从 P1 映射）
    p1_simbad = state.get("simbad_info") or {}
    sub_input = {
        "query_id": state.get("query_id", ""),
        "target_entity": state.get("target_entity") or "",
        "requested_properties": state.get("requested_properties", []),
        "property_spec": state.get("property_spec", []),
        "simbad_info": p1_simbad,
        # 从 P1 直接映射 → 不再需要 simbad_resolver 二次查询
        "simbad_status": "success" if p1_simbad.get("main_id") else "failed",
        "simbad_main_id": p1_simbad.get("main_id"),
        "simbad_aliases": p1_simbad.get("ALIASES", []),
        "simbad_object_type": p1_simbad.get("otype"),
        "simbad_coordinates": (
            {"ra": p1_simbad.get("ra") or p1_simbad.get("RA_ICRS"),
             "dec": p1_simbad.get("dec") or p1_simbad.get("DEC_ICRS"),
             "frame": "ICRS", "epoch": "J2000"}
            if (p1_simbad.get("ra") or p1_simbad.get("RA_ICRS")) else None
        ),
        "simbad_resolved_at": datetime.now().isoformat(),
    }

    try:
        subgraph = create_retrieval_subgraph()
        r = subgraph.invoke(sub_input)
    except Exception as exc:
        logger.exception("[Node 2] 子图执行失败")
        fallback = _empty_retrieval()
        fallback["error_log"] = [_err("retrieval_node", exc)]
        return fallback

    downloaded = r.get("downloaded_papers", [])

    out = {
        "database_results": {
            "total_catalogs_queried": (
                len(r.get("successful_catalogs", [])) + len(r.get("failed_catalogs", []))
            ),
            "successful_catalogs": r.get("successful_catalogs", []),
            "failed_catalogs": r.get("failed_catalogs", []),
            "sources": r.get("database_sources", []),
            "records": r.get("database_records", []),
        },
        "paper_results": {
            "total_papers_found": r.get("ads_total_found", 0),
            "downloaded_papers": len(downloaded),
            "failed_downloads": len(r.get("failed_downloads", [])),
            "search_metadata": {
                "search_query": r.get("ads_query_string"),
                "ads_query_string": r.get("ads_query_string"),
                "search_timestamp": r.get("retrieval_timestamp"),
            },
            "sources": r.get("paper_sources", []),
            # ↓ 契约改名：子图2 downloaded_papers -> 子图3 download_paths
            "download_paths": downloaded,
        },
        # B3 fix: 合并而非覆盖——保留 P1 的 OTYPES / SP_TYPE / RA / DEC
        "simbad_info": {
            **p1_simbad,  # P1 原始字段（main_id, otype, otypes, sp_type, ra, dec, ALIASES）
            "status": r.get("simbad_status", "failed"),
            "main_id": r.get("simbad_main_id"),
            "aliases": r.get("simbad_aliases", []),
            "object_type": r.get("simbad_object_type"),
            "coordinates": r.get("simbad_coordinates"),
            "resolved_at": r.get("simbad_resolved_at"),
        },
        "supplementary_sources": r.get("supplementary_sources", []),
        "supplementary_records": r.get("supplementary_records", []),
        "retrieval_timestamp": r.get("retrieval_timestamp") or datetime.now().isoformat(),
    }

    # 只上浮子图内部产生的错误（子图 error_log 是独立通道，不会重复累加）
    if r.get("error_log"):
        out["error_log"] = list(r["error_log"])

    logger.info(
        "[Node 2] 完成 db_records=%d db_sources=%d papers_downloaded=%d supp_records=%d",
        len(out["database_results"]["records"]),
        len(out["database_results"]["sources"]),
        len(downloaded),
        len(out["supplementary_records"]),
    )
    return out
# ══════════════════════════════════════════════════════════════
# Node 3: 多模态提取
# ══════════════════════════════════════════════════════════════

def _merge_extra_pdfs(download_paths: List[Dict], extra_pdfs: List[str]) -> List[Dict]:
    """
    把用户手动上传的 PDF 合并进 download_paths。

    手动 PDF 没有 bibcode，用 "USER_UPLOAD_{序号}" 作为合成标识，
    使其在 records 的 source_id 里可追溯。
    """
    from pathlib import Path

    merged = list(download_paths)
    seen = {Path(d.get("local_path", "")).resolve() for d in merged if d.get("local_path")}

    for i, p in enumerate(extra_pdfs or []):
        path = Path(p).expanduser().resolve()
        if not path.exists():
            logger.warning("[Node 3] 手动 PDF 不存在，跳过: %s", p)
            continue
        if path in seen:
            continue
        seen.add(path)
        merged.append({
            "bibcode": f"USER_UPLOAD_{i + 1}",
            "local_path": str(path),
            "file_size_mb": round(path.stat().st_size / (1024 * 1024), 3),
            "download_source": "user_upload",
        })
    return merged


def extraction_node(state: MainGraphState) -> Dict:
    """
    调用子图 3，从 PDF 抽取带 bbox 的 records。

    输入投影：paper_results.download_paths + extra_pdfs -> download_paths
             paper_results.sources -> paper_sources（子图声明为必填）
    输出映射：paper_records / processing_summary
    """
    paper_results = state.get("paper_results") or {}
    download_paths = _merge_extra_pdfs(
        paper_results.get("download_paths", []),
        state.get("extra_pdfs", []),
    )

    logger.info("[Node 3] 多模态提取开始 pdf_count=%d", len(download_paths))

    sub_input = {
        "query_id": state.get("query_id", ""),
        "target_entity": state.get("target_entity") or "",
        "entity_type": (state.get("simbad_info") or {}).get("object_type") or "Unknown",
        "requested_properties": state.get("requested_properties", []),
        "property_spec": state.get("property_spec", []),  # 新增
        "paper_sources": paper_results.get("sources", []),
        "download_paths": download_paths,
    }

    try:
        subgraph = create_extraction_subgraph()
        r = subgraph.invoke(sub_input)
    except Exception as exc:
        logger.exception("[Node 3] 子图执行失败")
        return {
            "paper_records": [],
            "processing_summary": {
                "total_papers": len(download_paths),
                "processed_papers": 0,
                "failed_papers": len(download_paths),
                "total_records_extracted": 0,
            },
            "error_log": [_err("extraction_node", exc)],
        }

    out = {
        "paper_records": r.get("paper_records", []),
        "processing_summary": r.get("processing_summary", {}),
    }
    if r.get("error_log"):
        out["error_log"] = list(r["error_log"])

    logger.info("[Node 3] 完成 paper_records=%d", len(out["paper_records"]))
    return out


def skip_extraction_node(state: MainGraphState) -> Dict:
    """
    跳过 Node 3 时的占位节点。

    保证 paper_records / processing_summary 键始终存在，
    使 final_aggregator 无需做特殊分支。
    """
    logger.info("[Node 3] 无可用 PDF，跳过多模态提取")
    return {
        "paper_records": [],
        "processing_summary": {
            "total_papers": 0,
            "processed_papers": 0,
            "failed_papers": 0,
            "total_records_extracted": 0,
            "skipped": True,
            "skip_reason": "no_pdf_available",
        },
    }

