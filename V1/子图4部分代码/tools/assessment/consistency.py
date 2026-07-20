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

    # ── 2. 字段值"形状"一致性 (V1.1: entity 感知) ──
    from tools._parse_utils import parse_numeric, has_uncertainty
    field_shape_map: dict[str, set[str]] = {}
    for rec in records:
        fn = rec.get("field_name", "unknown")
        en = rec.get("entity_name", "")
        key = f"{en}/{fn}" if en else fn
        v = rec.get("field_value")
        if v is None:
            shape = "null"
        elif has_uncertainty(v):
            shape = "uncertainty"
        elif parse_numeric(v) is not None:
            shape = "numeric"
        else:
            shape = "text"
        field_shape_map.setdefault(key, set()).add(shape)

    field_type_consistency: dict[str, bool] = {}
    for key, shapes in field_shape_map.items():
        normalized = shapes - {"uncertainty", "numeric"}
        field_type_consistency[key] = len(normalized) <= 1

    # ── 3. 单位一致性 (V1.1: entity 感知) ──
    unit_map: dict[str, set[str]] = {}
    for rec in records:
        fn = rec.get("field_name", "unknown")
        en = rec.get("entity_name", "")
        key = f"{en}/{fn}" if en else fn
        unit = rec.get("field_unit")
        if unit is not None:
            unit_map.setdefault(key, set()).add(str(unit))

    unit_consistency: dict[str, str] = {}
    for key, units in unit_map.items():
        if len(units) == 1:
            unit_consistency[key] = "consistent"
        elif len(units) == 0:
            unit_consistency[key] = "no_units"
        else:
            unit_consistency[key] = f"inconsistent: {units}"

    # ── 4. 汇总评分 ──
    issues: list[str] = []
    if missing_schema > 0:
        issues.append(f"{missing_schema} 条记录缺少必填字段")
    for fname, consistent in field_type_consistency.items():
        if not consistent:
            shapes = field_shape_map.get(fname, set())
            issues.append(f"字段 '{fname}' 值形状不一致: {sorted(shapes)}")
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
