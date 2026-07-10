"""
export_graph.py — Structured Export SubGraph (V1 Stub)

待后续重构为 Agent 模式。当前透传 State。
"""

from __future__ import annotations
import datetime
from typing import Any
from langgraph.graph import StateGraph, END
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)

def _stub_node(state: QualityGraphState) -> dict[str, Any]:
    logger.info("[ExportGraph] Stub: pass-through")
    return {"output_state": {"structured_data": {"csv": "", "csv_wide": "", "json": "",
            "row_count": 0, "column_count": 0}},
            "workflow_state": {"execution_status": "Success", "current_node": "export_stub",
            "workflow_history": [{"agent": "ExportGraph", "stage": "Stub",
            "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
            "duration": 0.0, "reason": "Stub: not yet implemented"}]}}

def build_export_graph() -> StateGraph[QualityGraphState]:
    g = StateGraph(QualityGraphState)
    g.add_node("stub", _stub_node)
    g.set_entry_point("stub"); g.add_edge("stub", END)
    return g
