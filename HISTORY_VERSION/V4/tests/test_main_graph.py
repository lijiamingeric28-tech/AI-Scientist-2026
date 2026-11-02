"""主图 characterization 测试 — 全 mock 离线

锁定：图装配 + 路由决策 + quality 空数据短路 + 端到端降级路径。
"""

import pytest

from astroquery_ai.main_graph import create_main_graph, run_pipeline
from astroquery_ai.main_graph import route_after_clarification, route_after_retrieval
from astroquery_ai.quality_adapter import quality_node


def test_main_graph_compiles():
    """主图可编译，节点集合完整"""
    graph = create_main_graph()
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {
        "clarification",
        "property_std",
        "retrieval",
        "extraction",
        "skip_extraction",
        "aggregation",
        "quality",
        "quality_finalize",
    }


# ══════════════════════════════════════════════════════════════
# 路由纯函数
# ══════════════════════════════════════════════════════════════

def test_route_after_clarification_cancelled():
    assert route_after_clarification({
        "clarification_status": "cancelled",
        "query_type": "astronomical",
        "target_entity": "M31",
    }) == "aggregation"


def test_route_after_clarification_greeting():
    assert route_after_clarification({
        "clarification_status": "confirmed",
        "query_type": "greeting",
        "target_entity": None,
    }) == "aggregation"


def test_route_after_clarification_normal():
    assert route_after_clarification({
        "clarification_status": "confirmed",
        "query_type": "astronomical",
        "target_entity": "M31",
    }) == "property_std"


def test_route_after_retrieval_with_pdf():
    assert route_after_retrieval({
        "paper_results": {"download_paths": [{"local_path": "/tmp/a.pdf"}]},
        "extra_pdfs": [],
    }) == "extraction"


def test_route_after_retrieval_with_manual_pdf():
    # 自动下载零 + 手动上传有 → 仍进提取（设计文档有意偏离点 2）
    assert route_after_retrieval({
        "paper_results": {"download_paths": []},
        "extra_pdfs": ["C:/tmp/manual.pdf"],
    }) == "extraction"


def test_route_after_retrieval_skip():
    assert route_after_retrieval({
        "paper_results": {"download_paths": []},
        "extra_pdfs": [],
    }) == "skip_extraction"


# ══════════════════════════════════════════════════════════════
# quality 空数据短路
# ══════════════════════════════════════════════════════════════

def test_quality_node_skips_empty_output():
    """final_output 无记录 → 跳过质量管线，不触发 quality_pipeline import"""
    result = quality_node({
        "final_output": {"records": [], "sources": []},
        "property_spec": [],
    })
    assert result["quality_report"] == {"skipped": True, "reason": "empty_final_output"}


# ══════════════════════════════════════════════════════════════
# 端到端降级路径
# ══════════════════════════════════════════════════════════════

def test_run_pipeline_hitl_loop(mock_sg1_llm, mock_ads_empty, no_network, monkeypatch):
    """
    Phase 4c: 真实 interrupt 流程 —— final_confirm 节点真 interrupt，
    run_pipeline 的 HITL 循环渲染 payload → input() 读答案 → resume 恢复。
    验证 interrupt → resume 全链路（不 mock interrupt，只 mock LLM/网络/input）。
    """
    import builtins

    def _boom(state):
        raise RuntimeError("SIMBAD 查询失败（测试注入）")

    monkeypatch.setattr("astroquery_ai.adapters.property_standardization_node", _boom)
    # CLI 交互：_prompt_for_interrupt 用 input() 读答案
    monkeypatch.setattr(builtins, "input", lambda *a: "y")

    state = run_pipeline(user_query="M31 的距离", query_id="test-e2e-hitl")

    # interrupt resume 后澄清完成
    assert state["clarification_status"] == "confirmed"
    assert state["target_entity"] == "M31"
    # 降级路径仍输出合法 final_output
    assert "quality_report" in state["final_output"]
    assert no_network == []


def test_run_pipeline_degraded_e2e(mock_sg1_llm, mock_stdin, mock_ads_empty, no_network, monkeypatch):
    """
    P1 性质标准化抛异常 → 降级链路全流程：
    澄清(confirmed) → P1(failed) → 检索(空) → 跳过提取 → 聚合(空 JSON) → quality(跳过)
    断言：永远输出合法 final_output + error_log 有记录 + 零网络。
    """
    def _boom(state):
        raise RuntimeError("SIMBAD 查询失败（测试注入）")

    monkeypatch.setattr("astroquery_ai.adapters.property_standardization_node", _boom)

    state = run_pipeline(user_query="M31 的距离", query_id="test-e2e-degraded")

    # 澄清正常完成
    assert state["clarification_status"] == "confirmed"
    assert state["target_entity"] == "M31"

    # 降级：P1 失败已记录
    errors = state.get("error_log") or []
    assert len(errors) >= 1
    assert any(e.get("node") == "property_standardization" for e in errors)

    # 永远输出合法 final_output（"永远输出 JSON" 约定）
    final_output = state["final_output"]
    assert isinstance(final_output, dict)
    assert "schema_version" in final_output
    assert "records" in final_output
    assert "sources" in final_output
    # Phase 4: quality 结果并入 final_output（断链修复）
    assert "quality_report" in final_output
    assert final_output["quality_report"].get("skipped") is True

    # 零网络（除 P1 外全链路 mock/短路）
    assert no_network == []
