"""
multi_source_variance.py  (原 statistical_conflict.py)

MultiSourceVarianceAnalyzer — 天文数据多源方差分析 (V3.0)

核心原则变更:
  旧逻辑 (V2.0 A2): 同一 (entity, field) 下不同来源的值差异
                   → Cohen's d → 冲突 → 裁决淘汰 (prefer_source/weighted_avg)
  新逻辑 (V3.0):    同一 (entity, field) 下不同来源的值差异
                   → 差异原因分类 → 全量保留标注
                   → 仅真正异常标记为 anomaly

差异原因推断 (利用 V2 Record 的 measurement_method/condition_tags/context_snippet):
  - measurement_method 不同 → methodological_variance (方法差异)
  - condition_tags 不同   → condition_variance (条件差异)
  - year 差距 > 5 年       → temporal_variation (时间演化)
  - 以上相同 + 差异小       → measurement_uncertainty (测量误差)
  - 以上相同 + 差异极大     → statistical_outlier (潜在异常)
  - 值完全相同 + 不同source  → duplicate_observation (重复收录)

异常检测 (仅以下情况标记为 anomaly):
  - extraction_confidence < 0.5 + 统计离群 → extraction_error
  - 单位维度不匹配 (如 K vs eV)           → unit_error
  - 同名 entity 关联到不同 entity_type      → cross_id_error
  - Cohen's d > 2.0 + 同方法/同条件        → statistical_outlier

向后兼容:
  - detect_conflicts_statistical() 保留, 内部调用 analyze_multi_source_variance()
  - has_conflicts → 现在等于 has_anomalies (只有异常才算冲突)
  - conflicts → 现在只包含 anomalies
  - 新增 has_variance / variances 字段
"""

from __future__ import annotations

import math
from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)

# ── 差异原因常量 ──
CAUSE_METHODOLOGICAL = "methodological_variance"
CAUSE_CONDITION = "condition_variance"
CAUSE_TEMPORAL = "temporal_variation"
CAUSE_UNCERTAINTY = "measurement_uncertainty"
CAUSE_DUPLICATE = "duplicate_observation"
CAUSE_UNKNOWN = "unknown"

# ── 异常类型常量 ──
ANOMALY_STATISTICAL = "statistical_outlier"
ANOMALY_EXTRACTION = "extraction_error"
ANOMALY_UNIT = "unit_error"
ANOMALY_CROSS_ID = "cross_id_error"

# ── Cohen's d 效应量阈值 ──
D_NEGLIGIBLE = 0.2
D_SMALL = 0.5
D_MEDIUM = 0.8
D_LARGE = 2.0   # V3.0: > 2.0 才考虑 anomaly

# ── 时间差异阈值 ──
TEMPORAL_GAP_YEARS = 5

# ── 单位维度映射 (用于检测维度不匹配) ──
_UNIT_DIMENSIONS: dict[str, str] = {
    # 温度
    "K": "temperature", "°C": "temperature", "℃": "temperature",
    # 长度/距离
    "m": "length", "km": "length", "cm": "length", "mm": "length",
    "pc": "length", "kpc": "length", "Mpc": "length", "Gpc": "length",
    "au": "length", "ly": "length", "Rsun": "length", "Rearth": "length",
    # 质量
    "kg": "mass", "g": "mass", "Msun": "mass", "Mjup": "mass", "Mearth": "mass",
    # 时间
    "s": "time", "yr": "time", "Myr": "time", "Gyr": "time", "d": "time",
    # 速度
    "km/s": "velocity", "m/s": "velocity",
    # 能量
    "erg": "energy", "J": "energy", "eV": "energy", "keV": "energy",
    # 密度
    "cm^-3": "density", "g/cm^3": "density",
    # 流量/通量
    "Jy": "flux_density", "mJy": "flux_density", "erg/s/cm^2": "flux",
    # 角量
    "deg": "angle", "rad": "angle", "arcsec": "angle", "mas": "angle",
    # 红移 (无量纲，特殊处理)
    "": "dimensionless",
    # 磁场
    "G": "magnetic_field", "T": "magnetic_field",
}


def _get_unit_dimension(unit: str | None) -> str:
    """获取单位的物理维度。"""
    if not unit:
        return "dimensionless"
    u = unit.strip().replace("°", "").replace("℃", "C")
    # 尝试精确匹配
    if u in _UNIT_DIMENSIONS:
        return _UNIT_DIMENSIONS[u]
    # 尝试拆分匹配 (如 "cm^-3 pc" → check each part)
    for known, dim in _UNIT_DIMENSIONS.items():
        if known and known in u:
            return dim
    return f"unknown:{u}"


def _infer_variance_cause(
    methods_a: set[str],
    methods_b: set[str],
    tags_a: set[str],
    tags_b: set[str],
    year_a: int | None,
    year_b: int | None,
    cohens_d: float,
    value_a: float,
    value_b: float,
) -> tuple[str, float]:
    """
    推断多源差异的原因。

    Returns:
        (cause_label, confidence)
    """
    # 1. 值完全相同 → 可能是重复收录
    if abs(value_a - value_b) < 1e-10:
        return CAUSE_DUPLICATE, 0.95

    # 2. 方法不同
    if methods_a and methods_b and methods_a != methods_b:
        overlap = methods_a & methods_b
        if not overlap:
            return CAUSE_METHODOLOGICAL, 0.85
        elif len(overlap) < min(len(methods_a), len(methods_b)):
            return CAUSE_METHODOLOGICAL, 0.70

    # 3. 条件不同 (波段/仪器)
    if tags_a and tags_b and tags_a != tags_b:
        overlap = tags_a & tags_b
        if not overlap:
            return CAUSE_CONDITION, 0.85
        elif len(overlap) < min(len(tags_a), len(tags_b)):
            return CAUSE_CONDITION, 0.70

    # 4. 时间差异
    if year_a and year_b and abs(year_a - year_b) > TEMPORAL_GAP_YEARS:
        return CAUSE_TEMPORAL, 0.75

    # 5. 同方法+同条件+同时间段 → 看效应量
    if cohens_d >= D_LARGE:
        return ANOMALY_STATISTICAL, 0.60  # 可能是异常，需进一步验证
    if cohens_d >= D_MEDIUM:
        return CAUSE_UNCERTAINTY, 0.65
    if cohens_d >= 0:
        return CAUSE_UNCERTAINTY, 0.80

    # 6. 无法判断 (cohens_d 无效或所有元数据为空)
    return CAUSE_UNKNOWN, 0.40


# ==========================================================
# V3.0: 多源方差分析 (新主函数)
# ==========================================================

def analyze_multi_source_variance(
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    多源方差分析 — V3.0 核心。

    对同一 (entity_type, entity_name, field_name) 下不同来源的值:
      - 计算统计描述 (range, median, Cohen's d)
      - 推断差异原因 (method/condition/temporal/uncertainty)
      - 检测真正异常 (extraction_error/unit_error/cross_id_error/statistical_outlier)

    Args:
        data: grounded_data JSON (V2, 含 measurement_method/condition_tags/extraction_confidence)

    Returns:
        {
            # ── V3.0 新增字段 ──
            "has_variance": bool,
            "variance_count": int,
            "variances": [{entity_type, entity_name, field_name, sources, value_range,
                          inferred_cause, cause_confidence, cohens_d_max, ...}],
            # ── V3.0 异常字段 ──
            "has_anomalies": bool,
            "anomaly_count": int,
            "anomalies": [{record_id, anomaly_type, field_name, evidence, ...}],
            # ── 向后兼容字段 ──
            "has_conflicts": bool,     # = has_anomalies
            "conflict_count": int,     # = anomaly_count
            "conflicts": list,         # = anomalies (兼容下游 conflict_extractor)
            "risk_level": str,
            "method": "multi_source_variance",
            "summary": str,
        }
    """
    records = data.get("records", [])
    sources = {s.get("source_id", ""): s for s in data.get("sources", [])}

    if not records:
        return _empty_result("无数据记录")

    # ── Step 1: 按 (entity_type, entity_name, field_name) 分组 ──
    from ...tools._parse_utils import parse_numeric

    field_source_groups: dict[tuple, dict[str, dict[str, Any]]] = {}
    # key=(et,en,fn) → {source_id: {values, records, methods, tags, confidences, year}}

    for rec in records:
        val = rec.get("field_value")
        nv = parse_numeric(val)
        if nv is None:
            continue
        et = rec.get("entity_type", "") or ""
        en = rec.get("entity_name", "") or ""
        fn = rec.get("field_name", "unknown")
        sid = rec.get("source_id", "unknown")
        key = (et, en, fn)

        if key not in field_source_groups:
            field_source_groups[key] = {}

        if sid not in field_source_groups[key]:
            src = sources.get(sid, {})
            field_source_groups[key][sid] = {
                "values": [],
                "records": [],
                "methods": set(),
                "tags": set(),
                "confidences": [],
                "year": src.get("year"),
                "unit": None,
            }

        grp = field_source_groups[key][sid]
        grp["values"].append(nv)
        grp["records"].append(rec)
        grp["confidences"].append(rec.get("extraction_confidence", 1.0))

        mm = rec.get("measurement_method", "")
        if mm:
            grp["methods"].add(mm)

        ct = rec.get("condition_tags", [])
        if isinstance(ct, list):
            grp["tags"].update(ct)

        unit = rec.get("field_unit", "")
        if unit and grp["unit"] is None:
            grp["unit"] = unit

    # ── Step 2: 分析每组 ──
    variances: list[dict] = []
    anomalies: list[dict] = []
    skipped_insufficient = 0

    for key, source_groups in field_source_groups.items():
        et, en, fn = key
        source_ids = list(source_groups.keys())

        if len(source_ids) < 2:
            continue  # 只有一个来源，无方差

        # 收集 per-source 统计
        source_stats = {}
        for sid, grp in source_groups.items():
            vals = grp["values"]
            n = len(vals)
            mean_v = sum(vals) / n if n > 0 else 0
            std_v = math.sqrt(sum((x - mean_v) ** 2 for x in vals) / n) if n > 1 else 0
            avg_confidence = sum(grp["confidences"]) / len(grp["confidences"]) if grp["confidences"] else 1.0

            source_stats[sid] = {
                "mean": round(mean_v, 4),
                "std": round(std_v, 4),
                "n": n,
                "measurement_methods": list(grp["methods"]),
                "condition_tags": list(grp["tags"]),
                "year": grp["year"],
                "unit": grp["unit"],
                "avg_extraction_confidence": round(avg_confidence, 3),
                "record_ids": [r.get("record_id", "") for r in grp["records"]],
            }

        all_values_sorted = sorted(
            [s["mean"] for s in source_stats.values()]
        )
        value_range = [all_values_sorted[0], all_values_sorted[-1]]

        # 两两比较: Cohen's d + 差异原因推断
        max_cohens_d = 0.0
        pairwise_causes: list[dict] = []
        all_causes: dict[str, int] = {}

        for i in range(len(source_ids)):
            for j in range(i + 1, len(source_ids)):
                sia, sib = source_ids[i], source_ids[j]
                sa = source_stats[sia]
                sb = source_stats[sib]

                na, nb = sa["n"], sb["n"]
                mean_a, mean_b = sa["mean"], sb["mean"]
                std_a, std_b = sa["std"], sb["std"]

                # Cohen's d (小样本时使用保守估计)
                if na < 2 or nb < 2:
                    # 单记录: 无法计算组内方差, 使用 mean 的绝对差异
                    cohens_d = abs(mean_a - mean_b) / max(abs(mean_a), abs(mean_b), 0.001)
                else:
                    var_a = std_a ** 2
                    var_b = std_b ** 2
                    pooled_std = math.sqrt(
                        ((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2)
                    ) if (na + nb) > 2 else 1.0
                    cohens_d = 0.0
                    if pooled_std > 0:
                        cohens_d = abs(mean_a - mean_b) / pooled_std

                if cohens_d > max_cohens_d:
                    max_cohens_d = cohens_d

                # SE + CI
                try:
                    se = math.sqrt(
                        (na + nb) / (na * nb) + cohens_d ** 2 / (2 * (na + nb))
                    )
                except (ValueError, ZeroDivisionError):
                    se = 0.0
                ci_low = round(cohens_d - 1.96 * se, 4)
                ci_high = round(cohens_d + 1.96 * se, 4)

                # 推断差异原因
                cause, cause_conf = _infer_variance_cause(
                    methods_a=set(sa["measurement_methods"]),
                    methods_b=set(sb["measurement_methods"]),
                    tags_a=set(sa["condition_tags"]),
                    tags_b=set(sb["condition_tags"]),
                    year_a=sa["year"],
                    year_b=sb["year"],
                    cohens_d=cohens_d,
                    value_a=mean_a,
                    value_b=mean_b,
                )

                all_causes[cause] = all_causes.get(cause, 0) + 1

                pairwise_causes.append({
                    "source_a": sia, "source_b": sib,
                    "mean_a": mean_a, "mean_b": mean_b,
                    "std_a": std_a, "std_b": std_b,
                    "n_a": na, "n_b": nb,
                    "cohens_d": round(cohens_d, 4),
                    "ci_95": [ci_low, ci_high],
                    "absolute_difference": round(abs(mean_a - mean_b), 2),
                    "inferred_cause": cause,
                    "cause_confidence": cause_conf,
                })

        # 确定组级别的差异原因 (取多数)
        primary_cause = max(all_causes, key=all_causes.get) if all_causes else CAUSE_UNKNOWN
        cause_conf = all_causes.get(primary_cause, 0) / sum(all_causes.values()) if all_causes else 0.0

        # ── 单位维度检查 ──
        unit_dims = set()
        for sid, ss in source_stats.items():
            dim = _get_unit_dimension(ss.get("unit"))
            unit_dims.add(dim)
        unit_mismatch = len(unit_dims) > 1 and "unknown" not in unit_dims

        # ── Cross-ID 检查 (V3.2: 组内检查永远 False — 组 key 已含 entity_type) ──
        # 真实 cross_id 检测移至 Step 3 之后: 按 (entity_name, field_name) 独立分组
        entity_types_in_group = set()
        for sid, grp in source_groups.items():
            for rec in grp["records"]:
                rt = rec.get("entity_type", "")
                if rt:
                    entity_types_in_group.add(rt)
        cross_id_risk = False  # V3.2: 组内不可能 >1, 由独立检测负责

        variance_entry = {
            "entity_type": et,
            "entity_name": en,
            "field_name": fn,
            "source_count": len(source_ids),
            "source_ids": source_ids,
            "source_stats": source_stats,
            "value_range": [round(v, 4) for v in value_range],
            "max_cohens_d": round(max_cohens_d, 4),
            "inferred_cause": primary_cause,
            "cause_confidence": round(cause_conf, 3),
            "pairwise_comparisons": pairwise_causes,
            "unit_mismatch_detected": unit_mismatch,
            "cross_id_risk": cross_id_risk,
        }
        variances.append(variance_entry)

        # ── Step 3: 异常检测 ──
        # A. 统计异常 (Cohen's d > 2.0 + 同方法/同条件)
        if primary_cause == ANOMALY_STATISTICAL:
            for pc in pairwise_causes:
                if pc["inferred_cause"] == ANOMALY_STATISTICAL:
                    anomalies.append({
                        "anomaly_type": ANOMALY_STATISTICAL,
                        "field_name": fn,
                        "entity_type": et,
                        "entity_name": en,
                        "source_a": pc["source_a"],
                        "source_b": pc["source_b"],
                        "value_a": pc["mean_a"],
                        "value_b": pc["mean_b"],
                        "cohens_d": pc["cohens_d"],
                        "ci_95": pc["ci_95"],
                        "evidence": {
                            "same_method": set(source_stats[pc["source_a"]]["measurement_methods"])
                                         == set(source_stats[pc["source_b"]]["measurement_methods"]),
                            "same_conditions": set(source_stats[pc["source_a"]]["condition_tags"])
                                            == set(source_stats[pc["source_b"]]["condition_tags"]),
                            "same_unit": source_stats[pc["source_a"]]["unit"]
                                        == source_stats[pc["source_b"]]["unit"],
                        },
                        "severity": "high",
                    })

        # B. 提取错误 (extraction_confidence < 0.5 + Cohen's d > 2.0)
        # 计划: "统计离群（IQR × 3 或 Cohen's d > 2.0）+ extraction_confidence < 0.5 → extraction_error"
        for sid, ss in source_stats.items():
            if ss["avg_extraction_confidence"] < 0.5:
                # 检查该 source 在所有 pairwise 比较中是否有 Cohen's d > 2.0
                is_statistical_outlier = any(
                    pc["cohens_d"] > 2.0
                    for pc in pairwise_causes
                    if pc["source_a"] == sid or pc["source_b"] == sid
                )
                if is_statistical_outlier:
                    anomalies.append({
                        "anomaly_type": ANOMALY_EXTRACTION,
                        "record_ids": ss["record_ids"],
                        "source_id": sid,
                        "field_name": fn,
                        "entity_type": et,
                        "entity_name": en,
                        "value": ss["mean"],
                        "other_sources_mean": round(
                            sum(source_stats[s2]["mean"] for s2 in source_ids if s2 != sid)
                            / max(len(source_ids) - 1, 1), 4
                        ),
                        "extraction_confidence": ss["avg_extraction_confidence"],
                        "max_pairwise_cohens_d": round(
                            max((pc["cohens_d"] for pc in pairwise_causes
                                 if pc["source_a"] == sid or pc["source_b"] == sid), default=0), 4
                        ),
                        "evidence": {
                            "low_confidence": True,
                            "statistical_outlier": True,
                            "cohens_d_threshold": 2.0,
                        },
                        "severity": "high",
                    })

        # C. 单位错误 (维度不匹配)
        if unit_mismatch:
            for sid, ss in source_stats.items():
                dim = _get_unit_dimension(ss.get("unit"))
                if dim == "dimensionless" and ss["unit"]:
                    continue  # 可能是空单位
            anomalies.append({
                "anomaly_type": ANOMALY_UNIT,
                "field_name": fn,
                "entity_type": et,
                "entity_name": en,
                "units_found": {sid: ss["unit"] for sid, ss in source_stats.items()},
                "dimensions_found": {sid: _get_unit_dimension(ss["unit"])
                                    for sid, ss in source_stats.items()},
                "evidence": {"unit_dimension_mismatch": True},
                "severity": "critical",
            })

        # D. 交叉识别错误 (V3.2: 组内检测禁用, 由 Step 3.5 独立检测完成)

    # ── Step 3.5: 独立 Cross-ID 检测 (V3.2 fix) ──
    # 按 (entity_name, field_name) 分组 (忽略 entity_type),
    # 检测"同名实体被不同 entity_type 标记"的情况
    cross_id_groups: dict[tuple, dict[str, set]] = {}
    for rec in records:
        en = rec.get("entity_name", "") or ""
        fn = rec.get("field_name", "")
        et = rec.get("entity_type", "") or ""
        sid = rec.get("source_id", "")
        if not en or not fn:
            continue
        key = (en, fn)
        if key not in cross_id_groups:
            cross_id_groups[key] = {"types": set(), "sources": set()}
        if et:
            cross_id_groups[key]["types"].add(et)
        if sid:
            cross_id_groups[key]["sources"].add(sid)

    for (en, fn), info in cross_id_groups.items():
        if len(info["types"]) > 1:
            anomalies.append({
                "anomaly_type": ANOMALY_CROSS_ID,
                "entity_name": en,
                "field_name": fn,
                "entity_types_found": sorted(info["types"]),
                "source_ids": sorted(info["sources"]),
                "evidence": {"multiple_entity_types": True},
                "severity": "critical",
            })

    # ── Step 4: 汇总输出 ──
    variance_count = len(variances)
    anomaly_count = len(anomalies)

    if anomaly_count == 0:
        risk_level = "none"
    elif anomaly_count <= 2:
        risk_level = "low"
    elif anomaly_count <= 5:
        risk_level = "medium"
    else:
        risk_level = "high"

    summary_parts = []
    if variance_count > 0:
        cause_summary = {}
        for v in variances:
            c = v["inferred_cause"]
            cause_summary[c] = cause_summary.get(c, 0) + 1
        summary_parts.append(
            f"Multi-source variance: {variance_count} groups "
            + "(" + ", ".join(f"{k}={v}" for k, v in cause_summary.items()) + ")"
        )
    if anomaly_count > 0:
        anomaly_summary = {}
        for a in anomalies:
            t = a["anomaly_type"]
            anomaly_summary[t] = anomaly_summary.get(t, 0) + 1
        summary_parts.append(
            f"Anomalies: {anomaly_count} "
            + "(" + ", ".join(f"{k}={v}" for k, v in anomaly_summary.items()) + ")"
        )
    if skipped_insufficient:
        summary_parts.append(f"{skipped_insufficient} groups skipped (insufficient data)")

    if not summary_parts:
        summary_parts.append("No multi-source variance detected")

    logger.info(
        "[MultiSourceVariance] %d variances, %d anomalies, risk=%s",
        variance_count, anomaly_count, risk_level,
    )

    return {
        # V3.0 新字段
        "has_variance": variance_count > 0,
        "variance_count": variance_count,
        "variances": variances,
        "has_anomalies": anomaly_count > 0,
        "anomaly_count": anomaly_count,
        "anomalies": anomalies,
        # 向后兼容字段
        "has_conflicts": anomaly_count > 0,       # 只有异常才算冲突
        "conflict_count": anomaly_count,
        "conflicts": anomalies,                    # 兼容下游的 conflict_extractor
        "risk_level": risk_level,
        "method": "multi_source_variance",
        "skipped_insufficient": skipped_insufficient,
        "summary": "; ".join(summary_parts) + "。",
    }


# ==========================================================
# 向后兼容: detect_conflicts_statistical (V2.0 API)
# ==========================================================

def detect_conflicts_statistical(
    data: dict[str, Any],
    threshold: float = 0.20,
    use_advanced: bool = True,
) -> dict[str, Any]:
    """
    向后兼容的冲突检测函数 (V2.0 API)。

    V3.0 中内部调用 analyze_multi_source_variance(),
    返回包含旧字段 + 新字段的完整结果。

    Args:
        data: grounded_data JSON
        threshold: 忽略 (保留参数兼容)
        use_advanced: 忽略 (始终使用 V3.0 逻辑)。若为 False, 回退到旧版简单检测器。
    """
    if not use_advanced:
        from ...tools.assessment.conflict_detector import detect_conflicts
        return detect_conflicts(data, threshold)

    return analyze_multi_source_variance(data)


# ==========================================================
# Helpers
# ==========================================================

def _empty_result(summary: str) -> dict[str, Any]:
    return {
        "has_variance": False, "variance_count": 0, "variances": [],
        "has_anomalies": False, "anomaly_count": 0, "anomalies": [],
        "has_conflicts": False, "conflict_count": 0, "conflicts": [],
        "risk_level": "none", "method": "multi_source_variance",
        "skipped_insufficient": 0, "summary": summary,
    }
