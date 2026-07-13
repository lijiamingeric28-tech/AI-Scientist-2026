"""
metadata_generator.py — Tool 4: MetadataGenerator

生成数据元信息: 字段定义/描述 + 来源汇总 + 处理记录。
"""
from __future__ import annotations
import datetime
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def generate_metadata(
    current_data: dict[str, Any],
    target_schema: dict[str, Any] | None,
    report_state: dict[str, Any],
    context_state: dict[str, Any],
    run_id: str = "",
) -> dict[str, Any]:
    """生成元数据。

    Returns: {field_definitions, source_summary, processing_record, run_info}
    """
    sources = current_data.get("sources", [])
    records = current_data.get("records", [])
    quality = report_state.get("quality") or {}
    normalization = report_state.get("normalization") or {}
    conflict = report_state.get("conflict") or {}
    resolution_report = conflict.get("resolution_report", {})

    # ── 1. Field Definitions ──
    field_definitions: dict[str, dict] = {}
    profile = quality.get("profile", {})
    semantic_types = profile.get("semantic_types", {})

    if target_schema:
        for f in target_schema.get("fields", []):
            name = f.get("name", "")
            if not name:
                continue
            st = semantic_types.get(name, {})
            st_type = st.get("semantic_type", "") if isinstance(st, dict) else str(st)
            field_definitions[name] = {
                "standard_unit": f.get("standard_unit"),
                "semantic_type": st_type,
                "criticality": f.get("criticality", "important"),
                "aliases": f.get("aliases", []),
                "description": "",  # LLM 填充
            }

    # 为不在 schema 中的字段也从 semantic_types 推断
    for fn, st in semantic_types.items():
        if fn not in field_definitions:
            st_type = st.get("semantic_type", "") if isinstance(st, dict) else str(st)
            field_definitions[fn] = {
                "standard_unit": st.get("standard_unit") if isinstance(st, dict) else None,
                "semantic_type": st_type,
                "criticality": "auxiliary",
                "is_extra_field": True,
            }

    # ── 2. Source Summary ──
    per_source = []
    quality_sources = quality.get("sources", {})
    per_source_routes = quality.get("per_source_routes", {})

    for s in sources:
        sid = s.get("source_id", "")
        qs = quality_sources.get(sid, {})
        rec_count = len([r for r in records if r.get("source_id") == sid])
        per_source.append({
            "source_id": sid,
            "title": s.get("title", ""),
            "year": s.get("year"),
            "journal": s.get("journal", ""),
            "record_count": rec_count,
            "quality_grade": qs.get("quality_scoring", {}).get("quality_level", "unknown"),
            "final_route": per_source_routes.get(sid, "Export"),
        })

    # ── 3. Processing Record ──
    processing = {
        "assessment": {
            "status": "Completed",
            "sources_assessed": quality.get("source_count", 0),
            "overall_quality": quality.get("quality_scoring", {}).get("quality_level", "unknown"),
            "total_issues": quality.get("total_issues", 0),
        },
    }

    if normalization:
        mods = normalization.get("modifications", {})
        processing["normalization"] = {
            "status": normalization.get("normalization_status", "Completed"),
            "modifications": mods.get("total", 0),
            "by_layer": mods.get("by_layer", {}),
            "errors": len(mods.get("errors", [])),
        }
    else:
        processing["normalization"] = {"status": "Skipped"}

    if resolution_report:
        processing["conflict"] = {
            "status": resolution_report.get("status", "Unknown"),
            "total_conflicts": resolution_report.get("metadata", {}).get("total_conflicts", 0),
            "auto_resolved": resolution_report.get("metadata", {}).get("auto_resolved", 0),
            "human_required": resolution_report.get("metadata", {}).get("human_required", 0),
        }
    elif conflict.get("identification"):
        processing["conflict"] = {"status": "Partially_Analyzed"}
    else:
        processing["conflict"] = {"status": "Skipped"}

    # ── 4. Run Info ──
    run_info = {
        "generated_at": datetime.datetime.now().isoformat(),
        "run_id": run_id,
        "graph_version": "V2.1",
        "research_domain": context_state.get("research_domain", "unknown"),
    }

    logger.info("[MetadataGenerator] %d fields, %d sources, %d processing stages",
                len(field_definitions), len(per_source),
                sum(1 for v in processing.values() if v.get("status") != "Skipped"))

    return {
        "field_definitions": field_definitions,
        "source_summary": {
            "total_sources": len(sources),
            "sources_exported": len(sources),
            "sources_human_review": 0,
            "per_source": per_source,
        },
        "processing_record": processing,
        "run_info": run_info,
    }
