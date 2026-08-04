"""
export_generation_agent.py — Stage 6: StructuredExportGenerationAgent

构建 quality_summary + 组装 Output State + 导出 CSV/JSON 文件。
"""
from __future__ import annotations
import datetime, json, os, time
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)

# 默认输出目录
_DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")


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
        # V3.1 fix: 统一从 traceability dict 读取 (已内嵌 trace_completeness)
        completeness = traceability.get("trace_completeness", {})

        # ── 构建 Quality Summary ──
        quality_summary = _build_quality_summary(rs, wf, validation, completeness)

        is_valid = validation.get("is_valid", True)
        status = "Success" if is_valid else "Failed"

        # V3.2 fix: 校验闸门 — 校验失败时标记 quarantine (consumable=false), 不静默产出
        quarantine = not is_valid

        # ── 导出 CSV/JSON 文件 ──
        output_dir = _resolve_output_dir(state)
        exported_files = _write_export_files(output_dir, structured_data,
                                              metadata, traceability, quality_summary, is_valid)

        elapsed = round(time.time() - t0, 3)
        logger.info("[ExportGeneration] %s%s, %d files exported to %s, %.2fs",
                    status, " (QUARANTINE)" if quarantine else "",
                    len(exported_files), output_dir, elapsed)

        return {
            "output_state": {
                "structured_data": structured_data,
                "metadata": metadata,
                "traceability": traceability,
                "quality_summary": quality_summary,
                "schema_version": "2.0.0",
                "export_format": "json",
                "exported_files": exported_files,
                "output_dir": output_dir,
                "consumable": not quarantine,
                "quarantine": quarantine,
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
    # V4 fix: has_unconverted_units 只统计单位转换失败 (kind=unconverted_unit),
    # 此前误把 Layer-3 生成工具的运行时报错当作单位转换失败
    unconv_errors = [e for e in mods.get("errors", []) if e.get("kind") == "unconverted_unit"]
    risk = {
        "has_human_review_items": resolution_report.get("metadata", {}).get("human_required", 0) > 0,
        "has_unresolved_conflicts": resolution_report.get("status") not in ("All_Resolved", "No_Conflicts", None),
        "has_unconverted_units": len(unconv_errors) > 0,
        "unconverted_unit_count": len(unconv_errors),
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


# ══════════════════════════════════════════════════
# 文件导出
# ══════════════════════════════════════════════════

def _resolve_output_dir(state: QualityGraphState) -> str:
    """解析输出目录，使用 run_id 创建子目录。"""
    wf = state.get("workflow_state", {})
    run_id = wf.get("run_id", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir = run_id[:8] if len(run_id) >= 8 else run_id
    base = os.environ.get("EXPORT_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR)
    output_dir = os.path.join(os.path.abspath(base), run_dir)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _write_export_files(
    output_dir: str,
    structured_data: dict,
    metadata: dict,
    traceability: dict,
    quality_summary: dict,
    is_valid: bool,
) -> list[str]:
    """将导出数据写入文件，返回文件路径列表。"""
    files = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # V4 fix: CSV 编码可配置 — 默认 utf-8-sig (含 BOM, Excel 直接打开中文不乱码);
    # 需要无 BOM 输出时设 EXPORT_CSV_ENCODING=utf-8 (pandas 默认读取)
    csv_encoding = os.environ.get("EXPORT_CSV_ENCODING", "utf-8-sig")

    # 1. JSON (完整 grounded_data)
    json_data = structured_data.get("json", {})
    if json_data:
        path = os.path.join(output_dir, f"grounded_data_{timestamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2, default=str)
        files.append(path)
        logger.info("[Export] JSON written: %s (%d records)", path,
                    len(json_data.get("records", [])))

    # 2. CSV 长表
    csv_str = structured_data.get("csv", "")
    if csv_str:
        path = os.path.join(output_dir, f"data_long_{timestamp}.csv")
        with open(path, "w", encoding=csv_encoding) as f:
            f.write(csv_str)
        files.append(path)
        logger.info("[Export] CSV (long) written: %s", path)

    # 3. CSV 宽表 (Pivot)
    csv_wide = structured_data.get("csv_wide", "")
    if csv_wide:
        path = os.path.join(output_dir, f"data_wide_{timestamp}.csv")
        with open(path, "w", encoding=csv_encoding) as f:
            f.write(csv_wide)
        files.append(path)
        logger.info("[Export] CSV (wide) written: %s", path)

    # 4. Quality Summary
    path = os.path.join(output_dir, f"quality_summary_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(quality_summary, f, ensure_ascii=False, indent=2, default=str)
    files.append(path)

    # 5. Metadata
    path = os.path.join(output_dir, f"metadata_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)
    files.append(path)

    # 6. Traceability (简化版，避免过大)
    trace_summary = {
        "data_lineage": traceability.get("data_lineage", {}),
        "trace_completeness": traceability.get("trace_completeness", {}),
        "modified_count": traceability.get("trace_completeness", {}).get("modified_count", 0),
        "decision_count": len(traceability.get("agent_decision_trail", [])),
    }
    path = os.path.join(output_dir, f"traceability_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace_summary, f, ensure_ascii=False, indent=2, default=str)
    files.append(path)

    # 7. Export manifest
    manifest = {
        "exported_at": datetime.datetime.now().isoformat(),
        "output_dir": output_dir,
        "files": [os.path.basename(f) for f in files],
        "validation_passed": is_valid,
        "row_count": structured_data.get("row_count", 0),
        "quality_level": quality_summary.get("quality_level", "unknown"),
        # V4 fix: 宽表折叠统计 + CSV 编码说明 (此前折叠静默无痕)
        "wide_collapse": structured_data.get("wide_collapse", {}),
        "csv_encoding": csv_encoding,
        "csv_encoding_note": ("utf-8-sig 含 BOM (Excel 兼容); "
                              "需要无 BOM 输出请设 EXPORT_CSV_ENCODING=utf-8"),
    }
    path = os.path.join(output_dir, f"manifest_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    files.append(path)

    return files
