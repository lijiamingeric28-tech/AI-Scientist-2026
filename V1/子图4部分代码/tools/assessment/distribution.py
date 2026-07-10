"""
distribution.py

DistributionProfiler — 分布分析工具 (V2.0 P1)

扩展 ProfilingAgent 的统计分析能力:
  - histogram binning (Sturges' rule)
  - skewness (Pearson's coefficient)
  - kurtosis (excess)
  - quantile summary (P10/P25/P50/P75/P90)
  - IQR
  - distribution type classification
"""

from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


def analyze_distribution(values: list[float]) -> dict[str, Any]:
    """
    对一组数值做完整的分布分析。

    Args:
        values: 数值列表

    Returns:
        {
            "count": int, "mean": float, "median": float, "std": float,
            "skewness": float, "kurtosis": float,
            "quantiles": {P10, P25, P50, P75, P90},
            "iqr": float,
            "histogram_bins": [int],
            "distribution_type": str,
            "summary": str,
        }
    """
    n = len(values)
    if n < 2:
        return {"count": n, "summary": "insufficient data", "distribution_type": "unknown"}

    sorted_vals = sorted(values)
    mean_val = sum(values) / n

    # ── 分位数 ──
    def _quantile(data: list[float], q: float) -> float:
        idx = q * (len(data) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
        frac = idx - lo
        return data[lo] * (1 - frac) + data[hi] * frac

    q10 = _quantile(sorted_vals, 0.10)
    q25 = _quantile(sorted_vals, 0.25)
    q50 = _quantile(sorted_vals, 0.50)
    q75 = _quantile(sorted_vals, 0.75)
    q90 = _quantile(sorted_vals, 0.90)
    iqr = q75 - q25

    # ── 标准差 ──
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(variance)

    # ── Skewness (Pearson's moment coefficient) ──
    if std > 0 and n >= 3:
        skew = (n / ((n - 1) * (n - 2))) * sum(((x - mean_val) / std) ** 3 for x in values)
    else:
        skew = 0.0

    # ── Kurtosis (excess) ──
    if std > 0 and n >= 4:
        kurt = ((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * sum(
            ((x - mean_val) / std) ** 4 for x in values
        ) - (3 * (n - 1) ** 2) / ((n - 2) * (n - 3))
    else:
        kurt = 0.0

    # ── Histogram bins (Sturges' rule) ──
    n_bins = max(4, math.ceil(math.log2(n) + 1))
    min_v, max_v = sorted_vals[0], sorted_vals[-1]
    bin_width = (max_v - min_v) / n_bins if n_bins > 0 and max_v > min_v else 1
    bins = [round(min_v + i * bin_width, 2) for i in range(n_bins + 1)]

    # ── Distribution type ──
    dist_type = _classify_distribution(skew, kurt)

    # ── Summary ──
    if abs(skew) < 0.5 and abs(kurt) < 1.0:
        summary = f"近似正态分布 (n={n}, mean={mean_val:.2f}, std={std:.2f})"
    elif abs(skew) >= 0.5:
        direction = "右偏(长尾在右侧)" if skew > 0 else "左偏(长尾在左侧)"
        summary = f"{direction}分布 (n={n}, skew={skew:.2f})"
    elif kurt >= 1.0:
        summary = f"厚尾分布 (n={n}, kurt={kurt:.2f}) — 可能存在极端值"
    else:
        summary = f"薄尾分布 (n={n}, kurt={kurt:.2f}) — 数值集中"

    return {
        "count": n, "mean": round(mean_val, 4), "median": q50, "std": round(std, 4),
        "skewness": round(skew, 4), "kurtosis": round(kurt, 4),
        "quantiles": {"P10": q10, "P25": q25, "P50": q50, "P75": q75, "P90": q90},
        "iqr": round(iqr, 4),
        "histogram_bins": bins,
        "distribution_type": dist_type,
        "summary": summary,
    }


def _classify_distribution(skew: float, kurt: float) -> str:
    """根据 skewness/kurtosis 分类分布类型。"""
    if abs(skew) < 0.3 and abs(kurt) < 0.5:
        return "normal"
    elif abs(skew) >= 0.5 and kurt >= 1.0:
        return "skewed_heavy_tailed"
    elif abs(skew) >= 0.5:
        return "skewed"
    elif kurt >= 1.0:
        return "heavy_tailed"
    elif skew > 0.3 and kurt < -0.5:
        return "bimodal_like"
    else:
        return "other"


def profile_field_distributions(records: list[dict]) -> dict[str, dict]:
    """对所有数值字段做分布分析。"""
    field_values: dict[str, list[float]] = {}
    for rec in records:
        val = rec.get("field_value")
        if isinstance(val, (int, float)):
            fn = rec.get("field_name", "unknown")
            field_values.setdefault(fn, []).append(float(val))

    results = {}
    for fn, vals in field_values.items():
        results[fn] = analyze_distribution(vals)
        logger.debug("[DistProfiler] %s: %s", fn, results[fn]["summary"])

    return results
