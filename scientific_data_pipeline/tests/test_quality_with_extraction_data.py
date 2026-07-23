"""
test_quality_with_extraction_data.py — 用真实提取数据测试 Quality 子图

利用 data/reports/ 中的提取结果，完整测试 Assessment → Normalization → Export 流程。
"""
import sys
sys.path.insert(0, '.')

import json, os, time

def main():
    # ── 1. 加载提取数据 ──
    reports_dir = "data/reports"
    # 找最大的 JSON 文件（最新/最完整的提取结果）
    json_files = sorted(
        [f for f in os.listdir(reports_dir) if f.endswith('.json')],
        key=lambda f: os.path.getsize(os.path.join(reports_dir, f)),
        reverse=True,
    )

    if not json_files:
        print("ERROR: No extraction JSON files found!")
        return False

    # 用最新的完整数据
    input_file = os.path.join(reports_dir, json_files[0])
    print(f"Loading: {input_file} ({os.path.getsize(input_file)} bytes)")

    with open(input_file, 'r', encoding='utf-8') as f:
        extraction_result = json.load(f)

    # 提取 grounded_data
    grounded_data = extraction_result.get("grounded_data", extraction_result)
    records = grounded_data.get("records", [])
    sources = grounded_data.get("sources", [])

    print(f"  Sources: {len(sources)}")
    print(f"  Records: {len(records)}")

    # 数据统计
    fields = set(r.get("field_name", "") for r in records)
    entity_types = set(r.get("entity_type", "") for r in records)
    units = set(r.get("field_unit", "") for r in records)
    print(f"  Unique fields: {sorted(fields)}")
    print(f"  Entity types: {entity_types}")
    print(f"  Units: {units}")
    print()

    # ── 2. 编译 Quality 子图 ──
    print("=" * 70)
    print("Compiling quality subgraph...")
    from subgraphs.quality.graph import compile_quality_graph
    graph = compile_quality_graph()
    nodes = list(graph.nodes.keys()) if hasattr(graph, 'nodes') else list(graph.builder._nodes.keys())
    print(f"  Nodes: {nodes}")
    print()

    # ── 3. 构建输入 State ──
    print("=" * 70)
    print("Building QualityGraphState input...")

    # 推断领域
    domain = "astronomy" if "FRB" in str(entity_types) or "pulsar" in str(fields).lower() else "materials_science"

    # 从实际数据自动构建 target_schema (只用数据中存在的字段)
    field_units = {}
    for r in records:
        fn = r.get("field_name", "")
        fu = r.get("field_unit", "")
        if fn not in field_units:
            field_units[fn] = set()
        if fu:
            field_units[fn].add(fu)

    target_schema = {
        "fields": [
            {"name": fn, "standard_unit": sorted(units)[0] if units else ""}
            for fn, units in sorted(field_units.items())
        ]
    }
    print(f"  Auto-detected target_schema: {target_schema}")

    quality_input = {
        "context_state": {
            "clarified_intent": {
                "entities": ["FRB"],
                "properties": sorted(fields),
                "conditions": {},
            },
            "research_domain": domain,
            "target_schema": target_schema,
        },
        "data_state": {
            "input_data": grounded_data,
            "current_data": grounded_data,
            "data_trace": [],
        },
        "report_state": {},
        "workflow_state": {
            "current_node": "start",
            "execution_status": "Success",
            "iteration_counter": 0,
            "retry_counter": 0,
            "route_decision": "",
            "workflow_history": [],
        },
        "output_state": {},
    }

    print(f"  Domain: {domain}")
    print(f"  Target schema fields: {len(target_schema['fields'])}")
    print()

    # ── 4. 运行 Quality 子图 ──
    print("=" * 70)
    print("Running quality subgraph...")
    t0 = time.time()

    try:
        result = graph.invoke(quality_input)
        elapsed = time.time() - t0
        print(f"  Completed in {elapsed:.2f}s")
    except Exception as e:
        print(f"  FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()

    # ── 5. 结果分析 ──
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    rs = result.get("report_state", {})
    wf = result.get("workflow_state", {})
    os_ = result.get("output_state", {})

    # ── Assessment 结果 ──
    quality = rs.get("quality", {})
    print("\n--- Assessment ---")
    profile = quality.get("profile", {})
    ds = profile.get("dataset_summary", {})
    print(f"  Records: {ds.get('record_count', '?')}")
    print(f"  Sources: {ds.get('source_count', '?')}")
    print(f"  Fields: {ds.get('field_count', '?')}")

    per_source_routes = quality.get("per_source_routes", {})
    route_counts = quality.get("route_counts", {})
    print(f"  Route distribution: {route_counts}")
    print(f"  Per-source routes:")
    for sid, route in per_source_routes.items():
        reason = quality.get("per_source_reasons", {}).get(sid, "?")
        print(f"    {sid[:30]}... → {route}")
        print(f"      理由: {reason[:120]}")

    # 质量评分
    for sid, sr in quality.get("sources", {}).items():
        scoring = sr.get("quality_scoring", {})
        print(f"  [{sid[:30]}...] score={scoring.get('overall_score', 0):.3f}, "
              f"level={scoring.get('quality_level', '?')}, "
              f"issues={sr.get('issue_count', 0)}, "
              f"conflicts={sr.get('conflict_risk', {}).get('conflict_count', 0)}")

        # 详细 issue
        for iss in sr.get("issues", [])[:5]:
            print(f"    [{iss.get('dimension', '?')}] {iss.get('detail', '')[:100]}")

    # ── Normalization 结果 ──
    norm = rs.get("normalization", {})
    if norm:
        print("\n--- Normalization ---")
        print(f"  Status: {norm.get('normalization_status', '?')}")
        mods = norm.get("modifications", {})
        print(f"  Total modifications: {mods.get('total', 0)}")
        by_layer = mods.get("by_layer", {})
        print(f"  By layer: base={by_layer.get('base', 0)}, adapted={by_layer.get('adapted', 0)}, generated={by_layer.get('generated', 0)}")

        validation = norm.get("validation", {})
        print(f"  Valid: {validation.get('is_valid', False)}")
        print(f"  Needs conflict analysis: {validation.get('needs_conflict_analysis', False)}")
        print(f"  Remaining issues: {validation.get('remaining_issues', [])}")
        print(f"  Route decision: {norm.get('route_decision', '?')}")

        # 每个 source 的工具计划
        sp = norm.get("source_plan", {})
        for sid, plan in sp.get("per_source_plans", {}).items():
            tools = [t.get("tool", "?") for t in plan.get("tools", [])]
            print(f"  [{sid[:30]}...] tools: {tools}")

    # ── Conflict 结果 ──
    conflict = rs.get("conflict", {})
    if conflict and conflict.get("resolution_report"):
        cr_report = conflict["resolution_report"]
        print("\n--- Conflict ---")
        print(f"  Status: {cr_report.get('status', '?')}")
        print(f"  Route: {cr_report.get('route_decision', '?')}")
        print(f"  Total: {cr_report.get('metadata', {}).get('total_conflicts', 0)}")
        print(f"  Auto-resolved: {cr_report.get('metadata', {}).get('auto_resolved', 0)}")
        print(f"  Human required: {cr_report.get('metadata', {}).get('human_required', 0)}")
    elif conflict:
        print("\n--- Conflict ---")
        ident = conflict.get("identification", {})
        print(f"  Total conflicts: {ident.get('total_conflicts', 0)}")
        if ident.get('total_conflicts', 0) == 0:
            print("  (No conflicts detected)")
    else:
        print("\n--- Conflict ---")
        print("  (Not executed)")

    # ── Workflow 追踪 ──
    print("\n--- Workflow Trace ---")
    history = wf.get("workflow_history", [])
    for h in history:
        agent = h.get("agent", "?")
        stage = h.get("stage", "?")
        status = h.get("status", "?")
        reason = h.get("reason", "")[:100]
        dur = h.get("duration", 0)
        print(f"  [{agent}/{stage}] {status} ({dur:.2f}s) — {reason}")

    print(f"\n  Iteration counter: {wf.get('iteration_counter', 0)}")
    print(f"  Final route decision: {wf.get('route_decision', '?')}")
    print(f"  Execution status: {wf.get('execution_status', '?')}")

    # ── Output ──
    print("\n--- Output ---")
    structured = os_.get("structured_data", {})
    if structured:
        print(f"  Rows: {structured.get('row_count', 0)}")
        print(f"  Columns: {structured.get('column_count', 0)}")
        json_data = structured.get("json", {})
        if json_data:
            out_records = json_data.get("records", [])
            print(f"  Output records: {len(out_records)}")

    quality_summary = os_.get("quality_summary", {})
    if quality_summary:
        print(f"  Quality level: {quality_summary.get('quality_level', '?')}")
        print(f"  Overall score: {quality_summary.get('overall_score', 0):.4f}")
        print(f"  Confidence: {quality_summary.get('calibrated_confidence', 0):.4f}")
        proc = quality_summary.get("processing_statistics", {})
        print(f"  LLM calls: {proc.get('total_llm_calls', 0)}")
        print(f"  Tool calls: {proc.get('total_tool_calls', 0)}")

    # ── 数据完整性 ──
    print("\n--- Data Integrity ---")
    input_count = len(records)
    output_count = structured.get("row_count", 0) if structured else 0
    if output_count == input_count:
        print(f"  [PASS] Input={input_count}, Output={output_count} (no data loss)")
    else:
        print(f"  [WARN] Input={input_count}, Output={output_count} (Δ={output_count-input_count})")

    # ── 错误检查 ──
    print("\n--- Error Check ---")
    last_error = wf.get("last_error")
    if last_error:
        print(f"  Last error: {last_error[:200]}")
    else:
        print(f"  No errors reported")

    # 检查是否有 LLM 失败
    mods = norm.get("modifications", {})
    if mods.get("errors"):
        print(f"  Normalization errors: {mods['errors'][:3]}")

    print()
    print("=" * 70)
    print("TEST COMPLETED SUCCESSFULLY")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
