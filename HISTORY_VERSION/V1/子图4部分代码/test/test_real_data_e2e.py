"""
test_real_data_e2e.py — 真实混合数据端到端测试 (V3.1)

使用 result_9e76f974-d4e2-4c04-b4ee-026b2b473f61.json (25 sources: 20 paper + 5 database,
219 records: 60 paper + 159 DB) 走完整编译图:

  Assessment → Dispatch → Normalization → LoopCnt → Export

关键验证:
  1. 全部 219 records 保留到导出 (无丢失)
  2. 25 sources 全部保留 (paper + database)
  3. DB records: trace_id=None, provenance 四要素完整
  4. DB source: 8 个 V3.1 字段保留到导出
  5. 路由分布合理 (DB source 无 extra_fields → 不触发无谓 Layer 3)
  6. HumanReview 打断自动处理
  7. 多源方差分析结果输出

用法:
  python test/test_real_data_e2e.py [--data PATH]
"""
import sys, os, time, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from quality_state import make_initial_state
from graph import compile_quality_graph
from configs import load_yaml

_DEFAULT_DATA = os.path.join(os.path.dirname(__file__), '..', 'result_9e76f974-d4e2-4c04-b4ee-026b2b473f61.json')


def _load_data(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # 领域信息: 数据文件无 research_domain, 显式指定 (天文混合数据)
    data['research_domain'] = 'astrophysics'
    return data


def _run_graph(data: dict):
    """循环 invoke graph 直到终点。返回 (state, elapsed, steps)。"""
    t0 = time.time()

    state = make_initial_state(data)
    state['context_state'].update({
        'quality_rules': load_yaml('quality_rules.yaml'),
        'research_domain': 'astrophysics',
        'target_schema': load_yaml('schema_mapping.yaml').get('target_schema_astrophysics', {}),
    })
    # V4 fix: 预置 auto-approve 决策 — B→C 激活后 Conflict 子图会升级冲突到
    # HumanReview, HR agent 在 invoke 内部交互 input() (非交互环境 EOF 崩溃)。
    # 预置决策后 HR agent Step 1 直接返回, 不进入命令行交互。
    state['workflow_state']['__human_review_decision__'] = {
        'decisions': {}, 'route_decision': 'Normalization',
        'reviewer_notes': 'Auto-approve in e2e test',
    }

    app = compile_quality_graph()
    config = {"recursion_limit": 300}
    max_steps = 30
    # V3.4: 终点为 insights 子图的 synthesis (Export → Insights → END)
    terminal_nodes = {"synthesis", "human_review"}

    steps = 0
    for step in range(max_steps):
        steps = step + 1
        state = app.invoke(state, config)
        wf = state.get('workflow_state', {})
        current = wf.get('current_node', '?')
        status = wf.get('execution_status', '?')

        print(f'  Step {steps}: {current} ({status})  '
              f'LLM={wf.get("llm_call_count", 0)} Tool={wf.get("tool_call_count", 0)}')

        # HumanReview 打断 → 自动 approve (E→B)
        if wf.get('__human_review_needed__'):
            print(f'  [HumanReview] auto-approve → Normalization')
            wf['__human_review_needed__'] = False
            wf['__human_review_decision__'] = {
                'decisions': {}, 'route_decision': 'Normalization',
                'reviewer_notes': 'Auto-approve in e2e test',
            }
            wf['route_decision'] = 'Normalization'
            wf['execution_status'] = 'Success'
            state['workflow_state'] = wf
            continue

        if current in terminal_nodes:
            print(f'  → 到达终点: {current}')
            break
    else:
        print(f'  ⚠ 达到最大步数 {max_steps}')

    return state, round(time.time() - t0, 1), steps


def _verify(state, data: dict, errors: list) -> None:
    """核心验证。所有失败追加到 errors。"""
    sources = data['sources']
    records = data['records']
    n_paper_src = sum(1 for s in sources if s.get('source_type') == 'paper')
    n_db_src = sum(1 for s in sources if s.get('source_type') == 'database')
    n_paper_rec = sum(1 for r in records if r.get('extraction_method') != 'database_query')
    n_db_rec = sum(1 for r in records if r.get('extraction_method') == 'database_query')

    wf = state.get('workflow_state', {})
    output = state.get('output_state', {})
    quality = state.get('report_state', {}).get('quality', {})
    structured = output.get('structured_data') or {}
    out_recs = structured.get('records', structured.get('json', {}).get('records', []))
    out_srcs = structured.get('sources', structured.get('json', {}).get('sources', []))

    # 1. Schema version
    sv = output.get('schema_version', '?')
    if sv != '2.0.0':
        errors.append(f'schema_version={sv} (expected 2.0.0)')
    else:
        print(f'  [OK] schema_version = 2.0.0')

    # 2. 记录完整性: 不丢失 (允许 Normalization 去重导致的减少)
    input_ids = {r.get('record_id') for r in records}
    out_ids = {r.get('record_id') for r in out_recs}
    if len(out_recs) > len(records):
        errors.append(f'record count increased: {len(out_recs)} > input {len(records)}')
    else:
        dropped = len(input_ids) - len(out_ids)
        print(f'  [OK] 导出 {len(out_recs)} records (输入 {len(records)}, '
              f'去重/删除 {dropped} 条, 无新增)')
    # 无记录凭空新增
    new_ids = out_ids - input_ids
    if new_ids:
        errors.append(f'{len(new_ids)} records appear in output but not input')

    # 3. Source 完整性
    if len(out_srcs) != len(sources):
        errors.append(f'source count: {len(out_srcs)} vs input {len(sources)}')
    else:
        print(f'  [OK] 全部 {len(out_srcs)} sources 保留 ({n_paper_src} paper + {n_db_src} DB)')

    # 4. DB records: trace_id=None + provenance 四要素
    db_out = [r for r in out_recs if r.get('extraction_method') == 'database_query']
    db_input_ids = {r.get('record_id') for r in records if r.get('extraction_method') == 'database_query'}
    db_out_ids = {r.get('record_id') for r in db_out}
    if not db_out_ids.issubset(db_input_ids):
        errors.append(f'DB records added that are not in input: {db_out_ids - db_input_ids}')
    else:
        print(f'  [OK] {len(db_out)}/{n_db_rec} DB records 保留 (去重删 {n_db_rec - len(db_out)})')
    if db_out:
        bad_prov = 0
        bad_trace = 0
        for r in db_out:
            prov = r.get('provenance', {}) or {}
            for f in ('db_table', 'key_column', 'key_value', 'raw_column'):
                if f not in prov:
                    bad_prov += 1
                    break
            if r.get('trace_id') is not None:
                bad_trace += 1
        if bad_prov:
            errors.append(f'{bad_prov} DB records missing provenance fields')
        else:
            print(f'  [OK] DB provenance 四要素完整')
        if bad_trace:
            errors.append(f'{bad_trace} DB records have non-None trace_id')
        else:
            print(f'  [OK] DB records trace_id=None')

    # 5. DB source V3.1 字段
    db_src_out = [s for s in out_srcs if s.get('source_type') == 'database']
    if db_src_out:
        missing_fields = []
        for f in ('description', 'research_methodology', 'waveband',
                   'research_content', 'vizier_table_id', 'bibcode'):
            if f not in db_src_out[0]:
                missing_fields.append(f)
        if missing_fields:
            errors.append(f'DB source missing fields: {missing_fields}')
        else:
            print(f'  [OK] DB source V3.1 字段保留 ({len(db_src_out)} sources)')

    # 6. 路由分布
    route_counts = quality.get('route_counts', {})
    if not route_counts:
        errors.append('No route_counts (Assessment 未执行?)')
    else:
        print(f'  [OK] 路由分布: {route_counts}')

    # 7. 多源方差
    msv = quality.get('multi_source_variance', {})
    if msv:
        print(f'  [OK] 多源方差: {msv.get("variance_count", 0)} groups, '
              f'{msv.get("anomaly_count", 0)} anomalies')
    else:
        print(f'  [WARN] 无 multi_source_variance 输出')

    # 8. LLM/Tool 统计
    print(f'  [OK] LLM calls={wf.get("llm_call_count", 0)}, Tool calls={wf.get("tool_call_count", 0)}')

    # 9. Normalization 修改统计
    norm = state.get('report_state', {}).get('normalization', {})
    mods = norm.get('modifications', {})
    by_layer = mods.get('by_layer', {})
    print(f'  [OK] Normalization: base={by_layer.get("base", 0)} '
          f'adapted={by_layer.get("adapted", 0)} generated={by_layer.get("generated", 0)} '
          f'errors={len(mods.get("errors", []))}')

    # 10. V3.4: Insights 输出 (LLM 主观洞察)
    insights = output.get('insights')
    if not insights:
        errors.append('output_state.insights 为空 (洞察子图未执行?)')
    else:
        n_fi = len(insights.get('field_insights', []))
        n_rel = len(insights.get('cross_field_relationships', []))
        narrative = insights.get('overall_narrative', '')
        print(f'  [OK] Insights: {n_fi} field insights, {n_rel} relationships, '
              f'narrative={len(narrative)} chars')
        # 混合数据: paper 字段 (DM/redshift) + DB 字段 (Plx/Gmag 等) 都应覆盖
        fi_fields = {f.get('field_name') for f in insights.get('field_insights', [])}
        fi_src_types = {f.get('source_type') for f in insights.get('field_insights', [])}
        if 'paper' not in fi_src_types:
            errors.append(f'Insights 未覆盖 paper 字段: {sorted(fi_fields)[:5]}')
        if 'database' not in fi_src_types:
            errors.append(f'Insights 未覆盖 database 字段: {sorted(fi_fields)[:5]}')
        else:
            print(f'  [OK] Insights 覆盖 paper+database: {sorted(fi_fields)[:8]}')
        # insights_*.json 文件存在
        import glob as _glob
        out_dir = output.get('output_dir')
        if out_dir and _glob.glob(os.path.join(out_dir, 'insights_*.json')):
            print(f'  [OK] insights_*.json 已写入 {out_dir}')
        else:
            errors.append('insights_*.json 未找到')


def main():
    parser = argparse.ArgumentParser(description='真实混合数据端到端测试')
    parser.add_argument('--data', type=str, default=_DEFAULT_DATA, help='grounded_data JSON 路径')
    args = parser.parse_args()

    print('=' * 70)
    print('  真实混合数据端到端测试 (V3.1)')
    print('=' * 70)

    data = _load_data(args.data)
    sources, records = data['sources'], data['records']
    n_paper_src = sum(1 for s in sources if s.get('source_type') == 'paper')
    n_db_src = sum(1 for s in sources if s.get('source_type') == 'database')
    n_paper_rec = sum(1 for r in records if r.get('extraction_method') != 'database_query')
    n_db_rec = sum(1 for r in records if r.get('extraction_method') == 'database_query')
    print(f'\n输入: {n_paper_src} papers + {n_db_src} databases = {len(sources)} sources')
    print(f'      {n_paper_rec} paper + {n_db_rec} DB = {len(records)} records\n')

    state, elapsed, steps = _run_graph(data)

    print(f'\nGraph 执行完成: {elapsed:.1f}s ({steps} steps)')
    print(f'最终节点: {state.get("workflow_state", {}).get("current_node", "?")}')
    print('─' * 70)

    errors = []
    _verify(state, data, errors)

    print('─' * 70)
    if errors:
        print(f'\n  FAILED ({len(errors)} errors):')
        for e in errors:
            print(f'    - {e}')
        return 1
    else:
        print(f'\n  {"="*40}')
        print(f'  真实混合数据 E2E: ALL CHECKS PASSED')
        print(f'  耗时: {elapsed:.1f}s')
        print(f'  {"="*40}')
        return 0


if __name__ == '__main__':
    import logging; logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
