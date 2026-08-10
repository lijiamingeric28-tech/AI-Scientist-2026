"""审计修复回归测试（由 test_audit_fixes_g*.py 合并，测试函数与辅助逻辑全部保留）"""

import pytest
import quality_pipeline  # noqa: F401
from subgraphs.data_assessment.agents.decision_reasoning_agent import DecisionReasoningAgent
from subgraphs.data_assessment.agents.profiling_agent import ProfilingAgent
from subgraphs.data_assessment.agents.quality_assessment_agent import QualityAssessmentAgent
from subgraphs.data_assessment.agents.quality_scoring_agent import QualityScoringAgent

# ==========================================================
# 来源: test_audit_fixes_g5.py
# ==========================================================
"""G5 组审计修复回归测试 (H-11 / M-04 / M-05 / L-09 / L-21 / L-24)

覆盖:
- H-11: scoring 节点 execution_status 透传 (A7 回归)
- M-04: profiling 统一读 current_data (E→A 重入不再基于过期数据)
- M-05: conditional_routes alias_fields 空守卫 (与主路由同款)
- L-09: decision_matrix 与路由同基准 (不再读 sr.issue_count)
- L-21: out_of_range 记录级计数 (分子分母同为记录数)
- L-24: Assessment LLM 完整性计数补记 llm_call_count

全部 0 网络 0 真实 LLM (L-24 用 monkeypatch 桩替换 analyze_missing_fields)。
"""





# ══════════════════════════════════════════════════════════
# 公共构造辅助
# ══════════════════════════════════════════════════════════

def _mk_record(rid, field="distance", value=100.0, unit="kpc",
               entity_type="G", entity_name="M31", sid="S1"):
    return {
        "record_id": rid, "source_id": sid,
        "entity_type": entity_type, "entity_name": entity_name,
        "field_name": field, "field_value": value, "field_unit": unit,
        "extraction_method": "database_query",
        "provenance": {"doi": "10.1000/x", "source_title": "Paper A",
                       "year": 2020, "access_path": "/data"},
    }


def _clean_src(expected=None, present=None, fmt_total=0, issue_count=0,
               quality_level="good", has_variance=False, variance_count=0,
               missing_unit=0, missing_prov=0):
    """构造决策 Agent 的"干净" source 报告 (可覆盖各缺陷场景)。"""
    expected = expected if expected is not None else ["a"]
    present = present if present is not None else ["a"]
    return {
        "record_count": 10, "title": "Paper A", "year": 2020,
        "extraction_quality": {"score": 1.0},
        "completeness": {
            "expected_fields": expected, "present_fields": present,
            "records_missing_unit": missing_unit,
            "records_missing_provenance": missing_prov,
            "records_missing_source": 0, "per_entity_missing": {},
        },
        "consistency": {"unit_consistency": {}},
        "format": {"total_issues": fmt_total},
        "source_reliability": {"score": 1.0},
        "conflict_risk": {
            "has_conflicts": False, "conflict_count": 0, "conflicts": [],
            "has_variance": has_variance, "variance_count": variance_count,
            "variances": [],
        },
        "quality_scoring": {"quality_level": quality_level, "overall_score": 0.9},
        "issue_count": issue_count,  # 模拟 quality_assessment 的 info 级计数
        "below_adaptive_threshold": False,
    }


def _decision_state(sources, records=None, profile=None):
    return {
        "report_state": {"quality": {
            "sources": sources,
            "profile": profile or {},
            "multi_source_variance": {"anomalies": [], "variances": []},
        }},
        "context_state": {"target_schema": {}, "quality_rules": {}},
        "data_state": {"current_data": {"records": records or [], "sources": []}},
        "workflow_state": {"execution_status": "Success", "retry_counter": 0,
                           "tool_call_count": 0},
    }


# ══════════════════════════════════════════════════════════
# H-11: scoring 节点 execution_status 透传
# ══════════════════════════════════════════════════════════

def test_scoring_passthrough_failed():
    """上游 Failed → scoring 必须透传, 不再硬编码 Success (A7 回归)。"""
    out = QualityScoringAgent().run({
        "report_state": {"quality": {}},
        "workflow_state": {"execution_status": "Failed", "tool_call_count": 0},
    })
    assert out["workflow_state"]["execution_status"] == "Failed"
    assert out["workflow_state"]["workflow_history"][0]["status"] == "Failed"


def test_scoring_passthrough_retry():
    """上游 Retry → scoring 透传 Retry。"""
    out = QualityScoringAgent().run({
        "report_state": {"quality": {}},
        "workflow_state": {"execution_status": "Retry", "tool_call_count": 0},
    })
    assert out["workflow_state"]["execution_status"] == "Retry"


def test_scoring_passthrough_success():
    """上游 Success → 保持 Success (正常路径行为不变)。"""
    out = QualityScoringAgent().run({
        "report_state": {"quality": {}},
        "workflow_state": {"execution_status": "Success", "tool_call_count": 0},
    })
    assert out["workflow_state"]["execution_status"] == "Success"
    # 其他非失败态 (如 None) 也不应意外变 Failed
    out2 = QualityScoringAgent().run({
        "report_state": {"quality": {}},
        "workflow_state": {"execution_status": None, "tool_call_count": 0},
    })
    assert out2["workflow_state"]["execution_status"] == "Success"


# ══════════════════════════════════════════════════════════
# M-04: profiling 统一读 current_data
# ══════════════════════════════════════════════════════════

def test_profiling_reads_current_data():
    """input_data 与 current_data 并存时, profile 必须基于 current_data。"""
    state = {
        "data_state": {
            "input_data": {"sources": [], "records": [_mk_record("r0")]},
            "current_data": {"sources": [],
                             "records": [_mk_record(f"r{i}") for i in range(3)]},
        },
        "context_state": {"research_domain": "default"},
        "workflow_state": {},
    }
    out = ProfilingAgent().run(state)
    ds = out["report_state"]["quality"]["profile"]["dataset_summary"]
    assert ds["record_count"] == 3, "profile 应基于 current_data (3 条)"


def test_profiling_falls_back_to_input_data():
    """current_data 缺失时回退 input_data (首次路径行为不变)。"""
    state = {
        "data_state": {"input_data": {"sources": [], "records": [_mk_record("r0")]}},
        "context_state": {"research_domain": "default"},
        "workflow_state": {},
    }
    out = ProfilingAgent().run(state)
    ds = out["report_state"]["quality"]["profile"]["dataset_summary"]
    assert ds["record_count"] == 1


# ══════════════════════════════════════════════════════════
# M-05: conditional_routes alias_fields 空守卫
# ══════════════════════════════════════════════════════════

def test_conditional_alias_guard_empty_expected():
    """expected_fields 为空 → 不得附加 alias_fields 条件 (与主路由同款守卫)。"""
    # present 有 a/b, expected 为空 → 若误判 alias 会全字段附条件
    src = _clean_src(expected=[], present=["a", "b"], fmt_total=1)
    out = DecisionReasoningAgent().run(_decision_state({"S1": src}))
    assert out["report_state"]["quality"]["per_source_routes"]["S1"] == "Normalization"
    conds = out["report_state"]["quality"]["conditional_routes"][0]["conditions"]
    assert not any(c["condition"] == "alias_fields" for c in conds), \
        f"expected 为空时不应有 alias_fields 条件: {conds}"


def test_conditional_alias_guard_present_when_expected():
    """expected 非空且确有别名 → alias_fields 条件仍正常附加 (守卫不破坏正常路径)。"""
    src = _clean_src(expected=["a"], present=["a", "b"], fmt_total=0)
    out = DecisionReasoningAgent().run(_decision_state({"S1": src}))
    conds = out["report_state"]["quality"]["conditional_routes"][0]["conditions"]
    assert any(c["condition"] == "alias_fields" for c in conds), f"缺少 alias_fields: {conds}"


# ══════════════════════════════════════════════════════════
# L-09: decision_matrix 与路由同基准
# ══════════════════════════════════════════════════════════

def test_matrix_consistent_with_route_variance_export():
    """5 个正常方差组 (info 级 issue_count=5) → 路由 Export, 矩阵必须同判 Export。

    旧实现读 sr.issue_count=5 → 误报 medium/Normalization, 与路由矛盾。
    """
    src = _clean_src(fmt_total=0, issue_count=5,
                     has_variance=True, variance_count=5)
    out = DecisionReasoningAgent().run(_decision_state({"S1": src}))
    quality = out["report_state"]["quality"]
    assert quality["per_source_routes"]["S1"] == "Export"
    dm = quality["decision_matrix"]["S1"]
    assert dm["repair_cost"] == "low", f"issue_count 是 info 级, 不应推高 repair_cost: {dm}"
    assert dm["matrix_route"] == "Export"
    assert dm["matrix_route"] == dm["rule_route"], "矩阵与主路由必须同基准"


def test_matrix_consistent_with_route_issues_normalization():
    """issues_found 有 4 项 (sr.issue_count=0) → 路由 Normalization, 矩阵必须同判。

    旧实现读 sr.issue_count=0 → 误报 low/Export, 与路由矛盾。
    """
    src = _clean_src(expected=["a"], present=["a", "b"], fmt_total=3,
                     missing_unit=3, missing_prov=3, issue_count=0)
    out = DecisionReasoningAgent().run(_decision_state({"S1": src}))
    quality = out["report_state"]["quality"]
    assert quality["per_source_routes"]["S1"] == "Normalization"
    dm = quality["decision_matrix"]["S1"]
    assert dm["repair_cost"] == "medium", f"4 项 issues_found 应推 medium: {dm}"
    assert dm["matrix_route"] == "Normalization"
    assert dm["matrix_route"] == dm["rule_route"], "矩阵与主路由必须同基准"


# ══════════════════════════════════════════════════════════
# L-21: out_of_range 记录级计数
# ══════════════════════════════════════════════════════════

def test_profile_out_of_range_record_level_count():
    """out_of_range_count 是覆盖记录数而非 (entity,field) 组合数。

    语义: out_of_range 标志按 (entity,field) 组判定 (组内任一条越界即标记),
    记录级计数 = 落在被标记组内的记录 id 集合大小。
    temperature 组被标记 → r1,r2 覆盖; elongation 组被标记 → r3 覆盖;
    旧口径只计 2 个字段组合, 新口径 3 条记录。
    """
    recs = [
        _mk_record("r1", field="temperature", value=1e6, unit="K"),   # 组被标记
        _mk_record("r2", field="temperature", value=300.0, unit="K"),  # 同组 → 被覆盖
        _mk_record("r3", field="elongation", value=150.0, unit="%",
                   entity_name="M32"),                                # 组被标记
    ]
    state = {"data_state": {"current_data": {"sources": [], "records": recs}},
             "context_state": {"research_domain": "default"},
             "workflow_state": {}}
    out = ProfilingAgent().run(state)
    profile = out["report_state"]["quality"]["profile"]
    assert profile["out_of_range_count"] == 3, \
        f"应为 3 条覆盖记录 (r1,r2,r3), 实际 {profile['out_of_range_count']}"


def test_profile_out_of_range_count_missing_record_id():
    """record_id 缺失时按记录去重计数, 不因同字段越界只计 1。

    1 个被标记组 (3 条记录) + 1 个正常组 → 覆盖 3 条记录;
    旧口径只计 1 个字段组合。
    """
    recs = [
        _mk_record("r1", field="temperature", value=1e6, unit="K"),
        _mk_record("r2", field="temperature", value=1e6, unit="K"),
        _mk_record("r3", field="temperature", value=1e6, unit="K"),
        _mk_record("r4", field="elongation", value=20.0, unit="%",
                   entity_name="M32"),
    ]
    for r in recs:
        r.pop("record_id")
    state = {"data_state": {"current_data": {"sources": [], "records": recs}},
             "context_state": {"research_domain": "default"},
             "workflow_state": {}}
    out = ProfilingAgent().run(state)
    assert out["report_state"]["quality"]["profile"]["out_of_range_count"] == 3, \
        f"应为 3 条覆盖记录, 实际 {out['report_state']['quality']['profile']['out_of_range_count']}"


def test_decision_oor_ratio_record_level_human():
    """4/5 记录越界 → 越界过半 → HumanReview (记录级比率)。"""
    src = _clean_src(fmt_total=0)
    records = [_mk_record(f"r{i}") for i in range(5)]
    profile = {"out_of_range_count": 4}
    out = DecisionReasoningAgent().run(_decision_state({"S1": src}, records, profile))
    assert out["report_state"]["quality"]["per_source_routes"]["S1"] == "HumanReview"


def test_decision_oor_ratio_record_level_normalization():
    """2/5 记录越界 (≤50%) → Normalization (不再触发 HumanReview)。"""
    src = _clean_src(fmt_total=0)
    records = [_mk_record(f"r{i}") for i in range(5)]
    profile = {"out_of_range_count": 2}
    out = DecisionReasoningAgent().run(_decision_state({"S1": src}, records, profile))
    assert out["report_state"]["quality"]["per_source_routes"]["S1"] == "Normalization"


# ══════════════════════════════════════════════════════════
# L-24: Assessment LLM 完整性计数补记
# ══════════════════════════════════════════════════════════

def _assessment_state(prev_llm_calls=0, target_fields=("distance", "redshift")):
    records = [_mk_record("r1")]
    return {
        "data_state": {"current_data": {
            "sources": [{"source_id": "S1", "title": "Paper A", "year": 2020}],
            "records": records,
        }},
        "context_state": {"research_domain": "default",
                          "target_schema": {"fields": [{"name": f} for f in target_fields]}},
        "report_state": {"quality": {}},
        "workflow_state": {"execution_status": "Success", "tool_call_count": 0,
                           "llm_call_count": prev_llm_calls},
    }


def test_llm_call_count_accumulated(monkeypatch):
    """缺失字段触发 LLM 完整性分析 → llm_call_count 按成功 sid 数累加 (L-24)。"""
    from quality_pipeline.tools.assessment import llm_completeness as llm_mod
    calls = []

    def _fake(title, present_fields, missing_fields, year=None):
        calls.append(title)
        return {"missing_expected_fields": list(missing_fields),
                "field_penalty": 0.1, "expected": "x", "optional": [], "irrelevant": []}

    monkeypatch.setattr(llm_mod, "analyze_missing_fields", _fake)
    out = QualityAssessmentAgent().run(_assessment_state(prev_llm_calls=3))
    assert len(calls) == 1, "应恰好 1 个 source 触发 LLM 完整性分析"
    assert out["workflow_state"]["llm_call_count"] == 4, \
        f"3 (历史) + 1 (本次) 应为 4, 实际 {out['workflow_state']['llm_call_count']}"
    assert out["report_state"]["quality"]["sources"]["S1"]["llm_completeness"] is not None


def test_llm_call_count_no_missing_fields():
    """无缺失字段 → 不触发 LLM → llm_call_count 保持原值 (累计语义一致)。"""
    out = QualityAssessmentAgent().run(
        _assessment_state(prev_llm_calls=5, target_fields=("distance",)))
    assert out["workflow_state"]["llm_call_count"] == 5
    src = out["report_state"]["quality"]["sources"]["S1"]
    assert src["llm_completeness"] is None


# ==========================================================
# 来源: test_audit_fixes_g6.py
# ==========================================================
"""G6 组审计修复回归测试 (H-02 / M-28 / M-29 / M-30 / M-31 / M-32 / L-10 / L-11 / L-12)

覆盖:
- H-02: format_checker DB 记录跳过 paper record_id 正则 (纯 DB 源可达 Export)
- M-28: consistency 数值/文本混合显式两族判定 (不再把 numeric+text 判 consistent)
- M-29: 统计冲突过滤非有限数值 ('NaN'/'inf' 字符串不再污染方差分析)
- M-30: 统计异常逐 pair 判定 (3 源 + 少数派 d>2.0 必须产出 anomaly)
- M-31: adaptive_threshold 域紧度乘子方向 (探索性更宽松, 精确更严格)
- M-32: 不对称误差 '12.3+1.4-2.1' 与 sexagesimal '12:34:56.7' 解析
- L-10: profiling 空串单位计缺失 (与 completeness V4 语义一致)
- L-11: per-entity bbox 缺失计数修复 (主循环 :86 判定对齐)
- L-12: ParenUncertainty 指数形式修正 ('1.2e-5(3)'/'1200(5)e3')

全部 0 网络 0 真实 LLM。
"""





# ══════════════════════════════════════════════════════════
# 公共构造辅助
# ══════════════════════════════════════════════════════════

def _mk_record6(rid, field="distance", value=100.0, unit="kpc",
               entity_type="G", entity_name="M31", sid="S1",
               method="database_query", tags=None):
    """构造一条 record (默认 DB 记录, 可指定 method/tags 控制差异原因推断)。"""
    rec = {
        "record_id": rid, "source_id": sid,
        "entity_type": entity_type, "entity_name": entity_name,
        "field_name": field, "field_value": value, "field_unit": unit,
        "extraction_method": method,
    }
    if tags is not None:
        rec["condition_tags"] = tags
    return rec


def _data(recs):
    sids = sorted({r["source_id"] for r in recs})
    return {"sources": [{"source_id": s} for s in sids], "records": recs}


def _clean_src6(expected=None, present=None, fmt_total=0):
    """构造决策 Agent 的"干净" source 报告。"""
    expected = expected if expected is not None else ["distance"]
    present = present if present is not None else ["distance"]
    return {
        "record_count": 10, "title": "Paper A", "year": 2020,
        "extraction_quality": {"score": 1.0},
        "completeness": {
            "expected_fields": expected, "present_fields": present,
            "records_missing_unit": 0, "records_missing_provenance": 0,
            "records_missing_source": 0, "per_entity_missing": {},
        },
        "consistency": {"unit_consistency": {}},
        "format": {"total_issues": fmt_total},
        "source_reliability": {"score": 1.0},
        "conflict_risk": {
            "has_conflicts": False, "conflict_count": 0, "conflicts": [],
            "has_variance": False, "variance_count": 0, "variances": [],
        },
        "quality_scoring": {"quality_level": "good", "overall_score": 0.9},
        "issue_count": 0,
        "below_adaptive_threshold": False,
    }


def _decision_state6(sources, records=None):
    return {
        "report_state": {"quality": {
            "sources": sources,
            "profile": {},
            "multi_source_variance": {"anomalies": [], "variances": []},
        }},
        "context_state": {"target_schema": {}, "quality_rules": {}},
        "data_state": {"current_data": {"records": records or [], "sources": []}},
        "workflow_state": {"execution_status": "Success", "retry_counter": 0,
                           "tool_call_count": 0},
    }


# ══════════════════════════════════════════════════════════
# H-02: format_checker DB 记录跳过 record_id 正则
# ══════════════════════════════════════════════════════════

def test_h02_db_records_skip_record_id_regex():
    """DB 记录 ('row1' 等非 paper 格式 record_id) 不再产生格式问题。"""
    from quality_pipeline.tools.assessment.format_checker import check_format
    records = [
        _mk_record6("row1", value="770.0"),
        _mk_record6("row2", value="780.0"),
    ]
    fmt = check_format({"records": records})
    assert fmt["record_id_format_issues"] == []
    assert fmt["total_issues"] == 0


def test_h02_paper_records_still_checked():
    """paper 记录 (非 database_query) 的 record_id 仍走原校验 (不过度跳过)。"""
    from quality_pipeline.tools.assessment.format_checker import check_format
    records = [_mk_record6("row1", value="770.0", method="llm_text")]
    fmt = check_format({"records": records})
    assert fmt["record_id_format_issues"] == ["row1"]


def test_h02_pure_db_source_routes_export():
    """H-02 决策级回归: 纯 DB 源 (record_id 非 paper 格式) 无格式问题 → 路由 Export。

    修复前 check_format 报 record_id 问题 → total_issues>0 → 路由 Normalization。
    """
    from quality_pipeline.tools.assessment.format_checker import check_format
    records = [
        _mk_record6("row1", value="770.0"),
        _mk_record6("row2", value="780.0"),
    ]
    fmt = check_format({"records": records})
    assert fmt["total_issues"] == 0
    src = _clean_src6(fmt_total=fmt["total_issues"])
    out = DecisionReasoningAgent().run(_decision_state6({"S1": src}, records))
    assert out["report_state"]["quality"]["per_source_routes"]["S1"] == "Export"


# ══════════════════════════════════════════════════════════
# M-28: consistency 数值/文本混合显式两族判定
# ══════════════════════════════════════════════════════════

def test_m28_numeric_text_mixed_inconsistent():
    """numeric + text 跨族混用 → 判不一致 (旧逻辑减掉 numeric 后恒 consistent)。"""
    from quality_pipeline.tools.assessment.consistency import check_consistency
    records = [
        _mk_record6("r1", field="distance", value="770", method="database_query"),
        _mk_record6("r2", field="distance", value="not observed", method="database_query"),
    ]
    r = check_consistency({"records": records})
    assert r["field_type_consistency"]["M31/distance"] is False


def test_m28_within_family_consistent():
    """数值族 (numeric+uncertainty) 与文本族 (text+null) 族内混用均一致。"""
    from quality_pipeline.tools.assessment.consistency import check_consistency
    numeric_family = [
        _mk_record6("r1", field="distance", value="770"),
        _mk_record6("r2", field="distance", value="770 ± 5"),
    ]
    r1 = check_consistency({"records": numeric_family})
    assert r1["field_type_consistency"]["M31/distance"] is True

    text_family = [
        {"record_id": "r1", "source_id": "S1", "field_name": "material",
         "field_value": None, "extraction_method": "database_query"},
        {"record_id": "r2", "source_id": "S1", "field_name": "material",
         "field_value": "steel", "extraction_method": "database_query"},
    ]
    r2 = check_consistency({"records": text_family})
    assert r2["field_type_consistency"]["material"] is True


# ══════════════════════════════════════════════════════════
# M-29: 统计冲突过滤非有限数值
# ══════════════════════════════════════════════════════════

def test_m29_inf_nan_excluded_from_variance():
    """'inf'/'NaN' 字符串不参与方差分析 — 不制造假 statistical_outlier。

    修复前 inf 组均值 inf → d=inf ≥ 2.0 → 假异常; nan 组均值 nan → 报告写 nan。
    """
    from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
    recs = [
        _mk_record6("r1", sid="S1", value="100.0"),
        _mk_record6("r2", sid="S2", value="100.5"),
        _mk_record6("r3", sid="S3", value="inf"),
        _mk_record6("r4", sid="S4", value="NaN"),
    ]
    r = analyze_multi_source_variance(_data(recs))
    assert r["anomalies"] == []
    # inf/NaN 源被排除后, 组内只剩 2 个有限源参与方差分析
    assert r["variance_count"] == 1
    assert r["variances"][0]["source_count"] == 2


# ══════════════════════════════════════════════════════════
# M-30: 统计异常逐 pair 判定
# ══════════════════════════════════════════════════════════

def test_m30_minority_large_d_pair_still_anomaly():
    """3 源 + 少数派 d>2.0 → 必须产出 anomaly (不再被组级多数原因门控)。

    S2/S3 同方法同条件且 d=9 → statistical_outlier; 另两对因 condition_tags
    不同判 condition_variance → 组级 primary=condition_variance, 旧逻辑 0 异常。
    """
    from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
    recs = [
        _mk_record6("r1", sid="S1", value="100.0", tags=["x"]),
        _mk_record6("r2", sid="S2", value="100.5", tags=["y"]),
        _mk_record6("r3", sid="S3", value="1000.0", tags=["y"]),
    ]
    r = analyze_multi_source_variance(_data(recs))
    types = [a["anomaly_type"] for a in r["anomalies"]]
    assert types.count("statistical_outlier") == 1
    # 组级原因确实是多数 (condition_variance) — 证明异常来自逐 pair 判定
    assert r["variances"][0]["inferred_cause"] == "condition_variance"
    assert r["anomalies"][0]["source_a"] == "S2"
    assert r["anomalies"][0]["source_b"] == "S3"


# ══════════════════════════════════════════════════════════
# M-31: adaptive_threshold 域紧度乘子方向
# ══════════════════════════════════════════════════════════

def test_m31_exploratory_looser_than_precise():
    """探索性 (astrophysics) 阈值 < 普通 < 精确 (materials_science)。

    旧配置 exploratory×1.30 反而更严格; 修复后 exploratory×0.80 更宽松。
    """
    from quality_pipeline.tools.assessment.adaptive_threshold import AdaptiveThresholdEngine
    engine = AdaptiveThresholdEngine()
    engine.set_domain("astrophysics")
    t_astro = engine.get_completeness_threshold("temperature", 5)
    engine.set_domain("biology")
    t_bio = engine.get_completeness_threshold("temperature", 5)
    engine.set_domain("materials_science")
    t_mat = engine.get_completeness_threshold("temperature", 5)
    assert t_astro < t_bio < t_mat


# ══════════════════════════════════════════════════════════
# M-32: 不对称误差 / sexagesimal 解析
# ══════════════════════════════════════════════════════════

def test_m32_asymmetric_error_parsed():
    """'12.3+1.4-2.1' (及空格系) 解析出首段数值, 不确定度取两侧较大偏差。"""
    from quality_pipeline.tools._parse_utils import is_numeric, parse_numeric, parse_uncertainty
    assert parse_numeric("12.3+1.4-2.1") == pytest.approx(12.3)
    assert parse_uncertainty("12.3+1.4-2.1") == pytest.approx(2.1)
    assert parse_numeric("12.3 +1.4 -2.1") == pytest.approx(12.3)
    assert parse_numeric("-12.3+1.4-2.1") == pytest.approx(-12.3)
    assert is_numeric("12.3+1.4-2.1")


def test_m32_sexagesimal_parsed():
    """'12:34:56.7' 转十进制度; 日期/非法分秒不误匹配。"""
    from quality_pipeline.tools._parse_utils import parse_numeric
    assert parse_numeric("12:34:56.7") == pytest.approx(12 + 34 / 60 + 56.7 / 3600)
    assert parse_numeric("12:34") == pytest.approx(12 + 34 / 60)
    assert parse_numeric("2024:01:01") is None  # 日期串 (首段≥360) 拒绝
    assert parse_numeric("12:99:00") is None    # 分 > 60 拒绝


def test_m32_parseable_strings_not_garbage():
    """format_checker 对可解析为数值的串不再报垃圾串 (V4 数值型字段分支)。"""
    from quality_pipeline.tools.assessment.format_checker import check_format
    records = [
        _mk_record6("r1", field="ra", value="12:34:56.7"),
        _mk_record6("r2", field="distance", value="12.3+1.4-2.1"),
    ]
    fmt = check_format({"records": records})
    assert fmt["string_format_issues"] == []
    assert fmt["total_issues"] == 0


# ══════════════════════════════════════════════════════════
# L-10: profiling 空串单位计缺失
# ══════════════════════════════════════════════════════════

def test_l10_empty_string_unit_counts_missing():
    """空串单位计缺失 (与 completeness V4 '空串=缺失' 语义一致)。"""
    from quality_pipeline.tools.assessment.profiling import data_profiling
    records = [
        _mk_record6("r1", value="770", unit=""),
        _mk_record6("r2", value="780", unit="kpc"),
    ]
    p = data_profiling({"sources": [{"source_id": "S1"}], "records": records})
    assert p["records_with_units"] == 1
    assert p["records_without_units"] == 1


# ══════════════════════════════════════════════════════════
# L-11: per-entity bbox 缺失计数
# ══════════════════════════════════════════════════════════

def test_l11_per_entity_bbox_missing_counted():
    """缺 bbox 的 paper 记录计入 per-entity 分数 (旧 not(...)[0:4] 恒 False)。"""
    from quality_pipeline.tools.assessment.extraction_quality import check_extraction_quality
    records = [
        {"record_id": "r1", "source_id": "S1", "field_name": "distance",
         "field_value": "770", "entity_type": "G", "entity_name": "M31",
         "extraction_method": "llm_text", "trace_id": "t1",
         "provenance": {"page": 1, "bbox": [1, 2, 3, 4]}},
        {"record_id": "r2", "source_id": "S1", "field_name": "distance",
         "field_value": "780", "entity_type": "G", "entity_name": "M31",
         "extraction_method": "llm_text", "trace_id": "t2",
         "provenance": {"page": 2}},  # 缺 bbox
    ]
    r = check_extraction_quality(records)
    assert r["missing_bbox"] == 1
    assert r["per_entity_issues"]["G:M31"] == ["missing bbox: 1/2"]
    assert r["per_entity_scores"]["G:M31"] < 1.0


# ══════════════════════════════════════════════════════════
# L-12: ParenUncertainty 指数形式修正
# ══════════════════════════════════════════════════════════

def test_l12_paren_uncertainty_exponent():
    """'1.2e-5(3)' 不确定度 3e-6 (旧实现 3e-4 偏差 100 倍); '1200(5)e3' 支持。"""
    from quality_pipeline.tools._parse_utils import parse_numeric, parse_uncertainty
    assert parse_numeric("1.2e-5(3)") == pytest.approx(1.2e-5)
    assert parse_uncertainty("1.2e-5(3)") == pytest.approx(3e-6)
    assert parse_numeric("1200(5)e3") == pytest.approx(1.2e6)
    assert parse_uncertainty("1200(5)e3") == pytest.approx(5000.0)


def test_l12_regular_paren_unchanged():
    """常规括号不确定度格式不回归。"""
    from quality_pipeline.tools._parse_utils import parse_uncertainty
    assert parse_uncertainty("776.2(5)") == pytest.approx(0.5)
    assert parse_uncertainty("0.0802(73)") == pytest.approx(0.0073)
    assert parse_uncertainty("790(3)") == pytest.approx(3.0)

