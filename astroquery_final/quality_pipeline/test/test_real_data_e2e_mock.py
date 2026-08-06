"""
test_real_data_e2e_mock.py — 零 LLM 成本的真实数据全链路验证 (V4.2)

复用 test_real_data_e2e 的图执行与验证逻辑, 但用 mock LLM (固定返回值):
  - 所有确定性环节真实执行: 字段映射(1178 别名) / 单位转换(34 组) /
    语义推断 / 路由 / Export 白名单保留 / 数据完整性
  - LLM 环节全部走 fallback (planning→Base tools, metadata→模板, insights→确定性模板)
  - 无 API 调用, 无成本

用法: python test/test_real_data_e2e_mock.py [--data test_data_sample10.json]
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── 在 import 模块前 patch get_llm ──
import unittest.mock as _mock
import utils.llm as _llm_mod

_FAKE_RESPONSES = {
    # 各 agent 期望的 JSON 结构 (解析失败 → 走 fallback, 正是我们要验证的)
    'planning': '{"tools": [], "reasoning": "mock"}',
    'insights': '{"insights": [], "relationships": [], "overall_grade": "good", '
                '"suitable_use_cases": [], "limitations": [], "recommended_caveats": [], '
                '"overall_narrative": "mock narrative"}',
}


def _fake_llm(*args, **kwargs):
    m = _mock.MagicMock()
    m.content = json.dumps({
        "tools": [], "reasoning": "mock-plan",
        "insights": [], "relationships": [],
        "overall_grade": "good", "suitable_use_cases": [],
        "limitations": [], "recommended_caveats": [],
        "overall_narrative": "mock narrative",
    })
    return m


_llm_mod.get_llm = _fake_llm

import test_real_data_e2e as e2e
from ..graph import compile_quality_graph
from ..quality_state import make_initial_state
from ..configs import load_yaml


def main():
    parser = argparse.ArgumentParser(description='零 LLM 全链路验证')
    parser.add_argument('--data', type=str, default=None)
    args = parser.parse_args()
    path = args.data or os.path.join(os.path.dirname(__file__), '..', 'test_data_sample10.json')
    if not os.path.exists(path):
        path = e2e._DEFAULT_DATA
    print('=' * 70)
    print('  零 LLM 成本真实数据全链路验证 (V4.2, mock LLM)')
    print('=' * 70)

    data = e2e._load_data(path)
    sources, records = data['sources'], data['records']
    n_paper = sum(1 for r in records if r.get('extraction_method') != 'database_query')
    n_db = sum(1 for r in records if r.get('extraction_method') == 'database_query')
    print(f'\n输入: {len(sources)} sources / {len(records)} records ({n_paper} paper + {n_db} DB)')
    print(f'数据文件: {os.path.basename(path)}')

    state, elapsed, steps = e2e._run_graph(data)

    print(f'\nGraph 执行完成: {elapsed:.1f}s ({steps} steps)')
    print('─' * 70)

    errors = []
    e2e._verify(state, data, errors)

    print('─' * 70)
    if errors:
        print(f'\n  FAILED ({len(errors)} errors):')
        for e in errors:
            print(f'    - {e}')
        return 1
    print(f'\n  {"="*40}')
    print(f'  零 LLM 全链路: ALL CHECKS PASSED (无 LLM 调用)')
    print(f'  {"="*40}')
    return 0


if __name__ == '__main__':
    import logging; logging.basicConfig(level=logging.ERROR)
    sys.exit(main())
