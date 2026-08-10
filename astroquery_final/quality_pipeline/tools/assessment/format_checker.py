"""
format_checker.py

Stage 2c：Format Assessment — 检查数据格式规范性，
包括数值格式、字符串格式等。
"""

from __future__ import annotations

import re
from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)

# 允许的数值前缀（近似值标识）
_ALLOWED_PREFIXES = {"~", "≈", "<", ">", "≤", "≥"}

# record_id 格式验证正则
_RECORD_ID_PATTERN = re.compile(r"^.+_.+_\d+$")


def check_format(data: dict[str, Any]) -> dict[str, Any]:
    """
    检查数据格式规范性。

    Args:
        data: grounded_data JSON。

    Returns:
        格式评估结果：
        {
            "score": float,
            "record_id_format_issues": list[str],
            "numeric_format_issues": list[dict],
            "string_format_issues": list[dict],
            "total_issues": int,
            "summary": str,
        }
    """
    logger.info("开始格式规范性评估...")

    records = data.get("records", [])
    if not records:
        return {
            "score": 1.0,
            "record_id_format_issues": [],
            "numeric_format_issues": [],
            "string_format_issues": [],
            "total_issues": 0,
            "summary": "无数据记录，跳过格式检查。",
        }

    record_id_issues: list[str] = []
    numeric_issues: list[dict] = []
    string_issues: list[dict] = []

    # V2: per-entity 分组统计
    entity_records: dict[tuple, list[dict]] = {}
    for rec in records:
        et = rec.get("entity_type", "") or ""
        en = rec.get("entity_name", "") or ""
        ekey = (et, en) if (et or en) else ("__global__", "")
        entity_records.setdefault(ekey, []).append(rec)

    per_entity_issue_count: dict[str, int] = {}

    # V4 fix: 字段级数值性 — 该字段存在 ≥1 条数值记录 → 数值型字段,
    # 其中的非数值垃圾串 ('all'/'+40_43' 等无前缀串) 应被标记
    field_numeric_flags: dict[str, bool] = {}
    for rec in records:
        fn = rec.get("field_name", "")
        if not fn:
            continue
        from ...tools._parse_utils import is_numeric as _is_num
        if _is_num(rec.get("field_value")):
            field_numeric_flags[fn] = True

    for rec in records:
        record_id = rec.get("record_id", "")
        field_name = rec.get("field_name", "")
        value = rec.get("field_value")
        entity_type = rec.get("entity_type", "") or ""
        entity_name = rec.get("entity_name", "") or ""

        # record_id 格式 (H-02 fix: DB 记录跳过 paper 格式校验 —
        # database 记录的 record_id 无 paper 命名约定, 与 extraction_quality.py 对齐)
        from ...tools.assessment.source_utils import is_database_record
        if not is_database_record(rec) and not _RECORD_ID_PATTERN.match(record_id):
            record_id_issues.append(record_id)

        # 数值格式检查 (V1.1: property_value 永远是 string)
        from ...tools._parse_utils import is_numeric
        if is_numeric(value):
            # string 类型的数值不会有 NaN/Inf, 但保留检查
            if isinstance(value, float):
                import math
                if math.isnan(value) or math.isinf(value):
                    numeric_issues.append({
                        "record_id": record_id,
                        "field_name": field_name,
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                        "issue": f"Invalid float: {value}",
                    })
        # 字符串格式检查
        elif isinstance(value, str):
            stripped = value.strip()
            # 尝试解析带前缀的数值字符串
            prefix = ""
            body = stripped
            for p in sorted(_ALLOWED_PREFIXES, key=len, reverse=True):
                if stripped.startswith(p):
                    prefix = p
                    body = stripped[len(p):].strip()
                    break

            # V1.1: 使用 parse_numeric 处理 ± 不确定度
            if body:
                from ...tools._parse_utils import parse_numeric
                if parse_numeric(body) is not None:
                    if prefix:
                        logger.debug("带前缀数值: '%s' (prefix='%s', body='%s')",
                                     stripped, prefix, body)
                elif prefix:
                    string_issues.append({
                        "record_id": record_id,
                        "field_name": field_name,
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                        "value": value,
                        "issue": f"前缀 '{prefix}' 后不是有效数值: '{body}'",
                    })
                elif field_numeric_flags.get(field_name):
                    # V4 fix: 数值型字段中的无前缀非数值串 — 此前 format_checker
                    # 只报带前缀串, 'all'/'+40_43' 等垃圾值静默通过
                    string_issues.append({
                        "record_id": record_id,
                        "field_name": field_name,
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                        "value": value,
                        "issue": f"数值型字段中的非数值串: '{value}'",
                    })

    total_issues = len(record_id_issues) + len(numeric_issues) + len(string_issues)

    # V2: per-entity 问题计数
    for ekey, erecs in entity_records.items():
        label = f"{ekey[0]}:{ekey[1]}" if ekey[0] and ekey[0] != "__global__" else (ekey[1] or "global")
        erec_ids = {r.get("record_id", "") for r in erecs}
        e_issues = 0
        for rid in record_id_issues:
            if rid in erec_ids:
                e_issues += 1
        for ni in numeric_issues:
            if ni.get("record_id", "") in erec_ids:
                e_issues += 1
        for si in string_issues:
            if si.get("record_id", "") in erec_ids:
                e_issues += 1
        per_entity_issue_count[label] = e_issues

    # 评分
    score = 1.0 - min(1.0, total_issues / max(1, len(records)) * 0.5)
    score = round(max(0.0, score), 4)

    result = {
        "score": score,
        "record_id_format_issues": record_id_issues,
        "numeric_format_issues": numeric_issues,
        "string_format_issues": string_issues,
        "total_issues": total_issues,
        # V2: per-entity breakdown
        "per_entity_issues": per_entity_issue_count,
        "entity_count": len(entity_records),
        "summary": f"格式问题 {total_issues} 项。" if total_issues else "格式规范性良好。",
    }

    logger.info("格式评估完成: score=%.2f, %d 个问题。", score, total_issues)
    return result
