"""
consistency.py

Stage 2b：Consistency Assessment — 检查数据一致性，
包括 Schema 一致性、字段一致性、数据类型一致性和单位一致性。
"""

from __future__ import annotations

from typing import Any

from ...utils.logger import get_logger

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

    # ── 1. Schema 一致性 (V3.1: paper/DB 分别检查) ──
    from ...tools.assessment.source_utils import is_database_record
    paper_required = {"record_id", "source_id", "field_name", "field_value",
                      "trace_id", "extraction_method"}
    db_required = {"record_id", "source_id", "field_name", "field_value",
                   "extraction_method"}
    missing_schema = 0
    for rec in records:
        req = db_required if is_database_record(rec) else paper_required
        if not req.issubset(rec.keys()):
            missing_schema += 1

    schema_consistency = {
        "paper_required_keys": sorted(paper_required),
        "db_required_keys": sorted(db_required),
        "records_missing_keys": missing_schema,
        "is_consistent": missing_schema == 0,
    }

    # ── 2. 字段值"形状"一致性 (V1.1: entity 感知) ──
    from ...tools._parse_utils import parse_numeric, has_uncertainty
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
        # M-28 fix: 显式两族判定 — 旧逻辑把 numeric 从集合中减掉,
        # {'numeric','text'} 混合被误判 consistent (检测失效);
        # 数值族 {numeric, uncertainty} 与文本族 {text, null} 族内任意混用一致,
        # 跨族混用 (数值+文本) 才判不一致
        consistent = (
            shapes <= {"numeric", "uncertainty"}
            or shapes <= {"text", "null"}
            or len(shapes) <= 1
        )
        field_type_consistency[key] = consistent

    # ── 3. 单位一致性 (V1.1: entity 感知) ──
    # A10 fix: canonical_unit 归一化后比较 — 'K' vs 'Kelvin'/'°K' 不再误报不一致
    from ...tools.assessment.source_utils import canonical_unit
    unit_map: dict[str, set[str]] = {}
    for rec in records:
        fn = rec.get("field_name", "unknown")
        en = rec.get("entity_name", "")
        key = f"{en}/{fn}" if en else fn
        unit = rec.get("field_unit")
        if unit is not None:
            unit_map.setdefault(key, set()).add(canonical_unit(str(unit)))

    unit_consistency: dict[str, str] = {}
    for key, units in unit_map.items():
        if len(units) == 1:
            unit_consistency[key] = "consistent"
        elif len(units) == 0:
            unit_consistency[key] = "no_units"
        else:
            unit_consistency[key] = f"inconsistent: {units}"

    # ── 4. Per-Entity score aggregation (V2) ──
    # 构建 entity→field 映射
    entity_field_map: dict[str, set[str]] = {}
    for rec in records:
        et = rec.get("entity_type", "") or ""
        en = rec.get("entity_name", "")
        elabel = f"{et}:{en}" if et else (en or "unknown")
        fn = rec.get("field_name", "unknown")
        ekey = f"{en}/{fn}" if en else fn
        entity_field_map.setdefault(elabel, set()).add(ekey)

    # 计算 per-entity 一致性
    per_entity_type_consistency: dict[str, float] = {}
    per_entity_unit_consistency: dict[str, float] = {}
    for elabel, ekeys in entity_field_map.items():
        # Type 一致性
        type_checks = 0
        type_passed = 0
        for k in ekeys:
            if k in field_type_consistency:
                type_checks += 1
                if field_type_consistency[k]:
                    type_passed += 1
        per_entity_type_consistency[elabel] = round(type_passed / max(type_checks, 1), 4)
        # Unit 一致性
        unit_checks = 0
        unit_passed = 0
        for k in ekeys:
            if k in unit_consistency:
                unit_checks += 1
                if not unit_consistency[k].startswith("inconsistent"):
                    unit_passed += 1
        per_entity_unit_consistency[elabel] = round(unit_passed / max(unit_checks, 1), 4)

    # ── 5. 汇总评分 ──
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

    # A9 fix: 连续化评分 — 旧二分 score∈{0,1/3,2/3,1}, 1 个字段单位不一致即整维
    # 失败; 改按字段记录数加权的连续公式: 0.4×schema + 0.3×type_ratio + 0.3×unit_ratio
    field_rec_count: dict[str, int] = {}
    for rec in records:
        fn = rec.get("field_name", "unknown")
        en = rec.get("entity_name", "")
        key = f"{en}/{fn}" if en else fn
        field_rec_count[key] = field_rec_count.get(key, 0) + 1

    def _ratio(ok_pred) -> float:
        total = sum(field_rec_count.values())
        if total == 0:
            return 1.0
        ok = sum(c for k, c in field_rec_count.items() if ok_pred(k))
        return ok / total

    schema_ok = 1.0 if schema_consistency["is_consistent"] else 0.0
    type_ok_ratio = _ratio(lambda k: field_type_consistency.get(k, True))
    unit_ok_ratio = _ratio(lambda k: not unit_consistency.get(k, "").startswith("inconsistent"))
    score = 0.4 * schema_ok + 0.3 * type_ok_ratio + 0.3 * unit_ok_ratio

    result = {
        "score": round(score, 4),
        "schema_consistency": schema_consistency,
        "field_type_consistency": field_type_consistency,
        "unit_consistency": unit_consistency,
        "issues": issues,
        # V2: per-entity consistency scores
        "per_entity_type_consistency": per_entity_type_consistency,
        "per_entity_unit_consistency": per_entity_unit_consistency,
        "summary": "; ".join(issues) if issues else "数据一致性良好。",
    }

    logger.info("一致性评估完成: score=%.2f, %d 个问题, %d entities。", score, len(issues), len(entity_field_map))
    return result
