"""
test_assessment_flow.py — Assessment Module Per-Source 流程测试
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from ..utils.logger import setup_logging; setup_logging()
from ..utils.llm import reset_llm, reset_llm_stats; reset_llm(); reset_llm_stats()

from generate_test_data import generate_test_data
from ..quality_state import make_initial_state
from ..configs import load_yaml

def main():
    t0 = time.time()

    print('=' * 70)
    print('  Assessment Module — Per-Source 流程测试')
    print('=' * 70)

    input_data = generate_test_data(8)
    state = make_initial_state(input_data)
    state['context_state'].update({
        'quality_rules': load_yaml('quality_rules.yaml'),
        'target_schema': load_yaml('schema_mapping.yaml').get('target_schema', {}),
    })

    print(f'\n输入: {len(input_data["sources"])} 篇论文, {len(input_data["records"])} 条记录\n')
    for rec in input_data['records']:
        sid = rec['source_id'][:25]
        print(f'  [{sid}] {rec["field_name"]:20s} = {str(rec["field_value"]):10s} {rec.get("field_unit",""):6s}')

    # ═══ Stage 1: Profiling ═══
    print(f'\n{"─" * 70}\nStage 1: ProfilingAgent\n{"─" * 70}')
    from ..Data_Assessment_agentV1.agents.profiling_agent import ProfilingAgent
    s1 = ProfilingAgent().run(state); state = {**state, **s1}
    p = s1['report_state']['quality']['profile']
    print(f'  Records: {p["dataset_summary"]["record_count"]}, '
          f'Sources: {p["dataset_summary"]["source_count"]}, '
          f'Fields: {p["dataset_summary"]["field_count"]}')
    print(f'  Status: {s1["workflow_state"]["execution_status"]}')

    # ═══ Stage 2: Per-Source Assessment ═══
    print(f'\n{"─" * 70}\nStage 2: QualityAssessmentAgent (per-source)\n{"─" * 70}')
    from ..Data_Assessment_agentV1.agents.quality_assessment_agent import QualityAssessmentAgent
    s2 = QualityAssessmentAgent().run(state); state = {**state, **s2}
    q = s2['report_state']['quality']
    sources = q['sources']
    print(f'  Assessed {len(sources)} sources:')
    for sid, sr in sources.items():
        title = sr.get('title', sid)[:50]
        recs = sr['record_count']
        issues = sr['issue_count']
        comp = sr['completeness']['score']
        cons = sr['consistency']['score']
        confs = sr['conflict_risk']['conflict_count']
        print(f'    [{sid[:25]}] {title} | {recs} recs | '
              f'comp={comp:.2f} cons={cons:.2f} conflicts={confs} | issues={issues}')

    # ═══ Stage 3: Per-Source Scoring ═══
    print(f'\n{"─" * 70}\nStage 3: QualityScoringAgent (per-source)\n{"─" * 70}')
    from ..Data_Assessment_agentV1.agents.quality_scoring_agent import QualityScoringAgent
    s3 = QualityScoringAgent().run(state); state = {**state, **s3}
    sc = s3['report_state']['quality']['quality_scoring']
    print(f'  Per-source scores:')
    for sid, score in sc['per_source_scores'].items():
        sr = sources.get(sid, {})
        lvl = sr.get('quality_scoring', {}).get('quality_level', '?')
        print(f'    [{sid[:25]}] score={score:.4f} ({lvl})')
    print(f'  Overall: {sc["overall_score"]:.4f} ({sc["quality_level"]})')

    # ═══ Stage 4: Per-Source Decision (V3.0) ═══
    print(f'\n{"─" * 70}\nStage 4: DecisionReasoningAgent (V3.0 per-source routing)\n{"─" * 70}')
    from ..Data_Assessment_agentV1.agents.decision_reasoning_agent import DecisionReasoningAgent
    s4 = DecisionReasoningAgent().run(state); state = {**state, **s4}
    dq = s4['report_state']['quality']
    print(f'  Per-source routes (V3.0: anomaly→Conflict, variance→Export):')
    for sid, route in dq['per_source_routes'].items():
        reason = dq['per_source_reasons'].get(sid, '')[:80]
        print(f'    [{sid[:25]}] → {route:15s} | {reason}')
    print(f'')
    rc = dq.get('route_counts', {})
    print(f'  Route Distribution: {rc}')
    print(f'  Summary:            {dq.get("assessment_summary", "")}')
    # V3.0: multi_source_variance summary
    msv = dq.get('multi_source_variance', {})
    if msv:
        print(f'  Variance groups:    {msv.get("variance_count", 0)}')
        print(f'  Anomaly count:      {msv.get("anomaly_count", 0)}')
    # V4 fix: 手工分段合并 ({**state, **s4}) 无 reducer, DecisionReasoning 返回
    # 不含 llm_call_count → 防御性 .get 读取
    print(f'  LLM calls:          {s4["workflow_state"].get("llm_call_count", 0)}')

    # ═══ LLM Stats ═══
    from ..utils.llm import print_llm_stats
    print_llm_stats()

    elapsed = time.time() - t0
    print(f'\n  Total: {elapsed:.1f}s')
    print('=' * 70)

if __name__ == '__main__':
    main()
