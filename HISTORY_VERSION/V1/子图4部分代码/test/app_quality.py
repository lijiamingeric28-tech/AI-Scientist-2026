"""
app_quality.py

Quality 子图调试入口。支持:
  - 加载 mock_data 或生成的测试数据
  - Human Review 交互式打断
  - 打印完整执行结果

用法:
    python app_quality.py                          # 使用 mock_data (8条)
    python app_quality.py --data test_data_1000.json  # 使用生成数据
    python app_quality.py --count 500              # 实时生成 500 条测试
"""

from __future__ import annotations  # V3.1 fix: future import 必须在文件顶部

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import os
import sys

from quality_state import make_initial_state
from graph import compile_quality_graph  # V3.1 fix: 实际路径是 graph.compile_quality_graph
from utils.logger import setup_logging, get_logger

logger = get_logger(__name__)

def load_data(data_path: str, validate: bool = True) -> dict:
    """从 JSON 文件加载 grounded_data，默认强校验。"""
    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if validate:
        from models.grounded_data import GroundedData
        validated = GroundedData.model_validate(raw)
        logger.info("输入校验通过: %d sources, %d records",
                    len(validated.sources), len(validated.records))
        return validated.model_dump()
    return raw

# ==========================================================
# Human Review 交互
# ==========================================================

def handle_human_review(state: dict) -> dict:
    """
    交互式处理 Human Review。

    显示冲突详情 → 等待用户输入 → 返回更新后的 state。
    """
    wf = state.get("workflow_state", {})
    pending = wf.get("__human_review_data__", [])

    if not pending:
        print("\n[HUMAN REVIEW] 无冲突需要决策。自动继续...")
        wf["__human_review_needed__"] = False
        return state

    print("\n" + "=" * 70)
    print("  [HUMAN REVIEW] 以下冲突需要您的判断")
    print("=" * 70)

    decisions = []

    for i, conflict in enumerate(pending):
        print(f"\n── 冲突 {i + 1}/{len(pending)} ──")
        print(f"  字段: {conflict.get('field_name', '?')}")
        print()
        print(f"  来源 A: {conflict.get('source_a_title', '?')}")
        print(f"    年份: {conflict.get('source_a_year', '?')}, "
              f"优先级: {conflict.get('source_a_priority', '?')}")
        print(f"    值: {conflict.get('value_a', '?')}")
        print()
        print(f"  来源 B: {conflict.get('source_b_title', '?')}")
        print(f"    年份: {conflict.get('source_b_year', '?')}, "
              f"优先级: {conflict.get('source_b_priority', '?')}")
        print(f"    值: {conflict.get('value_b', '?')}")
        print()

        while True:
            choice = input(f"  请选择 [A/B/both/custom]: ").strip().lower()
            if choice in ("a", "b", "both"):
                break
            elif choice == "custom":
                custom_val = input(f"  请输入修正值: ").strip()
                try:
                    custom_val = float(custom_val)
                    break
                except ValueError:
                    print("  请输入有效数值。")
            else:
                print("  无效选项，请重试。")

        decision = {
            "conflict_index": conflict.get("conflict_index", i),
            "field_name": conflict.get("field_name"),
            "record_a_id": conflict.get("record_a_id"),
            "record_b_id": conflict.get("record_b_id"),
        }

        if choice == "a":
            decision["choice"] = "keep_a"
        elif choice == "b":
            decision["choice"] = "keep_b"
        elif choice == "both":
            decision["choice"] = "keep_both"
        elif choice == "custom":
            decision["choice"] = "custom_value"
            decision["custom_value"] = custom_val

        decisions.append(decision)
        print(f"  -> 决策: {decision['choice']}")

    # 注入决策到 state
    wf["__human_review_decision__"] = decisions
    wf["__human_review_needed__"] = False
    state["workflow_state"] = wf

    print("\n" + "=" * 70)
    print("  人工决策已记录，恢复 Pipeline 执行...")
    print("=" * 70 + "\n")

    return state

# ==========================================================
# 主函数
# ==========================================================

def main():
    parser = argparse.ArgumentParser(description="Quality Pipeline 运行入口")
    parser.add_argument("--data", type=str, default=None,
                        help="grounded_data JSON 文件路径 (默认: mock_data)")
    parser.add_argument("--count", type=int, default=None,
                        help="实时生成 N 条测试数据")
    parser.add_argument("--no-interactive", action="store_true",
                        help="非交互模式: Human Review 自动放行")
    args = parser.parse_args()

    setup_logging()

    # ── 加载数据 ──
    if args.count:
        from generate_test_data import generate_test_data
        print(f"实时生成 {args.count} 条测试数据...")
        input_data = generate_test_data(args.count)
    elif args.data:
        data_path = os.path.join(os.path.dirname(__file__), args.data)
        print(f"加载数据: {data_path}")
        input_data = load_data(data_path)
    else:
        from mock_data import get_mock_data_json
        input_data = get_mock_data_json()

    total_records = len(input_data.get("records", []))
    total_sources = len(input_data.get("sources", []))
    print(f"数据: {total_sources} 篇论文, {total_records} 条记录\n")

    # ── 加载配置并注入 State ──
    from configs import load_yaml
    quality_rules = load_yaml("quality_rules.yaml")
    schema_mapping = load_yaml("schema_mapping.yaml")
    # V3.1 fix: 根据领域加载对应 target_schema
    domain = input_data.get("research_domain", "")
    if domain == "astrophysics":
        target_schema = schema_mapping.get("target_schema_astrophysics", {})
    else:
        target_schema = schema_mapping.get("target_schema", {})

    # ── 初始化 ──
    state = make_initial_state(input_data)
    # 注入配置文件到 context_state
    state["context_state"].update({
        "target_schema": target_schema,
        "quality_rules": quality_rules,
        "standard_units": schema_mapping.get("unit_conversions", {}),
    })
    app = compile_quality_graph()

    # ── 运行管道 (支持 Human Review 打断-恢复循环) ──
    max_rounds = 10  # 防止无限循环
    round_num = 0

    while round_num < max_rounds:
        round_num += 1
        state = app.invoke(state)

        wf = state.get("workflow_state", {})

        # 检查是否需要 Human Review
        if wf.get("__human_review_needed__"):
            if args.no_interactive:
                print("\n[HUMAN REVIEW] 非交互模式 — 自动放行")
                wf["__human_review_needed__"] = False
                wf["__human_review_decision__"] = []
                state["workflow_state"] = wf
            else:
                state = handle_human_review(state)
            continue  # 继续循环，恢复执行

        # 无打断 → 执行完成
        break
    else:
        print("\n警告: 达到最大循环次数，可能存在死循环。")

    # ── 输出结果 ──
    wf = state.get("workflow_state", {})
    data_s = state.get("data_state", {})
    report_s = state.get("report_state", {})
    output_s = state.get("output_state", {})

    print("\n" + "=" * 70)
    print("  Quality Pipeline — 执行结果")
    print("=" * 70)

    print(f"\n  Workflow: status={wf.get('execution_status')}, "
          f"iter={wf.get('iteration_counter')}, "
          f"retry={wf.get('retry_counter')}, "
          f"human_reviews={sum(1 for h in wf.get('workflow_history', []) if 'human_review' in h.get('node',''))}")

    quality = report_s.get("quality", {}) or {}
    scoring = quality.get("quality_scoring", {})
    print(f"  质量评分: {scoring.get('overall_score', 'N/A'):.4f} "
          f"({scoring.get('quality_level', 'N/A')})")

    norm = report_s.get("normalization", {}) or {}
    print(f"  规范化:   {norm.get('normalization_status', 'N/A')}, "
          f"修改 {norm.get('modified_count', 0)} 条")

    conflict = report_s.get("conflict", {}) or {}
    print(f"  冲突解决: {conflict.get('resolution_result', 'N/A')}, "
          f"置信度={conflict.get('confidence', 'N/A')}")

    output = output_s.get("structured_data", {}) or {}
    print(f"  输出:     {output.get('row_count', 0)} 行 x {output.get('column_count', 0)} 列")

    # 质量问题摘要
    quality_sum = output_s.get("quality_summary", {}) or {}
    recs = quality_sum.get("recommendations", [])
    if recs:
        print(f"\n  建议:")
        for r in recs:
            print(f"    - {r}")
    note = quality_sum.get("confidence_note", "")
    if note:
        print(f"  备注: {note}")

    # LLM 是否生效（基于统计数据而非单个报告）
    from utils.llm import get_llm_stats
    stats = get_llm_stats()
    if stats["total_calls"] > 0 and stats["success_rate"] > 0:
        print(f"\n  LLM: 调用 {stats['total_calls']} 次, 成功率 {stats['success_rate']}%,"
              f" 总耗时 {stats['total_thinking_seconds']:.1f}s")
    elif stats["total_calls"] > 0:
        print(f"\n  LLM: {stats['total_calls']} 次调用全部失败, 回退规则引擎")
    else:
        print(f"\n  LLM: 未调用 (规则引擎处理)")

    # ── LLM 调用统计 ──
    from utils.llm import print_llm_stats
    print_llm_stats()

    return state

if __name__ == "__main__":
    main()
