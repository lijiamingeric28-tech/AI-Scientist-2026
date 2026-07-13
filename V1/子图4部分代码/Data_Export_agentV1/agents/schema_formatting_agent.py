"""
schema_formatting_agent.py — Stage 2: SchemaFormattingAgent

JSON/CSV/Wide-Table 多格式导出 + Schema 对齐格式化。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from tools.export.format_exporter import export_formats
from tools.export.schema_formatter import format_to_schema
from utils.logger import get_logger
logger = get_logger(__name__)


class SchemaFormattingAgent:
    """Stage 2: Schema 格式转换 — 多格式导出 + 对齐"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        export_state = state.get("report_state", {}).get("export", {})
        organized = export_state.get("organized_data", {})
        target_schema = state.get("context_state", {}).get("target_schema")

        if not organized:
            logger.warning("[SchemaFormatting] No organized data found")
            return {
                "workflow_state": {
                    "current_node": "schema_formatting",
                    "execution_status": "Success",
                },
            }

        # Tool 2: 多格式导出
        exported = export_formats(organized)

        # Tool 3: Schema 对齐
        formatted = format_to_schema(exported, target_schema)

        elapsed = round(time.time() - t0, 3)
        issues_count = len(formatted.get("format_issues", []))
        logger.info("[SchemaFormatting] %d rows, %d cols → json+csv+wide, %d issues, %.2fs",
                    exported["row_count"], exported["column_count"], issues_count, elapsed)

        return {
            "report_state": {"export": {
                "organized_data": organized,
                "organization_summary": export_state.get("organization_summary", {}),
                "formatted_data": formatted.get("structured_data", exported),
                "format_issues": formatted.get("format_issues", []),
            }},
            "workflow_state": {
                "current_node": "schema_formatting",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "SchemaFormattingAgent", "stage": "SchemaFormatting",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Exported {exported['row_count']} rows × {exported['column_count']} cols, {issues_count} format issues",
                }],
            },
        }
