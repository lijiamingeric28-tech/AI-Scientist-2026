"""真实端到端 smoke 测试（network 标记，默认跳过）

验证：完整链路（澄清 → P1 性质标准化 → 检索 → 提取 → 聚合 → 质量）
连真实外部 API 跑通。这是测试体系唯一不 mock 的部分——
mock 短路路径保证 CI 可跑，smoke 保证真实集成不断裂。

运行：:

    python -m pytest tests/test_smoke_network.py -m network -v

前提：.env 配置了 DASHSCOPE_API_KEY（必需），ADS_API_TOKEN / UNPAYWALL_EMAIL
（论文检索），OPENAI_API_KEY（质量管线，可选——缺省时质量报告含错误但不失败）。

注意：真实链路耗时数分钟（SIMBAD + VizieR + ADS + LLM），
且依赖外部服务可用性——发布前手动运行。
"""

import importlib

import pytest

pytestmark = pytest.mark.network


@pytest.fixture
def mock_hr_interrupt(monkeypatch):
    """只 mock HITL 交互环节（interrupt → 'y' 确认），保留真实 LLM/API 调用。

    澄清子图的 final_confirm 等节点会 interrupt 等待用户输入；
    smoke 测试自动确认，其余全部走真实服务。
    """
    for mod_name in ("ask_entity", "ask_properties", "greeting_handler", "final_confirm"):
        mod = importlib.import_module(f"astroquery_ai.subgraph1.nodes.{mod_name}")
        monkeypatch.setattr(mod, "interrupt", lambda *a, **k: "y")


def test_smoke_m31_full_pipeline(mock_hr_interrupt):
    """M31 的距离：完整真实链路端到端"""
    from astroquery_ai.config import get_settings
    from astroquery_ai.main_graph import run_pipeline

    settings = get_settings()
    if not settings.dashscope_api_key:
        pytest.skip("DASHSCOPE_API_KEY 未配置，跳过真实 smoke 测试")

    state = run_pipeline(user_query="M31 的距离", query_id="smoke-m31")

    # 澄清完成（HITL 自动确认）
    assert state.get("clarification_status") == "confirmed", \
        f"澄清失败: {state.get('error_log', [])[:3]}"

    # 永远输出合法 final_output（"永远输出 JSON" 约定）
    final = state.get("final_output") or {}
    assert "schema_version" in final, "final_output 缺 schema_version"
    assert "sources" in final and "records" in final

    # 真实链路必须有数据（M31 是 VizieR 必命中天体）
    errors = state.get("error_log", []) or []
    assert len(final.get("records", [])) > 0, f"无记录, errors={errors[:3]}"

    # Phase 4a 断链修复：quality 结果并入 final_output
    assert "quality_report" in final, "final_output 缺 quality_report（断链回归）"

    # 打印摘要便于人工核对
    print(f"\n[SMOKE] sources={len(final.get('sources', []))} "
          f"records={len(final.get('records', []))} "
          f"errors={len(errors)}")


def test_smoke_simbad_p1(mock_hr_interrupt):
    """P1 性质标准化独立验证：SIMBAD 解析 + RAG 加载 + LLM 选性质"""
    from astroquery_ai.config import get_settings
    from astroquery_ai.property_standardization import (
        property_standardization_node,
        query_simbad,
    )

    settings = get_settings()
    if not settings.dashscope_api_key:
        pytest.skip("DASHSCOPE_API_KEY 未配置，跳过真实 smoke 测试")

    simbad, err = query_simbad("M31")
    assert simbad is not None, f"SIMBAD 查询失败: {err}"
    assert simbad.get("main_id"), "SIMBAD 未返回 main_id"

    state = property_standardization_node({
        "target_entity": "M31",
        "user_query": "M31 的距离",
        "requested_properties": ["distance"],
        "query_id": "smoke-p1",
        "simbad_info": simbad,
    })
    assert state.get("property_spec"), "P1 未产出 property_spec"
    print(f"\n[SMOKE-P1] main_id={simbad.get('main_id')} "
          f"otype={simbad.get('otype')} properties={len(state.get('property_spec', []))}")
