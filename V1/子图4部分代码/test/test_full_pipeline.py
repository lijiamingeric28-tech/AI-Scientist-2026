"""
test_full_pipeline.py — 五模块全流程集成测试 (分场景覆盖)

场景设计 (每个场景独立测试一组分支):
  Scene 1: A→B→D   — 别名/格式问题, Normalization 清洗后直接 Export
  Scene 2: A→C→B→C→D — 纯冲突, Conflict→Normalization→Conflict→Export
  Scene 3: A→D      — 完全干净数据, 直接 Export
  Scene 4: 混合场景   — 同时有 Normalization + Conflict 来源

用法:
  cd 子图4部分代码
  python test/test_full_pipeline.py
"""
from __future__ import annotations
import sys, os, time, io, copy
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from utils.logger import setup_logging
from utils.llm import reset_llm, reset_llm_stats, get_llm_stats

SEP = "=" * 80
SEP2 = "-" * 80


def banner(s):
    print(f"\n{SEP}\n  {s}\n{SEP}")


def section(s):
    print(f"\n  {s}\n  {SEP2}")


# ═══════════════════════════════════════════════════
# Scene 1: A→B→D — Normalization→Export
# ═══════════════════════════════════════════════════

def scene_1():
    """2 papers: aliases + format issues only, no conflicts"""
    return {
        "schema_version": "1.0.0",
        "sources": [
            {"source_id": "10.1016/j.msea.2024.001", "source_type": "paper",
             "doi": "10.1016/j.msea.2024.001",
             "title": "Tensile of Al-7075 after T6", "authors": ["Zhang, W."],
             "year": 2024, "journal": "MSEA", "access_path": "/cache/a.pdf",
             "retrieval_priority": 0.95},
            {"source_id": "10.1007/s11661-023-002", "source_type": "paper",
             "doi": "10.1007/s11661-023-002",
             "title": "Aging of Al-Zn-Mg-Cu", "authors": ["Wang, X."],
             "year": 2023, "journal": "MMTA", "access_path": "/cache/b.pdf",
             "retrieval_priority": 0.87},
        ],
        "records": [
            # Paper 1: 别名 YS/UTS + ~前缀 → Normalization
            {"record_id": "10.1016_j.msea.2024.001_yield_strength_1",
             "source_id": "10.1016/j.msea.2024.001", "field_name": "YS",
             "field_value": "~450", "field_unit": "MPa",
             "trace_id": "a1", "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},
             "extraction_method": "llm_table"},
            {"record_id": "10.1016_j.msea.2024.001_tensile_strength_1",
             "source_id": "10.1016/j.msea.2024.001", "field_name": "UTS",
             "field_value": 520, "field_unit": "MPa",
             "trace_id": "a2", "provenance": {"page": 3, "bbox": [120, 356, 280, 371]},
             "extraction_method": "llm_table"},
            # Paper 2: GPa需×1000→MPa + 缺单位 → Normalization
            {"record_id": "10.1007_s11661-023-002_yield_strength_1",
             "source_id": "10.1007/s11661-023-002", "field_name": "yield_strength",
             "field_value": 0.438, "field_unit": "GPa",
             "trace_id": "b1", "provenance": {"page": 5, "bbox": [90, 420, 250, 435]},
             "extraction_method": "llm_table"},
            {"record_id": "10.1007_s11661-023-002_yield_strength_2",
             "source_id": "10.1007/s11661-023-002", "field_name": "yield_strength",
             "field_value": 0.442, "field_unit": "GPa",
             "trace_id": "b2", "provenance": {"page": 6, "bbox": [90, 420, 250, 435]},
             "extraction_method": "llm_table"},
            {"record_id": "10.1007_s11661-023-002_hardness_1",
             "source_id": "10.1007/s11661-023-002", "field_name": "hardness",
             "field_value": 185, "field_unit": None,
             "trace_id": "b3", "provenance": {"page": 5, "bbox": [90, 452, 250, 467]},
             "extraction_method": "llm_table"},
        ],
    }


# ═══════════════════════════════════════════════════
# Scene 2: A→C→B→C→D — Conflict→Normalization→Conflict→Export
# ═══════════════════════════════════════════════════

def scene_2():
    """2 papers: 干净字段, 值不同, 纯冲突场景"""
    return {
        "schema_version": "1.0.0",
        "sources": [
            {"source_id": "10.1016/j.corsci.2022.004", "source_type": "paper",
             "doi": "10.1016/j.corsci.2022.004",
             "title": "Corrosion of 316L stainless steel", "authors": ["Mueller, F."],
             "year": 2022, "journal": "Corrosion Science", "access_path": "/cache/d.pdf",
             "retrieval_priority": 0.85},
            {"source_id": "10.1016/j.wear.2023.007", "source_type": "paper",
             "doi": "10.1016/j.wear.2023.007",
             "title": "Wear resistance of 316L coating", "authors": ["Brown, T."],
             "year": 2023, "journal": "Wear", "access_path": "/cache/g.pdf",
             "retrieval_priority": 0.83},
        ],
        "records": [
            # Paper 4: hardness=220,225 HV (标准字段, 干净)
            {"record_id": "10.1016_j.corsci.2022.004_hardness_1",
             "source_id": "10.1016/j.corsci.2022.004", "field_name": "hardness",
             "field_value": 220, "field_unit": "HV",
             "trace_id": "d1", "provenance": {"page": 3, "bbox": [100, 300, 200, 315]},
             "extraction_method": "llm_table"},
            {"record_id": "10.1016_j.corsci.2022.004_hardness_2",
             "source_id": "10.1016/j.corsci.2022.004", "field_name": "hardness",
             "field_value": 225, "field_unit": "HV",
             "trace_id": "d2", "provenance": {"page": 4, "bbox": [100, 300, 200, 315]},
             "extraction_method": "llm_table"},
            # Paper 7: hardness=320,315 HV (标准字段, 干净, 与Paper4冲突)
            {"record_id": "10.1016_j.wear.2023.007_hardness_1",
             "source_id": "10.1016/j.wear.2023.007", "field_name": "hardness",
             "field_value": 320, "field_unit": "HV",
             "trace_id": "g1", "provenance": {"page": 5, "bbox": [90, 400, 250, 415]},
             "extraction_method": "llm_table"},
            {"record_id": "10.1016_j.wear.2023.007_hardness_2",
             "source_id": "10.1016/j.wear.2023.007", "field_name": "hardness",
             "field_value": 315, "field_unit": "HV",
             "trace_id": "g2", "provenance": {"page": 6, "bbox": [90, 400, 250, 415]},
             "extraction_method": "llm_table"},
        ],
    }


# ═══════════════════════════════════════════════════
# Scene 3: A→D — 完全干净数据, 直接 Export
# ═══════════════════════════════════════════════════

def scene_3():
    """1 paper: 单字段, 干净"""
    return {
        "schema_version": "1.0.0",
        "sources": [
            {"source_id": "10.1016/j.actamat.2025.003", "source_type": "paper",
             "doi": "10.1016/j.actamat.2025.003",
             "title": "Ti-6Al-4V properties", "authors": ["Kim, S."],
             "year": 2025, "journal": "Acta Materialia", "access_path": "/cache/c.pdf",
             "retrieval_priority": 0.92},
        ],
        "records": [
            {"record_id": "10.1016_j.actamat.2025.003_yield_strength_1",
             "source_id": "10.1016/j.actamat.2025.003", "field_name": "yield_strength",
             "field_value": 880, "field_unit": "MPa",
             "trace_id": "c1", "provenance": {"page": 4, "bbox": [80, 300, 240, 315]},
             "extraction_method": "llm_table"},
            {"record_id": "10.1016_j.actamat.2025.003_yield_strength_2",
             "source_id": "10.1016/j.actamat.2025.003", "field_name": "yield_strength",
             "field_value": 870, "field_unit": "MPa",
             "trace_id": "c2", "provenance": {"page": 5, "bbox": [80, 300, 240, 315]},
             "extraction_method": "llm_table"},
        ],
    }


# ═══════════════════════════════════════════════════
# Print Helpers
# ═══════════════════════════════════════════════════

def print_input(data):
    for s in data["sources"]:
        n = sum(1 for r in data["records"] if r["source_id"] == s["source_id"])
        print(f"  [{s['source_id'][:30]:30s}] {s['title'][:50]} ({s['year']}) | {n} recs")


def run_scene(name, data, expected_branches):
    """运行一个测试场景。"""
    banner(f"SCENE: {name}")
    print(f"  Papers: {len(data['sources'])}, Records: {len(data['records'])}")
    print_input(data)

    setup_logging()
    reset_llm()
    reset_llm_stats()

    from quality_state import make_initial_state
    from configs import load_yaml

    state = make_initial_state(data)
    state["context_state"].update({
        "quality_rules": load_yaml("quality_rules.yaml") or {},
        "target_schema": load_yaml("schema_mapping.yaml").get("target_schema", {}),
        "research_domain": "materials_science",
    })

    from Data_Assessment_agentV1.assessment_graph import build_assessment_graph
    from Data_Normalization_agentV1.normalization_graph import build_normalization_graph
    from Data_Conflict_agentV1.conflict_graph import build_conflict_graph
    from Data_Export_agentV1.export_graph import build_export_graph

    assessment_app = build_assessment_graph().compile()
    normalization_app = build_normalization_graph().compile()
    conflict_app = build_conflict_graph().compile()
    export_app = build_export_graph().compile()

    branches = set()
    t0 = time.time()

    # ── Assessment ──
    t1 = time.time()
    state = assessment_app.invoke(state)
    t1e = time.time() - t1

    q = state["report_state"]["quality"]
    routes = q.get("per_source_routes", {})
    rc = q.get("route_counts", {})
    scoring = q.get("quality_scoring", {})
    section(f"Assessment ({t1e:.1f}s)")
    print(f"  Score: {scoring.get('overall_score',0):.4f} ({scoring.get('quality_level','?')})")
    print(f"  Routes: {rc}")
    for sid, r in routes.items():
        branch = {"Normalization": "A→B", "Conflict": "A→C", "Export": "A→D", "HumanReview": "A→E"}.get(r, r)
        print(f"    {sid[:30]} → {branch}")
        branches.add(branch)

    norm_n = rc.get("Normalization", 0)
    conf_n = rc.get("Conflict", 0)

    # ── Normalization (A→B) ──
    if norm_n > 0:
        state = normalization_app.invoke(state)
        norm = state["report_state"].get("normalization", {})
        mods = norm.get("modifications", {})
        section(f"Normalization (A→B→D)")
        print(f"  Status: {norm.get('normalization_status','?')}")
        print(f"  Mods: {mods.get('total',0)} total")
        branches.add("B→D")

    # ── Conflict (A→C→B→C→...) ──
    if conf_n > 0:
        section(f"Conflict (A→C)")
        state = conflict_app.invoke(state)
        conflict = state["report_state"].get("conflict", {})
        report = conflict.get("resolution_report", {})
        agg = conflict.get("reasoning", {}).get("aggregated", {})
        ident = conflict.get("identification", {})
        print(f"  Trigger: {ident.get('trigger_path','?')}")
        print(f"  Conflicts: {ident.get('total_conflicts',0)}")
        print(f"  Auto: {agg.get('auto_resolved',0)} | Human: {agg.get('human_required',0)}")
        print(f"  Route: {report.get('route_decision','?')}")
        branches.add("A→C")

        next_route = report.get("route_decision", "Export")
        cloop = 0
        while next_route == "Normalization" and cloop < 3:
            cloop += 1
            section(f"C→B→C Loop {cloop}/3")
            state = normalization_app.invoke(state)
            state = conflict_app.invoke(state)
            conflict2 = state["report_state"].get("conflict", {})
            report2 = conflict2.get("resolution_report", {})
            next_route = report2.get("route_decision", "Export")
            print(f"  → {next_route}")
            branches.add("C→B")

        if next_route == "Export":
            branches.add("C→D")
        elif next_route == "HumanReview":
            branches.add("C→E")

    # ── Export ──
    section("Export")
    state = export_app.invoke(state)
    os_out = state.get("output_state", {})
    qs = os_out.get("quality_summary", {})
    sd = os_out.get("structured_data", {})
    print(f"  Records: {sd.get('row_count',0)}")
    print(f"  Quality: {qs.get('quality_level','?')} ({qs.get('overall_score',0):.4f})")
    print(f"  Status: {state['workflow_state'].get('execution_status','?')}")

    stats = get_llm_stats()
    total = time.time() - t0
    print(f"\n  Time: {total:.1f}s | LLM: {stats['total_calls']} calls, {stats['total_time_seconds']:.1f}s")

    # Branch check
    print(f"\n  Expected: {expected_branches}")
    print(f"  Hit:      {branches}")
    missing = expected_branches - branches
    extra = branches - expected_branches
    if missing:
        print(f"  ✗ MISSING: {missing}")
    if extra:
        print(f"  △ EXTRA: {extra}")
    if not missing:
        print(f"  ✓ ALL COVERED")
    return branches, missing


# ═══════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════

def main():
    t_total = time.time()
    all_branches = set()
    all_missing = set()

    # Scene 1: A→B→D
    branches, missing = run_scene(
        "Scene 1: A→B→D (Normalization → Export)",
        scene_1(),
        {"A→B", "B→D"}
    )
    all_branches |= branches
    all_missing |= missing

    # Scene 2: A→C→B→C→D
    branches, missing = run_scene(
        "Scene 2: A→C→B→C→D (Conflict → Norm → Conflict → Export)",
        scene_2(),
        {"A→C", "C→B", "C→D"}
    )
    all_branches |= branches
    all_missing |= missing

    # Scene 3: A→D
    branches, missing = run_scene(
        "Scene 3: A→D (Clean → Export)",
        scene_3(),
        {"A→D"}
    )
    all_branches |= branches
    all_missing |= missing

    # ── Summary ──
    banner("OVERALL SUMMARY")
    all_expected = {"A→B", "A→C", "A→D", "B→D", "C→B", "C→D"}
    print(f"  Hit:      {sorted(all_branches)}")
    print(f"  Missing:  {sorted(all_missing)}")
    print(f"  Coverage: {len(all_branches & all_expected)}/{len(all_expected)}")
    print(f"  Total time: {time.time() - t_total:.1f}s")
    banner("DONE")


if __name__ == "__main__":
    main()
