"""全链路成功路径验证 — 零 LLM 零网络（重构后回归守护）

覆盖 test_main_graph.py 未覆盖的【成功路径】：
  用户输入 → 子图1(澄清) → P1(性质标准化) → 子图2(检索: 1 条数据库记录)
  → skip_extraction(无 PDF) → 聚合(final_output) → quality_pipeline 真实执行
  → quality_finalize(quality_report 并入 final_output)

LLM 全部 mock：子图1 分类/提取、P1 选性质、quality_pipeline get_llm。
网络全部 mock：SIMBAD(P1)、VizieR(database_query 节点)、ADS(mock_ads_empty)。
断言零网络请求。
"""

import json
import unittest.mock as _mock

import pytest

from astroquery_ai.main_graph import run_pipeline

# ══════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_p1(monkeypatch):
    """Mock P1：SIMBAD 查询 + LLM 选性质 → 固定 G 星系 + distance"""
    import astroquery_ai.property_standardization as ps

    def _fake_simbad(target_name):
        return ({
            "main_id": "M31",
            "otype": "G",
            "otypes": "G|SBG",
            "ra": "00:42:44.3",
            "dec": "+41:16:09",
            "sp_type": "",
            "ids": "M31|NGC 224|Andromeda Galaxy",
            "ALIASES": ["M31", "NGC 224", "Andromeda Galaxy"],
        }, None)

    def _fake_select(rag, target_name, user_request):
        return ([{"property_id": "distance", "reason": "test"}], None)

    monkeypatch.setattr(ps, "query_simbad", _fake_simbad)
    monkeypatch.setattr(ps, "select_properties_with_llm", _fake_select)


@pytest.fixture
def mock_database_query(monkeypatch):
    """Mock 子图2 database_query 节点 → 返回 1 条真实结构的数据库记录

    graph.py 用 `from .nodes import database_query` 绑定到 graph 模块命名空间，
    必须 patch graph 模块属性（patch nodes 包属性不生效）。
    """
    import importlib
    sg2_graph = importlib.import_module("subgraphs.subgraph2.graph")

    def _fake_database_query(state):
        return {
            "database_sources": [{
                "source_id": "SRC_DB_TEST",
                "source_type": "database",
                "title": "Test Catalog (mock)",
                "vizier_table_id": "II/125/iraspsc",
                "description": "mock",
            }],
            "database_records": [{
                "record_id": "SRC_DB_TEST_1",
                "source_id": "SRC_DB_TEST",
                "entity_type": "G",
                "entity_name": "M31",
                "field_name": "distance",
                "field_value": 0.77,
                "field_unit": "Mpc",
                "extraction_method": "database_query",
                "provenance": {
                    "db_table": "II/125/iraspsc",
                    "key_column": "IRAS",
                    "key_value": "00398+4039",
                    "raw_column": "Dist",
                },
            }],
            "successful_catalogs": ["II/125/iraspsc"],
            "failed_catalogs": [],
        }

    monkeypatch.setattr(sg2_graph, "database_query", _fake_database_query)


@pytest.fixture
def mock_ads_query_builder(monkeypatch):
    """Mock 子图2 build_ads_query（LLM 构造查询串）→ 固定字符串（patch graph 模块）"""
    import importlib
    sg2_graph = importlib.import_module("subgraphs.subgraph2.graph")

    def _fake_build(state):
        return {"ads_query_string": "M31 AND distance"}

    monkeypatch.setattr(sg2_graph, "build_ads_query", _fake_build)


@pytest.fixture
def mock_quality_llm(monkeypatch):
    """Mock quality_pipeline 的 LLM 工厂 → 固定 JSON（解析失败自动 fallback）"""
    import quality_pipeline.utils.llm as qllm

    def _fake_llm(*args, **kwargs):
        m = _mock.MagicMock()
        m.content = json.dumps({
            "tools": [], "reasoning": "mock-plan",
            "insights": [], "relationships": [],
            "overall_grade": "good", "suitable_use_cases": [],
            "limitations": [], "recommended_caveats": [],
            "overall_narrative": "mock narrative",
        })
        return m

    monkeypatch.setattr(qllm, "get_llm", _fake_llm)


# ══════════════════════════════════════════════════════════════
# 对抗性 LLM 响应（真实 LLM 格式漂移模拟）
# ══════════════════════════════════════════════════════════════

_VALID_JSON = json.dumps({
    "tools": [], "reasoning": "mock-plan",
    "insights": [], "relationships": [],
    "overall_grade": "good", "suitable_use_cases": [],
    "limitations": [], "recommended_caveats": [],
    "overall_narrative": "mock narrative",
})

# 真实 LLM 常见格式漂移：
_ADV_FENCE = '```json\n{"tools": [], "reasoning": "mock"}\n```'        # markdown 围栏包裹
_ADV_INVALID = "{tools: [], reasoning: mock}"                          # 非法 JSON（key 无引号）
_ADV_EMPTY = ""                                                        # 空返回
_ADV_TEXT = "抱歉，我无法回答这个问题。"                                 # 纯文本（无 JSON）
_ADV_TRUNCATED = '{"tools": [], "reasoning": "mock"'                    # 截断 JSON

_ADV_MODES = [
    ("fence", [_ADV_FENCE]),
    ("invalid_json", [_ADV_INVALID]),
    ("empty", [_ADV_EMPTY]),
    ("plain_text", [_ADV_TEXT]),
    ("truncated", [_ADV_TRUNCATED]),
    ("mixed_rotating", [_ADV_FENCE, _ADV_INVALID, _ADV_EMPTY, _ADV_TEXT, _ADV_TRUNCATED, _VALID_JSON]),
]


def _make_quality_llm(sequence):
    """按序返回响应；耗尽后循环最后一个（mixed 模式模拟真实漂移）"""
    state = {"i": 0}

    def fake(*args, **kwargs):
        m = _mock.MagicMock()
        m.content = sequence[min(state["i"], len(sequence) - 1)]
        state["i"] += 1
        return m

    return fake


@pytest.mark.parametrize("mode,sequence", _ADV_MODES)
def test_quality_llm_adversarial(
    mode, sequence,
    mock_sg1_llm, mock_stdin, mock_p1,
    mock_database_query, mock_ads_query_builder, mock_ads_empty,
    no_network, monkeypatch,
):
    """
    对抗性验证：LLM 返回 markdown 围栏 / 非法 JSON / 空 / 纯文本 / 截断 / 混合漂移
    时，解析链（正则提取 → json.loads → fallback）必须兜住，链路不炸。
    这正是"无 LLM 测试 → 真实场景"的主要鸿沟。
    """
    import builtins
    import quality_pipeline.utils.llm as qllm
    monkeypatch.setattr(builtins, "input", lambda *a: "y")
    monkeypatch.setattr(qllm, "get_llm", _make_quality_llm(sequence))

    state = run_pipeline(user_query="M31 的距离", query_id=f"test-adv-{mode}")

    # ── 主图回路仍完整 ──
    final_output = state["final_output"]
    assert final_output["schema_version"] == "2.0.0"
    assert len(final_output["records"]) == 1

    # ── 质量管线执行完成（LLM 全 fallback 或解析成功，均不跳过）──
    qr = final_output.get("quality_report") or {}
    assert qr.get("skipped") is not True, \
        f"[{mode}] 质量管线不应跳过: {qr.get('reason')}"
    output_state = qr.get("output_state") or {}
    structured = output_state.get("structured_data") or {}
    assert structured.get("row_count", 0) >= 1, f"[{mode}] 应产出结构化数据"

    # ── 零网络 ──
    assert no_network == []


# ══════════════════════════════════════════════════════════════
# 全链路测试
# ══════════════════════════════════════════════════════════════


def test_full_loop_success(
    mock_sg1_llm, mock_stdin, mock_p1,
    mock_database_query, mock_ads_query_builder, mock_ads_empty,
    mock_quality_llm, no_network, monkeypatch,
):
    """
    成功路径全链路：澄清 → P1 → 检索(1 条) → 跳过提取 → 聚合 → quality 全流程。
    验证重构后主图回路 + quality_pipeline 接缝 + quality_finalize 断链修复。
    """
    import builtins
    monkeypatch.setattr(builtins, "input", lambda *a: "y")

    state = run_pipeline(user_query="M31 的距离", query_id="test-full-loop")

    # ── 澄清完成 ──
    assert state["clarification_status"] == "confirmed"
    assert state["target_entity"] == "M31"

    # ── P1 产出 PropertySpec（系统中枢）──
    assert state.get("property_spec"), "P1 应产出 property_spec"
    assert state["property_spec"][0]["property_id"] == "distance"

    # ── 检索产出 1 条数据库记录 ──
    db = state.get("database_results") or {}
    assert len(db.get("records", [])) == 1
    assert db["records"][0]["field_name"] == "distance"

    # ── 无 PDF → skip_extraction ──
    assert state.get("paper_records", []) == []

    # ── 聚合：final_output 含三路契约 ──
    final_output = state["final_output"]
    assert final_output["schema_version"] == "2.0.0"
    assert len(final_output["records"]) == 1
    assert len(final_output["sources"]) == 1
    assert final_output["research_domain"] == "astrophysics"
    assert "query_metadata" in final_output
    assert "simbad_info" in final_output

    # ── quality_pipeline 真实执行（非 skipped）──
    qr = final_output.get("quality_report") or {}
    assert qr.get("skipped") is not True, f"质量管线不应跳过: {qr}"

    # ── Export → Insights 链：结构化数据产出 ──
    output_state = qr.get("output_state") or {}
    structured = output_state.get("structured_data") or {}
    assert structured, "质量管线应产出 structured_data"
    assert structured.get("row_count", 0) >= 1, "结构化数据应含记录"

    # ── 零网络 ──
    assert no_network == []
