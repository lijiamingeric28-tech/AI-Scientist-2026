"""
statistical_conflict.py

StatisticalConflictDetector — 基于统计学的冲突检测 (V2.0 A2)

使用 Cohen's d 效应量替代简单相对差异比较:
  - 考虑组内方差 (测量误差)
  - 考虑样本量 (小样本更宽松)
  - 提供置信区间
  - 效应量分级 (negligible/small/medium/large)
"""

from __future__ import annotations

import math
from typing import Any

from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)


def detect_conflicts_statistical(
    data: dict[str, Any],
    threshold: float = 0.20,
    use_advanced: bool = True,
) -> dict[str, Any]:
    """
    基于统计学的冲突检测。

    对每个 field_name, 按 source 分组, 计算组间 Cohen's d 效应量。

    Algorithm:
      pooled_std = sqrt(((n_a-1)*std_a² + (n_b-1)*std_b²) / (n_a+n_b-2))
      cohens_d = |mean_a - mean_b| / pooled_std

      判定:
        |d| < 0.2  → negligible
        0.2 ≤ |d| < 0.5 → small
        0.5 ≤ |d| < 0.8 → medium  → conflict
        |d| ≥ 0.8 → large  → conflict

    Args:
        data: grounded_data JSON
        threshold: 传统阈值 (backup)
        use_advanced: 是否使用 Cohen's d (True) 或回退到传统方法 (False)

    Returns:
        与 detect_conflicts() 相同格式的结果
    """
    if not use_advanced:
        from tools.assessment.conflict_detector import detect_conflicts
        return detect_conflicts(data, threshold)

    records = data.get("records", [])
    if not records:
        return {"has_conflicts": False, "conflict_count": 0, "conflicts": [],
                "risk_level": "none", "summary": "无数据记录"}

    conflicts = []
    skipped_insufficient = 0

    # V1.1: 按 (entity_type, entity_name, property_name, source_id) 分组
    from subgraphs.quality.tools._parse_utils import parse_numeric
    field_source_groups: dict[tuple, dict[str, list[float]]] = {}
    for rec in records:
        val = rec.get("field_value")
        nv = parse_numeric(val)
        if nv is None:
            continue
        et = rec.get("entity_type", "")
        en = rec.get("entity_name", "")
        fn = rec.get("field_name", "unknown")
        sid = rec.get("source_id", "unknown")
        key = (et, en, fn)
        field_source_groups.setdefault(key, {}).setdefault(sid, []).append(nv)

    for key, source_groups in field_source_groups.items():
        et, en, fn = key
        source_ids = list(source_groups.keys())
        if len(source_ids) < 2:
            continue

        # 两两比较
        for i in range(len(source_ids)):
            for j in range(i + 1, len(source_ids)):
                sia, sib = source_ids[i], source_ids[j]
                vals_a = source_groups[sia]
                vals_b = source_groups[sib]

                na, nb = len(vals_a), len(vals_b)
                if na < 2 or nb < 2:
                    skipped_insufficient += 1
                    continue

                mean_a = sum(vals_a) / na
                mean_b = sum(vals_b) / nb

                # 标准差
                var_a = sum((x - mean_a) ** 2 for x in vals_a) / (na - 1)
                var_b = sum((x - mean_b) ** 2 for x in vals_b) / (nb - 1)

                pooled_std = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
                if pooled_std == 0:
                    continue

                cohens_d = abs(mean_a - mean_b) / pooled_std
                abs_diff = abs(mean_a - mean_b)

                if cohens_d < 0.2:
                    effect = "negligible"
                    is_conflict = False
                elif cohens_d < 0.5:
                    effect = "small"
                    is_conflict = False
                elif cohens_d < 0.8:
                    effect = "medium"
                    is_conflict = True
                else:
                    effect = "large"
                    is_conflict = True

                se = math.sqrt((na + nb) / (na * nb) + cohens_d ** 2 / (2 * (na + nb)))
                ci_low = round(cohens_d - 1.96 * se, 4)
                ci_high = round(cohens_d + 1.96 * se, 4)

                if ci_low < 0.5 and is_conflict:
                    is_conflict = False
                    effect = f"{effect} (not significant)"

                if is_conflict:
                    conflicts.append({
                        "type": "cross_source_value_conflict",
                        "method": "cohens_d",
                        "field_name": fn,
                        "entity_type": et,
                        "entity_name": en,
                        "source_a": sia, "source_b": sib,
                        "mean_a": round(mean_a, 4), "mean_b": round(mean_b, 4),
                        "std_a": round(math.sqrt(var_a), 4),
                        "std_b": round(math.sqrt(var_b), 4),
                        "n_a": na, "n_b": nb,
                        "cohens_d": round(cohens_d, 4),
                        "effect_size": effect,
                        "ci_95": [ci_low, ci_high],
                        "absolute_difference": round(abs_diff, 2),
                        "pooled_std": round(pooled_std, 4),
                    })

    conflict_count = len(conflicts)
    if conflict_count == 0:
        risk_level = "none"
    elif conflict_count <= 2:
        risk_level = "low"
    elif conflict_count <= 5:
        risk_level = "medium"
    else:
        risk_level = "high"

    summary_parts = [f"Cohen's d: {conflict_count} conflicts"]
    if skipped_insufficient:
        summary_parts.append(f"{skipped_insufficient} groups skipped (insufficient data)")

    return {
        "has_conflicts": conflict_count > 0,
        "conflict_count": conflict_count,
        "conflicts": conflicts,
        "risk_level": risk_level,
        "method": "cohens_d",
        "skipped_insufficient": skipped_insufficient,
        "summary": "; ".join(summary_parts) + "。" if conflicts else "未检测到统计显著冲突。" if not conflicts else "",
    }
