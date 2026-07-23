"""missing_value_handler.py — Tool 4: Missing Value Handler"""
from typing import Any
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

def handle_missing_values(records: list[dict], strategy: str = "mark",
                          fill_value: Any = None, standard_units: dict[str, str] | None = None) -> dict[str, Any]:
    """处理缺失值: mark / drop / fill_default。

    V2.3: grounded_data 感知 — 只处理 field_value/field_unit 缺失,
    不因 provenance 不完整而删除记录 (那是 Assessment 的职责)。
    """
    marked, dropped = [], []
    if strategy == "drop":
        kept = []
        for rec in records:
            v = rec.get("field_value")
            if v is None or (isinstance(v, str) and v.strip() == ""):
                dropped.append(rec.get("record_id", "?"))
                continue
            kept.append(rec)
        records[:] = kept
    elif strategy == "fill_default":
        std = standard_units or {}
        for rec in records:
            v = rec.get("field_value")
            if v is None or (isinstance(v, str) and v.strip() == ""):
                rec["field_value"] = fill_value
                marked.append({"record_id": rec.get("record_id"), "field": rec.get("field_name"), "action": "filled_value"})
            from subgraphs.quality.tools._parse_utils import is_numeric
            if rec.get("field_unit") is None and is_numeric(rec.get("field_value")):
                tu = std.get(rec.get("field_name", ""))
                if tu:
                    rec["field_unit"] = tu
                    marked.append({"record_id": rec.get("record_id"), "field": rec.get("field_name"), "action": "filled_unit"})
    else:  # mark
        for rec in records:
            v = rec.get("field_value")
            if v is None or (isinstance(v, str) and v.strip() == ""):
                marked.append({"record_id": rec.get("record_id"), "field": rec.get("field_name"), "action": "marked", "issue": "empty_value"})
            from subgraphs.quality.tools._parse_utils import is_numeric
            if rec.get("field_unit") is None and is_numeric(v):
                marked.append({"record_id": rec.get("record_id"), "field": rec.get("field_name"), "action": "marked", "issue": "missing_unit"})
    logger.info("[MissingVal] strategy=%s, %d handled, %d dropped", strategy, len(marked), len(dropped))
    return {"data": records, "handled_count": len(marked) + len(dropped), "dropped_ids": dropped,
            "marked_issues": marked, "summary": f"Handled {len(marked)} marked, {len(dropped)} dropped"}
