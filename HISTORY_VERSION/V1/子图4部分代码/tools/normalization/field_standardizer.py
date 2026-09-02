"""field_standardizer.py — Tool 2: Field Standardization"""
import re
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

_PREFIX_RE = re.compile(r'^\s*(~|≈|ca\.\s*|approx\.\s*|about\s*|<|>|≤|≥)\s*', re.IGNORECASE)
_SUFFIX_RE = re.compile(r'\s*\((typical|nominal|approx|maximum|minimum)\)\s*$', re.IGNORECASE)

def standardize_field_values(records: list[dict]) -> dict[str, Any]:
    """标准化字段值: 去前缀/后缀, 字符串标准化。"""
    log = []
    for rec in records:
        val = rec.get("field_value")
        if isinstance(val, str):
            stripped = val.strip()
            m = _PREFIX_RE.match(stripped)
            body = stripped[m.end():].strip() if m else stripped
            m2 = _SUFFIX_RE.search(body)
            if m2: body = body[:m2.start()].strip()
            # V1.1: 先处理 ± 不确定度
            uncertainty = None
            if "±" in body:
                parts = body.split("±")
                body = parts[0].strip()
                try:
                    uncertainty = float(parts[1].strip().rstrip("%"))
                except (ValueError, TypeError):
                    pass
            try:
                nv = float(body)
                if nv == int(nv) and "." not in body: nv = int(nv)
                log.append({"record_id": rec.get("record_id"), "original": val, "new": nv, "action": "string_to_numeric"})
                rec["field_value"] = nv
                if uncertainty is not None:
                    rec["_uncertainty"] = uncertainty
            except (ValueError, TypeError):
                cleaned = body.lower().replace(" ", "_")
                if cleaned != val:
                    log.append({"record_id": rec.get("record_id"), "original": val, "new": cleaned, "action": "clean_string"})
                    rec["field_value"] = cleaned
    logger.info("[FieldStd] %d modifications", len(log))
    return {"data": records, "modification_log": log, "summary": f"Standardized {len(log)} fields"}
