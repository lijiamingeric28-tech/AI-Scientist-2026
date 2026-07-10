"""
consistency.py

Stage 2b：Consistency Assessment — 检查数据一致性，
包括 Schema 一致性、字段一致性、数据类型一致性和单位一致性。
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def check_consistency(data: dict[str, Any]) -> dict[str, Any]:
    """
    检查数据一致性。

    Args:
        data: grounded_data JSON。

    Returns:
        一致性评估结果：
        {
            "score": float,
            "schema_consistency": dict,
            "field_type_consistency": dict[str, bool],
            "unit_consistency": dict[str, str],
            "issues": list[str],
            "summary": str,
        }
    """
    logger.info("开始一致性评估...")

    records = data.get("records", [])
    if not records:
        return {
            "score": 1.0,
            "schema_consistency": {},
            "field_type_consistency": {},
            "unit_consistency": {},
            "issues": [],
            "summary": "无数据记录，跳过一致性检查。",
        }

    # ── 1. Schema 一致性 ──
    required_keys = {"record_id", "source_id", "field_name", "field_value",
                     "trace_id", "extraction_method"}
    missing_schema = 0
    for rec in records:
        if not required_keys.issubset(rec.keys()):
            missing_schema += 1

    schema_consistency = {
        "required_keys": sorted(required_keys),
        "records_missing_keys": missing_schema,
        "is_consistent": missing_schema == 0,
    }

    # ── 2. 字段类型一致性 ──
    field_type_map: dict[str, set[type]] = {}
    for rec in records:
        field_name = rec.get("field_name", "unknown")
        value = rec.get("field_value")
        if field_name not in field_type_map:
            field_type_map[field_name] = set()
        field_type_map[field_name].add(type(value))

    field_type_consistency: dict[str, bool] = {}
    for fname, types in field_type_map.items():
        field_type_consistency[fname] = len(types) == 1

    # ── 3. 单位一致性 ──
    unit_map: dict[str, set[str]] = {}
    for rec in records:
        field_name = rec.get("field_name", "unknown")
        unit = rec.get("field_unit")
        if unit is not None:
            if field_name not in unit_map:
                unit_map[field_name] = set()
            unit_map[field_name].add(str(unit))

    unit_consistency: dict[str, str] = {}
    for fname, units in unit_map.items():
        if len(units) == 1:
            unit_consistency[fname] = "consistent"
        elif len(units) == 0:
            unit_consistency[fname] = "no_units"
        else:
            unit_consistency[fname] = f"inconsistent: {units}"

    # ── 4. 汇总评分 ──
    issues: list[str] = []
    if missing_schema > 0:
        issues.append(f"{missing_schema} 条记录缺少必填字段")
    for fname, consistent in field_type_consistency.items():
        if not consistent:
            types_str = ", ".join(t.__name__ for t in field_type_map[fname])
            issues.append(f"字段 '{fname}' 类型不一致: {types_str}")
    for fname, status in unit_consistency.items():
        if status.startswith("inconsistent"):
            issues.append(f"字段 '{fname}' 单位不一致")

    total_checks = 3
    passed = 0
    if schema_consistency["is_consistent"]:
        passed += 1
    if all(field_type_consistency.values()):
        passed += 1
    if all(not v.startswith("inconsistent") for v in unit_consistency.values()):
        passed += 1

    score = passed / total_checks if total_checks else 1.0

    result = {
        "score": round(score, 4),
        "schema_consistency": schema_consistency,
        "field_type_consistency": field_type_consistency,
        "unit_consistency": unit_consistency,
        "issues": issues,
        "summary": "; ".join(issues) if issues else "数据一致性良好。",
    }

    logger.info("一致性评估完成: score=%.2f, %d 个问题。", score, len(issues))
    return result
