"""
output_validation_agent.py — Stage 5: OutputValidationAgent

5 维输出校验: Schema / 数据完整性 / 格式 / 溯源 / 质量一致性。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.tools.export.output_validator import validate_output
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


class OutputValidationAgent:
    """Stage 5: 输出校验 — 5 维检查"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        export_state = state.get("report_state", {}).get("export", {})
        organized = export_state.get("organized_data", {})
        metadata = export_state.get("metadata", {})
        traceability = export_state.get("traceability", {})
        target_schema = state.get("context_state", {}).get("target_schema")

        result = validate_output(
            organized, metadata, traceability, target_schema,
            state.get("report_state", {}), state.get("workflow_state", {})
        )

        elapsed = round(time.time() - t0, 3)
        is_valid = result["is_valid"]
        status = "Success" if is_valid else "Failed"

        logger.info("[OutputValidation] Valid=%s (%s), %.2fs", is_valid, result["summary"], elapsed)

        return {
            "report_state": {"export": {
                # 不再写回organized_data，避免重复累加
                "validation": result,
            }},
            "workflow_state": {
                "current_node": "output_validation",
                "execution_status": status,
                "workflow_history": [{
                    "agent": "OutputValidationAgent", "stage": "Validation",
                    "status": status, "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": result["summary"],
                }],
            },
        }
