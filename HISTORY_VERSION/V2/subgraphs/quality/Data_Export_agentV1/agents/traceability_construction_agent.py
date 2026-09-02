"""
traceability_construction_agent.py — Stage 4: TraceabilityConstructionAgent

构建完整数据溯源链: 数据世系 + 逐条记录溯源 + Agent 决策链。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.tools.export.traceability_builder import build_traceability
from subgraphs.quality.utils.logger import get_logger
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
        completeness = result["trace_completeness"]

        elapsed = round(time.time() - t0, 3)
        logger.info("[TraceabilityConstruction] %d records traced, %d modified, %d decisions, %.2fs",
                    completeness["records_with_trace"], completeness["modified_count"],
                    len(traceability.get("agent_decision_trail", [])), elapsed)

        return {
            "report_state": {"export": {
                # 不再写回organized_data，避免重复累加
                "traceability": traceability,
                "trace_completeness": completeness,
            }},
            "workflow_state": {
                "current_node": "traceability_construction",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "TraceabilityConstructionAgent", "stage": "Traceability",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Traced {completeness['records_with_trace']} records ({completeness['modified_count']} modified, {completeness['deleted_count']} deleted)",
                }],
            },
        }
