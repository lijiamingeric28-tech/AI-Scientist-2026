"""
profiling.py

Stage 1：Data Profiling — 对输入数据进行概要分析，
统计字段数量、数据类型分布、来源分布及总体规模。
"""

from __future__ import annotations

from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)


def data_profiling(data: dict[str, Any]) -> dict[str, Any]:
    """
    对 grounded_data 进行概要分析，为后续评估建立基线。

    Args:
        data: grounded_data JSON（含 sources 和 records）。

    Returns:
        概要分析结果字典：
        {
            "total_records": int,
            "total_sources": int,
            "field_names": list[str],
            "field_counts": dict[str, int],
            "source_distribution": dict[str, int],
            "extraction_method_counts": dict[str, int],
            "numeric_fields": list[str],
            "string_fields": list[str],
            "records_with_units": int,
            "records_without_units": int,
        }
    """
    logger.info("开始数据概要分析...")

    sources = data.get("sources", [])
    records = data.get("records", [])

    total_sources = len(sources)
    total_records = len(records)

    if total_records == 0:
        logger.warning("records 为空，返回空概要。")
        return {
            "total_records": 0,
            "total_sources": total_sources,
            "field_names": [],
            "field_counts": {},
            "source_distribution": {},
            "extraction_method_counts": {},
            "numeric_fields": [],
            "string_fields": [],
            "records_with_units": 0,
            "records_without_units": 0,
        }

    # 字段统计
    field_counts: dict[str, int] = {}
    source_distribution: dict[str, int] = {}
    extraction_method_counts: dict[str, int] = {}
    numeric_fields: set[str] = set()
    string_fields: set[str] = set()
    # V1.1: entity 统计
    entity_set: set[tuple] = set()
    entity_records: dict[str, int] = {}
    entity_properties: dict[str, set] = {}
    records_with_units = 0
    records_without_units = 0

    for rec in records:
        field_name = rec.get("field_name", "unknown")
        field_counts[field_name] = field_counts.get(field_name, 0) + 1

        source_id = rec.get("source_id", "unknown")
        source_distribution[source_id] = source_distribution.get(source_id, 0) + 1

        method = rec.get("extraction_method", "unknown")
        extraction_method_counts[method] = extraction_method_counts.get(method, 0) + 1

        # V1.1: entity 统计
        et = rec.get("entity_type", "")
        en = rec.get("entity_name", "")
        if en:
            entity_set.add((et, en))
            key = f"{et}:{en}" if et else en
            entity_records[key] = entity_records.get(key, 0) + 1
            entity_properties.setdefault(key, set()).add(field_name)

        # 数据类型分析
        value = rec.get("field_value")
        from ...tools._parse_utils import is_numeric
        if is_numeric(value):
            numeric_fields.add(field_name)
        elif isinstance(value, str):
            string_fields.add(field_name)

        # 单位分析 (L-10 fix: 空串单位计缺失 — 与 completeness V4 语义一致,
        # result_builder 对无单位字段统一产出空串, 此前空串计"有单位"
        # 导致 profiling 100% 覆盖而 completeness 报缺失, 两报告对撞)
        if rec.get("field_unit"):
            records_with_units += 1
        else:
            records_without_units += 1

    # 展开 entity_properties sets 为 list
    entity_props_summary = {k: sorted(v) for k, v in entity_properties.items()}

    profile = {
        "total_records": total_records,
        "total_sources": total_sources,
        "total_entities": len(entity_set),
        "entity_distribution": entity_records,
        "entity_properties": entity_props_summary,
        "field_names": sorted(field_counts.keys()),
        "field_counts": field_counts,
        "source_distribution": source_distribution,
        "extraction_method_counts": extraction_method_counts,
        "numeric_fields": sorted(numeric_fields),
        "string_fields": sorted(string_fields),
        "records_with_units": records_with_units,
        "records_without_units": records_without_units,
    }

    logger.info("数据概要分析完成: %d 条记录, %d 个来源, %d 个字段。",
                total_records, total_sources, len(profile["field_names"]))

    return profile
