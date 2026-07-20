"""
format_exporter.py — Tool 2: FormatExporter

多格式数据导出: JSON (长表/宽表) + CSV (长表/宽表)。
"""
from __future__ import annotations
import json
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def export_formats(
    organized_data: dict[str, Any],
    format_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将组织后的数据导出为多种格式。

    Args:
        organized_data: {sources, records, field_index}
        format_config: 可选配置 (如 csv_delimiter)

    Returns:
        {json, csv, csv_wide, json_wide, row_count, column_count}
    """
    sources = organized_data.get("sources", [])
    records = organized_data.get("records", [])
    field_index = organized_data.get("field_index", {})

    row_count = len(records)
    field_names = sorted(field_index.keys())
    column_count = len(field_names) + 1  # +source_id

    config = format_config or {}
    delimiter = config.get("csv_delimiter", ",")

    # ── JSON 长表 ──
    json_data = {
        "sources": sources,
        "records": records,
    }

    # ── CSV 长表 (V1.1: 增加 entity 列) ──
    csv_header = ["source_id", "entity_type", "entity_name",
                  "field_name", "field_value", "field_unit", "page", "bbox"]
    csv_lines = [delimiter.join(csv_header)]
    for r in records:
        prov = r.get("provenance") or {}
        row = [
            _csv_escape(str(r.get("source_id", ""))),
            _csv_escape(str(r.get("entity_type", ""))),
            _csv_escape(str(r.get("entity_name", ""))),
            _csv_escape(str(r.get("field_name", ""))),
            _csv_escape(str(r.get("field_value", ""))),
            _csv_escape(str(r.get("field_unit") or "")),
            _csv_escape(str(prov.get("page", ""))),
            _csv_escape(str(prov.get("bbox", ""))),
        ]
        csv_lines.append(delimiter.join(row))
    csv_str = "\n".join(csv_lines)

    # ── 宽表 (Pivot) ──
    source_ids = [s["source_id"] for s in sources]
    wide: dict[str, list] = {"source_id": source_ids}
    for fn in field_names:
        wide[fn] = []
        wide[f"{fn}_unit"] = []

    # 构建 source_id → {field_name → {value, unit}} 映射
    src_data: dict[str, dict[str, dict]] = {}
    for r in records:
        sid = r.get("source_id", "")
        fn = r.get("field_name", "")
        fv = r.get("field_value")
        fu = r.get("field_unit")
        src_data.setdefault(sid, {})[fn] = {"value": fv, "unit": fu}

    for sid in source_ids:
        sd = src_data.get(sid, {})
        for fn in field_names:
            fd = sd.get(fn, {})
            wide[fn].append(fd.get("value"))
            wide[f"{fn}_unit"].append(fd.get("unit"))

    # CSV 宽表
    wide_header = ["source_id"]
    for fn in field_names:
        wide_header.append(fn)
        wide_header.append(f"{fn}_unit")
    wide_lines = [delimiter.join(_csv_escape(h) for h in wide_header)]
    for i, sid in enumerate(source_ids):
        row = [_csv_escape(str(sid))]
        for fn in field_names:
            row.append(_csv_escape(str(wide[fn][i]) if wide[fn][i] is not None else ""))
            row.append(_csv_escape(str(wide[f"{fn}_unit"][i]) if wide[f"{fn}_unit"][i] is not None else ""))
        wide_lines.append(delimiter.join(row))
    csv_wide_str = "\n".join(wide_lines)

    # JSON 宽表
    json_wide: dict[str, list] = {"source_id": source_ids}
    for fn in field_names:
        json_wide[fn] = wide[fn]
        json_wide[f"{fn}_unit"] = wide[f"{fn}_unit"]

    logger.info("[FormatExporter] %d rows, %d cols → json+csv exported", row_count, column_count)

    return {
        "json": json_data,
        "csv": csv_str,
        "csv_wide": csv_wide_str,
        "json_wide": json_wide,
        "row_count": row_count,
        "column_count": column_count,
    }


def _csv_escape(val: str) -> str:
    """CSV 转义: 含逗号/引号/换行时加双引号包裹。"""
    if any(c in val for c in (',', '"', '\n', '\r')):
        return '"' + val.replace('"', '""') + '"'
    return val
