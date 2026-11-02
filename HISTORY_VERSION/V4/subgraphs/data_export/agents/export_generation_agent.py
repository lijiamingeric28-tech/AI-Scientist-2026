"""
export_generation_agent.py — Stage 6: StructuredExportGenerationAgent

构建 quality_summary + 组装 Output State + 导出 CSV/JSON 文件。
"""
from __future__ import annotations
import datetime
import json
import os
import sys
import time
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
logger = get_logger(__name__)


def _default_output_dir() -> str:
    """输出目录：源码态 = 包根 output/；打包态（PyInstaller onedir）= exe 旁 output/。

    2026-09-04：原为模块常量按包根相对路径求值——frozen 下包根实为
    sys._MEIPASS（_internal/），导出文件全部落进 _internal/output/，而
    web API（web.main.OUTPUT_DIR）扫描 exe 旁 output/，两侧分裂导致
    「任务数据包」恒空。必须运行时求值，口径与 web.main._FROZEN 一致。
    """
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "output")
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "output")


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
        exported_files = _write_export_iles(output_dir, structured_data,
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
        # M3 fix: 原排除集 (All_Resolved/No_Conflicts/None) 与 V3.0 实际状态值
        # (Annotated/No_Variance/Needs_Unit_Fix/Unresolved_Anomalies) 不匹配 → 恒 True
        "has_unresolved_conflicts": resolution_report.get("status") in ("Needs_Unit_Fix", "Unresolved_Anomalies"),
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
    base = os.environ.get("EXPORT_OUTPUT_DIR", _default_output_dir())
    output_dir = os.path.join(os.path.abspath(base), run_dir)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _write_export_iles(
    output_dir: str,
    structured_data: dict,
    metadata: dict,
    traceability: dict,
    quality_summary: dict,
    is_valid: bool,
) -> list[str]:
    """将导出数据写入文件，返回文件路径列表。

    M11 fix: 每个文件独立 try/except — 磁盘满/权限等 OSError 不再冒泡丢弃
    整条已组装的输出, 失败文件记入 manifest.failed_files 并继续, 至少返回部分文件。
    """
    files = []
    failed_files = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # V4 fix: CSV 编码可配置 — 默认 utf-8-sig (含 BOM, Excel 直接打开中文不乱码);
    # 需要无 BOM 输出时设 EXPORT_CSV_ENCODING=utf-8 (pandas 默认读取)
    csv_encoding = os.environ.get("EXPORT_CSV_ENCODING", "utf-8-sig")

    # 1. JSON (完整 grounded_data)
    json_data = structured_data.get("json", {})
    if json_data:
        path = os.path.join(output_dir, f"grounded_data_{timestamp}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2, default=str)
            files.append(path)
            logger.info("[Export] JSON written: %s (%d records)", path,
                        len(json_data.get("records", [])))
        except OSError as e:
            failed_files.append({"file": os.path.basename(path), "error": str(e)})
            logger.error("[Export] JSON write failed: %s (%s)", path, e)

    # 2. CSV 长表
    csv_str = structured_data.get("csv", "")
    if csv_str:
        path = os.path.join(output_dir, f"data_long_{timestamp}.csv")
        try:
            with open(path, "w", encoding=csv_encoding) as f:
                f.write(csv_str)
            files.append(path)
            logger.info("[Export] CSV (long) written: %s", path)
        except OSError as e:
            failed_files.append({"file": os.path.basename(path), "error": str(e)})
            logger.error("[Export] CSV (long) write failed: %s (%s)", path, e)

    # 3. CSV 宽表 (Pivot)
    csv_wide = structured_data.get("csv_wide", "")
    if csv_wide:
        path = os.path.join(output_dir, f"data_wide_{timestamp}.csv")
        try:
            with open(path, "w", encoding=csv_encoding) as f:
                f.write(csv_wide)
            files.append(path)
            logger.info("[Export] CSV (wide) written: %s", path)
        except OSError as e:
            failed_files.append({"file": os.path.basename(path), "error": str(e)})
            logger.error("[Export] CSV (wide) write failed: %s (%s)", path, e)

    # 4. Quality Summary
    path = os.path.join(output_dir, f"quality_summary_{timestamp}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(quality_summary, f, ensure_ascii=False, indent=2, default=str)
        files.append(path)
    except OSError as e:
        failed_files.append({"file": os.path.basename(path), "error": str(e)})
        logger.error("[Export] quality_summary write failed: %s (%s)", path, e)

    # 5. Metadata
    path = os.path.join(output_dir, f"metadata_{timestamp}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)
        files.append(path)
    except OSError as e:
        failed_files.append({"file": os.path.basename(path), "error": str(e)})
        logger.error("[Export] metadata write failed: %s (%s)", path, e)

    # 6. Traceability (简化版，避免过大)
    trace_summary = {
        "data_lineage": traceability.get("data_lineage", {}),
        "trace_completeness": traceability.get("trace_completeness", {}),
        "modified_count": traceability.get("trace_completeness", {}).get("modified_count", 0),
        "decision_count": len(traceability.get("agent_decision_trail", [])),
    }
    path = os.path.join(output_dir, f"traceability_{timestamp}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace_summary, f, ensure_ascii=False, indent=2, default=str)
        files.append(path)
    except OSError as e:
        failed_files.append({"file": os.path.basename(path), "error": str(e)})
        logger.error("[Export] traceability write failed: %s (%s)", path, e)

    # 7. Export manifest
    manifest = {
        "exported_at": datetime.datetime.now().isoformat(),
        "output_dir": output_dir,
        "files": [os.path.basename(f) for f in files],
        # M11 fix: 逐文件降级 — 写失败的清单可审计, 不再静默丢弃
        "failed_files": failed_files,
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
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        files.append(path)
    except OSError as e:
        failed_files.append({"file": os.path.basename(path), "error": str(e)})
        logger.error("[Export] manifest write failed: %s (%s)", path, e)

    if failed_files:
        logger.warning("[Export] %d file(s) failed to write: %s",
                       len(failed_files), [f["file"] for f in failed_files])

    return files
