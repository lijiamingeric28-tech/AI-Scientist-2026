"""
completeness.py

Stage 2a：Completeness Assessment — 检查数据完整性，
包括缺失字段、缺失值及元数据完整性。
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def check_completeness(
    data: dict[str, Any],
    target_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    检查数据完整性。

    Args:
        data: grounded_data JSON（含 sources 和 records）。
        target_schema: 目标 Schema 定义（可选）。若提供，检查字段覆盖率。

    Returns:
        完整性评估结果：
        {
            "score": float,              # 0-1 完整性评分
            "total_records": int,
            "records_missing_source": int,       # source_id 外键找不到
            "records_missing_unit": int,         # field_unit 为 None 的数值记录
            "records_missing_provenance": int,   # 溯源信息不完整
            "expected_fields": list[str],        # 目标 Schema 期望字段
            "present_fields": list[str],         # 实际存在的字段
            "missing_expected_fields": list[str],  # 目标 Schema 中缺失的字段
            "field_completeness": dict[str, float],  # 各字段的完整率
            "summary": str,
        }
    """
    logger.info("开始完整性评估...")

    sources = data.get("sources", [])
    records = data.get("records", [])

    total_records = len(records)
    if total_records == 0:
        return {
            "score": 0.0,
            "total_records": 0,
            "records_missing_source": 0,
            "records_missing_unit": 0,
            "records_missing_provenance": 0,
            "expected_fields": [],
            "present_fields": [],
            "missing_expected_fields": [],
            "field_completeness": {},
            "summary": "无数据记录。",
        }

    source_ids = {s.get("source_id") for s in sources}

    records_missing_source = 0
    records_missing_unit = 0
    records_missing_provenance = 0

    field_values: dict[str, list[Any]] = {}

    for rec in records:
        # 外键检查
        if rec.get("source_id") not in source_ids:
            records_missing_source += 1

        # 单位检查（仅数值字段）
        value = rec.get("field_value")
        if isinstance(value, (int, float)) and rec.get("field_unit") is None:
            records_missing_unit += 1

        # 溯源检查
        prov = rec.get("provenance", {})
        if prov is None or prov.get("page") is None or prov.get("bbox") is None:
            records_missing_provenance += 1

        # 收集字段值用于完整率计算
        field_name = rec.get("field_name", "unknown")
        if field_name not in field_values:
            field_values[field_name] = []
        field_values[field_name].append(value)

    # 字段完整率：每个字段不存在 None 值的比例
    field_completeness: dict[str, float] = {}
    for fname, values in field_values.items():
        non_null = sum(1 for v in values if v is not None)
        field_completeness[fname] = non_null / len(values) if values else 0.0

    # 目标 Schema 覆盖检查
    expected_fields: list[str] = []
    missing_expected_fields: list[str] = []
    if target_schema:
        schema_fields = target_schema.get("fields", [])
        expected_fields = [f.get("name", "") for f in schema_fields if f.get("name")]
        present_fields = sorted(field_values.keys())
        missing_expected_fields = [f for f in expected_fields if f not in present_fields]
    else:
        present_fields = sorted(field_values.keys())

    # 评分
    penalty_source = records_missing_source / total_records if total_records else 0
    penalty_unit = records_missing_unit / total_records if total_records else 0
    penalty_prov = records_missing_provenance / total_records if total_records else 0

    score = 1.0 - (0.4 * penalty_source + 0.3 * penalty_unit + 0.3 * penalty_prov)
    score = max(0.0, min(1.0, score))

    issues = []
    if records_missing_source > 0:
        issues.append(f"{records_missing_source} 条记录 source_id 外键无法匹配")
    if records_missing_unit > 0:
        issues.append(f"{records_missing_unit} 条数值记录的 field_unit 缺失")
    if records_missing_provenance > 0:
        issues.append(f"{records_missing_provenance} 条记录的溯源信息不完整")
    if missing_expected_fields:
        issues.append(f"目标 Schema 字段缺失: {missing_expected_fields}")

    result = {
        "score": round(score, 4),
        "total_records": total_records,
        "records_missing_source": records_missing_source,
        "records_missing_unit": records_missing_unit,
        "records_missing_provenance": records_missing_provenance,
        "expected_fields": expected_fields,
        "present_fields": present_fields,
        "missing_expected_fields": missing_expected_fields,
        "field_completeness": field_completeness,
        "summary": "; ".join(issues) if issues else "数据完整性良好。",
    }

    logger.info("完整性评估完成: score=%.2f, %d 条问题。", score, len(issues))
    return result
