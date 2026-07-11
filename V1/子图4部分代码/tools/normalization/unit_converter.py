"""unit_converter.py — Tool 3: Unit Conversion"""
from typing import Any
from configs import load_yaml
from utils.logger import get_logger
logger = get_logger(__name__)

def convert_units(records: list[dict], unit_conversions: list[dict] | None = None,
                  standard_units: dict[str, str] | None = None) -> dict[str, Any]:
    """统一单位转换。"""
    config = load_yaml("schema_mapping.yaml")
    rules = config.get("unit_conversions", {})
    cat_map: dict[str, dict] = {}
    for cat, cv in rules.items():
        for unit, factor in cv.items():
            cat_map[unit] = {"category": cat, "factor": factor}

    std_units = standard_units or {}
    for f in config.get("target_schema", {}).get("fields", []):
        n, u = f.get("name"), f.get("standard_unit")
        if n and u: std_units[n] = u

    conv_map: dict[str, str] = {}
    if unit_conversions:
        for uc in unit_conversions:
            if isinstance(uc, dict) and uc.get("field"):
                conv_map[uc["field"]] = uc.get("to", std_units.get(uc["field"], ""))

    log, unconv = [], []
    for rec in records:
        fn, val, unit = rec.get("field_name",""), rec.get("field_value"), rec.get("field_unit")
        target = conv_map.get(fn) or std_units.get(fn)
        if not target or unit == target or not isinstance(val, (int, float)):
            continue
        rule = cat_map.get(unit or "")
        if not rule:
            unconv.append({"record_id": rec.get("record_id"), "field": fn, "reason": f"no rule for unit '{unit}'"})
            continue
        factor = rule["factor"]
        try:
            new_val = _apply_factor(val, factor)
            log.append({"record_id": rec.get("record_id"), "field": fn,
                        "original_value": val, "new_value": new_val,
                        "from": unit, "to": target, "factor": str(factor)})
            rec["field_value"] = new_val
            rec["field_unit"] = target
        except Exception as e:
            unconv.append({"record_id": rec.get("record_id"), "reason": str(e)})
    logger.info("[UnitConv] %d converted, %d unconverted", len(log), len(unconv))
    return {"data": records, "conversion_log": log, "unconverted": unconv,
            "summary": f"Converted {len(log)} units" + (f", {len(unconv)} failed" if unconv else "")}

def _apply_factor(val: float, factor) -> float:
    if isinstance(factor, str) and factor == "offset_273.15":
        return val - 273.15  # K → °C
    elif isinstance(factor, str) and factor == "offset_-273.15":
        return val + 273.15  # °C → K
    elif isinstance(factor, str) and factor == "offset_32_5_9":
        return (val - 32.0) * 5.0 / 9.0  # °F → °C
    elif isinstance(factor, str) and factor.startswith("offset_"):
        return val + float(factor.replace("offset_", ""))
    elif isinstance(factor, str) and factor.startswith("offset_-"):
        return val - float(factor.replace("offset_-", ""))
    return val * float(factor)
