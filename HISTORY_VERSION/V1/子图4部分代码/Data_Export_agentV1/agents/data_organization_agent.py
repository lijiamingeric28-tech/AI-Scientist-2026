"""
data_organization_agent.py — Stage 1: DataOrganizationAgent

去除中间临时字段, 按 Target Schema 组织, 按 source 分组排序。
"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from tools.export.data_organizer import organize_data
from utils.logger import get_logger
logger = get_logger(__name__)


class DataOrganizationAgent:
    """Stage 1: 数据组织 — 过滤 + Schema 对齐 + 排序"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        data = state.get("data_state", {}).get("current_data", {})
        target_schema = state.get("context_state", {}).get("target_schema")

        organized, summary = organize_data(data, target_schema)

        elapsed = round(time.time() - t0, 3)
        logger.info("[DataOrganization] %d records, %d fields (%d standard + %d extra), %.2fs",
                    summary["total_records"], len(organized.get("field_index", {})),
                    len(summary["standard_fields"]), len(summary["extra_fields"]), elapsed)

        return {
            "report_state": {"export": {
                "organized_data": organized,
                "organization_summary": summary,
            }},
            "workflow_state": {
                "current_node": "data_organization",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "DataOrganizationAgent", "stage": "DataOrganization",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Organized {summary['total_records']} records ({len(summary['standard_fields'])} standard + {len(summary['extra_fields'])} extra fields)",
                }],
            },
        }
