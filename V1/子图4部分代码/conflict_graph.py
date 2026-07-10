"""
conflict_graph.py — Conflict Resolution SubGraph (V1 Stub)

待后续重构为 Agent 模式。当前透传 State → Export。
"""

from __future__ import annotations
import datetime
from typing import Any
from langgraph.graph import StateGraph, END
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)

def _stub_node(state: QualityGraphState) -> dict[str, Any]:
    logger.info("[ConflictGraph] Stub: pass-through")
    return {"workflow_state": {"route_decision": "Export", "execution_status": "Success",
            "current_node": "conflict_stub",
            "workflow_history": [{"agent": "ConflictGraph", "stage": "Stub",
            "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
            "duration": 0.0, "reason": "Stub: not yet implemented"}]}}

def build_conflict_graph() -> StateGraph[QualityGraphState]:
    g = StateGraph(QualityGraphState)
    g.add_node("stub", _stub_node)
    g.set_entry_point("stub"); g.add_edge("stub", END)
    return g
