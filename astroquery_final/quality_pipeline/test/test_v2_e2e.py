"""
test_v2_e2e.py — V3.1 全链路端到端测试 (Paper + Database 混合)

通过编译 graph.py 的完整 StateGraph, 循环 invoke() 走通:
  Assessment → Dispatch → Normalization → Export
  Assessment → Dispatch → Variance → Export

关键:
  - 使用 mock_data (V2 schema 完整数据 + V3.1 database 数据)
  - 使用 compile_quality_graph() 调用真实总图 + 路由逻辑
  - 循环 invoke, 直到到达终点 (current_node == "structured_export" 或在 HumanReview)
  - 验证 paper + database 两种 source_type 共存
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ..quality_state import make_initial_state
from ..graph import compile_quality_graph
from ..configs import load_yaml


def _run_graph(data, label=""):
    """循环 invoke graph 直到终点。返回 (state, elapsed, steps)。"""
    t0 = time.time()
    prefix = f"[{label}] " if label else ""

    state = make_initial_state(data)
    domain = data.get("research_domain", "")
    if domain == "astrophysics":
        target_schema = load_yaml("schema_mapping.yaml").get("target_schema_astrophysics", {})
    else:
        target_schema = load_yaml("schema_mapping.yaml").get("target_schema", {})

    state['context_state'].update({
        'quality_rules': load_yaml('quality_rules.yaml'),
        'research_domain': domain,
        'target_schema': target_schema,
    })

    app = compile_quality_graph()
    config = {"recursion_limit": 100}
    max_steps = 20
    terminal_nodes = {"structured_export", "human_review"}

    for step in range(max_steps):
        state = app.invoke(state, config)
        wf = state.get('workflow_state', {})
        current = wf.get('current_node', '?')
        status = wf.get('execution_status', '?')

        print(f'  {prefix}Step {step+1}: node={current}, status={status}, '
              f'route={wf.get("route_decision", "")}')

        # HumanReview 打断 → 自动 approve
        if wf.get('__human_review_needed__'):
            print(f'  {prefix}[HumanReview] auto-approve → Normalization')
            wf['__human_review_needed__'] = False
            wf['__human_review_decision__'] = {
                'decisions': {}, 'route_decision': 'Normalization',
                'reviewer_notes': 'Auto-approve in e2e test',
            }
            wf['route_decision'] = 'Normalization'
            wf['execution_status'] = 'Success'
            state['workflow_state'] = wf
            continue

        if current in terminal_nodes and status in ('Success', 'Failed'):
            print(f'  {prefix}→ 到达终点: {current}')
            break
    else:
        print(f'  {prefix}⚠ 达到最大步数 {max_steps}, 可能未走完流程')

    return state, round(time.time() - t0, 1), min(step + 1, max_steps)


def _verify(state, expected_sources=0, expected_records=0, errors=None):
    """验证输出。返回错误列表。"""
    if errors is None:
        errors = []
    wf = state.get('workflow_state', {})
    output = state.get('output_state', {})
    quality = state.get('report_state', {}).get('quality', {})

    sv = output.get('schema_version', '?')
    if sv != '2.0.0':
        errors.append(f'schema_version={sv} (expected 2.0.0)')

    # Workflow history
    history = wf.get('workflow_history', [])
    agents_seen = {h['agent'] for h in history if isinstance(h, dict)}
    expected_agents = {'ProfilingAgent', 'QualityAssessmentAgent', 'Dispatch'}
    missing_agents = expected_agents - agents_seen
    if missing_agents:
        errors.append(f'Missing agents: {missing_agents}')

    # 路由分布
    route_counts = quality.get('route_counts', {})
    if not route_counts:
        errors.append('No route_counts found')

    # 导出数据
    structured = output.get('structured_data') or {}
    out_recs = structured.get('records', structured.get('json', {}).get('records', []))
    if expected_records > 0 and len(out_recs) != expected_records:
        errors.append(f'Record count mismatch: {len(out_recs)} vs expected {expected_records}')

    out_srcs = structured.get('sources', structured.get('json', {}).get('sources', []))
    if expected_sources > 0 and len(out_srcs) != expected_sources:
        errors.append(f'Source count mismatch: {len(out_srcs)} vs expected {expected_sources}')

    # 多源方差
    msv = quality.get('multi_source_variance', {})

    return errors, route_counts, msv, history, out_recs, out_srcs


def test_paper_only():
    """测试 1: Paper-only 数据 (回归验证)。"""
    print('\n' + '=' * 70)
    print('  TEST 1: Paper-only 全链路')
    print('=' * 70)

    from mock_data import get_mock_data_json
    data = get_mock_data_json()
    n_src = len(data['sources'])
    n_rec = len(data['records'])
    print(f'输入: {n_src} papers, {n_rec} records')

    state, elapsed, steps = _run_graph(data, "paper")

    errors = []
    errors, route_counts, msv, history, out_recs, out_srcs = _verify(
        state, expected_sources=n_src, expected_records=n_rec, errors=errors)

    # Paper-specific checks
    if out_recs:
        rec = out_recs[0]
        for f in ['extraction_confidence', 'context_snippet', 'measurement_method',
                   'condition_tags', 'entity_type', 'entity_name']:
            if f not in rec:
                errors.append(f'Paper record missing V2 field: {f}')

    if out_srcs:
        src = out_srcs[0]
        for f in ['abstract', 'keywords', 'search_query', 'search_rank']:
            if f not in src:
                errors.append(f'Paper source missing V2 field: {f}')

    # V3.0: 方差检查
    if msv.get('variance_count', 0) > 0:
        print(f'  Multi-source variance: {msv["variance_count"]} groups, '
              f'{msv.get("anomaly_count", 0)} anomalies')
    else:
        print(f'  No multi-source variance detected')

    _print_result("Paper-only", errors, elapsed, steps, route_counts, history, msv)
    return len(errors) == 0


def test_mixed_paper_database():
    """测试 2: Paper + Database 混合数据 (V3.1 新增)。"""
    print('\n' + '=' * 70)
    print('  TEST 2: Paper + Database 混合全链路 (V3.1)')
    print('=' * 70)

    from mock_data import get_mixed_mock_data
    data = get_mixed_mock_data()
    n_src = len(data['sources'])
    n_rec = len(data['records'])
    # 统计各类型
    paper_srcs = [s for s in data['sources'] if s.get('source_type') != 'database']
    db_srcs = [s for s in data['sources'] if s.get('source_type') == 'database']
    db_recs = [r for r in data['records'] if r.get('extraction_method') == 'database_query']
    paper_recs = [r for r in data['records'] if r.get('extraction_method') != 'database_query']
    print(f'输入: {len(paper_srcs)} papers + {len(db_srcs)} databases, '
          f'{len(paper_recs)} paper records + {len(db_recs)} DB records')

    state, elapsed, steps = _run_graph(data, "mixed")

    errors = []
    errors, route_counts, msv, history, out_recs, out_srcs = _verify(
        state, expected_sources=n_src, expected_records=n_rec, errors=errors)

    # V3.1: Database-specific checks
    if out_recs:
        db_out = [r for r in out_recs if r.get('extraction_method') == 'database_query']
        paper_out = [r for r in out_recs if r.get('extraction_method') != 'database_query']

        print(f'  导出: {len(paper_out)} paper records + {len(db_out)} DB records')

        # DB records: 检查无 trace_id 但有 provenance.db_table
        if db_out:
            r = db_out[0]
            if r.get('trace_id') is not None:
                errors.append('DB record should have trace_id=None')
            prov = r.get('provenance', {}) or {}
            for f in ['db_table', 'key_column', 'key_value', 'raw_column']:
                if f not in prov:
                    errors.append(f'DB record provenance missing: {f}')
            # DB records 不应有 paper-specific 字段
            for f in ['extraction_confidence', 'context_snippet', 'measurement_method']:
                if r.get(f) is not None:
                    errors.append(f'DB record should not have {f}')

        # Paper records: unchanged
        if paper_out:
            r = paper_out[0]
            if r.get('trace_id') is None:
                errors.append('Paper record should have trace_id')

    # V3.1: DB source fields in export
    if out_srcs:
        db_src_out = [s for s in out_srcs if s.get('source_type') == 'database']
        if db_src_out:
            s = db_src_out[0]
            for f in ['description', 'research_methodology', 'waveband', 'research_content',
                       'vizier_table_id', 'bibcode']:
                if f not in s:
                    errors.append(f'DB source missing field: {f}')

    # V3.1: source reliability for DB sources
    quality = state.get('report_state', {}).get('quality', {})
    sources = quality.get('sources', {})
    db_source_scores = {}
    for sid, sr in sources.items():
        if sid.startswith('SRC_DB'):
            rel = sr.get('source_reliability', {})
            db_source_scores[sid] = rel.get('score', 0)
    if db_source_scores:
        print(f'  DB source reliability scores: {db_source_scores}')
        for sid, score in db_source_scores.items():
            if score <= 0:
                errors.append(f'DB source {sid} has zero reliability score')

    _print_result("Mixed paper+database", errors, elapsed, steps, route_counts, history, msv)
    return len(errors) == 0


def _print_result(name, errors, elapsed, steps, route_counts, history, msv):
    """格式化输出结果。"""
    print(f'\n--- {name} 结果 ---')
    print(f'  耗时: {elapsed:.1f}s, 步数: {steps}')
    print(f'  路由: {route_counts}')
    print(f'  历史: {len(history)} entries')
    if msv:
        print(f'  方差: {msv.get("variance_count", 0)} groups, '
              f'{msv.get("anomaly_count", 0)} anomalies')

    if errors:
        print(f'\n  FAILED ({len(errors)} errors):')
        for e in errors:
            print(f'    - {e}')
    else:
        print(f'  [OK] ALL CHECKS PASSED')


def main():
    print('=' * 70)
    print('  V3.1 全链路端到端测试 (Paper + Database)')
    print('=' * 70)

    ok1 = test_paper_only()
    ok2 = test_mixed_paper_database()

    print('\n' + '=' * 70)
    if ok1 and ok2:
        print('  ALL E2E TESTS PASSED')
        print('=' * 70)
        return 0
    else:
        failed = []
        if not ok1: failed.append('Paper-only')
        if not ok2: failed.append('Mixed paper+database')
        print(f'  FAILED: {", ".join(failed)}')
        print('=' * 70)
        return 1


if __name__ == '__main__':
    import logging; logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
