"""最终聚合节点

产出下游消费的唯一结构：

    {
      "schema_version": "2.0.0",
      "sources": [ ...db_sources, ...paper_sources ],
      "records": [ ...db_records, ...paper_records ]
    }

设计约束
--------
1. **不改写字段名**。数据库 records 保持子图 2 的原始字段名，论文 records
   保持子图 3 的原始字段名（含 bbox）。下游按 source_id 关联，不需要两边同构。

2. **永远出 JSON**。任何降级路径（用户取消、检索失败、无 PDF）都走到这里，
   顶层键集合恒定，只是数组可能为空。

3. **悬空 source_id 检查**。records 里引用的 source_id 若不在 sources 中，
   记入 error_log 但不阻断输出 —— 让下游能看到数据，同时暴露问题。
"""

import logging
from datetime import datetime
from typing import Dict

from .config import get_settings
from .state import MainGraphState

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0.0"


def final_aggregator(state: MainGraphState) -> Dict:
    """拼装最终输出"""
    db = state.get("database_results") or {}
    papers = state.get("paper_results") or {}

    db_sources = db.get("sources", []) or []
    db_records = db.get("records", []) or []
    paper_sources = papers.get("sources", []) or []
    paper_records = state.get("paper_records", []) or []
    supp_sources = state.get("supplementary_sources", []) or []
    supp_records = state.get("supplementary_records", []) or []
    figure_evidence = state.get("figure_evidence", []) or []

    # ── 只保留有产物的 source（2026-08-11 用户决策）：数据库/补充有 records、
    # 论文有 records 或 figure_evidence——0 产物的来源不进最终输出（不干净），
    # 且不再拖低质量管线的完整性评分。records 的 source_id 关联天然闭合。──
    db_ids_with_data = {r.get("source_id") for r in db_records}
    supp_ids_with_data = {r.get("source_id") for r in supp_records}
    paper_ids_with_data = {r.get("source_id") for r in paper_records}
    paper_ids_with_fig = {f.get("source_id") for f in figure_evidence}
    db_sources = [s for s in db_sources if s.get("source_id") in db_ids_with_data]
    supp_sources = [s for s in supp_sources if s.get("source_id") in supp_ids_with_data]
    paper_sources = [
        s for s in paper_sources
        if s.get("source_id") in (paper_ids_with_data | paper_ids_with_fig)
    ]

    # ── 拼装：数据库在前，论文在后，补充材料最后，均保留原始字段名 ──
    sources = [*db_sources, *paper_sources, *supp_sources]
    records = [*db_records, *paper_records, *supp_records]

    # ── 构造 final_output（补全 research_domain / simbad_info / error_log）──
    final_output = {
        "schema_version": SCHEMA_VERSION,
        "research_domain": get_settings().default_research_domain,  # M4: 补充领域标识
        "query_metadata": {
            "query_id": state.get("query_id", ""),
            "user_query": state.get("user_query", ""),
            "target_entity": state.get("target_entity", ""),
            "requested_properties": state.get("requested_properties", []),
            "retrieval_timestamp": state.get("retrieval_timestamp") or datetime.now().isoformat(),
        },
        "simbad_info": state.get("simbad_info", {}),  # M5: 补充 SIMBAD 解析结果
        "sources": sources,
        "records": records,
        # Figure 证据（独立通路，直接展示用，不进质量管线）
        "figure_evidence": state.get("figure_evidence", []) or [],
    }

    # ── 悬空 source_id 检查（非阻断）──
    errors = state.get("error_log", []) or []  # M6: 继承上游错误日志
    known_ids = {s.get("source_id") for s in sources if s.get("source_id")}
    dangling = sorted({
        r.get("source_id") for r in records
        if r.get("source_id") and r.get("source_id") not in known_ids
    })
    if dangling:
        preview = dangling[:10]
        logger.warning(
            "[Final Aggregator] 发现 %d 个悬空 source_id: %s%s",
            len(dangling), preview, " ..." if len(dangling) > 10 else "",
        )
        errors.append({
            "node": "final_aggregator",
            "error": (
                f"{len(dangling)} 个 record 引用了不存在的 source_id: {preview}"
            ),
            "timestamp": datetime.now().isoformat(),
        })

    logger.info(
        "[Final Aggregator] 输出完成 sources=%d (db=%d, paper=%d, supp=%d) "
        "records=%d (db=%d, paper=%d, supp=%d)",
        len(sources), len(db_sources), len(paper_sources), len(supp_sources),
        len(records), len(db_records), len(paper_records), len(supp_records),
    )

    # M6: error_log 始终存在（空列表或带错误）
    final_output["error_log"] = errors
    return {"final_output": final_output}
