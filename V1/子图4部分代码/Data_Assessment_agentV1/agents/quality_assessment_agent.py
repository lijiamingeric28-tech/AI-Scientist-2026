"""
quality_assessment_agent.py — Stage 2: QualityAssessmentAgent

职责: 对每篇论文独立调用 5 维度质量检测工具, 生成 per-source Quality Report。
- 每条记录有 source_id, 天然支持按来源分组评估
- 每个 source 独立评估后可分流到不同下游模块
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from quality_state import QualityGraphState
from utils.llm import set_agent_context
from utils.logger import get_logger

logger = get_logger(__name__)


class QualityAssessmentAgent:
    """Stage 2: Per-Source Quality Assessment — 每个来源独立评估。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ds = state.get("data_state", {})
        ctx = state.get("context_state", {})
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        input_data = ds.get("current_data", ds.get("input_data", {}))
        target_schema = ctx.get("target_schema")
        quality_rules = ctx.get("quality_rules", {})
        threshold = quality_rules.get("conflict_detection", {}).get("numeric_diff_threshold", 0.20)

        # ── V2.0 A1: 自适应阈值引擎 ──
        from tools.assessment.adaptive_threshold import AdaptiveThresholdEngine
        adaptive_engine = AdaptiveThresholdEngine(quality_rules)
        research_domain = ctx.get("research_domain", "default")
        adaptive_engine.set_domain(research_domain)

        all_records = input_data.get("records", [])
        all_sources = input_data.get("sources", [])

        # ── 按 source_id 分组 ──
        source_groups: dict[str, list[dict]] = {}
        for rec in all_records:
            sid = rec.get("source_id", "unknown")
            source_groups.setdefault(sid, []).append(rec)

        # 确保所有 sources 都有条目 (即使没有 records)
        for src in all_sources:
            sid = src.get("source_id", "")
            if sid not in source_groups:
                source_groups[sid] = []

        # ── 逐 source 评估 ──
        source_reports: dict[str, dict] = {}
        total_tool_count = 0
        total_issues = 0
        total_conflicts = 0

        from tools.assessment.completeness import check_completeness
        from tools.assessment.consistency import check_consistency
        from tools.assessment.format_checker import check_format
        from tools.assessment.source_checker import check_source_reliability
        from tools.assessment.statistical_conflict import detect_conflicts_statistical

        for sid, recs in source_groups.items():
            # 构建该 source 的子数据集
            sub_data = {
                "sources": [s for s in all_sources if s.get("source_id") == sid],
                "records": recs,
            }

            # ── V2.0 A1: 自适应冲突检测阈值 ──
            n_recs = len(recs)
            adaptive_conflict_threshold = adaptive_engine.get_conflict_threshold(
                "", n_recs)  # field-level will be refined in conflict_detector

            completeness = check_completeness(sub_data, target_schema)
            consistency = check_consistency(sub_data)
            fmt = check_format(sub_data)
            source_rel = check_source_reliability(sub_data)
            conflict_risk = detect_conflicts_statistical(sub_data, threshold=adaptive_conflict_threshold)
            total_tool_count += 5

            # ── V2.0 A1: 自适应 completeness 阈值 ──
            adaptive_comp_threshold = adaptive_engine.get_completeness_threshold("", n_recs)
            below_threshold = completeness["score"] < adaptive_comp_threshold

            # 该 source 的 issue list
            src_issues: list[dict] = []
            for dim_name, dim_result in [
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

            # 查找 source 元数据
            src_meta = next((s for s in all_sources if s.get("source_id") == sid), {})
            title = src_meta.get("title", sid)[:80]
            year = src_meta.get("year", "?")

            # ── V2.0 A3: LLM 增强完整性分析 ──
            llm_completeness = None
            missing = completeness.get("missing_expected_fields", [])
            present = completeness.get("present_fields", [])
            if missing:
                try:
                    from tools.assessment.llm_completeness import analyze_missing_fields
                    llm_completeness = analyze_missing_fields(title, present, missing, year)
                except Exception:
                    pass

            source_reports[sid] = {
                "title": title,
                "year": year,
                "record_count": len(recs),
                "completeness": completeness,
                "consistency": consistency,
                "format": fmt,
                "source_reliability": source_rel,
                "conflict_risk": conflict_risk,
                "issues": src_issues,
                "issue_count": len(src_issues),
                "llm_completeness": llm_completeness,
                "below_adaptive_threshold": below_threshold,
            }
            total_issues += len(src_issues)
            total_conflicts += conflict_risk.get("conflict_count", 0)

        # ── 汇总 Quality Report ──
        quality = dict(rs.get("quality", {}) or {})
        quality["sources"] = source_reports
        quality["source_count"] = len(source_reports)
        quality["total_issues"] = total_issues
        quality["total_conflicts"] = total_conflicts

        tc = wf.get("tool_call_count", 0) + total_tool_count
        elapsed = round(time.time() - t0, 3)

        logger.info("[QualityAssessmentAgent] %d sources, %d issues, %d conflicts, %.2fs",
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
                    "reason": f"{len(source_reports)} sources, {total_issues} issues, {total_conflicts} conflicts",
                }],
            },
        }
