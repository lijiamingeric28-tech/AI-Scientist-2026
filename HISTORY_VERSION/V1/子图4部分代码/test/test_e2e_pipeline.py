"""
test_e2e_pipeline.py — Assessment → Normalization 完整端到端流程测试

流程:
  1. 初始化多源测试数据 (5 papers, 含别名/格式/单位/缺失问题)
  2. Assessment 模块 (4 Stage)
  3. 根据 Assessment 路由结果分流到 Normalization
  4. Normalization 模块 (5 Stage)
  5. 打印每阶段输出 + LLM 调用统计 + 最终报告

用法:
  cd 子图4部分代码
  python test/test_e2e_pipeline.py
"""

import sys, io, json, time, os, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from utils.logger import setup_logging; setup_logging()
from utils.llm import reset_llm, reset_llm_stats; reset_llm(); reset_llm_stats()


def build_test_data():
    """构造 5 篇论文, 包含各种质量问题。"""
    return {
        "schema_version": "1.0.0",
        "sources": [
            {"source_id": "doi_paper1", "source_type": "paper",
             "doi": "10.1016/j.msea.2024.001",
             "title": "High-temperature tensile of Al-7075 alloy",
             "authors": ["Zhang, W.", "Li, H."], "year": 2024,
             "journal": "Materials Science and Engineering: A",
             "access_path": "/cache/msea_001.pdf", "retrieval_priority": 0.95},
            {"source_id": "doi_paper2", "source_type": "paper",
             "doi": "10.1007/s11661.002",
             "title": "Aging effect on Al-Zn-Mg-Cu alloy",
             "authors": ["Wang, X."], "year": 2023,
             "journal": "Metallurgical and Materials Transactions A",
             "access_path": "/cache/mmta_002.pdf", "retrieval_priority": 0.87},
            {"source_id": "doi_paper3", "source_type": "paper",
             "doi": "10.1016/j.actamat.003",
             "title": "Strain rate sensitivity of Ti-6Al-4V",
             "authors": ["Kim, S.", "Park, J."], "year": 2025,
             "journal": "Acta Materialia",
             "access_path": "/cache/actamat_003.pdf", "retrieval_priority": 0.92},
            {"source_id": "doi_paper4", "source_type": "paper",
             "doi": "10.1016/j.msea.004",
             "title": "Mechanical properties of 316L stainless steel",
             "authors": ["Mueller, F."], "year": 2022,
             "journal": "Materials Science and Engineering: A",
             "access_path": "/cache/msea_004.pdf", "retrieval_priority": 0.85},
            {"source_id": "doi_paper5", "source_type": "paper",
             "doi": "10.1007/s11661.005",
             "title": "Fatigue behavior of Inconel 718",
             "authors": ["Johnson, R."], "year": 2024,
             "journal": "Metallurgical and Materials Transactions A",
             "access_path": "/cache/mmta_005.pdf", "retrieval_priority": 0.89},
        ],
        "records": [
            # Paper 1: 别名问题 (YS, UTS, EL)
            {"record_id": "doi_paper1_yield_strength_1", "source_id": "doi_paper1",
             "field_name": "YS", "field_value": 450, "field_unit": "MPa",
             "trace_id": "d1_t1_r1", "provenance": {"page": 3, "bbox": [120,340,280,355]},
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper1_uts_1", "source_id": "doi_paper1",
             "field_name": "UTS", "field_value": "~520", "field_unit": "MPa",
             "trace_id": "d1_t1_r2", "provenance": {"page": 3, "bbox": [120,356,280,371]},
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper1_temp_1", "source_id": "doi_paper1",
             "field_name": "temperature", "field_value": 200, "field_unit": "C",
             "trace_id": "d1_t1_h1", "provenance": {"page": 3, "bbox": [100,300,150,315]},
             "extraction_method": "llm_text"},
            {"record_id": "doi_paper1_elong_1", "source_id": "doi_paper1",
             "field_name": "EL", "field_value": 12.5, "field_unit": "%",
             "trace_id": "d1_t1_r3", "provenance": {"page": 3, "bbox": [120,372,280,387]},
             "extraction_method": "llm_table"},

            # Paper 2: 单位问题 (GPa→MPa) + 缺单位
            {"record_id": "doi_paper2_yield_1", "source_id": "doi_paper2",
             "field_name": "yield_strength", "field_value": 0.438, "field_unit": "GPa",
             "trace_id": "d2_t1_r1", "provenance": {"page": 5, "bbox": [90,420,250,435]},
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper2_tensile_1", "source_id": "doi_paper2",
             "field_name": "tensile_strength", "field_value": 0.505, "field_unit": "GPa",
             "trace_id": "d2_t1_r2", "provenance": {"page": 5, "bbox": [90,436,250,451]},
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper2_hard_1", "source_id": "doi_paper2",
             "field_name": "hardness", "field_value": 185, "field_unit": None,
             "trace_id": "d2_t1_r3", "provenance": {"page": 5, "bbox": [90,452,250,467]},
             "extraction_method": "llm_table"},

            # Paper 3: ~前缀 + 重复 + 别名 TS
            {"record_id": "doi_paper3_yield_1", "source_id": "doi_paper3",
             "field_name": "yield_strength", "field_value": "~880", "field_unit": "MPa",
             "trace_id": "d3_t1_r1", "provenance": {"page": 4, "bbox": [80,300,240,315]},
             "extraction_method": "llm_text"},
            {"record_id": "doi_paper3_yield_1", "source_id": "doi_paper3",
             "field_name": "yield_strength", "field_value": "~880", "field_unit": "MPa",
             "trace_id": "d3_t1_r1", "provenance": {"page": 4, "bbox": [80,300,240,315]},
             "extraction_method": "llm_text"},
            {"record_id": "doi_paper3_ts_1", "source_id": "doi_paper3",
             "field_name": "TS", "field_value": 950, "field_unit": "MPa",
             "trace_id": "d3_t1_r2", "provenance": {"page": 4, "bbox": [80,316,240,331]},
             "extraction_method": "llm_table"},

            # Paper 4: 希腊字母别名 + K→°C + 缺溯源
            {"record_id": "doi_paper4_sigma_y_1", "source_id": "doi_paper4",
             "field_name": "σ_y", "field_value": 310, "field_unit": "MPa",
             "trace_id": "d4_t1_r1", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper4_sigma_uts_1", "source_id": "doi_paper4",
             "field_name": "σ_uts", "field_value": 620, "field_unit": "MPa",
             "trace_id": "d4_t1_r2", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper4_temp_1", "source_id": "doi_paper4",
             "field_name": "test_temperature", "field_value": 300, "field_unit": "K",
             "trace_id": "d4_t1_h1", "provenance": {"page": 2, "bbox": [50,250,120,265]},
             "extraction_method": "llm_text"},

            # Paper 5: 干净数据
            {"record_id": "doi_paper5_yield_1", "source_id": "doi_paper5",
             "field_name": "yield_strength", "field_value": 1050, "field_unit": "MPa",
             "trace_id": "d5_t1_r1", "provenance": {"page": 6, "bbox": [100,400,260,415]},
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper5_tensile_1", "source_id": "doi_paper5",
             "field_name": "tensile_strength", "field_value": 1200, "field_unit": "MPa",
             "trace_id": "d5_t1_r2", "provenance": {"page": 6, "bbox": [100,416,260,431]},
             "extraction_method": "llm_table"},
            {"record_id": "doi_paper5_temp_1", "source_id": "doi_paper5",
             "field_name": "temperature", "field_value": 650, "field_unit": "C",
             "trace_id": "d5_t1_h1", "provenance": {"page": 6, "bbox": [80,370,130,385]},
             "extraction_method": "llm_text"},
        ],
    }


def hdr(s):    print(f'\n{"="*70}\n  {s}\n{"="*70}')
def sub(s):    print(f'\n{"─"*70}\n  {s}\n{"─"*70}')
def sep():     print(f'{"─"*70}')


def main():
    t_total = time.time()
    hdr('Assessment → Normalization 端到端流程测试')

    # ═══════════════════════════════════════════════════
    # PHASE 0: 初始化
    # ═══════════════════════════════════════════════════
    sub('PHASE 0: 数据初始化')
    input_data = build_test_data()
    from quality_state import make_initial_state
    from configs import load_yaml
    state = make_initial_state(input_data)
    state['context_state'].update({
        'quality_rules': load_yaml('quality_rules.yaml'),
        'target_schema': load_yaml('schema_mapping.yaml').get('target_schema', {}),
        'research_domain': 'materials_science',
    })

    print(f'  输入: {len(input_data["sources"])} papers, {len(input_data["records"])} records')
    for src in input_data['sources']:
        print(f'    [{src["source_id"]}] {src["title"][:55]} ({src["year"]})')
    print(f'\n  原始数据预览:')
    for r in input_data['records']:
        fu = r.get("field_unit") or "-"
        print(f'    [{r["source_id"][:12]}] {r["field_name"]:18s} = {str(r["field_value"]):10s} {fu:6s}')

    # ═══════════════════════════════════════════════════
    # PHASE 1: Assessment
    # ═══════════════════════════════════════════════════
    hdr('PHASE 1: Assessment Module (4 Stages)')
    from Data_Assessment_agentV1.assessment_graph import build_assessment_graph
    t1 = time.time()
    state = build_assessment_graph().compile().invoke(state)
    t1e = time.time() - t1

    q = state['report_state']['quality']
    profile = q.get('profile', {})
    sources = q.get('sources', {})
    scoring = q.get('quality_scoring', {})

    # Stage 1 output
    sub('Assessment Stage 1: Profiling')
    ds = profile.get('dataset_summary', {})
    print(f'  Records: {ds.get("record_count")}, Sources: {ds.get("source_count")}, Fields: {ds.get("field_count")}')
    print(f'  Semantic types detected: {list(profile.get("semantic_types", {}).keys())}')
    dist = profile.get('distributions', {})
    for fn, d in list(dist.items())[:4]:
        if d.get('distribution_type') != 'unknown':
            print(f'    {fn}: {d.get("distribution_type")} (skew={d.get("skewness",0):.2f})')
    print(f'  Out of range: {profile.get("out_of_range_count", 0)}')
    print(f'  Elapsed: {t1e:.1f}s')

    # Stage 2 output
    sub('Assessment Stage 2: Quality Assessment (per-source)')
    for sid, sr in list(sources.items())[:3]:
        title = sr.get('title', sid)[:45]
        comp = sr['completeness']['score']
        cons = sr['consistency']['score']
        confs = sr['conflict_risk']['conflict_count']
        issues = sr.get('issue_count', 0)
        print(f'  [{sid}] {title} | comp={comp:.2f} cons={cons:.2f} conflicts={confs} issues={issues}')
    for sid, sr in sources.items():
        lc = sr.get('llm_completeness')
        if lc and lc.get('summary'):
            print(f'  LLM Completeness [{sid}]: {lc["summary"][:120]}...')

    # Stage 3 output
    sub('Assessment Stage 3: Scoring')
    print(f'  Overall: {scoring.get("overall_score",0):.4f} ({scoring.get("quality_level","?")})')
    print(f'  Calibrated confidence: {scoring.get("calibrated_confidence","?"):.4f}')
    cf = scoring.get('confidence_factors', {})
    if cf:
        print(f'  Factors: volume={cf.get("data_volume","?")} agreement={cf.get("agreement","?")} sparsity={cf.get("sparsity","?")}')
    print(f'  Per-source scores:')
    for sid, sr in list(sources.items())[:5]:
        print(f'    [{sid}] → {sr.get("quality_scoring",{}).get("overall_score",0):.4f} ({sr.get("quality_scoring",{}).get("quality_level","?")})')

    # Stage 4 output
    sub('Assessment Stage 4: Decision (V2.1 strict)')
    # V4 fix: decision_reasoning V3.5 后 route_decision → route_counts, 兼容旧键
    print(f'  Overall route: {q.get("route_decision", q.get("route_counts", {}))}')
    for sid, route in q['per_source_routes'].items():
        reason = q.get('per_source_reasons', {}).get(sid, '')[:100]
        title = sources.get(sid, {}).get('title', sid)[:40]
        print(f'    [{sid}] {title:40s} → {route:15s} | {reason}')
    export_n = sum(1 for r in q['per_source_routes'].values() if r == 'Export')
    norm_n = sum(1 for r in q['per_source_routes'].values() if r == 'Normalization')
    conf_n = sum(1 for r in q['per_source_routes'].values() if r == 'Conflict')
    print(f'  Summary: Export={export_n} Normalization={norm_n} Conflict={conf_n}')
    sep()

    # ═══════════════════════════════════════════════════
    # PHASE 2: Normalization (only for Normalization sources)
    # ═══════════════════════════════════════════════════
    if norm_n == 0:
        print('\n  No sources need normalization. Pipeline complete.')
    else:
        hdr('PHASE 2: Normalization Module (5 Stages)')
        t2 = time.time()
        before_data = copy.deepcopy(state['data_state']['current_data'])

        from Data_Normalization_agentV1.agents.source_router_agent import SourceRouterAgent
        from Data_Normalization_agentV1.agents.planning_agent import PlanningAgent
        from Data_Normalization_agentV1.agents.normalization_agent import NormalizationAgent
        from Data_Normalization_agentV1.agents.validation_agent import ValidationAgent
        from Data_Normalization_agentV1.agents.report_agent import ReportAgent

        agents = [
            ('Stage 1: SourceRouter', SourceRouterAgent()),
            ('Stage 2: ToolPlanning', PlanningAgent()),
            ('Stage 3: ToolExecutor', NormalizationAgent()),
            ('Stage 4: Validation',   ValidationAgent()),
            ('Stage 5: Report',       ReportAgent()),
        ]

        for name, agent in agents:
            t_s = time.time()
            result = agent.run(state)
            state = {**state, **result}
            t_e = time.time() - t_s

            norm = state.get('report_state', {}).get('normalization', {})
            wf = state.get('workflow_state', {})

            print(f'\n  {name} ({t_e:.2f}s)')
            print(f'  {"─"*50}')

            if 'SourceRouter' in name:
                sp = norm.get('source_plan', {})
                print(f'    Trigger: {sp.get("trigger_source")}')
                print(f'    To normalize: {sp.get("total_to_normalize")} sources')
                print(f'    Skipped: {sp.get("total_skipped")} sources')
                for sid, info in sp.get('sources_to_normalize', {}).items():
                    conds = [c.get('condition') for c in info.get('conditions', [])]
                    print(f'      [{sid}] {info["record_count"]}recs | {conds}')

            elif 'ToolPlanning' in name:
                reg = norm.get('tool_registry', {})
                print(f'    Method: {norm.get("planning_method")}')
                print(f'    Base tools: {reg.get("base_tools", [])}')
                print(f'    Adapted tools: {len(reg.get("adapted_tools", []))}')
                print(f'    Generated tools: {len(reg.get("generated_tools", []))}')
                for sid, bs in reg.get('by_source', {}).items():
                    print(f'      [{sid}] base={bs.get("base",[])}')
                    for a in bs.get('adapted', []):
                        print(f'        adapted: {a.get("base_tool")}/{a.get("adaptation")}')
                    for g in bs.get('generated', []):
                        print(f'        generated: {g.get("tool_name")} (conf={g.get("confidence",0):.2f})')

            elif 'ToolExecutor' in name:
                mods = norm.get('modifications', {})
                print(f'    Total modifications: {mods["total"]}')
                bl = mods.get('by_layer', {})
                print(f'    By layer: base={bl.get("base",0)} adapted={bl.get("adapted",0)} generated={bl.get("generated",0)}')
                ps = mods.get('per_source', {})
                for sid, info in list(ps.items())[:5]:
                    print(f'      [{sid}] {info.get("total",0)} mods')
                errors = mods.get('errors', [])
                if errors:
                    print(f'    Errors: {len(errors)}')
                    for e in errors[:3]:
                        print(f'      {e}')

            elif 'Validation' in name:
                val = norm.get('validation', {})
                print(f'    Valid: {val.get("is_valid")}')
                print(f'    Schema check: {"PASS" if val.get("schema_check",{}).get("passed") else "FAIL"}')
                print(f'    Conflict check: {val.get("conflict_check",{}).get("conflict_count",0)} conflicts')
                rem = val.get('remaining_issues', [])
                if rem:
                    print(f'    Remaining issues ({len(rem)}):')
                    for iss in rem[:3]:
                        print(f'      - {iss[:100]}')
                print(f'    Route: {wf.get("route_decision")}')

            elif 'Report' in name:
                print(f'    Status: {norm.get("normalization_status")}')
                print(f'    Summary: {norm.get("normalization_summary", "")[:150]}')
                reg_sum = norm.get('tool_registry_summary', {})
                print(f'    Tools used: base={reg_sum.get("base_tools_used",0)} adapted={reg_sum.get("adapted_tools_used",0)} generated={reg_sum.get("generated_tools_used",0)}')

        t2e = time.time() - t2

        # BEFORE vs AFTER
        hdr('PHASE 3: 数据对比 (BEFORE → AFTER)')
        before_recs = before_data['records']
        after_recs = state['data_state']['current_data']['records']
        before_map = {r['record_id']: r for r in before_recs}
        after_map = {r['record_id']: r for r in after_recs}

        changed = 0
        for rid, br in sorted(before_map.items()):
            ar = after_map.get(rid)
            if not ar:
                print(f'  [{rid}] DELETED (duplicate)')
                changed += 1
                continue
            diffs = []
            if br.get('field_name') != ar.get('field_name'):
                diffs.append(f'name: {br["field_name"]} → {ar["field_name"]}')
            bv, av = str(br.get('field_value','')), str(ar.get('field_value',''))
            if bv != av:
                diffs.append(f'value: {bv} → {av}')
            if br.get('field_unit') != ar.get('field_unit'):
                diffs.append(f'unit: {br["field_unit"]} → {ar["field_unit"]}')
            if diffs:
                changed += 1
                print(f'  [{rid}] {"; ".join(diffs)}')
        if changed == 0:
            print('  (no changes — data was already clean)')
        sep()

    # ═══════════════════════════════════════════════════
    # LLM 统计
    # ═══════════════════════════════════════════════════
    hdr('LLM 调用统计')
    from utils.llm import print_llm_stats
    print_llm_stats()

    total_elapsed = time.time() - t_total
    print(f'\n  Assessment: {t1e:.1f}s')
    if norm_n > 0:
        print(f'  Normalization: {t2e:.1f}s')
    print(f'  Total: {total_elapsed:.1f}s')
    print(f'  Final route: {state["workflow_state"]["route_decision"]}')
    hdr('END-TO-END TEST COMPLETE')


if __name__ == '__main__':
    main()
