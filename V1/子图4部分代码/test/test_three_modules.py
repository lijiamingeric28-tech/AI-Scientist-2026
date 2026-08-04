"""
test_three_modules.py — Assessment → Normalization → Conflict 三模块联调测试

流程:
  1. 初始化多源测试数据 (5 papers, 含别名/格式/单位/缺失/冲突问题)
  2. Assessment 模块 (4 Stage) — 完整评估 + 路由决策
  3. Normalization 模块 (5 Stage) — 按需规范化
  4. Conflict 模块 (6 Stage) — 冲突检测与裁决
  5. 必要时 B⇄C 循环 (max 3次)
  6. 打印每模块/每阶段输出 + LLM 调用统计 + 最终数据对比

用法:
  cd 子图4部分代码
  python test/test_three_modules.py
"""
from __future__ import annotations

import sys, os, json, time, copy, io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from utils.logger import setup_logging, get_logger
from utils.llm import reset_llm, reset_llm_stats, print_llm_stats, get_llm_stats
setup_logging()
reset_llm()
reset_llm_stats()

logger = get_logger(__name__)

# ── Display helpers ──
SEP_LONG  = "=" * 80
SEP_SHORT = "─" * 80
SEP_THIN  = "-" * 60


def hdr(s):
    print(f"\n{SEP_LONG}")
    print(f"  {s}")
    print(f"{SEP_LONG}")


def sub(s):
    print(f"\n  {s}")
    print(f"  {SEP_SHORT}")


def phase(n, s):
    print(f"\n{'#'*80}")
    print(f"# PHASE {n}: {s}")
    print(f"{'#'*80}")


def kv(k, v, indent=4):
    print(f"{' ' * indent}{k}: {v}")


def separator():
    print(f"  {SEP_THIN}")


# ══════════════════════════════════════════════════════════════
# Build Test Data
# ══════════════════════════════════════════════════════════════

def build_test_data():
    """
    5 papers, 含完整的质量问题矩阵:
      Paper 1: 别名 (YS, UTS, EL) + ~ 前缀 → 需要 Normalization
      Paper 2: GPa (需 ×1000 → MPa) + 缺单位 → 需要 Normalization
      Paper 3: 希腊字母别名 (σ_y, σ_uts) + 缺溯源 → 需要 Normalization
      Paper 4: 干净数据 → 应直接 Export
      Paper 5: 与 Paper 1 同材料 (Al-7075) 但值不同 → 产生跨来源冲突

    领域: 材料科学 (materials_science)
    """
    return {
        "schema_version": "grounded_data_v1",
        "sources": [
            {
                "source_id": "doi_paper1", "source_type": "paper",
                "doi": "10.1016/j.msea.2024.001",
                "title": "High-temperature tensile properties of Al-7075 alloy after T6 treatment",
                "authors": ["Zhang, W.", "Li, H."], "year": 2024,
                "journal": "Materials Science and Engineering: A",
                "access_path": "/cache/msea_001.pdf", "retrieval_priority": 0.95,
            },
            {
                "source_id": "doi_paper2", "source_type": "paper",
                "doi": "10.1007/s11661.002",
                "title": "Aging effect on Al-Zn-Mg-Cu alloy mechanical properties",
                "authors": ["Wang, X."], "year": 2023,
                "journal": "Metallurgical and Materials Transactions A",
                "access_path": "/cache/mmta_002.pdf", "retrieval_priority": 0.87,
            },
            {
                "source_id": "doi_paper3", "source_type": "paper",
                "doi": "10.1016/j.actamat.003",
                "title": "Strain rate sensitivity of Ti-6Al-4V alloy at elevated temperatures",
                "authors": ["Kim, S.", "Park, J."], "year": 2025,
                "journal": "Acta Materialia",
                "access_path": "/cache/actamat_003.pdf", "retrieval_priority": 0.92,
            },
            {
                "source_id": "doi_paper4", "source_type": "paper",
                "doi": "10.1016/j.corsci.004",
                "title": "Corrosion behavior of 316L stainless steel in chloride environment",
                "authors": ["Mueller, F."], "year": 2022,
                "journal": "Corrosion Science",
                "access_path": "/cache/corsci_004.pdf", "retrieval_priority": 0.85,
            },
            {
                "source_id": "doi_paper5", "source_type": "paper",
                "doi": "10.1016/j.msea.2025.005",
                "title": "Enhanced strength of Al-7075 processed by cryogenic rolling",
                "authors": ["Johnson, R.", "Lee, S."], "year": 2025,
                "journal": "Materials Science and Engineering: A",
                "access_path": "/cache/msea_005.pdf", "retrieval_priority": 0.91,
            },
        ],
        "records": [
            # ── Paper 1: 别名问题 (YS, UTS, EL) + ~ 前缀 ──
            {"record_id": "p1_ys_1", "source_id": "doi_paper1",
             "field_name": "YS", "field_value": 450, "field_unit": "MPa",
             "trace_id": "d1_t1_r1",
             "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_uts_1", "source_id": "doi_paper1",
             "field_name": "UTS", "field_value": "~520", "field_unit": "MPa",
             "trace_id": "d1_t1_r2",
             "provenance": {"page": 3, "bbox": [120, 356, 280, 371]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_el_1", "source_id": "doi_paper1",
             "field_name": "EL", "field_value": 12.5, "field_unit": "%",
             "trace_id": "d1_t1_r3",
             "provenance": {"page": 3, "bbox": [120, 372, 280, 387]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_temp_1", "source_id": "doi_paper1",
             "field_name": "temperature", "field_value": 200, "field_unit": "C",
             "trace_id": "d1_t1_h1",
             "provenance": {"page": 2, "bbox": [100, 250, 150, 265]},
             "extraction_method": "llm_text"},
            # Additional records for Cohen's d (need >=2 per source)
            {"record_id": "p1_ys_2", "source_id": "doi_paper1",
             "field_name": "YS", "field_value": 460, "field_unit": "MPa",
             "trace_id": "d1_t2_r1",
             "provenance": {"page": 4, "bbox": [120, 340, 280, 355]},
             "extraction_method": "llm_table"},
            {"record_id": "p1_uts_2", "source_id": "doi_paper1",
             "field_name": "UTS", "field_value": "~515", "field_unit": "MPa",
             "trace_id": "d1_t2_r2",
             "provenance": {"page": 4, "bbox": [120, 356, 280, 371]},
             "extraction_method": "llm_table"},

            # ── Paper 2: 单位问题 (GPa 需要 ×1000 → MPa) + 缺单位 ──
            {"record_id": "p2_ys_1", "source_id": "doi_paper2",
             "field_name": "yield_strength", "field_value": 0.438, "field_unit": "GPa",
             "trace_id": "d2_t1_r1",
             "provenance": {"page": 5, "bbox": [90, 420, 250, 435]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_ts_1", "source_id": "doi_paper2",
             "field_name": "tensile_strength", "field_value": 0.505, "field_unit": "GPa",
             "trace_id": "d2_t1_r2",
             "provenance": {"page": 5, "bbox": [90, 436, 250, 451]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_hard_1", "source_id": "doi_paper2",
             "field_name": "hardness", "field_value": 185, "field_unit": None,
             "trace_id": "d2_t1_r3",
             "provenance": {"page": 5, "bbox": [90, 452, 250, 467]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_elong_1", "source_id": "doi_paper2",
             "field_name": "elongation", "field_value": 8.0, "field_unit": "%",
             "trace_id": "d2_t1_r4",
             "provenance": {"page": 5, "bbox": [90, 468, 250, 483]},
             "extraction_method": "llm_table"},
            {"record_id": "p2_ys_2", "source_id": "doi_paper2",
             "field_name": "yield_strength", "field_value": 0.442, "field_unit": "GPa",
             "trace_id": "d2_t2_r1",
             "provenance": {"page": 6, "bbox": [90, 420, 250, 435]},
             "extraction_method": "llm_table"},

            # ── Paper 3: 希腊字母 σ 别名 + 缺溯源 + 重复记录 ──
            {"record_id": "p3_sy_1", "source_id": "doi_paper3",
             "field_name": "σ_y", "field_value": 880, "field_unit": "MPa",
             "trace_id": "d3_t1_r1",
             "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p3_sy_1_dup", "source_id": "doi_paper3",
             "field_name": "σ_y", "field_value": 880, "field_unit": "MPa",
             "trace_id": "d3_t1_r1",
             "provenance": None,
             "extraction_method": "llm_table"},  # exact duplicate
            {"record_id": "p3_suts_1", "source_id": "doi_paper3",
             "field_name": "σ_uts", "field_value": 950, "field_unit": "MPa",
             "trace_id": "d3_t1_r2",
             "provenance": None,
             "extraction_method": "llm_table"},
            {"record_id": "p3_elong_1", "source_id": "doi_paper3",
             "field_name": "elongation", "field_value": 15.0, "field_unit": "%",
             "trace_id": "d3_t1_r3",
             "provenance": {"page": 4, "bbox": [80, 300, 240, 315]},
             "extraction_method": "llm_text"},
            {"record_id": "p3_sy_2", "source_id": "doi_paper3",
             "field_name": "σ_y", "field_value": 870, "field_unit": "MPa",
             "trace_id": "d3_t2_r1",
             "provenance": None,
             "extraction_method": "llm_table"},

            # ── Paper 4: 干净数据 — 无问题 (应直接 Export) ──
            {"record_id": "p4_hard_1", "source_id": "doi_paper4",
             "field_name": "hardness", "field_value": 220, "field_unit": "HV",
             "trace_id": "d4_t1_r1",
             "provenance": {"page": 3, "bbox": [100, 300, 200, 315]},
             "extraction_method": "llm_table"},
            {"record_id": "p4_cr_1", "source_id": "doi_paper4",
             "field_name": "corrosion_rate", "field_value": 0.15, "field_unit": "mm/year",
             "trace_id": "d4_t1_r2",
             "provenance": {"page": 3, "bbox": [100, 316, 200, 331]},
             "extraction_method": "llm_table"},

            # ── Paper 5: 与 Paper 1 同材料 (Al-7075)但值不同 → 冲突 ──
            # yield_strength: Paper1=450-460, Paper5=520-530 → Cohen's d will detect
            {"record_id": "p5_ys_1", "source_id": "doi_paper5",
             "field_name": "yield_strength", "field_value": 520, "field_unit": "MPa",
             "trace_id": "d5_t1_r1",
             "provenance": {"page": 6, "bbox": [100, 400, 260, 415]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_ys_2", "source_id": "doi_paper5",
             "field_name": "yield_strength", "field_value": 530, "field_unit": "MPa",
             "trace_id": "d5_t2_r1",
             "provenance": {"page": 6, "bbox": [100, 416, 260, 431]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_ts_1", "source_id": "doi_paper5",
             "field_name": "tensile_strength", "field_value": 580, "field_unit": "MPa",
             "trace_id": "d5_t1_r2",
             "provenance": {"page": 6, "bbox": [100, 432, 260, 447]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_ts_2", "source_id": "doi_paper5",
             "field_name": "tensile_strength", "field_value": 590, "field_unit": "MPa",
             "trace_id": "d5_t2_r2",
             "provenance": {"page": 7, "bbox": [100, 400, 260, 415]},
             "extraction_method": "llm_table"},
            {"record_id": "p5_elong_1", "source_id": "doi_paper5",
             "field_name": "elongation", "field_value": 18.5, "field_unit": "%",
             "trace_id": "d5_t1_r3",
             "provenance": {"page": 6, "bbox": [100, 448, 260, 463]},
             "extraction_method": "llm_table"},
        ],
    }


# ══════════════════════════════════════════════════════════════
# Print Helpers
# ══════════════════════════════════════════════════════════════

def print_input_summary(data):
    """Print input data overview."""
    sources = data.get("sources", [])
    records = data.get("records", [])
    print(f"  输入: {len(sources)} papers, {len(records)} records")
    for src in sources:
        rec_count = sum(1 for r in records if r["source_id"] == src["source_id"])
        journal_short = (src.get("journal", "") or "")[:45]
        print(f"    [{src['source_id']}] {src['title'][:50]:50s} ({src['year']}) | {journal_short} | {rec_count} recs")
    print(f"\n  原始数据样例:")
    for r in records[:12]:
        fu = r.get("field_unit") or "(none)"
        v = str(r.get("field_value", ""))
        print(f"    [{r['source_id'][:12]}] {r['field_name']:20s} = {v:10s} {fu:8s}")


def print_assessment_summary(state, elapsed):
    """Print Assessment module results."""
    q = state["report_state"]["quality"]
    profile = q.get("profile", {})
    sources = q.get("sources", {})
    scoring = q.get("quality_scoring", {})

    # Stage 1: Profiling
    sub("Stage 1/4: ProfilingAgent")
    ds = profile.get("dataset_summary", {})
    kv("Records", ds.get("record_count"))
    kv("Sources", ds.get("source_count"))
    kv("Fields", ds.get("field_count"))
    st = profile.get("semantic_types", {})
    if st:
        st_list = [f"{fn}({info.get('semantic_type','?')})" for fn, info in list(st.items())[:8]]
        kv("Semantic types", ", ".join(st_list))
    dist = profile.get("distributions", {})
    for fn, d in list(dist.items())[:5]:
        if d and d.get("distribution_type") != "unknown":
            kv(f"  {fn}", f"{d.get('distribution_type')} (n={d.get('count')}, skew={d.get('skewness',0):.2f}, kurt={d.get('kurtosis',0):.2f})", indent=2)
    kv("Elapsed", f"{elapsed:.2f}s")

    # Stage 2: Quality Assessment
    sub("Stage 2/4: QualityAssessmentAgent (per-source)")
    for sid, sr in sources.items():
        title = sr.get("title", sid)[:50]
        comp = sr["completeness"]["score"]
        cons = sr["consistency"]["score"]
        fmt_s = sr["format"]["score"]
        conf_c = sr["conflict_risk"]["conflict_count"]
        issues = sr.get("issue_count", 0)
        below = "⚠️below" if sr.get("below_adaptive_threshold") else ""
        print(f"    [{sid}]\n"
              f"      Title: {title}\n"
              f"      Completeness={comp:.2f} Consistency={cons:.2f} Format={fmt_s:.2f} "
              f"Conflicts={conf_c} Issues={issues} {below}")
        lc = sr.get("llm_completeness")
        if lc and lc.get("summary"):
            kv("      LLM Completeness", lc["summary"][:120])

    # Stage 3: Scoring
    sub("Stage 3/4: QualityScoringAgent")
    kv("Overall score", f"{scoring.get('overall_score',0):.4f}")
    kv("Quality level", scoring.get("quality_level", "?"))
    kv("Calibrated confidence", f"{scoring.get('calibrated_confidence','?'):.4f}")
    cf = scoring.get("confidence_factors", {})
    kv("Confidence factors", f"vol={cf.get('data_volume','?')} agr={cf.get('agreement','?')} spa={cf.get('sparsity','?')}")
    kv("Penalty applied", f"{scoring.get('penalty_applied',False)} ({scoring.get('penalty_reason','none')})")
    print(f"    Per-source scores:")
    for sid, sr in sources.items():
        ps = sr.get("quality_scoring", {})
        print(f"      [{sid}] {ps.get('overall_score',0):.4f} ({ps.get('quality_level','?')})")

    # Stage 4: Decision
    sub("Stage 4/4: DecisionReasoningAgent (V2.1)")
    # V4 fix: decision_reasoning V3.5 后 route_decision → route_counts, 兼容旧键
    kv("Overall route", q.get("route_decision", q.get("route_counts", {})))
    kv("Assessment summary", q.get("assessment_summary", "")[:150])
    print(f"    Per-source routing:")
    for sid, route in q["per_source_routes"].items():
        reason = q.get("per_source_reasons", {}).get(sid, "")[:100]
        title = sources.get(sid, {}).get("title", sid)[:45]
        print(f"      [{sid}] {title:45s} → {route:15s} | {reason}")
    export_n = sum(1 for r in q["per_source_routes"].values() if r == "Export")
    norm_n = sum(1 for r in q["per_source_routes"].values() if r == "Normalization")
    conf_n = sum(1 for r in q["per_source_routes"].values() if r == "Conflict")
    print(f"    → Export={export_n}  Normalization={norm_n}  Conflict={conf_n}")
    return q["per_source_routes"], norm_n, conf_n


def print_normalization_stage(name, state, elapsed):
    """Print one Normalization stage result."""
    norm = state.get("report_state", {}).get("normalization", {})
    wf = state.get("workflow_state", {})

    print(f"\n  [{name}] ({elapsed:.2f}s)")
    print(f"  {SEP_THIN}")

    if "SourceRouter" in name:
        sp = norm.get("source_plan", {})
        kv("Trigger", sp.get("trigger_source"), indent=2)
        kv("To normalize", sp.get("total_to_normalize"), indent=2)
        kv("Skipped", sp.get("total_skipped"), indent=2)
        for sid, info in sp.get("sources_to_normalize", {}).items():
            conds = [c.get("condition") for c in info.get("conditions", [])]
            ca = info.get("conflict_actions")
            conflict_info = f" + {len(ca)} conflict actions" if ca else ""
            print(f"      [{sid}] {info['record_count']} recs | conditions={conds}{conflict_info}")

    elif "ToolPlanning" in name:
        reg = norm.get("tool_registry", {})
        kv("Method", norm.get("planning_method"), indent=2)
        kv("Base tools", reg.get("base_tools", []), indent=2)
        kv("Adapted tools", len(reg.get("adapted_tools", [])), indent=2)
        kv("Generated tools", len(reg.get("generated_tools", [])), indent=2)
        for sid, bs in reg.get("by_source", {}).items():
            print(f"      [{sid}] base={bs.get('base',[])} adapted={len(bs.get('adapted',[]))} generated={len(bs.get('generated',[]))}")

    elif "ToolExecutor" in name:
        mods = norm.get("modifications", {})
        kv("Total modifications", mods.get("total", 0), indent=2)
        bl = mods.get("by_layer", {})
        kv("By layer", f"base={bl.get('base',0)} adapted={bl.get('adapted',0)} generated={bl.get('generated',0)}", indent=2)
        ps = mods.get("per_source", {})
        for sid, info in ps.items():
            print(f"      [{sid}] {info.get('total', 0)} mods")
        errors = mods.get("errors", [])
        if errors:
            kv("Errors", len(errors), indent=2)
            for e in errors[:3]:
                print(f"        {e}")

    elif "Validation" in name:
        val = norm.get("validation", {})
        kv("Valid", val.get("is_valid"), indent=2)
        schema_check = val.get("schema_check", {})
        kv("Schema check", f"{'PASS' if schema_check.get('passed') else 'FAIL'}", indent=2)
        cc = val.get("conflict_check", {})
        kv("Conflict check", f"has_conflicts={cc.get('has_conflicts')}, count={cc.get('conflict_count',0)}, method={cc.get('method','?')}", indent=2)
        kv("Remaining issues", len(val.get("remaining_issues", [])), indent=2)
        kv("Needs conflict analysis", val.get("needs_conflict_analysis"), indent=2)
        kv("Route", wf.get("route_decision"), indent=2)

    elif "Report" in name:
        kv("Status", norm.get("normalization_status"), indent=2)
        kv("Summary", norm.get("normalization_summary", "")[:200], indent=2)


def print_conflict_summary(state, elapsed):
    """Print Conflict module results."""
    conflict = state.get("report_state", {}).get("conflict", {})

    ident = conflict.get("identification", {})
    sub("Stage 1/6: ConflictIdentificationAgent")
    kv("Trigger path", ident.get("trigger_path"))
    kv("Total conflicts", ident.get("total_conflicts"))
    kv("Involved fields", ident.get("involved_fields"))
    kv("Involved sources", ident.get("involved_sources"))

    classification = conflict.get("classification", {})
    sub("Stage 2/6: ConflictClassificationAgent")
    kv("By type", classification.get("by_type", {}))
    kv("By severity", classification.get("by_severity", {}))
    for c in classification.get("classified_conflicts", []):
        print(f"      [{c['conflict_id']}] {c.get('field_name'):20s} → "
              f"{c.get('type')}/{c.get('subtype')}/{c.get('severity')}")

    evidence = conflict.get("evidence", {})
    sub("Stage 3/6: EvidenceCollectionAgent")
    for cid, ev in evidence.items():
        src = ev.get("source_reliability", {})
        stat = ev.get("statistical_evidence", {})
        domain = ev.get("domain_rules", {})
        print(f"      [{cid}] reliability_gap={src.get('reliability_gap',0):.3f} "
              f"verdict={src.get('verdict')} | cohens_d={stat.get('cohens_d',0):.2f} "
              f"sig={stat.get('statistically_significant')} | rules={len(domain.get('matched_rules',[]))}")

    reasoning = conflict.get("reasoning", {})
    sub("Stage 4/6: ResolutionReasoningAgent")
    agg = reasoning.get("aggregated", {})
    kv("Auto-resolved", agg.get("auto_resolved", 0))
    kv("Human required", agg.get("human_required", 0))
    for r in reasoning.get("per_conflict", []):
        chain = r.get("reasoning_chain", [])
        chain_str = chain[0][:80] if chain else "no reasoning"
        print(f"      [{r['conflict_id']}] strategy={r['strategy']} "
              f"resolution={r['resolution']} | {chain_str}...")

    conf = conflict.get("confidence", {})
    sub("Stage 5/6: ConfidenceEvaluationAgent")
    for cid, cval in conf.items():
        comps = cval.get("components", {})
        print(f"      [{cid}] overall={cval.get('overall_confidence',0):.3f} "
              f"meets_threshold={cval.get('meets_auto_threshold')} "
              f"level={cval.get('confidence_level')} | "
              f"src={comps.get('source_agreement',0):.2f} stat={comps.get('statistical_clarity',0):.2f} "
              f"domain={comps.get('domain_rule_match',0):.2f} hist={comps.get('historical_corroboration',0):.2f}")

    report = conflict.get("resolution_report", {})
    sub("Stage 6/6: ResolutionReportAgent")
    kv("Status", report.get("status"))
    kv("Route decision", report.get("route_decision"))
    kv("Summary", report.get("summary", "")[:250])
    plan = report.get("resolution_plan", {})
    actions = plan.get("actions_to_normalize", [])
    annotations = plan.get("annotations_to_add", [])
    human_items = plan.get("human_review_items", [])
    if actions:
        kv("Actions to normalize", len(actions))
        for a in actions[:5]:
            print(f"        {a['conflict_id']}: {a.get('field','?')} → {a.get('new_value','?')} ({a.get('action')})")
    if annotations:
        kv("Annotations to add", len(annotations))
    if human_items:
        kv("Human review items", len(human_items))
        for h in human_items[:3]:
            print(f"        {h['conflict_id']}: {h.get('reason','')[:100]}")

    return report.get("route_decision"), report.get("status")


def print_data_comparison(before, after, label):
    """Compare before/after data and print changes."""
    before_map = {r["record_id"]: r for r in before.get("records", [])}
    after_map = {r["record_id"]: r for r in after.get("records", [])}

    changed = 0
    deleted = 0
    for rid, br in sorted(before_map.items()):
        ar = after_map.get(rid)
        if not ar:
            if label:
                print(f"    [{rid}] DELETED (duplicate removed)")
            deleted += 1
            changed += 1
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
            if label:
                print(f"    [{rid}] {'; '.join(diffs)}")
    if label:
        if changed == 0:
            print("    (no changes — data was already clean)")
        kv("Total changes", f"{changed} records ({deleted} deleted)")
    return changed


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main():
    t_total = time.time()
    hdr("三模块联调测试: Assessment → Normalization → Conflict")
    hdr("领域: 材料科学 | 5 篇论文 | 含别名/格式/单位/缺失/冲突全场景")

    # ── PHASE 0: 初始化 ──
    phase(0, "数据初始化")
    input_data = build_test_data()
    from quality_state import make_initial_state
    from configs import load_yaml

    state = make_initial_state(input_data)
    state["context_state"].update({
        "quality_rules": load_yaml("quality_rules.yaml") or {},
        "target_schema": load_yaml("schema_mapping.yaml").get("target_schema", {}),
        "research_domain": "materials_science",
    })

    print_input_summary(input_data)

    # ── PHASE 1: Assessment ──
    phase(1, "Assessment Module (4 Stages)")
    from Data_Assessment_agentV1.assessment_graph import build_assessment_graph
    t1 = time.time()
    before_assessment = copy.deepcopy(state["data_state"]["current_data"])
    state = build_assessment_graph().compile().invoke(state)
    t1e = time.time() - t1

    per_source_routes, norm_count, conf_count = print_assessment_summary(state, t1e)

    # ── PHASE 2: Normalization ──
    if norm_count == 0:
        print("\n  ✓ 无来源需要 Normalization，跳过 Phase 2")
        norm_ran = False
    else:
        phase(2, "Normalization Module (5 Stages)")
        t2 = time.time()
        before_norm = copy.deepcopy(state["data_state"]["current_data"])

        from Data_Normalization_agentV1.normalization_graph import build_normalization_graph
        state = build_normalization_graph().compile().invoke(state)
        t2e = time.time() - t2

        norm = state.get("report_state", {}).get("normalization", {})
        wf = state.get("workflow_state", {})

        # Print each stage from report
        sp = norm.get("source_plan", {})
        print_normalization_stage("Stage 1/5: SourceRouterAgent", state, 0)
        print_normalization_stage("Stage 2/5: ToolPlanningAgent", state, 0)
        print_normalization_stage("Stage 3/5: ToolExecutorAgent", state, 0)
        print_normalization_stage("Stage 4/5: ValidationAgent", state, 0)
        print_normalization_stage("Stage 5/5: ReportAgent", state, 0)

        norm_ran = True

        # Show normalization data changes
        sub("Normalization 数据变更 (BEFORE → AFTER)")
        print_data_comparison(before_norm, state["data_state"]["current_data"], label=True)

    # ── PHASE 3: Conflict (if needed) ──
    wf = state.get("workflow_state", {})
    route = wf.get("route_decision", "")
    norm = state.get("report_state", {}).get("normalization", {})
    needs_conflict = (route == "Conflict"
                      or norm.get("validation", {}).get("needs_conflict_analysis")
                      or conf_count > 0)

    conflict_ran = False
    conflict_round = 0
    MAX_LOOP = 3

    while (needs_conflict or route == "Conflict") and conflict_round < MAX_LOOP:
        conflict_round += 1
        phase(3, f"Conflict Module (6 Stages) — Round {conflict_round}/{MAX_LOOP}")
        t3 = time.time()
        before_conflict = copy.deepcopy(state["data_state"]["current_data"])

        from Data_Conflict_agentV1.conflict_graph import build_conflict_graph
        state = build_conflict_graph().compile().invoke(state)
        t3e = time.time() - t3

        next_route, status = print_conflict_summary(state, t3e)

        conflict_ran = True

        # Check if we need to go back to Normalization
        if next_route == "Normalization" and conflict_round < MAX_LOOP:
            sub(f"Conflict → Normalization (C→B, round {conflict_round})")
            before_norm2 = copy.deepcopy(state["data_state"]["current_data"])

            from Data_Normalization_agentV1.normalization_graph import build_normalization_graph
            state = build_normalization_graph().compile().invoke(state)

            print_normalization_stage("Stage 1/5: SourceRouterAgent", state, 0)
            print_normalization_stage("Stage 2/5: ToolPlanningAgent", state, 0)
            print_normalization_stage("Stage 3/5: ToolExecutorAgent", state, 0)
            print_normalization_stage("Stage 4/5: ValidationAgent", state, 0)
            print_normalization_stage("Stage 5/5: ReportAgent", state, 0)

            print_data_comparison(before_norm2, state["data_state"]["current_data"], label=True)

            # Re-check for conflicts
            wf = state.get("workflow_state", {})
            route = wf.get("route_decision", "")
            norm = state.get("report_state", {}).get("normalization", {})
            needs_conflict = (route == "Conflict"
                              or norm.get("validation", {}).get("needs_conflict_analysis"))
        else:
            route = next_route
            break

    if not conflict_ran and (needs_conflict or route == "Conflict"):
        print(f"\n  ⚠ Conflict needed but not run (may be initial detection without B→C path)")

    # ── PHASE 4: 最终数据汇总 ──
    phase(4, "最终数据汇总")
    final_data = state["data_state"]["current_data"]
    final_records = final_data.get("records", [])
    final_sources = final_data.get("sources", [])

    print(f"  最终数据: {len(final_sources)} sources, {len(final_records)} records")
    print(f"\n  处理后的数据:")

    # Group by source
    from collections import defaultdict
    by_source = defaultdict(list)
    for r in final_records:
        by_source[r["source_id"]].append(r)

    for src in final_sources:
        sid = src["source_id"]
        recs = by_source.get(sid, [])
        print(f"\n    [{sid}] {src.get('title','')[:55]}")
        for r in sorted(recs, key=lambda x: x.get("field_name", "")):
            fu = r.get("field_unit") or "(none)"
            v = str(r.get("field_value", ""))
            print(f"      {r['field_name']:22s} = {v:10s} {fu:8s}")

    # ── PHASE 5: 最终路由判决 ──
    phase(5, "最终路由判决")
    wf = state.get("workflow_state", {})
    final_route = wf.get("route_decision", "Export")

    quality = state.get("report_state", {}).get("quality", {})
    norm = state.get("report_state", {}).get("normalization", {})
    conflict = state.get("report_state", {}).get("conflict", {})

    print(f"  最终路由: {final_route}")
    print(f"  执行状态: {wf.get('execution_status', 'N/A')}")
    print(f"  迭代次数: {wf.get('iteration_counter', 0)}")

    if final_route == "Export":
        print(f"\n  ✓ 数据已准备就绪，可进入 Export 模块")
    elif final_route == "HumanReview":
        pending = conflict.get("resolution_report", {}).get("resolution_plan", {}).get("human_review_items", [])
        print(f"\n  ⚠ 需要人工审核 ({len(pending)} 项待处理)")
        for p in pending[:5]:
            print(f"    - {p.get('conflict_id','?')}: {p.get('reason','')[:100]}")
    elif final_route == "Normalization":
        print(f"\n  → 需要进一步规范化处理")

    # ── LLM 统计 ──
    hdr("LLM 调用统计")
    print_llm_stats()
    stats = get_llm_stats()
    print(f"\n  总调用次数: {stats['total_calls']}")
    print(f"  首次策略成功: {stats['success_calls']} ({stats.get('first_strategy_rate',0):.1f}%)")
    print(f"  回退后成功: {stats['fallback_calls']}")
    print(f"  全部失败: {stats['failed_calls']}")
    print(f"  成功率: {stats.get('success_rate',0):.1f}%")
    print(f"  总耗时: {stats['total_time_seconds']:.2f}s")

    # ── 性能统计 ──
    total_elapsed = time.time() - t_total
    hdr("性能统计")
    kv("Assessment", f"{t1e:.2f}s")
    if norm_ran:
        kv("Normalization", f"{t2e:.2f}s")
    if conflict_ran:
        kv("Conflict", f"~{t3e:.2f}s/round (x{conflict_round})")
    kv("Total elapsed", f"{total_elapsed:.1f}s")
    kv("Final route", final_route)

    hdr("三模块联调测试完成")
    print(f"\n  结论: 数据已通过 Assessment → Normalization → Conflict 管道")
    print(f"  最终目标: {'→ Export (可直接导出)' if final_route == 'Export' else '→ ' + final_route}")
    print(f"  如有 HumanReview 项, 请通过人工审核界面处理后重新运行")

    return final_route


if __name__ == "__main__":
    main()
