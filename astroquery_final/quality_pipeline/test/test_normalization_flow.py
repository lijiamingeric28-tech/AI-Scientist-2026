"""
test_normalization_flow.py — Normalization V1.1 完整流程测试

先跑 Assessment 获取 per_source_routes + Quality Report，
再跑 Normalization 5 Stage 处理标记为 Normalization 的 sources，
展示数据前后对比 + 每 Stage 输出 + LLM 调用统计。

用法:
  cd 子图4部分代码
  python test/test_normalization_flow.py
"""

import sys, io, json, time, os, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from ..utils.logger import setup_logging; setup_logging()
from ..utils.llm import reset_llm, reset_llm_stats; reset_llm(); reset_llm_stats()


def build_test_data():
    """构造 5 篇论文, 每篇有不同质量问题, 使 Assessment 路由到 Normalization。"""
    return {
        "schema_version": "1.0.0",
        "sources": [
            {"source_id": "10.1016/j.msea.2024.001", "source_type": "paper",
             "doi": "10.1016/j.msea.2024.001",
             "title": "High-temperature tensile of Al-7075 alloy",
             "authors": ["Zhang, W.", "Li, H."], "year": 2024,
             "journal": "Materials Science and Engineering: A",
             "access_path": "/cache/msea_2024_001.pdf", "retrieval_priority": 0.95},
            {"source_id": "10.1007/s11661-2023.002", "source_type": "paper",
             "doi": "10.1007/s11661-2023.002",
             "title": "Aging effect on Al-Zn-Mg-Cu alloy",
             "authors": ["Wang, X."], "year": 2023,
             "journal": "Metallurgical and Materials Transactions A",
             "access_path": "/cache/mmta_2023_002.pdf", "retrieval_priority": 0.87},
            {"source_id": "10.1016/j.actamat.2025.003", "source_type": "paper",
             "doi": "10.1016/j.actamat.2025.003",
             "title": "Strain rate sensitivity of Ti-6Al-4V",
             "authors": ["Kim, S.", "Park, J."], "year": 2025,
             "journal": "Acta Materialia",
             "access_path": "/cache/actamat_2025_003.pdf", "retrieval_priority": 0.92},
            {"source_id": "10.1016/j.msea.2022.004", "source_type": "paper",
             "doi": "10.1016/j.msea.2022.004",
             "title": "Mechanical properties of 316L stainless steel",
             "authors": ["Mueller, F.", "Schmidt, K."], "year": 2022,
             "journal": "Materials Science and Engineering: A",
             "access_path": "/cache/msea_2022_004.pdf", "retrieval_priority": 0.85},
            {"source_id": "10.1007/s11661-2024.005", "source_type": "paper",
             "doi": "10.1007/s11661-2024.005",
             "title": "Fatigue behavior of Inconel 718 at elevated temperature",
             "authors": ["Johnson, R.", "Smith, A."], "year": 2024,
             "journal": "Metallurgical and Materials Transactions A",
             "access_path": "/cache/mmta_2024_005.pdf", "retrieval_priority": 0.89},
        ],
        "records": [
            # ── Paper 1: 别名 + 格式问题 ──
            {"record_id": "p1_yield_1",  "source_id": "10.1016/j.msea.2024.001",
             "field_name": "YS",          "field_value": 450, "field_unit": "MPa",
             "trace_id": "d1_p3_tb1_r1", "provenance": {"page": 3, "bbox": [120,340,280,355]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_tensile_1","source_id": "10.1016/j.msea.2024.001",
             "field_name": "UTS",         "field_value": "~520", "field_unit": "MPa",
             "trace_id": "d1_p3_tb1_r2", "provenance": {"page": 3, "bbox": [120,356,280,371]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_temp_1",   "source_id": "10.1016/j.msea.2024.001",
             "field_name": "temperature", "field_value": 200, "field_unit": "C",
             "trace_id": "d1_p3_tb1_h1", "provenance": {"page": 3, "bbox": [100,300,150,315]},
             "extraction_method": "llm_text"},
            {"record_id": "p1_elong_1",  "source_id": "10.1016/j.msea.2024.001",
             "field_name": "EL",          "field_value": 12.5, "field_unit": "%",
             "trace_id": "d1_p3_tb1_r3", "provenance": {"page": 3, "bbox": [120,372,280,387]},
             "extraction_method": "llm_table"},

            # ── Paper 2: 单位问题 (GPa→MPa) + 缺单位 ──
            {"record_id": "p2_yield_1",  "source_id": "10.1007/s11661-2023.002",
             "field_name": "yield_strength", "field_value": 0.438, "field_unit": "GPa",
             "trace_id": "d2_p5_tb1_r1", "provenance": {"page": 5, "bbox": [90,420,250,435]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_tensile_1","source_id": "10.1007/s11661-2023.002",
             "field_name": "tensile_strength","field_value": 0.505, "field_unit": "GPa",
             "trace_id": "d2_p5_tb1_r2", "provenance": {"page": 5, "bbox": [90,436,250,451]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_hard_1",   "source_id": "10.1007/s11661-2023.002",
             "field_name": "hardness",   "field_value": 185, "field_unit": None,
             "trace_id": "d2_p5_tb1_r3", "provenance": {"page": 5, "bbox": [90,452,250,467]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_density_1","source_id": "10.1007/s11661-2023.002",
             "field_name": "density",    "field_value": 2.81, "field_unit": None,
             "trace_id": "d2_p6_p1",    "provenance": {"page": 6, "bbox": None},
             "extraction_method": "llm_text"},

            # ── Paper 3: 格式问题 (~前缀) + 重复记录 ──
            {"record_id": "p3_yield_1",  "source_id": "10.1016/j.actamat.2025.003",
             "field_name": "yield_strength", "field_value": "~880", "field_unit": "MPa",
             "trace_id": "d3_p4_tb1_r1", "provenance": {"page": 4, "bbox": [80,300,240,315]},
             "extraction_method": "llm_text"},
            {"record_id": "p3_yield_1",  "source_id": "10.1016/j.actamat.2025.003",
             "field_name": "yield_strength", "field_value": "~880", "field_unit": "MPa",
             "trace_id": "d3_p4_tb1_r1", "provenance": {"page": 4, "bbox": [80,300,240,315]},
             "extraction_method": "llm_text"},  # 重复!
            {"record_id": "p3_tensile_1","source_id": "10.1016/j.actamat.2025.003",
             "field_name": "TS",          "field_value": 950, "field_unit": "MPa",
             "trace_id": "d3_p4_tb1_r2", "provenance": {"page": 4, "bbox": [80,316,240,331]},
             "extraction_method": "llm_table"},
            {"record_id": "p3_elong_1",  "source_id": "10.1016/j.actamat.2025.003",
             "field_name": "elongation",  "field_value": "approx. 8.5", "field_unit": "%",
             "trace_id": "d3_p4_tb1_r3", "provenance": {"page": 4, "bbox": [80,332,240,347]},
             "extraction_method": "llm_text"},

            # ── Paper 4: 缺溯源 + 单位转换 ──
            {"record_id": "p4_yield_1",  "source_id": "10.1016/j.msea.2022.004",
             "field_name": "σ_y",         "field_value": 310, "field_unit": "MPa",
             "trace_id": "d4_p2_tb1_r1", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p4_tensile_1","source_id": "10.1016/j.msea.2022.004",
             "field_name": "σ_uts",       "field_value": 620, "field_unit": "MPa",
             "trace_id": "d4_p2_tb1_r2", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p4_temp_1",   "source_id": "10.1016/j.msea.2022.004",
             "field_name": "test_temperature","field_value": 300, "field_unit": "K",
             "trace_id": "d4_p2_tb1_h1", "provenance": {"page": 2, "bbox": [50,250,120,265]},
             "extraction_method": "llm_text"},

            # ── Paper 5: 干净数据 (应该 Export, 不进入 Normalization) ──
            {"record_id": "p5_yield_1",  "source_id": "10.1007/s11661-2024.005",
             "field_name": "yield_strength", "field_value": 1050, "field_unit": "MPa",
             "trace_id": "d5_p6_tb1_r1", "provenance": {"page": 6, "bbox": [100,400,260,415]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_tensile_1","source_id": "10.1007/s11661-2024.005",
             "field_name": "tensile_strength","field_value": 1200, "field_unit": "MPa",
             "trace_id": "d5_p6_tb1_r2", "provenance": {"page": 6, "bbox": [100,416,260,431]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_temp_1",   "source_id": "10.1007/s11661-2024.005",
             "field_name": "temperature","field_value": 650, "field_unit": "C",
             "trace_id": "d5_p6_tb1_h1", "provenance": {"page": 6, "bbox": [80,370,130,385]},
             "extraction_method": "llm_text"},
        ],
    }


def print_records(title, records, limit=99):
    print(f'\n    {title} ({len(records)} records):')
    for r in records[:limit]:
        fn = r.get("field_name","?")
        fv = r.get("field_value","?")
        fu = r.get("field_unit","") or ""
        print(f'      [{r["source_id"][:20]}...] {fn:18s} = {str(fv):12s} {fu:8s}')


def main():
    t0 = time.time()

    print('=' * 70)
    print('  Normalization V1.1 — 完整流程测试')
    print('=' * 70)

    input_data = build_test_data()
    from ..quality_state import make_initial_state
    from ..configs import load_yaml
    state = make_initial_state(input_data)
    state['context_state'].update({
        'quality_rules': load_yaml('quality_rules.yaml'),
        'target_schema': load_yaml('schema_mapping.yaml').get('target_schema', {}),
        'research_domain': 'materials_science',
    })

    # ═══ 先跑 Assessment 获取 Quality Report ═══
    print('\n' + '-' * 70)
    print('  [PRE] Running Assessment to generate Quality Report...')
    print('-' * 70)

    from ..Data_Assessment_agentV1.assessment_graph import build_assessment_graph
    asm_graph = build_assessment_graph().compile()
    state = asm_graph.invoke(state)

    q = state['report_state']['quality']

    # 手动标记: Paper 1-4 需要 Normalization (模拟正确的 Assessment 判断)
    # Paper 1: 别名 YS/UTS/EL → schema_mapping
    # Paper 2: GPa→MPa + 缺单位 → unit_conversion + missing_value
    # Paper 3: ~前缀 + 重复 + 别名 TS → field_std + dup + schema
    # Paper 4: 希腊字母别名 + 缺溯源 + K→°C → schema + missing + unit
    # Paper 5: 干净 → Export
    manual_routes = {
        "10.1016/j.msea.2024.001": "Normalization",
        "10.1007/s11661-2023.002": "Normalization",
        "10.1016/j.actamat.2025.003": "Normalization",
        "10.1016/j.msea.2022.004": "Normalization",
        "10.1007/s11661-2024.005": "Export",
    }
    q['per_source_routes'] = manual_routes
    q['route_decision'] = "Normalization"  # overall = worst case
    # 添加 conditional routes 让 PlanningAgent 知道修复什么
    q['conditional_routes'] = [
        {"source_id": "10.1016/j.msea.2024.001", "primary_route": "Normalization",
         "conditions": [{"condition": "alias_fields", "route": "Normalization", "reason": "YS/UTS/EL need mapping"},
                        {"condition": "format_issues", "route": "Normalization", "reason": "~520 needs cleaning"}]},
        {"source_id": "10.1007/s11661-2023.002", "primary_route": "Normalization",
         "conditions": [{"condition": "unit_inconsistency", "route": "Normalization", "reason": "GPa→MPa"},
                        {"condition": "completeness_low", "route": "Normalization", "reason": "missing units/provenance"}]},
        {"source_id": "10.1016/j.actamat.2025.003", "primary_route": "Normalization",
         "conditions": [{"condition": "format_issues", "route": "Normalization", "reason": "~880, approx. 8.5"},
                        {"condition": "duplicate_records", "route": "Normalization", "reason": "duplicate yield record"},
                        {"condition": "alias_fields", "route": "Normalization", "reason": "TS→tensile_strength"}]},
        {"source_id": "10.1016/j.msea.2022.004", "primary_route": "Normalization",
         "conditions": [{"condition": "alias_fields", "route": "Normalization", "reason": "σ_y, σ_uts"},
                        {"condition": "completeness_low", "route": "Normalization", "reason": "missing provenance"},
                        {"condition": "unit_inconsistency", "route": "Normalization", "reason": "K→°C"}]},
    ]
    state['report_state']['quality'] = q

    print(f'\n  Assessment result (manual override):')
    print(f'    Overall route: {q["route_decision"]}')
    for sid, route in q['per_source_routes'].items():
        title = q['sources'].get(sid, {}).get('title', sid)[:50]
        score = q['sources'].get(sid, {}).get('quality_scoring', {}).get('overall_score', 0)
        print(f'      [{sid[:25]}] → {route:15s} (score={score:.4f})  {title}')

    # ═══ 数据: BEFORE ═══
    print('\n' + '=' * 70)
    print('  DATA BEFORE NORMALIZATION')
    print('=' * 70)
    before_data = copy.deepcopy(state['data_state']['current_data'])
    print_records('BEFORE', before_data['records'])

    # ═══ 手动跑 Normalization 5 Stage ═══
    print('\n' + '=' * 70)
    print('  NORMALIZATION — 5 STAGE FLOW')
    print('=' * 70)

    norm_total = 0

    # Stage 1: SourceRouter
    print('\n' + '-' * 70)
    print('  Stage 1: SourceRouterAgent')
    print('-' * 70)
    t1 = time.time()
    from ..Data_Normalization_agentV1.agents.source_router_agent import SourceRouterAgent
    s1 = SourceRouterAgent().run(state); state = {**state, **s1}
    t1e = time.time() - t1
    sp = s1['report_state']['normalization']['source_plan']
    print(f'    Trigger: {sp["trigger_source"]}')
    print(f'    To normalize: {sp["total_to_normalize"]} sources')
    print(f'    Skipped: {sp["total_skipped"]} sources')
    for sid, info in sp['sources_to_normalize'].items():
        print(f'      [{sid[:25]}] {info["record_count"]} recs |'
              f' full_norm={info["needs_full_normalization"]} |'
              f' conditions={[c.get("condition") for c in info["conditions"]]}' if info["conditions"] else " no conditions")

    if not sp['sources_to_normalize']:
        print('    → No sources to normalize. Export.')
        return

    # Stage 2: Planning
    print('\n' + '-' * 70)
    print('  Stage 2: ToolPlanningAgent (V2.0)')
    print('-' * 70)
    t2 = time.time()
    from ..Data_Normalization_agentV1.agents.planning_agent import PlanningAgent
    s2 = PlanningAgent().run(state); state = {**state, **s2}
    t2e = time.time() - t2
    registry = s2['report_state']['normalization'].get('tool_registry', {})
    method = s2['report_state']['normalization']['planning_method']
    print(f'    Method: {method}')
    print(f'    Base tools: {registry.get("base_tools", [])}')
    print(f'    Adapted tools: {len(registry.get("adapted_tools", []))}')
    print(f'    Generated tools: {len(registry.get("generated_tools", []))}')
    for sid, by_src in registry.get('by_source', {}).items():
        print(f'      [{sid[:25]}] base={by_src["base"]} adapted={by_src.get("adapted",[])} generated={by_src.get("generated",[])}')

    # Stage 3: Normalization
    print('\n' + '-' * 70)
    print('  Stage 3: NormalizationAgent (6 Tools)')
    print('-' * 70)
    t3 = time.time()
    from ..Data_Normalization_agentV1.agents.normalization_agent import NormalizationAgent
    s3 = NormalizationAgent().run(state); state = {**state, **s3}
    t3e = time.time() - t3
    mods = s3['report_state']['normalization']['modifications']
    print(f'    Total modifications: {mods["total"]}')
    print(f'    By layer: base={mods.get("by_layer",{}).get("base",0)} adapted={mods.get("by_layer",{}).get("adapted",0)} generated={mods.get("by_layer",{}).get("generated",0)}')
    print(f'    By type: {json.dumps(mods.get("by_type", mods.get("by_layer",{})), indent=6)}')
    print(f'    Per source:')
    for sid, ps in mods['per_source'].items():
        print(f'      [{sid[:25]}] {ps["total"]} mods, tasks={ps.get("tasks",ps.get("note","?"))}')
    # 展示具体修改
    for k, v in mods['details'].items():
        if v:
            print(f'    {k}:')
            for item in v[:3]:
                print(f'      {json.dumps(item, ensure_ascii=False)[:120]}')

    # Stage 4: Validation
    print('\n' + '-' * 70)
    print('  Stage 4: ValidationAgent')
    print('-' * 70)
    t4 = time.time()
    from ..Data_Normalization_agentV1.agents.validation_agent import ValidationAgent
    s4 = ValidationAgent().run(state); state = {**state, **s4}
    t4e = time.time() - t4
    val = s4['report_state']['normalization']['validation']
    print(f'    Valid: {val["is_valid"]}')
    print(f'    Schema check: {"PASS" if val["schema_check"]["passed"] else "FAIL"}')
    fmt_msg = "PASS" if val["format_check"]["passed"] else f'FAIL — {val["format_check"]["missing_units"]} missing units'
    print(f'    Format check: {fmt_msg}')
    print(f'    Conflict check: {val["conflict_check"]["conflict_count"]} conflicts')
    print(f'    Semantic check: {val["semantic_check"]["out_of_range_count"]} out of range')
    print(f'    Remaining issues: {len(val["remaining_issues"])}')
    for iss in val["remaining_issues"]:
        print(f'      - {iss[:100]}')
    print(f'    Route decision: {s4["workflow_state"]["route_decision"]}')

    # Stage 5: Report
    print('\n' + '-' * 70)
    print('  Stage 5: ReportAgent')
    print('-' * 70)
    t5 = time.time()
    from ..Data_Normalization_agentV1.agents.report_agent import ReportAgent
    s5 = ReportAgent().run(state); state = {**state, **s5}
    t5e = time.time() - t5
    rpt = s5['report_state']['normalization']
    print(f'    Status: {rpt["normalization_status"]}')
    print(f'    Summary: {rpt["normalization_summary"]}')
    print(f'    Tool calls: {rpt["total_tool_calls"]}')

    # ═══ 数据: AFTER ═══
    print('\n' + '=' * 70)
    print('  DATA AFTER NORMALIZATION')
    print('=' * 70)
    after_data = state['data_state']['current_data']
    print_records('AFTER', after_data['records'])

    # ═══ BEFORE vs AFTER 对比 ═══
    print('\n' + '=' * 70)
    print('  BEFORE → AFTER DIFF')
    print('=' * 70)
    before_by_id = {r['record_id']: r for r in before_data['records']}
    after_by_id = {r['record_id']: r for r in after_data['records']}
    changed = 0
    for rid, br in before_by_id.items():
        ar = after_by_id.get(rid)
        if not ar: continue  # record was deleted (duplicate)
        diffs = []
        if br.get('field_name') != ar.get('field_name'):
            diffs.append(f'field_name: {br["field_name"]} → {ar["field_name"]}')
        if br.get('field_value') != ar.get('field_value'):
            diffs.append(f'value: {br["field_value"]} → {ar["field_value"]}')
        if br.get('field_unit') != ar.get('field_unit'):
            diffs.append(f'unit: {br["field_unit"]} → {ar["field_unit"]}')
        if diffs:
            changed += 1
            print(f'  [{rid[:30]}] {"; ".join(diffs)}')
    # deleted records
    for rid in before_by_id:
        if rid not in after_by_id:
            print(f'  [{rid[:30]}] DELETED (duplicate/rejected)')
            changed += 1
    if changed == 0:
        print('  (no changes)')

    # ═══ LLM Stats ═══
    from ..utils.llm import print_llm_stats
    print_llm_stats()

    elapsed = time.time() - t0
    print(f'\n  Stage timing: Router={t1e:.3f}s Plan={t2e:.3f}s Norm={t3e:.3f}s Val={t4e:.3f}s Report={t5e:.3f}s')
    print(f'  Total: {elapsed:.1f}s')
    print('=' * 70)


if __name__ == '__main__':
    main()
