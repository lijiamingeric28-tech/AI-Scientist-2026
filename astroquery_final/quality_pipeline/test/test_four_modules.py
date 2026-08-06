"""
test_four_modules.py — Assessment → Normalization → Conflict → Export 四模块联调测试

流程:
  Assessment (4 Stage) → Router
    ├── Export → ExportGraph (6 Stage) → END
    ├── Normalization (5 Stage) → Router
    │   ├── Export → ExportGraph → END
    │   └── Conflict (6 Stage) → Router
    │       ├── Normalization (B⇄C 循环, max 3次)
    │       └── Export → ExportGraph → END
    └── HumanReview → STOP

用法:
  cd 子图4部分代码
  python test/test_four_modules.py
"""
from __future__ import annotations

import sys, os, json, time, copy, io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from ..utils.logger import setup_logging, get_logger
from ..utils.llm import reset_llm, reset_llm_stats, print_llm_stats, get_llm_stats
setup_logging()
reset_llm()
reset_llm_stats()

logger = get_logger(__name__)

# ── Display ──
SEP = "=" * 80
SEP2 = "─" * 80
SEP3 = "-" * 60


def banner(s):
    print(f"\n{SEP}\n  {s}\n{SEP}")


def section(s):
    print(f"\n  {s}\n  {SEP2}")


def kv(k, v, indent=4):
    print(f"{' ' * indent}{k}: {v}")


# ═══════════════════════════════════════════════════════════
# Test Data
# ═══════════════════════════════════════════════════════════

def build_test_data():
    """
    5 papers, 覆盖全场景:
      Paper 1: 别名 (YS, UTS, EL) + ~前缀 → Normalization
      Paper 2: GPa 需 ×1000 + 缺单位 → Normalization
      Paper 3: 希腊字母 σ 别名 + 缺溯源 + 重复 → Normalization
      Paper 4: 干净数据 → Export (直接通过)
      Paper 5: 与 Paper 1 同材料 (Al-7075) 但值不同 → Conflict
    """
    return {
        "schema_version": "grounded_data_v1",
        "sources": [
            {"source_id": "doi_paper1", "source_type": "paper",
             "doi": "10.1016/j.msea.2024.001",
             "title": "High-temperature tensile of Al-7075 alloy after T6 treatment",
             "authors": ["Zhang, W.", "Li, H."], "year": 2024,
             "journal": "Materials Science and Engineering: A",
             "access_path": "/cache/msea_001.pdf", "retrieval_priority": 0.95},

            {"source_id": "doi_paper2", "source_type": "paper",
             "doi": "10.1007/s11661.002",
             "title": "Aging effect on Al-Zn-Mg-Cu alloy mechanical properties",
             "authors": ["Wang, X."], "year": 2023,
             "journal": "Metallurgical and Materials Transactions A",
             "access_path": "/cache/mmta_002.pdf", "retrieval_priority": 0.87},

            {"source_id": "doi_paper3", "source_type": "paper",
             "doi": "10.1016/j.actamat.003",
             "title": "Strain rate sensitivity of Ti-6Al-4V at elevated temperatures",
             "authors": ["Kim, S.", "Park, J."], "year": 2025,
             "journal": "Acta Materialia",
             "access_path": "/cache/actamat_003.pdf", "retrieval_priority": 0.92},

            {"source_id": "doi_paper4", "source_type": "paper",
             "doi": "10.1016/j.corsci.004",
             "title": "Corrosion behavior of 316L stainless steel in chloride environment",
             "authors": ["Mueller, F."], "year": 2022,
             "journal": "Corrosion Science",
             "access_path": "/cache/corsci_004.pdf", "retrieval_priority": 0.85},

            {"source_id": "doi_paper5", "source_type": "paper",
             "doi": "10.1016/j.msea.2025.005",
             "title": "Enhanced strength of Al-7075 processed by cryogenic rolling",
             "authors": ["Johnson, R.", "Lee, S."], "year": 2025,
             "journal": "Materials Science and Engineering: A",
             "access_path": "/cache/msea_005.pdf", "retrieval_priority": 0.91},
        ],
        "records": [
            # ── Paper 1: 别名 (YS, UTS, EL) + ~前缀 ──
            {"record_id": "p1_ys_1", "source_id": "doi_paper1",
             "field_name": "YS", "field_value": 450, "field_unit": "MPa",
             "trace_id": "t1", "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_ys_2", "source_id": "doi_paper1",
             "field_name": "YS", "field_value": 460, "field_unit": "MPa",
             "trace_id": "t2", "provenance": {"page": 4, "bbox": [120, 340, 280, 355]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_uts_1", "source_id": "doi_paper1",
             "field_name": "UTS", "field_value": "~520", "field_unit": "MPa",
             "trace_id": "t3", "provenance": {"page": 3, "bbox": [120, 356, 280, 371]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_el_1", "source_id": "doi_paper1",
             "field_name": "EL", "field_value": 12.5, "field_unit": "%",
             "trace_id": "t4", "provenance": {"page": 3, "bbox": [120, 372, 280, 387]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_temp_1", "source_id": "doi_paper1",
             "field_name": "temperature", "field_value": 200, "field_unit": "C",
             "trace_id": "t5", "provenance": {"page": 2, "bbox": [100, 250, 150, 265]},
             "extraction_method": "llm_text"},

            # ── Paper 2: GPa 需 ×1000 + 缺单位 ──
            {"record_id": "p2_ys_1", "source_id": "doi_paper2",
             "field_name": "yield_strength", "field_value": 0.438, "field_unit": "GPa",
             "trace_id": "t6", "provenance": {"page": 5, "bbox": [90, 420, 250, 435]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_ys_2", "source_id": "doi_paper2",
             "field_name": "yield_strength", "field_value": 0.442, "field_unit": "GPa",
             "trace_id": "t7", "provenance": {"page": 6, "bbox": [90, 420, 250, 435]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_ts_1", "source_id": "doi_paper2",
             "field_name": "tensile_strength", "field_value": 0.505, "field_unit": "GPa",
             "trace_id": "t8", "provenance": {"page": 5, "bbox": [90, 436, 250, 451]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_hard_1", "source_id": "doi_paper2",
             "field_name": "hardness", "field_value": 185, "field_unit": None,
             "trace_id": "t9", "provenance": {"page": 5, "bbox": [90, 452, 250, 467]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_elong_1", "source_id": "doi_paper2",
             "field_name": "elongation", "field_value": 8.0, "field_unit": "%",
             "trace_id": "t10", "provenance": {"page": 5, "bbox": [90, 468, 250, 483]},
             "extraction_method": "llm_table"},

            # ── Paper 3: σ 别名 + 缺溯源 + 重复 ──
            {"record_id": "p3_sy_1", "source_id": "doi_paper3",
             "field_name": "σ_y", "field_value": 880, "field_unit": "MPa",
             "trace_id": "t11", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p3_sy_1_dup", "source_id": "doi_paper3",
             "field_name": "σ_y", "field_value": 880, "field_unit": "MPa",
             "trace_id": "t11", "provenance": None,
             "extraction_method": "llm_table"},  # exact duplicate
            {"record_id": "p3_sy_2", "source_id": "doi_paper3",
             "field_name": "σ_y", "field_value": 870, "field_unit": "MPa",
             "trace_id": "t12", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p3_suts_1", "source_id": "doi_paper3",
             "field_name": "σ_uts", "field_value": 950, "field_unit": "MPa",
             "trace_id": "t13", "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p3_elong_1", "source_id": "doi_paper3",
             "field_name": "elongation", "field_value": 15.0, "field_unit": "%",
             "trace_id": "t14", "provenance": {"page": 4, "bbox": [80, 300, 240, 315]},
             "extraction_method": "llm_text"},

            # ── Paper 4: 干净数据 ──
            {"record_id": "p4_hard_1", "source_id": "doi_paper4",
             "field_name": "hardness", "field_value": 220, "field_unit": "HV",
             "trace_id": "t15", "provenance": {"page": 3, "bbox": [100, 300, 200, 315]},
             "extraction_method": "llm_table"},
            {"record_id": "p4_cr_1", "source_id": "doi_paper4",
             "field_name": "corrosion_rate", "field_value": 0.15, "field_unit": "mm/year",
             "trace_id": "t16", "provenance": {"page": 3, "bbox": [100, 316, 200, 331]},
             "extraction_method": "llm_table"},

            # ── Paper 5: 与 Paper 1 同材料 (Al-7075) → 冲突 ──
            {"record_id": "p5_ys_1", "source_id": "doi_paper5",
             "field_name": "yield_strength", "field_value": 520, "field_unit": "MPa",
             "trace_id": "t17", "provenance": {"page": 6, "bbox": [100, 400, 260, 415]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_ys_2", "source_id": "doi_paper5",
             "field_name": "yield_strength", "field_value": 530, "field_unit": "MPa",
             "trace_id": "t18", "provenance": {"page": 6, "bbox": [100, 416, 260, 431]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_ts_1", "source_id": "doi_paper5",
             "field_name": "tensile_strength", "field_value": 580, "field_unit": "MPa",
             "trace_id": "t19", "provenance": {"page": 6, "bbox": [100, 432, 260, 447]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_ts_2", "source_id": "doi_paper5",
             "field_name": "tensile_strength", "field_value": 590, "field_unit": "MPa",
             "trace_id": "t20", "provenance": {"page": 7, "bbox": [100, 400, 260, 415]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_elong_1", "source_id": "doi_paper5",
             "field_name": "elongation", "field_value": 18.5, "field_unit": "%",
             "trace_id": "t21", "provenance": {"page": 6, "bbox": [100, 448, 260, 463]},
             "extraction_method": "llm_table"},
        ],
    }


# ═══════════════════════════════════════════════════════════
# Print helpers
# ═══════════════════════════════════════════════════════════

def print_input(data):
    sources = data["sources"]
    records = data["records"]
    print(f"  输入: {len(sources)} papers, {len(records)} records")
    for s in sources:
        sid = s["source_id"]
        n = sum(1 for r in records if r["source_id"] == sid)
        print(f"    [{sid}] {s['title'][:50]:50s} ({s['year']}) | {n} recs")
    print(f"\n  原始数据示例:")
    for r in records[:8]:
        fu = r.get("field_unit") or "(none)"
        print(f"    [{r['source_id'][:12]}] {r['field_name']:20s} = {str(r['field_value']):10s} {fu}")


def print_assessment(state, elapsed):
    q = state["report_state"]["quality"]
    sources = q.get("sources", {})
    scoring = q.get("quality_scoring", {})

    section("Assessment 结果")
    kv("Overall quality", f"{scoring.get('overall_score',0):.4f} ({scoring.get('quality_level','?')})")
    kv("Calibrated confidence", f"{scoring.get('calibrated_confidence',0):.4f}")
    kv("Route distribution", q.get("route_counts", {}))
    kv("Assessment summary", q.get("assessment_summary", "")[:150])
    kv("Elapsed", f"{elapsed:.1f}s")

    print(f"\n    Per-source routing:")
    for sid, route in q.get("per_source_routes", {}).items():
        sr = sources.get(sid, {})
        title = sr.get("title", sid)[:45]
        issues = sr.get("issue_count", 0)
        conflicts = sr.get("conflict_risk", {}).get("conflict_count", 0)
        grade = sr.get("quality_scoring", {}).get("quality_level", "?")
        print(f"      [{sid}] {title:45s} → {route:15s} | "
              f"grade={grade:9s} issues={issues} conflicts={conflicts}")

    return q["per_source_routes"]


def print_normalization(state):
    norm = state.get("report_state", {}).get("normalization", {})
    sp = norm.get("source_plan", {})

    section("Normalization: SourceRouter")
    kv("Trigger", sp.get("trigger_source", "?"))
    kv("To normalize", sp.get("total_to_normalize", 0))

    section("Normalization: ToolPlanning & Execution")
    mods = norm.get("modifications", {})
    kv("Total modifications", mods.get("total", 0))
    bl = mods.get("by_layer", {})
    kv("By layer", f"base={bl.get('base',0)} adapted={bl.get('adapted',0)} generated={bl.get('generated',0)}")
    for sid, info in mods.get("per_source", {}).items():
        print(f"      [{sid}] {info.get('total',0)} mods")

    section("Normalization: Validation")
    val = norm.get("validation", {})
    kv("Valid", val.get("is_valid", False))
    kv("Schema pass", val.get("schema_check", {}).get("passed", False))
    cc = val.get("conflict_check", {})
    kv("Conflicts detected", f"{cc.get('conflict_count',0)} (method={cc.get('method','?')})")
    kv("Needs conflict analysis", val.get("needs_conflict_analysis", False))

    section("Normalization: Report")
    kv("Status", norm.get("normalization_status", "?"))
    kv("Summary", norm.get("normalization_summary", "")[:200])

    return norm.get("validation", {}).get("needs_conflict_analysis", False)


def print_conflict(state):
    conflict = state.get("report_state", {}).get("conflict", {})

    ident = conflict.get("identification", {})
    section("Conflict: Identification")
    kv("Trigger", ident.get("trigger_path", "?"))
    kv("Total conflicts", ident.get("total_conflicts", 0))
    kv("Fields", ident.get("involved_fields", []))

    classification = conflict.get("classification", {})
    section("Conflict: Classification")
    for c in classification.get("classified_conflicts", []):
        print(f"      [{c['conflict_id']}] {c.get('field_name','?'):20s} → "
              f"{c.get('type','?')}/{c.get('subtype','?')}/{c.get('severity','?')}")

    evidence = conflict.get("evidence", {})
    section("Conflict: Evidence")
    for cid, ev in evidence.items():
        src = ev.get("source_reliability", {})
        stat = ev.get("statistical_evidence", {})
        print(f"      [{cid}] gap={src.get('reliability_gap',0):.3f} verdict={src.get('verdict','?')} "
              f"| d={stat.get('cohens_d',0):.2f} sig={stat.get('statistically_significant','?')}")

    reasoning = conflict.get("reasoning", {})
    section("Conflict: Reasoning")
    agg = reasoning.get("aggregated", {})
    kv("Auto-resolved", agg.get("auto_resolved", 0))
    kv("Human required", agg.get("human_required", 0))
    for r in reasoning.get("per_conflict", []):
        chain = r.get("reasoning_chain", [])
        c0 = chain[0][:80] if chain else ""
        print(f"      [{r['conflict_id']}] strategy={r['strategy']:20s} resolution={r['resolution']:18s} | {c0}")

    report = conflict.get("resolution_report", {})
    section("Conflict: Report")
    kv("Status", report.get("status", "?"))
    kv("Route", report.get("route_decision", "?"))
    kv("Summary", report.get("summary", "")[:200])
    plan = report.get("resolution_plan", {})
    for a in plan.get("actions_to_normalize", []):
        print(f"      action: {a['conflict_id']} → {a.get('new_value','?')} ({a.get('action','?')})")

    return report.get("route_decision", "Export"), report.get("status", "?")


def print_export(state):
    os_out = state.get("output_state", {})

    section("Export: Structured Data")
    sd = os_out.get("structured_data", {})
    kv("Row count", sd.get("row_count", 0))
    kv("Column count", sd.get("column_count", 0))
    kv("Formats", [k for k in sd.keys() if k in ("json", "csv", "csv_wide", "json_wide")])

    section("Export: Metadata")
    meta = os_out.get("metadata", {})
    kv("Fields defined", len(meta.get("field_definitions", {})))
    kv("LLM descriptions", meta.get("field_descriptions_llm", False))
    kv("Processing stages",
       {k: v.get("status", "?") for k, v in meta.get("processing_record", {}).items()})

    section("Export: Traceability")
    trace = os_out.get("traceability", {})
    completeness = trace.get("trace_completeness",
                             state.get("report_state", {}).get("export", {}).get("trace_completeness", {}))
    kv("Records traced", completeness.get("records_with_trace", 0))
    kv("Modified", completeness.get("modified_count", 0))
    kv("Unmodified", completeness.get("unmodified_count", 0))
    kv("Deleted", completeness.get("deleted_count", 0))
    kv("Decision points", len(trace.get("agent_decision_trail", [])))

    section("Export: Quality Summary")
    qs = os_out.get("quality_summary", {})
    kv("Overall score", f"{qs.get('overall_score',0):.4f}")
    kv("Quality level", qs.get("quality_level", "?"))
    kv("Calibrated confidence", f"{qs.get('calibrated_confidence',0):.4f}")
    kv("LLM calls", qs.get("processing_statistics", {}).get("total_llm_calls", 0))
    kv("Tool calls", qs.get("processing_statistics", {}).get("total_tool_calls", 0))
    kv("Total elapsed", f"{qs.get('processing_statistics', {}).get('total_elapsed_seconds', 0):.1f}s")
    kv("B⇄C iterations", qs.get("processing_statistics", {}).get("b_c_loop_iterations", 0))
    issues = qs.get("issues_summary", {})
    kv("Issues", f"assessment={issues.get('assessment_issues',0)} "
               f"norm_mods={issues.get('normalization_modifications',0)} "
               f"conflicts_resolved={issues.get('conflicts_resolved',0)}")
    risk = qs.get("risk_indicators", {})
    kv("Risks", {k: v for k, v in risk.items() if v})
    kv("Recommendation", qs.get("recommendation", "")[:200])

    section("Export: Final Data Preview")
    records = sd.get("json", {}).get("records", [])
    from collections import defaultdict
    by_src = defaultdict(list)
    for r in records:
        by_src[r["source_id"]].append(r)
    for src_id in sorted(by_src)[:5]:
        recs = by_src[src_id]
        print(f"      [{src_id}] {len(recs)} records:")
        for r in sorted(recs, key=lambda x: x.get("field_name", ""))[:6]:
            fu = r.get("field_unit") or ""
            print(f"        {r['field_name']:22s} = {str(r['field_value']):10s} {fu}")


def print_data_changes(before, after):
    """对比处理前后的数据变化。"""
    b_map = {r["record_id"]: r for r in before.get("records", [])}
    a_map = {r["record_id"]: r for r in after.get("records", [])}

    changed = 0
    deleted = 0
    changes = []
    for rid in sorted(b_map):
        br = b_map[rid]
        ar = a_map.get(rid)
        if not ar:
            changes.append(f"      [{rid}] DELETED (duplicate)")
            deleted += 1
            continue
        diffs = []
        if br.get("field_name") != ar.get("field_name"):
            diffs.append(f"name: {br['field_name']} → {ar['field_name']}")
        bv, av = str(br.get("field_value", "")), str(ar.get("field_value", ""))
        if bv != av:
            diffs.append(f"value: {bv} → {av}")
        if br.get("field_unit") != ar.get("field_unit"):
            diffs.append(f"unit: {br.get('field_unit')} → {ar.get('field_unit')}")
        if diffs:
            changed += 1
            changes.append(f"      [{rid}] {'; '.join(diffs)}")

    if changes:
        section(f"数据变更 ({changed} total, {deleted} deleted)")
        for c in changes:
            print(c)
    else:
        print(f"\n    数据变更: 无 (数据已为最终状态)")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    t_total = time.time()
    banner("四模块联调测试: Assessment → Normalization → Conflict → Export")
    banner("领域: 材料科学 | 5 篇论文 | 含别名/格式/单位/缺失/冲突/干净全场景")

    # ── Init ──
    from ..quality_state import make_initial_state
    from ..configs import load_yaml

    input_data = build_test_data()
    state = make_initial_state(input_data)
    state["context_state"].update({
        "quality_rules": load_yaml("quality_rules.yaml") or {},
        "target_schema": load_yaml("schema_mapping.yaml").get("target_schema", {}),
        "research_domain": "materials_science",
    })

    banner("输入数据概览")
    print_input(input_data)
    before_data = copy.deepcopy(state["data_state"]["current_data"])

    # ── V2.3: 使用 per-source 分发 + 并行 Norm/Conflict ──
    from ..Data_Assessment_agentV1.assessment_graph import build_assessment_graph
    from ..Data_Normalization_agentV1.normalization_graph import build_normalization_graph
    from ..Data_Conflict_agentV1.conflict_graph import build_conflict_graph
    from ..Data_Export_agentV1.export_graph import build_export_graph

    assessment_app = build_assessment_graph().compile()
    normalization_app = build_normalization_graph().compile()
    conflict_app = build_conflict_graph().compile()
    export_app = build_export_graph().compile()

    # ═══════════════════════════════════════════════════
    # MODULE 1: Assessment
    # ═══════════════════════════════════════════════════
    banner("MODULE 1/4: Assessment (4 Stages) [PARALLEL]")
    t1 = time.time()
    state = assessment_app.invoke(state)
    t1e = time.time() - t1
    per_source_routes = print_assessment(state, t1e)

    norm_count = sum(1 for r in per_source_routes.values() if r == "Normalization")
    conf_count = sum(1 for r in per_source_routes.values() if r == "Conflict")
    export_count = sum(1 for r in per_source_routes.values() if r == "Export")
    human_count = sum(1 for r in per_source_routes.values() if r == "HumanReview")

    # ═══════════════════════════════════════════════════
    # V2.3: Dispatch — per-source 分发到 Norm/Conflict
    # ═══════════════════════════════════════════════════
    banner(f"V2.3 Dispatch: Norm={norm_count} Conflict={conf_count} Export={export_count} Human={human_count}")

    b_c_loop = 0
    MAX_LOOP = 3

    # ── 并行执行 Normalization + Conflict ──
    # 由于 LangGraph 单线程, 这里用顺序但各自处理不同 source 子集实现伪并行
    norm_ran = False
    conflict_ran = False

    if norm_count > 0:
        banner(f"MODULE 2/4: Normalization (5 Stages) — {norm_count} sources")
        t2 = time.time()
        state = normalization_app.invoke(state)
        t2e = time.time() - t2
        needs_conflict = print_normalization(state)
        norm_ran = True

    if conf_count > 0:
        banner(f"MODULE 3/4: Conflict (6 Stages) — {conf_count} sources")
        t3 = time.time()
        state = conflict_app.invoke(state)
        t3e = time.time() - t3
        next_route, c_status = print_conflict(state)
        conflict_ran = True

        # B⇄C 循环
        while next_route == "Normalization" and b_c_loop < MAX_LOOP:
            b_c_loop += 1
            banner(f"C→B Loop Round {b_c_loop}/{MAX_LOOP}")
            state = normalization_app.invoke(state)
            needs_conflict = print_normalization(state)
            if needs_conflict:
                state = conflict_app.invoke(state)
                next_route, c_status = print_conflict(state)
            else:
                break

    # 如果 Normalization 发现有冲突需要分析
    if norm_ran and not conflict_ran:
        wf = state.get("workflow_state", {})
        norm = state.get("report_state", {}).get("normalization", {})
        if norm.get("validation", {}).get("needs_conflict_analysis"):
            banner(f"MODULE 3/4: Conflict (6 Stages) — B→C from Norm validation")
            state = conflict_app.invoke(state)
            next_route, c_status = print_conflict(state)
            conflict_ran = True

    # ═══════════════════════════════════════════════════
    # MODULE 4: Export
    # ═══════════════════════════════════════════════════
    banner("MODULE 4/4: Export (6 Stages) — 最终结构化输出")
    t4 = time.time()
    state = export_app.invoke(state)
    t4e = time.time() - t4
    print_export(state)

    # ═══════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════
    banner("全链路数据变更对比")
    print_data_changes(before_data, state["data_state"]["current_data"])

    banner("LLM 调用统计")
    from ..utils.llm import print_llm_stats
    print_llm_stats()
    stats = get_llm_stats()
    print(f"\n  总调用: {stats['total_calls']} | 成功率: {stats.get('success_rate',0):.1f}% "
          f"| 首次策略: {stats.get('first_strategy_rate',0):.1f}% "
          f"| 总耗时: {stats['total_time_seconds']:.1f}s")

    total_elapsed = time.time() - t_total
    banner("性能总览")
    kv("Assessment", f"{t1e:.1f}s")
    if norm_ran:
        kv("Normalization", f"{t2e:.1f}s")
    kv("Export", f"{t4e:.1f}s")
    kv("B⇄C loops", b_c_loop)
    kv("Total elapsed", f"{total_elapsed:.1f}s")

    wf = state.get("workflow_state", {})
    qs = state.get("output_state", {}).get("quality_summary", {})
    banner("最终判决")
    kv("Route", repr(wf.get("route_decision", "")))
    kv("Status", wf.get("execution_status", "?"))
    kv("Quality", f"{qs.get('quality_level','?')} (score={qs.get('overall_score',0):.4f})")
    kv("Recommendation", qs.get("recommendation", ""))

    banner("四模块联调测试完成 ✓")
    return state


if __name__ == "__main__":
    main()
