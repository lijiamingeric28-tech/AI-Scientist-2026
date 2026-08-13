"""
quality_assessment_agent.py — Stage 2: QualityAssessmentAgent (V3.0)

职责: 对每篇论文独立调用质量检测工具, 生成 per-source Quality Report。
V3.0: 冲突检测 → 多源方差分析 (不再淘汰数据, 只标注差异 + 检测异常)。
V2.3: 并行处理 — sources 使用 ThreadPoolExecutor 并发评估,
      LLM 完整性分析也并行执行, 大幅缩短总耗时。
"""
from __future__ import annotations

import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

# 并行线程数 (I/O 密集型 LLM 调用, 可设较多)
_MAX_WORKERS = 8

# 异常类型常量
_ANOMALY_STATISTICAL = "statistical_outlier"
_ANOMALY_EXTRACTION = "extraction_error"
_ANOMALY_UNIT = "unit_error"
_ANOMALY_CROSS_ID = "cross_id_error"


def _filter_source_anomalies(anomalies: list[dict], sid: str) -> list[dict]:
    """从全局异常列表中筛选涉及指定 source 的异常。"""
    result = []
    for a in anomalies:
        atype = a.get("anomaly_type", "")
        if atype == _ANOMALY_STATISTICAL:
            if a.get("source_a") == sid or a.get("source_b") == sid:
                result.append(a)
        elif atype == _ANOMALY_EXTRACTION:
            if a.get("source_id") == sid:
                result.append(a)
        elif atype == _ANOMALY_UNIT:
            units_found = a.get("units_found", {})
            if isinstance(units_found, dict) and sid in units_found:
                result.append(a)
        elif atype == _ANOMALY_CROSS_ID:
            # V3.0 fix: 只对涉及同名 entity 的 source 可见 (不广播到全部 source)
            pass  # cross_id 异常不属于任何特定 source, 由 downstream Conflict 处理
        else:
            # 通用fallback: 检查 source_a/source_b 或 source_id
            if a.get("source_a") == sid or a.get("source_b") == sid or a.get("source_id") == sid:
                result.append(a)
    return result


def _assess_single_source(
    sid: str,
    recs: list[dict],
    all_sources: list[dict],
    target_schema: dict | None,
    global_variance_result: dict,
    adaptive_engine,
) -> dict:
    """评估单个 source (在独立线程中运行) — V3.0 方差分析版。"""
    sub_data = {
        "sources": [s for s in all_sources if s.get("source_id") == sid],
        "records": recs,
    }
    n_recs = len(recs)

    from quality_pipeline.tools.assessment.completeness import check_completeness
    from quality_pipeline.tools.assessment.consistency import check_consistency
    from quality_pipeline.tools.assessment.format_checker import check_format
    from quality_pipeline.tools.assessment.source_checker import check_source_reliability
    from quality_pipeline.tools.assessment.extraction_quality import check_extraction_quality

    # ── V2.3: 提取质量 (grounded_data 特有) ──
    extraction_quality = check_extraction_quality(recs)

    completeness = check_completeness(sub_data, target_schema)
    consistency = check_consistency(sub_data)
    fmt = check_format(sub_data)
    source_rel = check_source_reliability(sub_data)

    # ── V3.0: per-source 异常筛选 (替代旧 per-source 冲突筛选) ──
    source_anomalies = _filter_source_anomalies(
        global_variance_result.get("anomalies", []), sid
    )
    # per-source 方差 (该 source 参与的多源差异组)
    source_variances = [
        v for v in global_variance_result.get("variances", [])
        if sid in v.get("source_ids", [])
    ]

    conflict_risk = {
        # V3.0: has_conflicts → 仅当此 source 存在 anomaly
        "has_conflicts": len(source_anomalies) > 0,
        "conflict_count": len(source_anomalies),
        "conflicts": source_anomalies,  # 兼容下游 (实际是 anomalies)
        "risk_level": global_variance_result.get("risk_level", "none"),
        "method": global_variance_result.get("method", "multi_source_variance"),
        # V3.0 新增
        "has_variance": len(source_variances) > 0,
        "variance_count": len(source_variances),
        "variances": source_variances,
        "summary": (
            f"{len(source_anomalies)} anomaly(ies), "
            f"{len(source_variances)} multi-source variance group(s)"
        ),
    }

    # ── A4 fix: 自适应阈值 (第 9 项检查) — 逐字段计算, 替代"首字段代表全 source" ──
    # 任一关键字段 coverage < 动态阈值 → below_adaptive_threshold=True + 违规清单
    field_completeness = completeness.get("field_completeness", {}) or {}
    adaptive_issues: list[str] = []
    below_threshold = False
    if field_completeness:
        for fname, coverage in field_completeness.items():
            if not isinstance(coverage, (int, float)):
                continue
            threshold = adaptive_engine.get_completeness_threshold(fname, n_recs)
            if coverage < threshold:
                adaptive_issues.append(f"{fname}({coverage:.2f}<{threshold:.2f})")
        below_threshold = len(adaptive_issues) > 0
    else:
        # 兜底: 无逐字段数据时用总分
        comp_field = next(iter(completeness.get("present_fields", [])), "general")
        below_threshold = completeness["score"] < adaptive_engine.get_completeness_threshold(comp_field, n_recs)

    # ── V3.0: Issue list (anomalies 作为 error, variances 作为 info) ──
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

    # 异常 → error
    for a in source_anomalies:
        atype = a.get("anomaly_type", "unknown")
        field = a.get("field_name", "")
        detail = (
            f"[{atype}] {a.get('entity_name','?')}: "
            f"{a.get('evidence', {})}"
        )
        src_issues.append({
            "dimension": "anomaly", "severity": "error",
            "field": field, "detail": detail,
        })

    # 多源方差 → info (不阻塞 export, 仅标注)
    for v in source_variances:
        cause = v.get("inferred_cause", "unknown")
        field = v.get("field_name", "")
        detail = (
            f"multi_source_variance[{cause}]: "
            f"{v.get('entity_name','?')} "
            f"range={v.get('value_range',[])} "
            f"({v.get('source_count',0)} sources)"
        )
        src_issues.append({
            "dimension": "multi_source_variance", "severity": "info",
            "field": field, "detail": detail,
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
        "adaptive_issues": adaptive_issues,  # A4: 违规字段清单 (供 Decision 第 9 项检查)
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
        from quality_pipeline.tools.assessment.adaptive_threshold import AdaptiveThresholdEngine
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

        # ── V3.0: 全局多源方差分析 (必须先做, 不能并行) ──
        from quality_pipeline.tools.assessment.statistical_conflict import analyze_multi_source_variance
        global_variance_result = analyze_multi_source_variance(input_data)
        tool_count = 1

        # ══════════════════════════════════════════════════
        # V2.3: 并行处理所有 sources (4 tools each)
        # ══════════════════════════════════════════════════
        source_reports: dict[str, dict] = {}
        total_issues = 0
        total_anomalies = 0
        total_variances = 0

        n_workers = min(_MAX_WORKERS, max(1, len(source_groups)))
        logger.info("[QualityAssessment] Processing %d sources with %d workers",
                    len(source_groups), n_workers)

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {}
            for sid, recs in source_groups.items():
                future = executor.submit(
                    _assess_single_source,
                    sid, recs, all_sources, target_schema,
                    global_variance_result, adaptive_engine,
                )
                futures[future] = sid

            for future in as_completed(futures):
                try:
                    result = future.result()
                    sid = result.pop("source_id")
                    source_reports[sid] = result
                    total_issues += result["issue_count"]
                    total_anomalies += result["conflict_risk"]["conflict_count"]
                    total_variances += result["conflict_risk"].get("variance_count", 0)
                    tool_count += 5  # V2.3: +extraction_quality
                except Exception as e:
                    sid = futures[future]
                    logger.error("[QualityAssessment] Source %s failed: %s", sid, e)
                    source_reports[sid] = {
                        "title": sid, "year": "?", "record_count": 0,
                        "completeness": {"score": 0.0}, "consistency": {"score": 0.0},
                        "format": {"score": 0.0, "total_issues": 0},
                        "source_reliability": {"score": 0.0},
                        "conflict_risk": {"has_conflicts": False, "conflict_count": 0, "conflicts": [],
                                         "has_variance": False, "variance_count": 0, "variances": []},
                        "issues": [], "issue_count": 0,
                        "llm_completeness": None, "below_adaptive_threshold": False,
                        "error": str(e),
                    }

        # ══════════════════════════════════════════════════
        # V2.3: 并行 LLM 完整性分析 (最慢的部分)
        # ══════════════════════════════════════════════════
        llm_count = 0  # L-24 fix: LLM 完整性调用计数 (按成功返回的 sid 数累加)
        llm_sources = [
            (sid, sr) for sid, sr in source_reports.items()
            if sr.get("has_missing_fields")
        ]
        if llm_sources:
            logger.info("[QualityAssessment] Running LLM completeness for %d sources in parallel",
                        len(llm_sources))

            def _llm_task(sid, sr):
                try:
                    from quality_pipeline.tools.assessment.llm_completeness import analyze_missing_fields
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
                        llm_count += 1  # L-24 fix: 成功返回的 sid 计一次 LLM 调用
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
        quality["total_anomalies"] = total_anomalies
        quality["total_variances"] = total_variances
        # V3.0: 保存全局方差分析结果供下游 Conflict Agent 使用
        quality["multi_source_variance"] = {
            "has_variance": global_variance_result.get("has_variance", False),
            "variance_count": global_variance_result.get("variance_count", 0),
            "variances": global_variance_result.get("variances", []),
            "has_anomalies": global_variance_result.get("has_anomalies", False),
            "anomaly_count": global_variance_result.get("anomaly_count", 0),
            "anomalies": global_variance_result.get("anomalies", []),
            "risk_level": global_variance_result.get("risk_level", "none"),
            "summary": global_variance_result.get("summary", ""),
        }

        tc = wf.get("tool_call_count", 0) + tool_count
        elapsed = round(time.time() - t0, 3)

        # A7 fix: execution_status 透传 — profiling 的 Failed/Retry 此前被无条件
        # 覆写 Success, 子图级重试机制形同虚设 (finalize 读到的永远是 Success)
        prev_status = wf.get("execution_status", "Success")
        any_failed = any(sr.get("error") for sr in source_reports.values())
        if prev_status == "Failed" or any_failed:
            exec_status = "Failed"
        elif prev_status == "Retry":
            exec_status = "Retry"
        else:
            exec_status = "Success"

        logger.info("[QualityAssessmentAgent] %d sources, %d issues, %d anomalies, %d variance groups, %.2fs (PARALLEL) status=%s",
                    len(source_reports), total_issues, total_anomalies, total_variances, elapsed, exec_status)

        return {
            "report_state": {"quality": quality},
            "workflow_state": {
                "current_node": "quality_assessment",
                "execution_status": exec_status,
                "tool_call_count": tc,
                "llm_call_count": wf.get("llm_call_count", 0) + llm_count,  # L-24 fix: 与其余节点累计语义一致
                "workflow_history": [{
                    "agent": "QualityAssessmentAgent", "stage": "QualityAssessment",
                    "status": exec_status,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(source_reports)} sources (parallel), {total_issues} issues, {total_anomalies} anomalies, {total_variances} variance groups",
                }],
            },
        }
