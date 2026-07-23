"""format_standardizer.py — Tool 6: Format Standardization (V1.1)"""
from typing import Any
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

def standardize_format(records: list[dict]) -> dict[str, Any]:
    """标准化数值/日期格式。"""
    log = []
    for rec in records:
        v = rec.get("field_value")
        clean = False
        if isinstance(v, float) and v == int(v):
            rec["field_value"] = int(v)
            clean = True
        if isinstance(v, str):
            stripped = v.strip()
            if stripped != v:
                rec["field_value"] = stripped
                clean = True
        if clean:
            log.append({"record_id": rec.get("record_id"), "field": rec.get("field_name"), "fix": "format_cleanup"})
    logger.info("[FormatStd] %d format fixes", len(log))
    return {"data": records, "format_log": log, "summary": f"Fixed {len(log)} format issues"}
