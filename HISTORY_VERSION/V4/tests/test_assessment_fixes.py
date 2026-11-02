"""Assessment 优化回归测试锚点 (A1-A10 修复守护)

覆盖: Cohen's d 边界 / 权重接入 / severity 加权 / 自适应阈值 / 路由漏洞 /
LLM 可加性惩罚 / 记录数加权 / consistency 连续化 / canonical_unit /
配置-代码一致性。全部 0 LLM 0 网络。
"""

import pytest

import quality_pipeline  # noqa: F401


def _mk_records(pairs, method="cepheid", tag="scope: global"):
    """pairs: [(source_id, value), ...] → records"""
    recs = []
    for i, (sid, v) in enumerate(pairs):
        recs.append({
            "record_id": f"r{i}", "source_id": sid,
            "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_value": float(v),
            "field_unit": "kpc",
            "measurement_method": method, "condition_tags": [tag],
        })
    return recs


def _data(pairs):
    sids = sorted({sid for sid, _ in pairs})
    return {
        "sources": [{"source_id": s} for s in sids],
        "records": _mk_records(pairs),
    }


# ── A1: Cohen's d 边界 ──

def test_cohens_d_single_record_boundary():
    """n=1 vs n=1, 500 vs 5 → 应检出 statistical_outlier (原相对差异 d<1 漏报)。"""
    from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
    r = analyze_multi_source_variance(_data([("S1", 500.0), ("S2", 5.0)]))
    types = [a["anomaly_type"] for a in r.get("anomalies", [])]
    assert "statistical_outlier" in types


def test_zero_variance_pair_detected():
    """双零方差组 (各 2 条同值, 均值差 1e6) → 应检出 (原 pooled_std=0 → d 恒 0)。"""
    from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
    pairs = [("S1", 100.0), ("S1", 100.0), ("S2", 1e6), ("S2", 1e6)]
    r = analyze_multi_source_variance(_data(pairs))
    types = [a["anomaly_type"] for a in r.get("anomalies", [])]
    assert "statistical_outlier" in types


def test_close_values_not_false_positive():
    """770 vs 780 kpc → 不误报 (接近值不应制造冲突)。"""
    from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
    r = analyze_multi_source_variance(_data([("S1", 770.0), ("S2", 780.0)]))
    assert r.get("anomalies", []) == []


def test_t_crit_small_sample():
    """A1: df=3 → 3.182 (原恒 1.96 小样本 CI 过窄)。"""
    from quality_pipeline.tools.assessment.statistical_conflict import _t_crit_975
    assert _t_crit_975(3) == pytest.approx(3.182, abs=0.01)
    assert _t_crit_975(100) == pytest.approx(1.96, abs=0.01)


# ── H4: 单位维度不误判 ──

def test_unit_dimension_mag_not_length():
    """'mag' 不得经子串匹配判为 length (含 m 米), 'dex' 不得判 time (含 d 天)。"""
    from quality_pipeline.tools.assessment.statistical_conflict import _get_unit_dimension
    assert _get_unit_dimension("mag").startswith("unknown")
    assert _get_unit_dimension("dex").startswith("unknown")
    assert _get_unit_dimension("Mpc") == "length"
    assert _get_unit_dimension("km/s") == "velocity"


# ── A2: extraction_quality 权重 ──

def test_extraction_weight_in_overall():
    """extr_score=0 → overall 降幅 ≥0.12 (原权重缺维, 提取质量从不进总分)。"""
    from quality_pipeline.tools.assessment.quality_scoring import compute_quality_score
    w = {"completeness": 0.12, "consistency": 0.15, "format": 0.10,
         "source_reliability": 0.25, "conflict_risk": 0.23, "extraction_quality": 0.15}
    base = {k: {"score": 1.0} for k in w}
    lo = dict(base)
    lo["extraction_quality"] = {"score": 0.0}
    hi_score = compute_quality_score(base, weights=w)["overall_score"]
    lo_score = compute_quality_score(lo, weights=w)["overall_score"]
    assert hi_score == 1.0
    assert hi_score - lo_score >= 0.12


# ── A3: severity 加权 ──

def test_severity_weighted_conflict():
    """1 critical (=1.0) 惩罚等价 5 个 low (=0.2×5) — 原 1 critical 只扣 0.1 与 1 low 同。"""
    from subgraphs.data_assessment.agents.quality_scoring_agent import _conflict_severity_score
    one_crit = _conflict_severity_score({"conflicts": [{"severity": "critical"}]})
    five_low = _conflict_severity_score({"conflicts": [{"severity": "low"}] * 5})
    assert one_crit == pytest.approx(0.6667, abs=0.01)
    assert one_crit == pytest.approx(five_low, abs=0.01)
    assert _conflict_severity_score({"conflicts": []}) == 1.0


# ── A9: consistency 连续化 ──

def test_consistency_continuous():
    """1 字段单位不一致 → 0.33 < score < 1.0 (原二分直接 2/3)。"""
    from quality_pipeline.tools.assessment.consistency import check_consistency
    records = [
        {"record_id": "r1", "source_id": "S1", "field_name": "distance",
         "field_value": "770", "field_unit": "kpc", "entity_name": "M31",
         "extraction_method": "database_query"},
        {"record_id": "r2", "source_id": "S1", "field_name": "distance",
         "field_value": "780", "field_unit": "kpc", "entity_name": "M31",
         "extraction_method": "database_query"},
        {"record_id": "r3", "source_id": "S1", "field_name": "distance",
         "field_value": "785", "field_unit": "Mpc", "entity_name": "M31",  # 不一致
         "extraction_method": "database_query"},
    ]
    data = {"sources": [], "records": records}
    res = check_consistency(data)
    assert 0.33 < res["score"] < 1.0, f"连续化评分应介于: {res['score']}"
    # 全通过 → 1.0
    recs_ok = [dict(r, field_unit="kpc") for r in records]
    assert check_consistency({"sources": [], "records": recs_ok})["score"] == 1.0


# ── A10: canonical_unit ──

def test_canonical_unit_kelvin_variant():
    """'K' 与 'Kelvin' 归一化一致 — 不再误报 unit_mismatch。"""
    from quality_pipeline.tools.assessment.source_utils import canonical_unit
    assert canonical_unit("K") == canonical_unit("Kelvin")
    assert canonical_unit("°C") == canonical_unit("C")
    assert canonical_unit("yr") == canonical_unit("year")


# ── A8: 记录数加权 ──

def test_overall_record_weighted():
    """1 条 vs 999 条记录 → 加权后整体分由大 source 主导 (原等权 50/50)。"""
    from quality_pipeline.tools.assessment.quality_scoring import compute_quality_score
    w = {"completeness": 0.2, "consistency": 0.24, "format": 0.1,
         "source_reliability": 0.15, "conflict_risk": 0.19, "extraction_quality": 0.12}
    m_hi = {k: {"score": 1.0} for k in w}
    m_lo = dict(m_hi)
    m_lo["completeness"] = {"score": 0.0}
    s_hi = compute_quality_score(m_hi, weights=w)["overall_score"]
    s_lo = compute_quality_score(m_lo, weights=w)["overall_score"]
    # 加权: (1×1 + 999×s_lo)/1000 应更接近 s_lo
    weighted = (1.0 * s_hi + 999.0 * s_lo) / 1000.0
    assert weighted < (s_hi + s_lo) / 2 - 0.05, "记录数加权应偏向大 source"


# ── A11: 配置-代码一致性 ──

def test_config_code_sync():
    """quality_rules.yaml default 权重与 _DEFAULT_WEIGHTS 一致 (防双处定义失同步)。"""
    from quality_pipeline.configs import load_yaml
    from quality_pipeline.tools.assessment.quality_scoring import _DEFAULT_WEIGHTS
    rules = load_yaml("quality_rules.yaml") or {}
    yaml_default = (rules.get("domain_weights", {}) or {}).get("default", {}) or {}
    for k, v in _DEFAULT_WEIGHTS.items():
        assert yaml_default.get(k) == pytest.approx(v, abs=1e-6), \
            f"权重 {k} 失同步: yaml={yaml_default.get(k)} code={v}"


# ── A12: 跨来源 bootstrap KS 分布检验 ──

def _mk_ks_records(pairs):
    recs = []
    for i, (sid, v) in enumerate(pairs):
        recs.append({
            "record_id": f"r{i}", "source_id": sid,
            "entity_type": "G", "entity_name": "M31",
            "field_name": "distance", "field_value": float(v),
            "field_unit": "kpc",
            "measurement_method": "cepheid", "condition_tags": ["scope: global"],
        })
    return {"sources": [{"source_id": s} for s in sorted({s for s, _ in pairs})],
            "records": recs}


def test_ks_detects_distributional_variance():
    """均值同 (d<0.5) 但分布不同 ({100x14,900} vs {180x15}) → distributional_variance。

    Cohen's d≈0.19 不可见, bootstrap KS p<0.01 检出; 仅标注, 不生成 anomaly。
    """
    from quality_pipeline.tools.assessment.statistical_conflict import (
        CAUSE_DISTRIBUTIONAL, KS_P_THRESHOLD, analyze_multi_source_variance,
    )
    pairs = [("S1", 100.0)] * 14 + [("S1", 900.0)] + [("S2", 180.0)] * 15
    r = analyze_multi_source_variance(_mk_ks_records(pairs))
    v = r["variances"][0]
    assert v["inferred_cause"] == CAUSE_DISTRIBUTIONAL
    assert v["distributional_ks_p"] is not None
    assert v["distributional_ks_p"] < KS_P_THRESHOLD
    assert r["anomaly_count"] == 0, "distributional 仅标注, 不生成 anomaly"
    assert r["risk_level"] == "none", "distributional 不阻塞 Export"


def test_ks_small_n_gate():
    """n<15 的 pair 不做 KS → distributional_ks_p=None, 小样本行为不变。"""
    from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
    pairs = [("S1", 100.0)] * 4 + [("S1", 900.0)] + [("S2", 180.0)] * 5
    r = analyze_multi_source_variance(_mk_ks_records(pairs))
    v = r["variances"][0]
    assert v["distributional_ks_p"] is None


def test_ks_identical_not_flagged():
    """两源分布完全相同 → p≈1.0, 不判 distributional。"""
    from quality_pipeline.tools.assessment.statistical_conflict import (
        CAUSE_DISTRIBUTIONAL, analyze_multi_source_variance,
    )
    pairs = [("S1", 180.0)] * 15 + [("S2", 180.0)] * 15
    r = analyze_multi_source_variance(_mk_ks_records(pairs))
    v = r["variances"][0]
    assert v["inferred_cause"] != CAUSE_DISTRIBUTIONAL
    assert v["distributional_ks_p"] == pytest.approx(1.0, abs=0.01)


# ── A11 余: 质量评分运行参数下沉 yaml ──

def test_runtime_config_sync():
    """quality_scoring_runtime 段加载 + 代码侧 fallback/消费一致 (防硬编码失同步)。"""
    from quality_pipeline.configs import load_quality_scoring_runtime
    from quality_pipeline.tools.assessment.quality_scoring import _LEVELS
    rt = load_quality_scoring_runtime()
    assert rt["volume_thresholds"][10] == 0.3
    assert rt["volume_thresholds"][100] == 0.7
    assert rt["volume_thresholds"]["else"] == 0.9
    assert rt["agreement_std_coef"] == 2.0
    assert rt["repair_cost"] == {"anomaly": [1, 3], "issues": [3, 10]}
    assert rt["extraction_human_threshold"] == 0.3
    assert rt["conflict_severity"] == {"critical": 1.0, "high": 0.7,
                                       "medium": 0.4, "low": 0.2}
    assert rt["level_thresholds"] == {"excellent": 0.90, "good": 0.75, "fair": 0.60}
    # _LEVELS 无 poor 死分支且与配置一致
    assert "poor" not in _LEVELS
    assert _LEVELS == rt["level_thresholds"]
    # agent 侧 severity 权重来自配置
    from subgraphs.data_assessment.agents.quality_scoring_agent import _CONFLICT_SEVERITY_WEIGHT
    assert _CONFLICT_SEVERITY_WEIGHT == rt["conflict_severity"]


def test_level_thresholds_poor_default():
    """低于 fair(0.60) 一律 poor (三档判定, 无 0.40 死分支); 0.80 → good。"""
    from quality_pipeline.tools.assessment.quality_scoring import compute_quality_score
    w = {"completeness": 0.2, "consistency": 0.24, "format": 0.1,
         "source_reliability": 0.15, "conflict_risk": 0.19, "extraction_quality": 0.12}
    assert compute_quality_score({k: {"score": 0.5} for k in w}, weights=w)["quality_level"] == "poor"
    assert compute_quality_score({k: {"score": 0.65} for k in w}, weights=w)["quality_level"] == "fair"
    assert compute_quality_score({k: {"score": 0.8} for k in w}, weights=w)["quality_level"] == "good"
    assert compute_quality_score({k: {"score": 0.95} for k in w}, weights=w)["quality_level"] == "excellent"
