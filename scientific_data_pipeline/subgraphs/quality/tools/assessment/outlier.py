"""
outlier.py

OutlierDetector — 异常值检测工具 (V2.0 P2)

双策略互补:
  Method A — IQR 法 (稳健, 不受极端值影响)
  Method B — Modified Z-Score (适合小样本)

Consensus: 两种方法都判定 → definite_outlier; 一种 → suspected
"""

from __future__ import annotations

import math
from typing import Any

from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)


def detect_outliers(values: list[float]) -> dict[str, Any]:
    """
    对一组数值做异常值检测。

    Returns:
        {
            "count": int,
            "outliers": [{"index": int, "value": float, "label": str, "z_score": float}],
            "definite_count": int,
            "suspected_count": int,
            "outlier_ratio": float,
        }
    """
    n = len(values)
    if n < 4:
        return {"count": n, "outliers": [], "definite_count": 0,
                "suspected_count": 0, "outlier_ratio": 0.0,
                "summary": "样本不足 (n<4)"}

    sorted_vals = sorted(values)
    q1 = _quantile(sorted_vals, 0.25)
    q3 = _quantile(sorted_vals, 0.75)
    iqr = q3 - q1

    # ── Method A: IQR ──
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    # ── Method B: Modified Z-Score ──
    median = _quantile(sorted_vals, 0.50)
    abs_devs = [abs(x - median) for x in values]
    mad = _quantile(sorted(abs_devs), 0.50)
    if mad == 0:
        mad = 1e-10  # avoid div by zero

    outliers = []
    definite_count = 0
    suspected_count = 0

    for i, x in enumerate(values):
        # IQR check
        iqr_outlier = (x < lower_bound or x > upper_bound)
        # Modified Z-Score
        m_z = 0.6745 * (x - median) / mad
        z_outlier = abs(m_z) > 3.5

        if iqr_outlier and z_outlier:
            label = "definite_outlier"
            definite_count += 1
        elif iqr_outlier or z_outlier:
            label = "suspected_outlier"
            suspected_count += 1
        else:
            continue

        outliers.append({
            "index": i,
            "value": x,
            "label": label,
            "modified_z_score": round(m_z, 4),
            "iqr_bounds": [round(lower_bound, 4), round(upper_bound, 4)],
        })

    return {
        "count": n,
        "outliers": outliers,
        "definite_count": definite_count,
        "suspected_count": suspected_count,
        "outlier_ratio": round((definite_count + suspected_count) / n, 4),
        "iqr_bounds": [round(lower_bound, 4), round(upper_bound, 4)],
        "summary": f"{definite_count} definite, {suspected_count} suspected "
                   f"({(definite_count+suspected_count)/n*100:.1f}%)"
                   if outliers else "无异常值",
    }


def _quantile(data: list[float], q: float) -> float:
    idx = q * (len(data) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
    return data[lo] * (1 - (idx - lo)) + data[hi] * (idx - lo)


def detect_all_fields(records: list[dict]) -> dict[str, dict]:
    """对所有数值字段做异常值检测 (V1.1: entity 感知 + string 数值)。"""
    from subgraphs.quality.tools._parse_utils import parse_numeric
    # 按 (entity_type, entity_name, field_name) 分组, 避免不同 entity 混在一起
    entity_field_values: dict[tuple, list[float]] = {}
    for rec in records:
        nv = parse_numeric(rec.get("field_value"))
        if nv is None:
            continue
        key = (rec.get("entity_type", ""), rec.get("entity_name", ""), rec.get("field_name", "unknown"))
        entity_field_values.setdefault(key, []).append(nv)

    results = {}
    for (et, en, fn), vals in entity_field_values.items():
        label = f"{fn}" if not en else f"{en}/{fn}"
        results[label] = detect_outliers(vals)

    return results
