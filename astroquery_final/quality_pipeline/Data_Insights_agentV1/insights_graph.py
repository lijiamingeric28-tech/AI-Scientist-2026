"""
insights_graph.py — DataInsights SubGraph (V3.4)

架构: 4 节点线性串联
  START → FieldInsightAgent → RelationshipAgent
        → RecommendationAgent → SynthesisAgent → END

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from ..quality_state import QualityGraphState
from ..utils.logger import get_logger

logger = get_logger(__name__)

from ..Data_Insights_agentV1.agents.field_insight_agent import FieldInsightAgent
from ..Data_Insights_agentV1.agents.relationship_agent import RelationshipAgent
from ..Data_Insights_agentV1.agents.recommendation_agent import RecommendationAgent
from ..Data_Insights_agentV1.agents.synthesis_agent import SynthesisAgent

_field = FieldInsightAgent()
_rel = RelationshipAgent()
_rec = RecommendationAgent()
_syn = SynthesisAgent()


def _field_node(state: QualityGraphState) -> dict[str, Any]:
    return _field.run(state)


def _rel_node(state: QualityGraphState) -> dict[str, Any]:
    return _rel.run(state)


def _rec_node(state: QualityGraphState) -> dict[str, Any]:
    return _rec.run(state)


def _syn_node(state: QualityGraphState) -> dict[str, Any]:
    return _syn.run(state)


def build_insights_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("field_insight", _field_node)
    graph.add_node("relationship", _rel_node)
    graph.add_node("recommendation", _rec_node)
    graph.add_node("synthesis", _syn_node)

    graph.set_entry_point("field_insight")
    graph.add_edge("field_insight", "relationship")
    graph.add_edge("relationship", "recommendation")
    graph.add_edge("recommendation", "synthesis")
    graph.add_edge("synthesis", END)

    logger.info("[Workflow] DataInsights SubGraph built (4 Agents, V3.4).")
    return graph
