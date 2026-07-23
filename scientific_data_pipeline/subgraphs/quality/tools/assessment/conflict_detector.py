"""
conflict_detector.py

Stage 2e：Conflict Risk Assessment (传统方法, V1.1 去硬编码)
V1.1: entity_type/entity_name 显式分组 + 条件字段从 semantic_type 推断。
"""
from __future__ import annotations
from typing import Any
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

_DEFAULT_THRESHOLD = 0.20


def _is_condition_field(field_name: str) -> bool:
    """从 semantic_type 推断是否为条件字段 (V1.1: 不再硬编码字段名)。"""
    try:
        from subgraphs.quality.tools.assessment.semantic_type import _load_semantic_rules
        rules = _load_semantic_rules()
        fn_lower = field_name.lower()
        # 检查语义类型
        for type_name, rule in rules.items():
            if type_name in ("temperature", "strain_rate", "pressure", "humidity",
                             "exposure_time", "wavelength", "resolution",
                             "magnetic_field", "electric_field", "ph"):
                if any(kw.lower() in fn_lower for kw in rule.get("keywords", [])):
                    return True
            # 条件标记
            if rule.get("expected_in_study") in ("conditional",):
                if any(kw.lower() in fn_lower for kw in rule.get("keywords", [])):
                    return True
    except Exception:
        pass
    # fallback: 通用关键词
    generic = ("temperature", "temp", "strain_rate", "strain rate",
               "pressure", "humidity", "exposure", "wavelength", "resolution")
    return any(k in fn_lower for k in generic)


def detect_conflicts(
    data: dict[str, Any],
    threshold: float = _DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """检测 grounded_data 中的跨来源数值冲突 (V1.1: entity 感知 + 去硬编码)。

    冲突条件: 同一 (entity_type, entity_name, field_name) 下,
             不同 source 的数值差异超过阈值。
    """
    records = data.get("records", [])
    if not records:
        return {"has_conflicts": False, "conflict_count": 0, "conflicts": [],
                "risk_level": "none", "summary": "无数据记录"}

    from subgraphs.quality.tools._parse_utils import parse_numeric

    # V1.1: 按 (entity_type, entity_name, field_name) 分组
    # 同一组的记录是同一实体的同一属性 — 天然不需要材料/条件推断
    field_groups: dict[tuple, list[dict]] = {}
    for rec in records:
        nv = parse_numeric(rec.get("field_value"))
        if nv is None:
            continue
        key = (rec.get("entity_type", ""), rec.get("entity_name", ""),
               rec.get("field_name", "unknown"))
        field_groups.setdefault(key, []).append(rec)

    conflicts: list[dict] = []
    skipped_condition = 0

    for (et, en, field_name), group in field_groups.items():
        if len(group) < 2:
            continue

        is_condition = _is_condition_field(field_name)

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                ri, rj = group[i], group[j]
                if ri.get("source_id") == rj.get("source_id"):
                    continue

                vi = parse_numeric(ri["field_value"])
                vj = parse_numeric(rj["field_value"])
                if vi is None or vj is None or (vi == 0 and vj == 0):
                    continue

                rel_diff = abs(vi - vj) / max(abs(vi), abs(vj))
                abs_diff = abs(vi - vj)

                if is_condition and abs_diff <= 50:
                    skipped_condition += 1
                    continue

                if rel_diff > threshold:
                    conflicts.append({
                        "type": "cross_source_value_conflict",
                        "field_name": field_name,
                        "entity_type": et, "entity_name": en,
                        "record_a": ri.get("record_id"),
                        "record_b": rj.get("record_id"),
                        "source_a": ri.get("source_id"),
                        "source_b": rj.get("source_id"),
                        "value_a": vi, "value_b": vj,
                        "relative_difference": round(rel_diff, 4),
                        "absolute_difference": round(abs_diff, 2),
                        "threshold": threshold,
                        "is_condition_field": is_condition,
                    })

    conflict_count = len(conflicts)
    risk_level = "none" if conflict_count == 0 else (
        "low" if conflict_count <= 2 else ("medium" if conflict_count <= 5 else "high"))

    parts = [f"{conflict_count} conflicts" if conflicts else "No conflicts"]
    if skipped_condition:
        parts.append(f"{skipped_condition} condition-field comparisons skipped")
    summary = "; ".join(parts) + "。"

    logger.info("[ConflictDetector] %d conflicts, risk=%s", conflict_count, risk_level)
    return {
        "has_conflicts": conflict_count > 0, "conflict_count": conflict_count,
        "conflicts": conflicts, "risk_level": risk_level,
        "skipped_condition_field": skipped_condition,
        "summary": summary,
    }
