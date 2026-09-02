"""
schema_formatter.py — Tool 3: SchemaFormatter

列重排序 + 单位标准化 + 值格式化。
"""
from __future__ import annotations
from typing import Any
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


def format_to_schema(
    exported: dict[str, Any],
    target_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Schema 对齐格式化。

    Args:
        exported: FormatExporter 的输出
        target_schema: context_state.target_schema

    Returns:
        {structured_data, format_issues}
    """
    issues = []
    structured = dict(exported)

    if not target_schema:
        logger.warning("[SchemaFormatter] No target_schema — skipping format validation")
        return {"structured_data": structured, "format_issues": issues}

    field_defs: dict[str, dict] = {}
    field_order: list[str] = []
    for f in target_schema.get("fields", []):
        name = f.get("name", "")
        if name:
            field_defs[name] = f
            field_order.append(name)

    # ── 值格式化 ──
    records = exported.get("json", {}).get("records", [])
    format_issues_list = []
    for r in records:
        fn = r.get("field_name", "")
        fv = r.get("field_value")
        fu = r.get("field_unit")
        std = field_defs.get(fn, {}).get("standard_unit")

        # 数值截断
        if isinstance(fv, float):
            r["field_value"] = round(fv, 6)

        # 单位检查
        if std and fu and fu != std:
            # 标准化比较
            def _norm(u):
                return (u or "").replace("°", "").replace("℃", "C").strip()
            if _norm(fu) != _norm(std or ""):
                format_issues_list.append({
                    "record_id": r.get("record_id"),
                    "field": fn,
                    "issue": "unit_mismatch",
                    "current": fu,
                    "expected": std,
                })

    if format_issues_list:
        issues.extend(format_issues_list)
        logger.warning("[SchemaFormatter] %d unit mismatches found", len(format_issues_list))

    # ── 宽表列排序 ──
    if field_order:
        json_wide = exported.get("json_wide", {})
        ordered_wide: dict[str, list] = {"source_id": json_wide.get("source_id", [])}
        for fn in field_order:
            if fn in json_wide:
                ordered_wide[fn] = json_wide[fn]
                ordered_wide[f"{fn}_unit"] = json_wide.get(f"{fn}_unit", [])
        # 追加不在 schema 中的字段
        for fn in json_wide:
            if fn not in ordered_wide and fn != "source_id" and not fn.endswith("_unit"):
                ordered_wide[fn] = json_wide[fn]
        structured["json_wide"] = ordered_wide

    logger.info("[SchemaFormatter] %d fields ordered, %d format issues",
                len(field_order), len(format_issues_list))

    return {"structured_data": structured, "format_issues": issues}
