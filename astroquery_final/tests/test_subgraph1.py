"""子图1（意图澄清）characterization 测试 — 全 mock 离线

锁定：图装配 + 状态契约 + 天文/寒暄两条流程的最终状态。
"""

import pytest

from subgraphs.subgraph1.graph import create_intent_clarification_subgraph


def test_subgraph1_compiles():
    """图可编译，节点集合完整"""
    graph = create_intent_clarification_subgraph()
    # get_graph() 含 __start__/__end__ 伪节点，过滤
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {
        "initial_parse",
        "polite_reject",
        "greeting_handler",
        "ask_entity",
        "handle_failure",
        "ask_properties",
        "final_confirm",
    }


def test_astronomical_query_confirmed(mock_sg1_llm, mock_stdin):
    """天文查询完整流：M31 + distance → final_confirm('y') → confirmed"""
    graph = create_intent_clarification_subgraph()
    result = graph.invoke({
        "user_query": "M31 的距离",
        "query_id": "test-1",
    })

    assert result["query_type"] == "astronomical"
    assert result["target_entity"] == "M31"
    assert result["requested_properties"] == ["distance"]
    assert result["clarification_status"] == "confirmed"
    assert result["user_confirmed"] is True
    # 对话历史包含追问与确认（至少 2 条：assistant + user）
    assert len(result.get("chat_history", [])) >= 2


def test_greeting_then_astronomical(monkeypatch):
    """寒暄 → 引导输入 → 二次解析为天文查询 → confirmed"""
    import importlib

    def _mod(name):
        return importlib.import_module(f"subgraphs.subgraph1.nodes.{name}")

    init_mod = _mod("initial_parse")
    query_types = iter(["greeting", "astronomical"])
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: next(query_types))
    monkeypatch.setattr(
        init_mod,
        "extract_entity_and_properties",
        lambda user_input, chat_history: {
            "target_entity": "M31",
            "requested_properties": ["distance"],
        },
    )
    # greeting_handler 的 interrupt → 新查询；final_confirm 的 interrupt → 确认
    interrupt_values = iter(["M31 的距离", "y"])
    for mod_name in ("greeting_handler", "final_confirm"):
        monkeypatch.setattr(_mod(mod_name), "interrupt", lambda *a, **k: next(interrupt_values))

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({
        "user_query": "你好",
        "query_id": "test-2",
    })

    assert result["target_entity"] == "M31"
    assert result["clarification_status"] == "confirmed"


def test_invalid_query_polite_reject(monkeypatch):
    """无效查询 → polite_reject → END，不进入交互节点"""
    import importlib
    init_mod = importlib.import_module("subgraphs.subgraph1.nodes.initial_parse")
    monkeypatch.setattr(init_mod, "classify_query_type", lambda user_input: "invalid")

    graph = create_intent_clarification_subgraph()
    result = graph.invoke({
        "user_query": "asdfg!@#$",
        "query_id": "test-3",
    })

    assert result["query_type"] == "invalid"
    # polite_reject 后无 target_entity
    assert result.get("target_entity") is None
