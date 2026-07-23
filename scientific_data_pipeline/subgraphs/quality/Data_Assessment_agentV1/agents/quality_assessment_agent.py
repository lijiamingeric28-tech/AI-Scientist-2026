"""
quality_assessment_agent.py — Stage 2: QualityAssessmentAgent (V2.3)

职责: 对每篇论文独立调用质量检测工具, 生成 per-source Quality Report。
V2.3: 并行处理 — sources 使用 ThreadPoolExecutor 并发评估,
      LLM 完整性分析也并行执行, 大幅缩短总耗时。
"""
from __future__ import annotations

import datetime, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)

# 并行线程数 (I/O 密集型 LLM 调用, 可设较多)
_MAX_WORKERS = 8


def _assess_single_source(
    sid: str,
    recs: list[dict],
    all_sources: list[dict],
    target_schema: dict | None,
    global_conflict_risk: dict,
    adaptive_engine,
) -> dict:
    """评估单个 source (在独立线程中运行)。"""
    sub_data = {
        "sources": [s for s in all_sources if s.get("source_id") == sid],
        "records": recs,
    }
    n_recs = len(recs)

    from subgraphs.quality.tools.assessment.completeness import check_completeness
    from subgraphs.quality.tools.assessment.consistency import check_consistency
    from subgraphs.quality.tools.assessment.format_checker import check_format
    from subgraphs.quality.tools.assessment.source_checker import check_source_reliability
    from subgraphs.quality.tools.assessment.extraction_quality import check_extraction_quality

    # ── V2.3: 提取质量 (grounded_data 特有) ──
    extraction_quality = check_extraction_quality(recs)

    completeness = check_completeness(sub_data, target_schema)
    consistency = check_consistency(sub_data)
    fmt = check_format(sub_data)
    source_rel = check_source_reliability(sub_data)

    # per-source 冲突筛选
    source_conflicts = [
        c for c in global_conflict_risk.get("conflicts", [])
        if c.get("source_a") == sid or c.get("source_b") == sid
    ]
    conflict_risk = {
        "has_conflicts": len(source_conflicts) > 0,
        "conflict_count": len(source_conflicts),
        "conflicts": source_conflicts,
        "risk_level": global_conflict_risk.get("risk_level", "none"),
        "method": global_conflict_risk.get("method", "cohens_d"),
        "summary": f"{len(source_conflicts)} conflict(s) involving this source",
    }

    # 自适应阈值
    comp_field = next(iter(completeness.get("present_fields", [])), "general")
    adaptive_comp_threshold = adaptive_engine.get_completeness_threshold(comp_field, n_recs)
    below_threshold = completeness["score"] < adaptive_comp_threshold

    # Issue list (V2.3: 加入 extraction_quality)
    src_issues: list[dict] = []
    for dim_name, dim_result in [
        ("extraction_quality", extraction_quality),
        ("completeness", completeness), ("consistency", consistency),
        ("format", fmt), ("source_reliability", source_rel),
    ]:
        for iss in dim_result.get("issues", []):
            src_issues.append({
                "dimension": dim_name, "severity": "warning",
                "field": iss if isinstance(iss, str) else iss.get("field_name", ""),
                "detail": str(iss),
            })
    for c in conflict_risk.get("conflicts", []):
        src_issues.append({
            "dimension": "conflict_risk", "severity": "error",
            "field": c.get("field_name", ""),
            "detail": f"{c.get('type','?')}: {c.get('value_a','?')} vs {c.get('value_b','?')}",
        })

    src_meta = next((s for s in all_sources if s.get("source_id") == sid), {})
    title = src_meta.get("title", sid)[:80]
    year = src_meta.get("year", "?")

    return {
        "source_id": sid,
        "title": title, "year": year,
        "record_count": n_recs,
        "extraction_quality": extraction_quality,
        "completeness": completeness,
        "consistency": consistency,
        "format": fmt,
        "source_reliability": source_rel,
        "conflict_risk": conflict_risk,
        "issues": src_issues,
        "issue_count": len(src_issues),
        "llm_completeness": None,  # filled later
        "below_adaptive_threshold": below_threshold,
        "has_missing_fields": len(completeness.get("missing_expected_fields", [])) > 0,
        "present_fields": completeness.get("present_fields", []),
        "missing_expected_fields": completeness.get("missing_expected_fields", []),
    }


class QualityAssessmentAgent:
    """Stage 2: Per-Source Quality Assessment — V2.3 并行处理。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ds = state.get("data_state", {})
        ctx = state.get("context_state", {})
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        input_data = ds.get("current_data", ds.get("input_data", {}))
        target_schema = ctx.get("target_schema")
        quality_rules = ctx.get("quality_rules", {})
        research_domain = ctx.get("research_domain", "default")

        # ── 自适应阈值引擎 ──
        from subgraphs.quality.tools.assessment.adaptive_threshold import AdaptiveThresholdEngine
        adaptive_engine = AdaptiveThresholdEngine(quality_rules)
        adaptive_engine.set_domain(research_domain)

        all_records = input_data.get("records", [])
        all_sources = input_data.get("sources", [])

        # ── 分组 ──
        source_groups: dict[str, list[dict]] = {}
        for rec in all_records:
            sid = rec.get("source_id", "unknown")
            source_groups.setdefault(sid, []).append(rec)
        for src in all_sources:
            sid = src.get("source_id", "")
            if sid not in source_groups:
                source_groups[sid] = []

        # ── 全局冲突检测 (必须先做, 不能并行) ──
        from subgraphs.quality.tools.assessment.statistical_conflict import detect_conflicts_statistical
        global_conflict_risk = detect_conflicts_statistical(input_data, use_advanced=True)
        tool_count = 1

        # ══════════════════════════════════════════════════
        # V2.3: 并行处理所有 sources (4 tools each)
        # ══════════════════════════════════════════════════
        source_reports: dict[str, dict] = {}
        total_issues = 0
        total_conflicts = 0

        n_workers = min(_MAX_WORKERS, max(1, len(source_groups)))
        logger.info("[QualityAssessment] Processing %d sources with %d workers",
                    len(source_groups), n_workers)

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {}
            for sid, recs in source_groups.items():
                future = executor.submit(
                    _assess_single_source,
                    sid, recs, all_sources, target_schema,
                    global_conflict_risk, adaptive_engine,
                )
                futures[future] = sid

            for future in as_completed(futures):
                try:
                    result = future.result()
                    sid = result.pop("source_id")
                    source_reports[sid] = result
                    total_issues += result["issue_count"]
                    total_conflicts += result["conflict_risk"]["conflict_count"]
                    tool_count += 5  # V2.3: +extraction_quality
                except Exception as e:
                    sid = futures[future]
                    logger.error("[QualityAssessment] Source %s failed: %s", sid, e)
                    source_reports[sid] = {
                        "title": sid, "year": "?", "record_count": 0,
                        "completeness": {"score": 0.0}, "consistency": {"score": 0.0},
                        "format": {"score": 0.0, "total_issues": 0},
                        "source_reliability": {"score": 0.0},
                        "conflict_risk": {"has_conflicts": False, "conflict_count": 0, "conflicts": []},
                        "issues": [], "issue_count": 0,
                        "llm_completeness": None, "below_adaptive_threshold": False,
                        "error": str(e),
                    }

        # ══════════════════════════════════════════════════
        # V2.3: 并行 LLM 完整性分析 (最慢的部分)
        # ══════════════════════════════════════════════════
        llm_sources = [
            (sid, sr) for sid, sr in source_reports.items()
            if sr.get("has_missing_fields")
        ]
        if llm_sources:
            logger.info("[QualityAssessment] Running LLM completeness for %d sources in parallel",
                        len(llm_sources))

            def _llm_task(sid, sr):
                try:
                    from subgraphs.quality.tools.assessment.llm_completeness import analyze_missing_fields
                    return sid, analyze_missing_fields(
                        sr["title"], sr.get("present_fields", []),
                        sr.get("missing_expected_fields", []), sr.get("year"),
                    )
                except Exception:
                    return sid, None

            with ThreadPoolExecutor(max_workers=min(n_workers, len(llm_sources))) as executor:
                llm_futures = {executor.submit(_llm_task, sid, sr): sid for sid, sr in llm_sources}
                for future in as_completed(llm_futures):
                    try:
                        sid, llm_result = future.result()
                        if llm_result:
                            source_reports[sid]["llm_completeness"] = llm_result
                    except Exception as e:
                        sid = llm_futures[future]
                        logger.warning("[QualityAssessment] LLM completeness failed for %s: %s", sid, e)

        # ── 汇总 ──
        quality = dict(rs.get("quality", {}) or {})
        quality["sources"] = source_reports
        quality["source_count"] = len(source_reports)
        quality["total_issues"] = total_issues
        quality["total_conflicts"] = total_conflicts

        tc = wf.get("tool_call_count", 0) + tool_count
        elapsed = round(time.time() - t0, 3)

        logger.info("[QualityAssessmentAgent] %d sources, %d issues, %d conflicts, %.2fs (PARALLEL)",
                    len(source_reports), total_issues, total_conflicts, elapsed)

        return {
            "report_state": {"quality": quality},
            "workflow_state": {
                "current_node": "quality_assessment",
                "execution_status": "Success",
                "tool_call_count": tc,
                "workflow_history": [{
                    "agent": "QualityAssessmentAgent", "stage": "QualityAssessment",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(source_reports)} sources (parallel), {total_issues} issues, {total_conflicts} conflicts",
                }],
            },
        }
