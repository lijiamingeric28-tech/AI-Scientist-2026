"""
test_full_pipeline.py — Assessment V2.0 完整流程测试

覆盖:
  - 多源数据模拟 (含冲突/缺失/格式问题/异常值)
  - 4 Agent 逐 Stage 执行
  - LLM 调用计时 + 返回结果
  - 调用次数统计
  - 最终 Quality Report 输出

用法:
  cd V1
  python test_full_pipeline.py
"""

import sys, io, json, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from utils.logger import setup_logging; setup_logging()
from utils.llm import reset_llm, reset_llm_stats; reset_llm(); reset_llm_stats()

from quality_state import make_initial_state
from configs import load_yaml

# ══════════════════════════════════════════════════════════
# 手工构造多源测试数据 (3篇论文, 带可控噪声)
# ══════════════════════════════════════════════════════════

def build_test_data():
    """构建 3 篇论文的测试数据, 每篇有不同质量问题。"""
    return {
        "schema_version": "1.0.0",
        "sources": [
            {
                "source_id": "10.1016/j.msea.2023.001",
                "source_type": "paper",
                "doi": "10.1016/j.msea.2023.001",
                "title": "High-temperature tensile properties of Al-7075 alloy",
                "authors": ["Zhang, W.", "Li, H.", "Chen, Y."],
                "year": 2023,
                "journal": "Materials Science and Engineering: A",
                "access_path": "/cache/msea_2023_001.pdf",
                "retrieval_priority": 0.95,
            },
            {
                "source_id": "10.1007/s11661-022-002",
                "source_type": "paper",
                "doi": "10.1007/s11661-022-002",
                "title": "Effect of aging on Al-Zn-Mg-Cu alloy mechanical properties",
                "authors": ["Wang, X.", "Liu, J."],
                "year": 2022,
                "journal": "Metallurgical and Materials Transactions A",
                "access_path": "/cache/mmta_2022_002.pdf",
                "retrieval_priority": 0.87,
            },
            {
                "source_id": "10.1016/j.actamat.2024.003",
                "source_type": "paper",
                "doi": "10.1016/j.actamat.2024.003",
                "title": "Strain rate effects on Al-7075 mechanical response",
                "authors": ["Kim, S.", "Park, J."],
                "year": 2024,
                "journal": "Acta Materialia",
                "access_path": "/cache/actamat_2024_003.pdf",
                "retrieval_priority": 0.92,
            },
        ],
        "records": [
            # ── Paper 1: Al-7075, 高质量 ──
            {"record_id": "p1_yield_1",  "source_id": "10.1016/j.msea.2023.001",
             "field_name": "yield_strength",  "field_value": 450, "field_unit": "MPa",
             "trace_id": "doc1_p3_tb2_r1", "provenance": {"page": 3, "bbox": [120,340,280,355]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_tensile_1","source_id": "10.1016/j.msea.2023.001",
             "field_name": "tensile_strength","field_value": 520, "field_unit": "MPa",
             "trace_id": "doc1_p3_tb2_r2", "provenance": {"page": 3, "bbox": [120,356,280,371]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_temp_1",   "source_id": "10.1016/j.msea.2023.001",
             "field_name": "temperature",    "field_value": 200, "field_unit": "C",
             "trace_id": "doc1_p3_tb1_h1", "provenance": {"page": 3, "bbox": [100,300,150,315]},
             "extraction_method": "llm_text"},
            {"record_id": "p1_elong_1",  "source_id": "10.1016/j.msea.2023.001",
             "field_name": "elongation",     "field_value": 12.5, "field_unit": "%",
             "trace_id": "doc1_p3_tb2_r3", "provenance": {"page": 3, "bbox": [120,372,280,387]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_hard_1",   "source_id": "10.1016/j.msea.2023.001",
             "field_name": "hardness",       "field_value": 185, "field_unit": "HV",
             "trace_id": "doc1_p4_tb1_r1", "provenance": {"page": 4, "bbox": [90,200,250,215]},
             "extraction_method": "llm_table"},

            # ── Paper 2: Al-Zn-Mg-Cu, 有冲突 + 格式问题 ──
            {"record_id": "p2_yield_1",  "source_id": "10.1007/s11661-022-002",
             "field_name": "yield_strength",  "field_value": 438, "field_unit": "MPa",
             "trace_id": "doc2_p5_tb1_r3", "provenance": {"page": 5, "bbox": [90,420,250,435]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_tensile_1","source_id": "10.1007/s11661-022-002",
             "field_name": "tensile_strength","field_value": "~505", "field_unit": "GPa",
             "trace_id": "doc2_p5_tb1_r4", "provenance": {"page": 5, "bbox": [90,436,250,451]},
             "extraction_method": "llm_text"},
            {"record_id": "p2_temp_1",   "source_id": "10.1007/s11661-022-002",
             "field_name": "test_temperature","field_value": 120, "field_unit": "C",
             "trace_id": "doc2_p5_tb1_h2", "provenance": {"page": 5, "bbox": [90,396,150,411]},
             "extraction_method": "llm_text"},
            {"record_id": "p2_elong_1",  "source_id": "10.1007/s11661-022-002",
             "field_name": "EL",              "field_value": 14.2, "field_unit": "%",
             "trace_id": "doc2_p5_tb1_r5", "provenance": {"page": 5, "bbox": [90,452,250,467]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_density_1","source_id": "10.1007/s11661-022-002",
             "field_name": "density",         "field_value": 2.81, "field_unit": None,
             "trace_id": "doc2_p6_p1",      "provenance": {"page": 6, "bbox": None},
             "extraction_method": "llm_text"},

            # ── Paper 3: Al-7075, 少字段 + 异常值 ──
            {"record_id": "p3_yield_1",  "source_id": "10.1016/j.actamat.2024.003",
             "field_name": "yield_strength",  "field_value": 1200, "field_unit": "MPa",
             "trace_id": "doc3_p4_tb1_r1", "provenance": {"page": 4, "bbox": [80,300,240,315]},
             "extraction_method": "llm_table"},
            {"record_id": "p3_tensile_1","source_id": "10.1016/j.actamat.2024.003",
             "field_name": "tensile_strength","field_value": 1350, "field_unit": "MPa",
             "trace_id": "doc3_p4_tb1_r2", "provenance": {"page": 4, "bbox": [80,316,240,331]},
             "extraction_method": "llm_table"},
        ],
    }

# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════

def hdr(title):
    print(f'\n{"=" * 70}')
    print(f'  {title}')
    print(f'{"=" * 70}')

def sub(title):
    print(f'\n{"─" * 70}')
    print(f'  {title}')
    print(f'{"─" * 70}')

# ══════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════

def main():
    t_total_start = time.time()

    hdr('Assessment V2.0 — 完整流程测试')

    # ── 加载数据 ──
    input_data = build_test_data()
    state = make_initial_state(input_data)
    state['context_state'].update({
        'quality_rules': load_yaml('quality_rules.yaml'),
        'target_schema': load_yaml('schema_mapping.yaml').get('target_schema', {}),
        'research_domain': 'materials_science',
    })

    print(f'\n输入数据: {len(input_data["sources"])} 篇论文, {len(input_data["records"])} 条记录')
    for src in input_data['sources']:
        print(f'  [{src["source_id"][:25]}] {src["title"][:60]} ({src["year"]})')
    print(f'\n噪声设计:')
    print(f'  Paper 1: 高质量 (5 records, 完整)')
    print(f'  Paper 2: 格式问题 ("~505", 单位 GPa→MPa, 别名 EL→elongation, 缺单位, 缺溯源)')
    print(f'  Paper 3: 异常值 (yield=1200, tensile=1350 — 可能超物理范围), 仅2字段')

    # ═══ Stage 1 ═══
    sub('Stage 1: ProfilingAgent')
    t1 = time.time()
    from Data_Assessment_agentV1.agents.profiling_agent import ProfilingAgent
    s1 = ProfilingAgent().run(state); state = {**state, **s1}
    t1e = time.time() - t1

    p = s1['report_state']['quality']['profile']
    print(f'  执行耗时: {t1e:.3f}s')
    print(f'  状态: {s1["workflow_state"]["execution_status"]}')
    print(f'  数据集: {p["dataset_summary"]["record_count"]} records, '
          f'{p["dataset_summary"]["source_count"]} sources, '
          f'{p["dataset_summary"]["field_count"]} fields')
    print(f'  Schema 缺失: {p["schema_summary"]["missing_fields"]}')
    print(f'  Schema 多余: {p["schema_summary"]["extra_fields"]}')
    print(f'  物理不可行值: {p["out_of_range_count"]}')

    print(f'\n  分布分析 (P1):')
    for fn, d in p.get('distributions', {}).items():
        if d.get('distribution_type') == 'unknown':
            print(f'    {fn:20s} | insufficient data')
        else:
            print(f'    {fn:20s} | {d.get("distribution_type","?"):15s} | '
                  f'skew={d.get("skewness",0):+.3f} kurt={d.get("kurtosis",0):+.3f} | '
                  f'P50={d.get("quantiles",{}).get("P50",0):.1f} IQR={d.get("iqr",0):.1f}')

    print(f'\n  语义推断 (P3):')
    for fn, st in p.get('semantic_types', {}).items():
        print(f'    {fn:20s} → {st["semantic_type"] or "unknown":20s} '
              f'conf={st["confidence"]:.2f} plausible={st["physically_plausible"]}')

    print(f'\n  异常值 (P2):')
    for fn, ol in p.get('outliers', {}).items():
        if ol['outliers']:
            for o in ol['outliers']:
                print(f'    {fn}: value={o["value"]} label={o["label"]} z={o["modified_z_score"]:.1f}')
    if not any(ol['outliers'] for ol in p.get('outliers', {}).values()):
        print(f'    (无异常值 — 样本量较小)')

    # ═══ Stage 2 ═══
    sub('Stage 2: QualityAssessmentAgent (per-source, A1/A2/A3)')
    t2 = time.time()
    from Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
    s2 = QualityAssessmentAgent().run(state); state = {**state, **s2}
    t2e = time.time() - t2

    q = s2['report_state']['quality']
    print(f'  执行耗时: {t2e:.3f}s')
    print(f'  Sources 评估: {len(q["sources"])}')

    for sid, sr in q['sources'].items():
        title = sr.get('title', sid)[:50]
        cr = sr['conflict_risk']
        method = cr.get('method', 'N/A')
        lc = sr.get('llm_completeness')
        print(f'\n  [{sid[:25]}] {title}')
        print(f'    records={sr["record_count"]}, '
              f'comp={sr["completeness"]["score"]:.2f}, '
              f'cons={sr["consistency"]["score"]:.2f}, '
              f'fmt={sr["format"]["score"]:.2f}, '
              f'src_rel={sr["source_reliability"]["score"]:.2f}')
        print(f'    冲突检测 ({method}): {cr["conflict_count"]} conflicts, risk={cr["risk_level"]}')
        if cr.get('conflicts'):
            for c in cr['conflicts'][:3]:
                print(f'      [{c["field_name"]}] cohens_d={c["cohens_d"]:.2f} '
                      f'effect={c["effect_size"]} CI={c["ci_95"]} '
                      f'A({c["n_a"]}recs)={c["mean_a"]} vs B({c["n_b"]}recs)={c["mean_b"]}')
        if lc:
            print(f'    LLM 完整性分析 (A3): {lc.get("summary", "")[:120]}')
        if sr.get('below_adaptive_threshold'):
            print(f'    低于自适应阈值')
        if sr['issues']:
            for iss in sr['issues'][:3]:
                print(f'    issue: [{iss["dimension"]}] {iss["detail"][:80]}')

    # ═══ Stage 3 ═══
    sub('Stage 3: QualityScoringAgent (S1/S2/S3)')
    t3 = time.time()
    from Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
    s3 = QualityScoringAgent().run(state); state = {**state, **s3}
    t3e = time.time() - t3

    sc = s3['report_state']['quality']['quality_scoring']
    print(f'  执行耗时: {t3e:.3f}s')
    print(f'  领域权重 (S1): {list(sc.get("dimension_weights", {}).keys())}')
    print(f'  惩罚 (S2): {sc.get("penalty_applied", False)} — {sc.get("penalty_reason", "N/A")}')
    print(f'  校准置信度 (S3): {sc.get("calibrated_confidence", "N/A")} '
          f'(volume={sc.get("confidence_factors",{}).get("data_volume","?")}, '
          f'agreement={sc.get("confidence_factors",{}).get("agreement","?")}, '
          f'sparsity={sc.get("confidence_factors",{}).get("sparsity","?")})')
    print(f'\n  Per-source scores:')
    for sid, score in sc['per_source_scores'].items():
        sr = q['sources'].get(sid, {})
        lvl = sr.get('quality_scoring', {}).get('quality_level', '?')
        title = sr.get('title', sid)[:45]
        print(f'    {title:45s} → {score:.4f} ({lvl})')
    print(f'\n  Overall: {sc["overall_score"]:.4f} ({sc["quality_level"]})')

    # ═══ Stage 4 ═══
    sub('Stage 4: DecisionReasoningAgent (D1/D2/D3)')
    t4 = time.time()
    from Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
    s4 = DecisionReasoningAgent().run(state); state = {**state, **s4}
    t4e = time.time() - t4

    dq = s4['report_state']['quality']
    print(f'  执行耗时: {t4e:.3f}s')
    print(f'\n  D1: LLM Per-Source 决策:')
    for sid, route in dq['per_source_routes'].items():
        reason = dq['per_source_reasons'].get(sid, '')[:100]
        title = q['sources'].get(sid, {}).get('title', sid)[:40]
        print(f'    {title:40s} → {route:15s} | {reason}')

    print(f'\n  D2: 决策矩阵 (Quality × Repair Cost):')
    for sid, dm in dq.get('decision_matrix', {}).items():
        title = q['sources'].get(sid, {}).get('title', sid)[:40]
        print(f'    {title:40s} | Q={dm["quality_level"]:9s} '
              f'Cost={dm["repair_cost"]:6s} → matrix={dm["matrix_route"]:15s} '
              f'rule={dm["rule_route"]}')

    print(f'\n  D3: 条件路由 (前2个 source):')
    for cr in dq.get('conditional_routes', [])[:2]:
        print(f'    [{cr["source_id"][:25]}] primary={cr["primary_route"]}')
        for c in cr['conditions']:
            print(f'      condition={c["condition"]:20s} → {c["route"]:15s} | {c["reason"][:60]}')

    print(f'\n  Aggregation:')
    print(f'    Overall Route: {dq["route_decision"]}')
    print(f'    Need Normalization: {dq["need_normalization"]}')
    print(f'    Need Conflict: {dq["need_conflict_analysis"]}')

    # ═══ LLM 统计 ═══
    hdr('LLM 调用统计 + 耗时汇总')
    from utils.llm import print_llm_stats
    print_llm_stats()

    print(f'\n  各 Stage 耗时:')
    print(f'    Stage 1 (Profiling):     {t1e:.3f}s')
    print(f'    Stage 2 (Assessment):    {t2e:.3f}s')
    print(f'    Stage 3 (Scoring):       {t3e:.3f}s')
    print(f'    Stage 4 (Decision):      {t4e:.3f}s')
    print(f'    ─────────────────────────')
    print(f'    Total:                   {time.time() - t_total_start:.1f}s')

    # ═══ 最终 Quality Report ═══
    hdr('FINAL QUALITY REPORT')
    fq = state['report_state']['quality']
    sc = fq.get('quality_scoring', {})
    print(f'')
    print(f'  Records Analyzed:      {fq["profile"]["dataset_summary"]["record_count"]}')
    print(f'  Sources:               {fq["profile"]["dataset_summary"]["source_count"]}')
    print(f'  Fields:                {fq["profile"]["dataset_summary"]["field_count"]}')
    print(f'  Physically Implausible:{fq["profile"]["out_of_range_count"]}')
    print(f'  Quality Score:         {sc.get("overall_score", "N/A"):.4f}')
    print(f'  Quality Level:         {sc.get("quality_level", "N/A")}')
    print(f'  Calibrated Confidence: {sc.get("calibrated_confidence", "N/A")}')
    print(f'  Issues Found:          {fq["total_issues"]}')
    print(f'  Conflicts:             {fq["total_conflicts"]}')
    print(f'  Need Normalization:    {fq["need_normalization"]}')
    print(f'  Need Conflict:         {fq["need_conflict_analysis"]}')
    print(f'  Overall Route:         {fq["route_decision"]}')
    print(f'  ---')
    print(f'  Assessment Summary:')
    print(f'    {fq["assessment_summary"]}')
    print(f'  LLM Decision Reasoning:')
    print(f'    {fq.get("decision_reasoning", "")[:300]}')
    print(f'  ---')
    print(f'  Per-Source Route Summary:')
    for sid, route in dq['per_source_routes'].items():
        title = q['sources'].get(sid, {}).get('title', sid)[:60]
        print(f'    [{sid[:25]}] {title}')
        print(f'      → {route}')
    print(f'  ---')
    print(f'  Downstream Handoff:')
    print(f'    Main Graph Router reads: workflow_state.route_decision = "{fq["route_decision"]}"')
    export_count = sum(1 for r in dq['per_source_routes'].values() if r == 'Export')
    norm_count = sum(1 for r in dq['per_source_routes'].values() if r == 'Normalization')
    conf_count = sum(1 for r in dq['per_source_routes'].values() if r == 'Conflict')
    print(f'    Export: {export_count} sources, Normalization: {norm_count}, Conflict: {conf_count}')
    print(f'    Conditional routes available for per-field processing decisions.')

    hdr('TEST COMPLETE')
    return state

if __name__ == '__main__':
    main()
