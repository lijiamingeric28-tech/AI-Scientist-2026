"""
export_graph.py — Export SubGraph (V1.0)

架构: 一个 Stage = 一个 Agent
  START → DataOrganizationAgent → SchemaFormattingAgent
        → MetadataGenerationAgent → TraceabilityConstructionAgent
        → OutputValidationAgent → StructuredExportGenerationAgent → END

Graph 职责: 仅编排, 不调用 Tool/Prompt/LLM/Rule。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from quality_state import QualityGraphState
from utils.logger import get_logger

logger = get_logger(__name__)

# ── 6 个 Agent ──
from Data_Export_agentV1.agents.data_organization_agent import DataOrganizationAgent
from Data_Export_agentV1.agents.schema_formatting_agent import SchemaFormattingAgent
from Data_Export_agentV1.agents.metadata_generation_agent import MetadataGenerationAgent
from Data_Export_agentV1.agents.traceability_construction_agent import TraceabilityConstructionAgent
from Data_Export_agentV1.agents.output_validation_agent import OutputValidationAgent
from Data_Export_agentV1.agents.export_generation_agent import StructuredExportGenerationAgent


# ── 实例化 ──
_organization = DataOrganizationAgent()
_formatting = SchemaFormattingAgent()
_metadata = MetadataGenerationAgent()
_traceability = TraceabilityConstructionAgent()
_validation = OutputValidationAgent()
_export_gen = StructuredExportGenerationAgent()


# ==========================================================
# Stage Nodes — 极简: 只调用 Agent.run()
# ==========================================================

def _data_organization_node(state: QualityGraphState) -> dict[str, Any]:
    return _organization.run(state)


def _schema_formatting_node(state: QualityGraphState) -> dict[str, Any]:
    return _formatting.run(state)


def _metadata_generation_node(state: QualityGraphState) -> dict[str, Any]:
    return _metadata.run(state)


def _traceability_node(state: QualityGraphState) -> dict[str, Any]:
    return _traceability.run(state)


def _output_validation_node(state: QualityGraphState) -> dict[str, Any]:
    return _validation.run(state)


def _export_generation_node(state: QualityGraphState) -> dict[str, Any]:
    return _export_gen.run(state)


# ==========================================================
# 子图出口状态透传 (V3.3: 供主图 Stage Gate 消费)
# ==========================================================

def _finalize(state: QualityGraphState) -> dict[str, Any]:
    """透传子图最终 execution_status (Retry/Failed 冒泡到主图 Gate)。"""
    status = state.get("workflow_state", {}).get("execution_status", "Success")
    return {"workflow_state": {"execution_status": status}}


# ==========================================================
# 构建 SubGraph
# ==========================================================

def build_export_graph() -> StateGraph[QualityGraphState]:
    graph: StateGraph[QualityGraphState] = StateGraph(QualityGraphState)

    graph.add_node("data_organization", _data_organization_node)
    graph.add_node("schema_formatting", _schema_formatting_node)
    graph.add_node("metadata_generation", _metadata_generation_node)
    graph.add_node("traceability_construction", _traceability_node)
    graph.add_node("output_validation", _output_validation_node)
    graph.add_node("export_generation", _export_generation_node)
    graph.add_node("finalize", _finalize)

    graph.set_entry_point("data_organization")

    # 线性流水线: 6 Stage → finalize → END
    graph.add_edge("data_organization", "schema_formatting")
    graph.add_edge("schema_formatting", "metadata_generation")
    graph.add_edge("metadata_generation", "traceability_construction")
    graph.add_edge("traceability_construction", "output_validation")

    # V3.2: 校验失败时仍进入 export_generation (构建 output_state),
    # 但由 export_generation 标记 quarantine (consumable=false)
    graph.add_edge("output_validation", "export_generation")
    # V3.5 fix: 单一终点边 — export_generation → finalize → END (删除重复边)
    graph.add_edge("export_generation", "finalize")
    graph.add_edge("finalize", END)

    logger.info("[Workflow] Export SubGraph built (6 Agents).")
    return graph
