"""子图2（并行检索）characterization 测试 — 全 mock 离线

锁定：图装配 + 空输入短路路径（零网络）+ ADS 限额降级路径。
"""

import pytest

from astroquery_ai.subgraph2.graph import create_retrieval_subgraph

SG2_INPUT = {
    "query_id": "test-2",
    "target_entity": "M31",
    "simbad_aliases": [],
    "simbad_info": {},
    "property_spec": [],
    "requested_properties": [],
}


def test_subgraph2_compiles():
    """图可编译，节点集合完整"""
    graph = create_retrieval_subgraph()
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {
        "database_query",
        "build_ads_query",
        "ads_search",
        "unpaywall_query",
        "pdf_download",
        "supplementary_query",
        "result_aggregator",
    }


def test_empty_input_zero_network(mock_ads_empty, no_network):
    """空别名 + 空 PropertySpec → 全链路短路，零网络请求"""
    graph = create_retrieval_subgraph()
    result = graph.invoke(dict(SG2_INPUT))

    # 数据库：无别名 → 零查询
    assert result["database_query_status"] == "completed"
    assert result["database_sources"] == []
    assert result["database_records"] == []
    assert result["successful_catalogs"] == []
    # 论文：无 PropertySpec → 跳过 LLM 查询构造；ADS 返回零论文
    assert result["ads_search_status"] == "completed"
    assert result["ads_total_found"] == 0
    assert result["ads_papers_metadata"] == []
    # 下游全部短路（Phase 2 统一键名 download_paths）
    assert result["download_paths"] == []
    assert result["paper_sources"] == []
    assert result["supplementary_sources"] == []
    # 汇总结构
    assert result["retrieval_timestamp"]
    # 零网络
    assert no_network == []


def test_retrieval_node_assembles_download_paths(monkeypatch):
    """适配层 retrieval_node 从统一键 download_paths 组装 paper_results（Phase 2 回归盲区）"""
    from astroquery_ai.adapters import retrieval_node

    fake_state = {
        "query_id": "test-2",
        "target_entity": "M31",
        "simbad_aliases": [],
        "simbad_info": {},
        "property_spec": [],
        "requested_properties": [],
        "download_paths": [{"bibcode": "A", "local_path": "/tmp/a.pdf"}],
        "ads_total_found": 1,
        "paper_sources": [],
        "retrieval_timestamp": "2026-01-01T00:00:00Z",
    }

    class _FakeGraph:
        def invoke(self, state, config=None):
            return fake_state

    monkeypatch.setattr("astroquery_ai.adapters.create_retrieval_subgraph",
                        lambda *a, **k: _FakeGraph())

    out = retrieval_node({
        "query_id": "test-2",
        "target_entity": "M31",
        "simbad_info": {},
        "property_spec": [],
        "requested_properties": [],
        "extra_pdfs": [],
    })

    assert out["paper_results"]["download_paths"] == [
        {"bibcode": "A", "local_path": "/tmp/a.pdf"}
    ]
    assert out["paper_results"]["downloaded_papers"] == 1


def test_ads_rate_limit_skipped(mock_ads_rate_limit, no_network):
    """ADS 429 → 标记 skipped + 记入 error_log，主流程继续"""
    graph = create_retrieval_subgraph()
    result = graph.invoke(dict(SG2_INPUT))

    assert result["ads_search_status"] == "skipped"
    assert result["ads_total_found"] == 0
    assert result["error_log"], "rate limit 应记入 error_log"
    # ads_search 的 429 分支写固定消息 "ADS API rate limit reached"
    assert any("rate limit" in e.get("error", "").lower() for e in result["error_log"])
    assert no_network == []
