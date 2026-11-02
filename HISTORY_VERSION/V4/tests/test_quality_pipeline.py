"""quality_pipeline characterization 测试 — 全 mock 离线

锁定：make_initial_state 契约 + 主图编译（不跑真实 LLM 流程）。
"""

import pytest

from quality_pipeline.quality_state import make_initial_state
from quality_pipeline.graph import build_quality_graph

# 最小 grounded_data（对应 final_output 的结构：sources + records）
MINIMAL_GROUNDED_DATA = {
    "schema_version": "2.0.0",
    "research_domain": "astrophysics",
    "sources": [
        {"source_id": "vizier:1", "source_name": "Mock Catalog"},
    ],
    "records": [
        {
            "record_id": "rec-1",
            "source_id": "vizier:1",
            "entity_name": "M31",
            "entity_type": "Gal",
            "field_name": "distance",
            "field_value": "0.78",
            "unit": "Mpc",
        }
    ],
}


def test_make_initial_state_contract():
    """make_initial_state 产出五组嵌套 state 契约"""
    state = make_initial_state(dict(MINIMAL_GROUNDED_DATA))

    # 五组顶层键
    assert set(state.keys()) == {
        "context_state",
        "data_state",
        "report_state",
        "workflow_state",
        "output_state",
    }

    # context_state：research_domain 透传
    assert state["context_state"]["research_domain"] == "astrophysics"
    assert "target_schema" in state["context_state"]
    assert "standard_units" in state["context_state"]

    # data_state：grounded_data 深拷贝进入 input_data / current_data
    assert state["data_state"]["input_data"]["records"][0]["field_name"] == "distance"
    assert state["data_state"]["current_data"]["records"][0]["field_name"] == "distance"
    assert state["data_state"]["data_trace"] == []
    # entity_index 从 records 构建
    assert "Gal:M31" in state["data_state"]["entity_index"]

    # workflow_state：初始阶段 + 队列结构
    wf = state["workflow_state"]
    assert wf["current_node"] == "assessment"
    assert wf["phase"] == "assessment"
    assert set(wf["pending_sources"].keys()) == {
        "Normalization", "Conflict", "Export", "HumanReview",
    }
    assert wf["workflow_history"] == []

    # report_state / output_state 空壳（OutputState 无 "output" 键）
    assert state["report_state"]["quality"] is None
    assert "structured_data" in state["output_state"]
    assert "schema_version" in state["output_state"]


def test_make_initial_state_empty_data():
    """空 grounded_data 也能构建合法 state（不抛异常）"""
    state = make_initial_state({})
    assert state["data_state"]["input_data"] == {}
    assert state["data_state"]["entity_index"] == {}


def test_quality_graph_compiles():
    """主图可编译，节点集合完整（模块级 Agent 实例化不触发网络）"""
    graph = build_quality_graph().compile()
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {
        "assessment_graph",
        "normalization_graph",
        "conflict_graph",
        "export_graph",
        "insights_graph",
        "loop_controller",
        "human_review",
        "dispatch",
        "pre_normalization",
        "gate_assessment",
        "gate_normalization",
        "gate_conflict",
    }
