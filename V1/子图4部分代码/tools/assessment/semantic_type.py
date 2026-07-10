"""
semantic_type.py

SemanticTypeInferrer — 语义类型推断工具 (V2.0 新增)

从 field_name + field_unit 推断物理量类型，判断数值是否在物理可行范围内。
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)

# ==========================================================
# 物理量规则库 (可扩展)
# ==========================================================

_SEMANTIC_RULES: dict[str, dict] = {
    "temperature": {
        "keywords": ["temp", "temperature", "T"],
        "units": ["°C", "C", "K", "F", "℃"],
        "feasible_ranges": {
            "°C": [-273.15, 6000],
            "C": [-273.15, 6000],
            "K": [0, 6273],
            "F": [-459.67, 10832],
            "℃": [-273.15, 6000],
        },
    },
    "mechanical_stress": {
        "keywords": ["strength", "stress", "yield", "tensile", "compressive", "ultimate"],
        "units": ["MPa", "GPa", "psi", "ksi", "Pa", "N/mm²"],
        "feasible_ranges": {
            "MPa": [0, 5000],
            "GPa": [0, 500],
            "psi": [0, 725000],
            "ksi": [0, 725],
        },
    },
    "density": {
        "keywords": ["density", "rho", "ρ", "specific_weight"],
        "units": ["g/cm^3", "g/cm³", "kg/m^3", "kg/m³", "lb/in³"],
        "feasible_ranges": {
            "g/cm^3": [0.5, 22.6],
            "g/cm³": [0.5, 22.6],
            "kg/m^3": [500, 22600],
            "kg/m³": [500, 22600],
        },
    },
    "elongation": {
        "keywords": ["elongation", "strain", "elong", "EL"],
        "units": ["%", "mm/mm", "in/in"],
        "feasible_ranges": {
            "%": [0, 100],
            "mm/mm": [0, 1.0],
        },
    },
    "strain_rate": {
        "keywords": ["strain_rate", "strain rate", "rate"],
        "units": ["s^-1", "s⁻¹", "/s", "1/s", "s-1"],
        "feasible_ranges": {
            "s^-1": [1e-10, 1e8],
            "s⁻¹": [1e-10, 1e8],
        },
    },
    "hardness": {
        "keywords": ["hardness", "HV", "HRC", "HB", "Vickers", "Brinell", "Rockwell"],
        "units": ["HV", "HRC", "HB", "GPa"],
        "feasible_ranges": {
            "HV": [1, 3000],
            "HRC": [0, 70],
            "HB": [1, 800],
        },
    },
    "thermal_conductivity": {
        "keywords": ["thermal_conductivity", "thermal conductivity", "k_thermal"],
        "units": ["W/mK", "W/(m·K)", "W/m·K"],
        "feasible_ranges": {
            "W/mK": [0.01, 2500],
        },
    },
    "fatigue_life": {
        "keywords": ["fatigue", "cycles", "N_f", "fatigue_life"],
        "units": ["cycles", "N"],
        "feasible_ranges": {
            "cycles": [1, 1e10],
        },
    },
    "fracture_toughness": {
        "keywords": ["fracture", "toughness", "K_IC", "KIC"],
        "units": ["MPa√m", "MPa·m^0.5", "ksi√in"],
        "feasible_ranges": {
            "MPa√m": [0.1, 300],
        },
    },
}


def infer_semantic_type(
    field_name: str,
    field_unit: str | None = None,
    field_value: float | None = None,
) -> dict[str, Any]:
    """
    从 field_name + field_unit 推断语义类型，并验证物理可行性。

    Args:
        field_name: 字段名
        field_unit: 字段单位
        field_value: 字段值 (用于可行性校验)

    Returns:
        {
            "semantic_type": str | None,
            "confidence": float,
            "physically_plausible": bool | None,
            "feasible_range": [min, max] | None,
            "out_of_range": bool,
            "unit_recognized": bool,
            "matched_by": "keyword" | "unit" | "both" | "none",
        }
    """
    result: dict[str, Any] = {
        "semantic_type": None,
        "confidence": 0.0,
        "physically_plausible": None,
        "feasible_range": None,
        "out_of_range": False,
        "unit_recognized": False,
        "matched_by": "none",
    }

    fn_lower = field_name.lower()
    unit_str = (field_unit or "").strip()

    # 按规则匹配
    best_match = None
    best_score = 0

    for type_name, rules in _SEMANTIC_RULES.items():
        score = 0
        matched_by = "none"

        # 关键词匹配
        keyword_hit = any(kw.lower() in fn_lower for kw in rules["keywords"])
        if keyword_hit:
            score += 1
            matched_by = "keyword"

        # 单位匹配
        unit_hit = unit_str in rules["units"]
        if unit_hit:
            score += 1
            matched_by = "both" if keyword_hit else "unit"

        if score > best_score:
            best_score = score
            best_match = type_name
            result["matched_by"] = matched_by

    if best_match is None:
        return result

    rules = _SEMANTIC_RULES[best_match]
    result["semantic_type"] = best_match
    result["confidence"] = 0.5 + best_score * 0.25  # 0.75 for keyword+unit, 0.5 for one
    result["unit_recognized"] = unit_str in rules["units"]

    # 物理可行性校验
    if field_value is not None and isinstance(field_value, (int, float)):
        feasible = rules["feasible_ranges"].get(unit_str)
        if feasible is None and unit_str:
            # try normalized unit
            from tools.assessment.field_standardizer import _NUMERIC_PREFIXES
            import re
            clean_unit = re.sub(r'^\s*[~≈<>≤≥]*\s*', '', unit_str)
            feasible = rules["feasible_ranges"].get(clean_unit)

        if feasible:
            result["feasible_range"] = feasible
            result["physically_plausible"] = feasible[0] <= field_value <= feasible[1]
            result["out_of_range"] = not result["physically_plausible"]
        else:
            result["physically_plausible"] = True  # 无规则时默认合理

    return result


def infer_all_fields(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    对所有 records 的 field_name 做语义类型推断。

    Returns:
        {field_name: semantic_info}
    """
    result: dict[str, dict[str, Any]] = {}
    seen = set()

    for rec in records:
        fn = rec.get("field_name", "")
        if fn in seen:
            continue
        seen.add(fn)
        result[fn] = infer_semantic_type(
            fn,
            rec.get("field_unit"),
            rec.get("field_value"),
        )

    return result
