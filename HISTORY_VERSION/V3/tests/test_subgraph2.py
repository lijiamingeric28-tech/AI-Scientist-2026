"""子图2（并行检索）characterization 测试 — 全 mock 离线

锁定：图装配 + 空输入短路路径（零网络）+ ADS 限额降级路径。
"""

import pytest

# 先导入 astroquery_ai 完成 adapters → subgraphs.* 导入链，
# 否则直接 import subgraphs.subgraph2.graph 会与 astroquery_ai/__init__ 循环导入。
import astroquery_ai  # noqa: F401

from subgraphs.subgraph2.graph import create_retrieval_subgraph

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

    monkeypatch.setattr("subgraphs.subgraph2.graph.create_retrieval_subgraph",
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


# ══════════════════════════════════════════════════════════════
# R2-1: ADS PUB_PDF 兜底带 Authorization 头（否则必 401）
# ══════════════════════════════════════════════════════════════

class _FakeSettings:
    """模拟统一 Settings（astroquery_ai.config），字段与 Config.api 读取一致"""

    def __init__(self, ads_api_token: str = ""):
        self.ads_api_token = ads_api_token
        self.unpaywall_email = ""


def test_ads_pub_pdf_url_includes_bearer_header(monkeypatch):
    """有 token → link_gateway PUB_PDF 请求带 Authorization: Bearer {token}"""
    from subgraphs.subgraph2.nodes.pdf_download import build_ordered_urls

    monkeypatch.setattr(
        "subgraphs.subgraph2.config._settings",
        _FakeSettings(ads_api_token="FAKE_TOKEN"),
    )

    paper = {
        "bibcode": "2014MNRAS.427.1463Z",
        "doi": "10.1093/mnras/stt138",
        "esources": ["PUB_PDF"],
    }
    ordered = build_ordered_urls(paper, [])

    ads_entry = [u for u in ordered if u["source"] == "ads_pub_pdf"]
    assert len(ads_entry) == 1
    assert ads_entry[0]["headers"] == {"Authorization": "Bearer FAKE_TOKEN"}


def test_ads_pub_pdf_url_without_token_no_header(monkeypatch):
    """无 token → 保持原行为（不带 Authorization 头），仅告警"""
    from subgraphs.subgraph2.nodes.pdf_download import build_ordered_urls

    monkeypatch.setattr("subgraphs.subgraph2.config._settings", _FakeSettings())

    paper = {
        "bibcode": "2014MNRAS.427.1463Z",
        "doi": "10.1093/mnras/stt138",
        "esources": ["PUB_PDF"],
    }
    ordered = build_ordered_urls(paper, [])

    ads_entry = [u for u in ordered if u["source"] == "ads_pub_pdf"]
    assert len(ads_entry) == 1
    assert "headers" not in ads_entry[0]


def test_download_from_url_merges_auth_headers(monkeypatch, tmp_path):
    """download_from_url 把附加 headers 合并进默认 UA 请求头"""
    import importlib
    pdf_mod = importlib.import_module("subgraphs.subgraph2.nodes.pdf_download")

    captured = {}

    class _Resp:
        status_code = 200
        headers = {"content-length": "100"}

        def iter_content(self, chunk_size=8192):
            yield b"%PDF-1.4 fake pdf"

    def fake_get(url, headers=None, timeout=0, stream=False):
        captured["url"] = url
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(pdf_mod.requests, "get", fake_get)

    target = tmp_path / "paper.pdf"
    res = pdf_mod.download_from_url(
        "https://api.adsabs.harvard.edu/v1/link_gateway/X/PUB_PDF",
        str(target),
        headers={"Authorization": "Bearer TOKEN"},
    )

    assert res["success"] is True
    assert captured["headers"]["Authorization"] == "Bearer TOKEN"
    assert captured["headers"]["User-Agent"], "默认 UA 必须保留"


# ══════════════════════════════════════════════════════════════
# R2-2: retrieval_priority 用真实 ADS score（被引量作次级）
# ══════════════════════════════════════════════════════════════

class _PaperWithScore:
    bibcode = "2014MNRAS.427.1463Z"
    doi = ["10.1093/mnras/stt138"]
    title = ["Test Paper"]
    author = ["Author A"]
    year = 2014
    pub = "MNRAS"
    abstract = "abstract"
    keyword = ["galaxies"]
    citation_count = 500
    identifier = []
    esources = []
    score = 0.8


class _PaperNoScore:
    bibcode = "2014MNRAS.427.1463Z"
    doi = ["10.1093/mnras/stt138"]
    title = ["Test Paper"]
    author = ["Author A"]
    year = 2014
    pub = "MNRAS"
    abstract = "abstract"
    keyword = ["galaxies"]
    citation_count = 120
    identifier = []
    esources = []


def test_extract_paper_metadata_uses_real_score():
    """paper.score 存在 → 用真实 score，被引量仅记录"""
    from subgraphs.subgraph2.utils.paper_utils import extract_paper_metadata

    meta = extract_paper_metadata(_PaperWithScore(), 1, '"M31"')

    assert meta["score"] == 0.8
    assert meta["score_source"] == "ads"
    assert meta["citation_count"] == 500


def test_extract_paper_metadata_score_fallback_to_citations():
    """无 score 字段 → 回退被引量（历史行为），score_source 标记区分"""
    from subgraphs.subgraph2.utils.paper_utils import extract_paper_metadata

    meta = extract_paper_metadata(_PaperNoScore(), 1, '"M31"')

    assert meta["score"] == 120
    assert meta["score_source"] == "citation_fallback"


def test_ads_search_requests_score_and_normalizes_batch(monkeypatch):
    """fl 含 'score'；真实 score 按批内最大值归一化后重算 retrieval_priority"""
    import importlib
    ads_mod = importlib.import_module("subgraphs.subgraph2.nodes.ads_search")

    captured = {}

    class _SearchQuery:
        def __init__(self, *args, **kwargs):
            captured["fl"] = kwargs.get("fl", [])

        def __iter__(self):
            return iter([_PaperWithScore()])

    monkeypatch.setattr(ads_mod.ads, "SearchQuery", _SearchQuery)

    out = ads_mod.ads_search({
        "query_id": "test-score",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
        "ads_query_string": '"M31"',
    })

    assert "score" in captured["fl"]
    meta = out["ads_papers_metadata"][0]
    assert meta["score_source"] == "ads"
    assert meta["score"] == 0.8
    # 批内单篇 max_score=0.8 → normalized_score=1.0
    # priority = 0.5*1.0 + 0.3*min(500/1000,1) + 0.2*(1/(1+0.05*12)) = 0.775
    assert abs(meta["retrieval_priority"] - 0.775) < 1e-6


# ══════════════════════════════════════════════════════════════
# R2-3: PDF 并发 — 仅 arXiv 直链任务受 arxiv_max_workers 限制
# ══════════════════════════════════════════════════════════════

def test_pdf_download_workers_not_capped_to_arxiv_limit(monkeypatch, tmp_path):
    """ThreadPoolExecutor 用 max_workers=5；arXiv 限流信号量为 arxiv_max_workers=3"""
    import importlib
    import threading as _threading
    import concurrent.futures as _cf
    pdf_mod = importlib.import_module("subgraphs.subgraph2.nodes.pdf_download")

    captured = {}
    real_exec = _cf.ThreadPoolExecutor
    real_sem = _threading.Semaphore  # 先捕获真实引用，patch 后不能再用属性访问

    def _fake_exec(*args, **kwargs):
        captured["max_workers"] = kwargs.get("max_workers")
        return real_exec(*args, **kwargs)

    def _fake_sem(*args, **kwargs):
        # 只记录第一个值：pdf_download 先创建 arxiv 信号量(3)，
        # 之后线程池等机制可能再建 Semaphore，会覆盖记录。
        if "sem_value" not in captured:
            captured["sem_value"] = args[0] if args else kwargs.get("value", 1)
        return real_sem(*args, **kwargs)

    def _fake_download(paper, urls, save_dir, timeout=60, max_size_mb=50):
        return {"success": True, "local_path": f"{save_dir}/x.pdf",
                "file_size": 1024, "source": "mock", "error": None}

    monkeypatch.setattr(pdf_mod, "ThreadPoolExecutor", _fake_exec)
    monkeypatch.setattr(pdf_mod.threading, "Semaphore", _fake_sem)
    monkeypatch.setattr(pdf_mod, "download_with_waterfall_strategy", _fake_download)
    monkeypatch.setattr(pdf_mod.time, "sleep", lambda *a: None)
    import subgraphs.subgraph2.config as sg2_config
    monkeypatch.setitem(sg2_config._OUTPUT, "papers_dir", str(tmp_path))

    papers = [{
        "bibcode": f"2014MNRAS.427.1{b}Z",
        "doi": f"10.1093/mnras/10.1{b}",
        "title": "T", "authors": ["a"], "year": 2014, "journal": "MNRAS",
        "abstract": "", "keywords": [], "retrieval_priority": 0.5,
        "search_query": "q", "search_rank": i,
        "arxiv_id": "2301.12345" if i == 0 else None,
    } for i, b in enumerate("23")]

    out = pdf_mod.pdf_download({
        "query_id": "test-concurrency",
        "ads_papers_metadata": papers,
        "unpaywall_results": {},
    })

    assert captured["max_workers"] == 5, "非 arXiv 任务并发应取 max_workers=5"
    assert captured["sem_value"] == 3, "arXiv 任务并发上限应为 arxiv_max_workers=3"
    assert out["pdf_download_status"] == "completed"
    assert len(out["download_paths"]) == 2


# ══════════════════════════════════════════════════════════════
# R2-4: supplementary key_value 按行记录实际匹配值
# ══════════════════════════════════════════════════════════════

def test_supplementary_key_value_per_row(monkeypatch, tmp_path):
    """每行 record 的 provenance.key_value 取该行 entity 列实际值，非恒取首行"""
    import importlib
    sq_mod = importlib.import_module("subgraphs.subgraph2.nodes.supplementary_query")

    class _Col:
        def __init__(self, unit):
            self.unit = unit

    class _Table:
        colnames = ["Name", "Dist"]
        _units = {"Name": "", "Dist": "Mpc"}
        _rows = [
            {"Name": "M31", "Dist": "0.77"},
            {"Name": "NGC 224", "Dist": "0.78"},
        ]

        def __iter__(self):
            return iter(self._rows)

        def __getitem__(self, key):
            return _Col(self._units.get(key, ""))

    class _FakeVizier:
        def find_catalogs(self, bibcode):
            return {}

        def get_catalogs(self, table_id):
            return [_Table()]

    monkeypatch.setattr(sq_mod, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(sq_mod, "_CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(sq_mod, "_catalog_real_exists", lambda cid: True)
    monkeypatch.setattr(sq_mod, "_load_table_meta", lambda tid: {
        "title": "t", "description": "d", "columns": ["Name", "Dist [Mpc] distance"]})
    monkeypatch.setattr(sq_mod, "_llm_judge_table", lambda meta, ent: {
        "table_class": "whole_entity",
        "entity_column": "Name",
        "property_columns": [{"column": "Dist", "standard_name": "distance"}],
    })
    monkeypatch.setattr(sq_mod, "query_with_fallback",
                        lambda fn, **kw: fn(_FakeVizier()))
    monkeypatch.setattr(sq_mod, "map_columns_to_properties",
                        lambda **kw: {"Dist": "distance"})
    monkeypatch.setattr(sq_mod.time, "sleep", lambda *a: None)

    out = sq_mod.supplementary_query({
        "query_id": "test-suppl",
        "target_entity": "M31",
        "simbad_aliases": ["M31", "NGC 224"],
        "simbad_object_type": "G",
        "property_spec": [{"property_id": "distance", "unit": "Mpc"}],
        "paper_sources": [{
            "source_id": "2014MNRAS.427.1463Z",
            "title": "Test Paper",
        }],
    })

    records = out["supplementary_records"]
    assert len(records) == 2
    kv_by_row = [r["provenance"]["key_value"] for r in records]
    assert kv_by_row == ["M31", "NGC 224"], "key_value 应按行取实际匹配值"
    assert [r["provenance"]["row_index"] for r in records] == [0, 1]
