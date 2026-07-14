"""
data_organizer.py — Tool 1: DataOrganizer

过滤 Workflow 中间临时字段, 按 Target Schema 组织数据结构,
按 source 分组排序, 构建 field_index。
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

# 需过滤的临时字段
_TEMP_RECORD_FIELDS = {"_modified", "_conflict_cache", "_temp_score",
                        "_normalized", "_resolution_status", "_source_path",
                        "_prefer_a", "_missing_unit"}

# V2.3: grounded_data 输出字段白名单 (只保留 schema 规定的字段)
_GROUNDED_DATA_RECORD_FIELDS = {
    "record_id", "source_id", "field_name", "field_value", "field_unit",
    "trace_id", "provenance", "extraction_method"
}

_PUBLIC_SOURCE_FIELDS = {"source_id", "doi", "title", "authors", "year",
                          "journal", "source_type", "access_path", "retrieval_priority"}


def organize_data(
    current_data: dict[str, Any],
    target_schema: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """去除临时字段, 按 Target Schema 组织数据。

    Returns: (organized_data, summary)
    """
    sources = current_data.get("sources", [])
    records = current_data.get("records", [])

    # Step 1 (V2.3): 白名单过滤 — 只保留 grounded_data schema 字段
    clean_records = []
    filtered_count = 0
    for r in records:
        clean = {k: v for k, v in r.items()
                 if k not in _TEMP_RECORD_FIELDS}
        filtered_count += 1 if len(clean) < len(r) else 0
        clean_records.append(clean)

    # Step 2: 过滤 source 字段
    clean_sources = []
    for s in sources:
        clean_s = {k: v for k, v in s.items() if k in _PUBLIC_SOURCE_FIELDS}
        if "source_id" in clean_s:
            clean_sources.append(clean_s)

    # Step 3: Schema 字段对齐
    expected_fields = set()
    if target_schema:
        for f in target_schema.get("fields", []):
            expected_fields.add(f.get("name", ""))

    actual_fields: set[str] = set()
    standard_fields: set[str] = set()
    extra_fields: set[str] = set()
    for r in clean_records:
        fn = r.get("field_name", "")
        actual_fields.add(fn)
        if fn in expected_fields or not expected_fields:
            standard_fields.add(fn)
        else:
            extra_fields.add(fn)

    # Step 4: 排序
    clean_sources.sort(key=lambda s: (-(s.get("year") or 0), s.get("title", "")))
    clean_records.sort(key=lambda r: (r.get("source_id", ""), r.get("field_name", ""), r.get("record_id", "")))

    # Step 5: 构建 field_index
    field_index: dict[str, dict] = {}
    for fn in standard_fields | extra_fields:
        f_recs = [r for r in clean_records if r.get("field_name") == fn]
        source_ids = sorted(set(r.get("source_id", "") for r in f_recs))
        values = [r.get("field_value") for r in f_recs if r.get("field_value") is not None]
        units = list(set(r.get("field_unit") for r in f_recs if r.get("field_unit")))
        standard_unit = None
        if target_schema:
            for f in target_schema.get("fields", []):
                if f.get("name") == fn:
                    standard_unit = f.get("standard_unit")
                    break
        field_index[fn] = {
            "record_count": len(f_recs),
            "source_count": len(source_ids),
            "sources": source_ids,
            "units_used": sorted(units),
            "standard_unit": standard_unit,
            "data_type": _infer_type(values),
            "sample_values": values[:5],
            "is_extra": fn in extra_fields,
        }

    summary = {
        "total_sources": len(clean_sources),
        "total_records": len(clean_records),
        "standard_fields": sorted(standard_fields),
        "extra_fields": sorted(extra_fields),
        "records_filtered": filtered_count,
        "sources_trimmed": len(sources) - len(clean_sources),
    }

    logger.info("[DataOrganizer] %d records, %d fields (%d standard + %d extra)",
                summary["total_records"], len(field_index),
                len(standard_fields), len(extra_fields))

    organized = {
        "sources": clean_sources,
        "records": clean_records,
        "field_index": field_index,
    }
    return organized, summary


def _infer_type(values: list) -> str:
    nums = [v for v in values if isinstance(v, (int, float))]
    strs = [v for v in values if isinstance(v, str)]
    if nums and not strs:
        return "numeric"
    elif strs and not nums:
        return "string"
    elif nums and strs:
        return "mixed"
    return "empty"
