"""
export_generation_agent.py — Stage 6: StructuredExportGenerationAgent

构建 quality_summary + 组装 Output State + 完成 Workflow。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)


class StructuredExportGenerationAgent:
    """Stage 6: 最终输出 — Quality Summary + Output State 组装"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        export_state = state.get("report_state", {}).get("export", {})
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        structured_data = export_state.get("formatted_data", {})
        metadata = export_state.get("metadata", {})
        traceability = export_state.get("traceability", {})
        validation = export_state.get("validation", {})
        completeness = export_state.get("trace_completeness", {})

        # ── 构建 Quality Summary ──
        quality_summary = _build_quality_summary(rs, wf, validation, completeness)

        is_valid = validation.get("is_valid", True)
        status = "Success" if is_valid else "Failed"

        elapsed = round(time.time() - t0, 3)
        logger.info("[ExportGeneration] %s, route=END, %.2fs", status, elapsed)

        return {
            "output_state": {
                "structured_data": structured_data,
                "metadata": metadata,
                "traceability": traceability,
                "quality_summary": quality_summary,
                "schema_version": "grounded_data_v1",
                "export_format": "json",
            },
            "workflow_state": {
                "route_decision": "",
                "execution_status": status,
                "current_node": "structured_export",
                "workflow_history": [{
                    "agent": "StructuredExportGenerationAgent", "stage": "ExportGeneration",
                    "status": status, "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Export {'completed' if is_valid else 'failed'}, {structured_data.get('row_count', 0)} rows",
                }],
            },
        }


def _build_quality_summary(
    report_state: dict[str, Any],
    workflow_state: dict[str, Any],
    validation: dict[str, Any],
    trace_completeness: dict[str, Any],
) -> dict[str, Any]:
    """整合三模块报告, 构建质量摘要。"""
    quality = report_state.get("quality") or {}
    normalization = report_state.get("normalization") or {}
    conflict = report_state.get("conflict") or {}
    scoring = quality.get("quality_scoring", {})
    resolution_report = conflict.get("resolution_report", {})

    # 1. Overall Metrics
    overall_score = scoring.get("overall_score", 0)
    quality_level = scoring.get("quality_level", "unknown")
    calibrated_conf = scoring.get("calibrated_confidence", 0)
    confidence_factors = scoring.get("confidence_factors", {})

    # 2. Processing Statistics
    proc_stats = {
        "total_llm_calls": workflow_state.get("llm_call_count", 0),
        "total_tool_calls": workflow_state.get("tool_call_count", 0),
        "total_elapsed_seconds": _compute_total_elapsed(workflow_state),
        "b_c_loop_iterations": workflow_state.get("iteration_counter", 0),
    }

    # 3. Issues Summary
    mods = normalization.get("modifications", {})
    issues_summary = {
        "assessment_issues": quality.get("total_issues", 0),
        "normalization_modifications": mods.get("total", 0),
        "conflicts_resolved": resolution_report.get("metadata", {}).get("auto_resolved", 0),
        "remaining_issues": len((normalization.get("validation") or {}).get("remaining_issues", [])),
    }

    # 4. Risk Indicators
    risk = {
        "has_human_review_items": resolution_report.get("metadata", {}).get("human_required", 0) > 0,
        "has_unresolved_conflicts": resolution_report.get("status") not in ("All_Resolved", "No_Conflicts", None),
        "has_unconverted_units": len(mods.get("errors", [])) > 0,
        "data_completeness_warning": overall_score < 0.7,
        "validation_passed": validation.get("is_valid", True),
    }

    # 5. Recommendation
    recommendation = _generate_recommendation(quality_level, risk, issues_summary)

    return {
        "overall_score": overall_score,
        "quality_level": quality_level,
        "calibrated_confidence": calibrated_conf,
        "confidence_breakdown": confidence_factors,
        "processing_statistics": proc_stats,
        "issues_summary": issues_summary,
        "risk_indicators": risk,
        "recommendation": recommendation,
    }


def _compute_total_elapsed(workflow_state: dict) -> float:
    """从 workflow_history 计算总耗时。"""
    history = workflow_state.get("workflow_history", [])
    if len(history) < 2:
        return 0.0
    # 累加每个 stage 的 duration
    total = sum(h.get("duration", 0) for h in history)
    return round(total, 2)


def _generate_recommendation(quality_level: str, risk: dict, issues: dict) -> str:
    """基于风险指标生成建议。"""
    warnings = []
    if risk["has_human_review_items"]:
        warnings.append(f"{issues['remaining_issues']} items require human review")
    if risk["has_unresolved_conflicts"]:
        warnings.append("unresolved conflicts remain")
    if risk["has_unconverted_units"]:
        warnings.append("some units could not be converted")
    if risk["data_completeness_warning"]:
        warnings.append("data completeness below threshold")
    if not risk["validation_passed"]:
        warnings.append("output validation failed")

    if not warnings:
        return f"Data ready for analysis. Quality level: {quality_level}. No significant risks detected."
    else:
        return f"Data exported with {len(warnings)} warning(s): {'; '.join(warnings)}. Quality level: {quality_level}. Review recommended before use."
