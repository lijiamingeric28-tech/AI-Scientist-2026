"""
conflict_extractor.py — Tool 1: ConflictExtractor

从 Quality Report 或 Normalization Report 中提取冲突列表，
去重、排序、分配唯一 ID。
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def extract_conflicts(
    quality_report: dict[str, Any] | None,
    normalization_report: dict[str, Any] | None,
    trigger_path: str,
) -> dict[str, Any]:
    """
    从上游报告中提取和汇总冲突列表。

    Args:
        quality_report: Assessment 的 quality report (A→C 路径)
        normalization_report: Normalization 的 report (B→C 路径)
        trigger_path: "A→C" 或 "B→C"

    Returns:
        {trigger_path, total_conflicts, conflicts, involved_sources, involved_fields, summary}
    """
    raw_conflicts: list[dict] = []

    if trigger_path == "A→C" and quality_report:
        sources = quality_report.get("sources", {})
        for sid, src in sources.items():
            conflict_risk = src.get("conflict_risk", {})
            for c in conflict_risk.get("conflicts", []):
                c["_source_path"] = "A→C"
                raw_conflicts.append(c)

    elif trigger_path == "B→C" and normalization_report:
        validation = normalization_report.get("validation", {})
        conflict_check = validation.get("conflict_check", {})
        for c in conflict_check.get("conflicts", []):
            c["_source_path"] = "B→C"
            # ── V2.2 fix: 从正确的结构读取已修改字段 ──
            # modifications 结构: {total, by_layer: {base, adapted, generated},
            #                       details: {base:[...], adapted:[...], generated:[...]},
            #                       per_source: {sid: {total, tools:[...]}}}
            modifications = normalization_report.get("modifications", {})
            modified_fields = set()
            # 从 details 中各层的 log 提取 modified field
            details = modifications.get("details", {})
            for layer_name in ("base", "adapted", "generated"):
                layer_logs = details.get(layer_name, [])
                if isinstance(layer_logs, list):
                    for entry in layer_logs:
                        if isinstance(entry, dict):
                            field = entry.get("field", entry.get("field_name", ""))
                            if field:
                                modified_fields.add(field)
            # 也从 conversion_log / mapping_log 提取
            for layer_name in ("base", "adapted", "generated"):
                layer_logs = modifications.get(layer_name, [])
                if isinstance(layer_logs, list):
                    for entry in layer_logs:
                        if isinstance(entry, dict):
                            field = entry.get("field", entry.get("field_name", ""))
                            if field:
                                modified_fields.add(field)

            # V1.1: 检查 (entity_name, field_name) 是否已被修改
            en = c.get("entity_name", "")
            fn = c.get("field_name", "")
            if fn in modified_fields and not en:
                continue
            if f"{en}/{fn}" in modified_fields or fn in modified_fields:
                continue
            raw_conflicts.append(c)

    # V1.1: 去重 key 加入 entity — 不同实体的同名冲突不去重
    deduped: dict[tuple, dict] = {}
    for c in raw_conflicts:
        key = (c.get("entity_type", ""), c.get("entity_name", ""),
               c.get("field_name", ""), c.get("source_a", ""), c.get("source_b", ""))
        if key not in deduped or c.get("cohens_d", 0) > deduped[key].get("cohens_d", 0):
            deduped[key] = c

    conflicts = list(deduped.values())
    conflicts.sort(key=lambda c: c.get("cohens_d", 0), reverse=True)

    # 分配 ID + 汇总 entity 信息
    involved_sources: set[str] = set()
    involved_fields: set[str] = set()
    involved_entities: set[str] = set()
    for i, c in enumerate(conflicts):
        cid = f"CF-{i+1:03d}"
        c["conflict_id"] = cid
        if c.get("source_a"):
            involved_sources.add(c["source_a"])
        if c.get("source_b"):
            involved_sources.add(c["source_b"])
        fn = c.get("field_name", "")
        en = c.get("entity_name", "")
        if fn:
            involved_fields.add(f"{en}/{fn}" if en else fn)
        if en:
            involved_entities.add(en)

    total = len(conflicts)
    summary = f"Identified {total} conflict(s) via {trigger_path} in {len(involved_entities)} entities, fields: {sorted(involved_fields)}"

    logger.info("[ConflictExtractor] %d conflicts extracted (%s), sources=%d, entities=%d, fields=%d",
                total, trigger_path, len(involved_sources), len(involved_entities), len(involved_fields))

    return {
        "trigger_path": trigger_path,
        "total_conflicts": total,
        "conflicts": conflicts,
        "involved_sources": sorted(involved_sources),
        "involved_entities": sorted(involved_entities),
        "involved_fields": sorted(involved_fields),
        "summary": summary,
    }
