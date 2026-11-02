"""
traceability_construction_agent.py — Stage 4: TraceabilityConstructionAgent

构建完整数据溯源链: 数据世系 + 逐条记录溯源 + Agent 决策链。
"""
from __future__ import annotations
import datetime
import time
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.tools.export.traceability_builder import build_traceability
from quality_pipeline.utils.logger import get_logger
logger = get_logger(__name__)


class TraceabilityConstructionAgent:
    """Stage 4: 溯源信息构建 — 4 维溯源链"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        export_state = state.get("report_state", {}).get("export", {})
        ds = state.get("data_state", {})
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        input_data = ds.get("input_data", {})
        current_data = ds.get("current_data", {})
        data_trace = ds.get("data_trace", [])

        result = build_traceability(
            input_data, current_data, data_trace, rs, wf
        )
        traceability = result["traceability"]
        # V3.1 fix: trace_completeness 已内嵌于 traceability dict, 不再冗余写入

        elapsed = round(time.time() - t0, 3)
        tc = traceability.get("trace_completeness", {})
        logger.info("[TraceabilityConstruction] %d records traced, %d modified, %d decisions, %.2fs",
                    tc.get("records_with_trace", 0), tc.get("modified_count", 0),
                    len(traceability.get("agent_decision_trail", [])), elapsed)

        return {
            "report_state": {"export": {
                "formatted_data": export_state.get("formatted_data", {}),
                "organized_data": export_state.get("organized_data", {}),
                "organization_summary": export_state.get("organization_summary", {}),
                "format_issues": export_state.get("format_issues", []),
                "metadata": export_state.get("metadata", {}),
                "traceability": traceability,
            }},
            "workflow_state": {
                "current_node": "traceability_construction",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "TraceabilityConstructionAgent", "stage": "Traceability",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Traced {tc.get('records_with_trace', 0)} records ({tc.get('modified_count', 0)} modified, {tc.get('deleted_count', 0)} deleted)",
                }],
            },
        }
