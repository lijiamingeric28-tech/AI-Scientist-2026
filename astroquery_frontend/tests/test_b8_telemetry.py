"""批次 B8「质量管线埋点」回归测试 — M-15 / L-08（全 mock 离线）。

M-15: 失败/空数据早退路径不发子步骤终止事件 → 子步骤前端永久 waiting。
      锚点：各早退分支补发 step_progress 终止事件（failed/skipped/completed，
      带 data 摘要）；空数据路径收到 skipped 事件。
L-08: figure_extractor 循环内同一步骤重复 completed（len(tasks) 为 5 倍数时）。
      锚点：completed 只由循环后埋点统一发（恒单条）。
"""

from __future__ import annotations

import importlib

import pytest

import astroquery_ai  # noqa: F401  先导入解循环依赖（与 test_audit_fixes_retrieval 同模式）


@pytest.fixture()
def captured_events():
    """配置 events 发射器捕获所有 emit 事件；测后复位为 no-op（不泄漏到其他测试）。"""
    from events import configure as configure_emitter

    captured: list = []

    def _pub(task_id, event):
        captured.append({"task_id": task_id, **event})

    configure_emitter(_pub)
    try:
        yield captured
    finally:
        configure_emitter(None)


def _steps(captured, stage_id, step):
    return [e for e in captured if e.get("stage_id") == stage_id and e.get("step") == step]


# ══════════════════════════════════════════════════════════════
# M-15: database_query 配置加载失败早退 → database/match failed
# ══════════════════════════════════════════════════════════════

def test_database_query_config_fail_emits_failed(captured_events, monkeypatch):
    """M-15 锚点：catalog 配置加载抛异常 → 早退分支补发 database/match failed"""
    mod = importlib.import_module("subgraphs.subgraph2.nodes.database_query")

    def _boom(*a, **k):
        raise RuntimeError("config boom")

    monkeypatch.setattr(mod, "load_catalog_config", _boom)

    out = mod.database_query({
        "query_id": "t-db",
        "target_entity": "M31",
        "simbad_aliases": [],
        "simbad_info": {},
        "property_spec": [],
    })

    assert out["database_query_status"] == "failed"
    evs = _steps(captured_events, "retrieval", "database/match")
    assert evs, "config 失败早退路径未发 database/match 终止事件"
    assert evs[-1]["status"] == "failed"
    assert evs[-1]["data"] == {"matched_catalogs": 0, "total_queries": 0}


# ══════════════════════════════════════════════════════════════
# M-15: ads_search 空结果早退 → paper/search skipped/failed/completed
# ══════════════════════════════════════════════════════════════

def test_ads_search_empty_all_rate_limited_emits_skipped(captured_events, monkeypatch):
    """M-15 锚点：ADS 全 429 → 早退分支补发 paper/search skipped（回归锚点）"""
    mod = importlib.import_module("subgraphs.subgraph2.nodes.ads_search")

    class _RateLimitSearchQuery:
        def __init__(self, *args, **kwargs):
            raise Exception("429 rate limit exceeded")

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(mod.ads, "SearchQuery", _RateLimitSearchQuery)

    out = mod.ads_search({
        "query_id": "t-ads",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
        "ads_query_strings": [],
    })

    assert out["ads_search_status"] == "skipped"
    evs = _steps(captured_events, "retrieval", "paper/search")
    assert evs, "ADS 全限流早退路径未发 paper/search 终止事件"
    assert evs[-1]["status"] == "skipped"
    assert evs[-1]["data"] == {"per_query": [], "deduped": 0}


def test_ads_search_empty_query_failed_emits_failed(captured_events, monkeypatch):
    """M-15 锚点：ADS 查询 3 次失败且 LLM 重建失败 → paper/search failed"""
    mod = importlib.import_module("subgraphs.subgraph2.nodes.ads_search")

    class _FailSearchQuery:
        def __init__(self, *args, **kwargs):
            raise Exception("invalid query syntax")

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(mod.ads, "SearchQuery", _FailSearchQuery)
    # 离线全 mock：跳过退避睡眠 + LLM 重建（rebuild 返回空 → 记失败）
    monkeypatch.setattr(mod.time, "sleep", lambda *a: None)
    monkeypatch.setattr(mod, "_llm_build_group_query", lambda *a, **k: "")

    out = mod.ads_search({
        "query_id": "t-ads",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
        "ads_query_strings": [],
    })

    assert out["ads_search_status"] == "failed"
    evs = _steps(captured_events, "retrieval", "paper/search")
    assert evs and evs[-1]["status"] == "failed"
    assert evs[-1]["data"] == {"per_query": [], "deduped": 0}


def test_ads_search_empty_clean_emits_completed(captured_events, monkeypatch):
    """M-15 锚点：ADS 零命中且无错误 → paper/search completed（正常完成语义）"""
    mod = importlib.import_module("subgraphs.subgraph2.nodes.ads_search")

    class _EmptySearchQuery:
        def __init__(self, *args, **kwargs):
            pass

        def __iter__(self):
            return iter([])

    monkeypatch.setattr(mod.ads, "SearchQuery", _EmptySearchQuery)

    out = mod.ads_search({
        "query_id": "t-ads",
        "target_entity": "M31",
        "requested_properties": [],
        "property_spec": [],
        "ads_query_strings": [],
    })

    assert out["ads_search_status"] == "completed"
    evs = _steps(captured_events, "retrieval", "paper/search")
    assert evs and evs[-1]["status"] == "completed"
    assert evs[-1]["data"] == {"per_query": [], "deduped": 0}


# ══════════════════════════════════════════════════════════════
# M-15: pdf_download 无论文早退 → paper/download skipped
# ══════════════════════════════════════════════════════════════

def test_pdf_download_empty_emits_skipped(captured_events):
    """M-15 锚点：无论文可下载 → 早退分支补发 paper/download skipped"""
    mod = importlib.import_module("subgraphs.subgraph2.nodes.pdf_download")

    out = mod.pdf_download({
        "query_id": "t-pdf",
        "ads_papers_metadata": [],
        "unpaywall_results": {},
    })

    assert out["pdf_download_status"] == "skipped"
    evs = _steps(captured_events, "retrieval", "paper/download")
    assert evs, "无论文早退路径未发 paper/download 终止事件"
    assert evs[-1]["status"] == "skipped"
    assert evs[-1]["data"] == {"downloaded": 0, "failed": 0}


# ══════════════════════════════════════════════════════════════
# M-15: bbox_annotator 零任务早退 → bbox skipped
# ══════════════════════════════════════════════════════════════

def test_bbox_annotator_no_tasks_emits_skipped(captured_events):
    """M-15 锚点：无标注任务（含全部坏记录）→ 早退分支补发 bbox skipped"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.bbox_annotator")

    out = mod.bbox_batch_annotator({
        "raw_extractions": {},
        "paper_image_paths": {},
        "target_entity": "M31",
        "query_id": "t-bbox",
    })

    assert out["bbox_annotation_status"] == "completed"
    evs = _steps(captured_events, "extraction", "bbox")
    assert evs, "零任务早退路径未发 bbox 终止事件"
    assert evs[-1]["status"] == "skipped"
    assert evs[-1]["data"] == {"success": 0, "failed": 0}


# ══════════════════════════════════════════════════════════════
# M-15: figure_extractor 无页面早退 → figure skipped（返回值不变）
# ══════════════════════════════════════════════════════════════

def test_figure_extractor_empty_emits_skipped(captured_events):
    """M-15 锚点：无页面可检测 → 早退分支补发 figure skipped，返回值保持 {"figure_evidence": []}"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.figure_extractor")

    out = mod.figure_extractor({
        "paper_image_paths": {},
        "target_entity": "M31",
        "query_id": "t-fig",
    })

    assert out == {"figure_evidence": []}
    evs = _steps(captured_events, "extraction", "figure")
    assert evs, "无页面早退路径未发 figure 终止事件"
    assert evs[-1]["status"] == "skipped"
    assert evs[-1]["data"] == {"figures": 0}


# ══════════════════════════════════════════════════════════════
# L-08: figure_extractor 循环内不重复 completed（5 倍数任务数）
# ══════════════════════════════════════════════════════════════

def _write_page_images(tmp_path, n):
    from PIL import Image

    paths = []
    for i in range(n):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (10, 10), "white").save(p)
        paths.append(str(p))
    return paths


@pytest.mark.parametrize("n_pages", [5, 3])  # 5=审计锚点（5 的倍数），3=非倍数对照
def test_figure_extractor_single_completed(captured_events, monkeypatch, tmp_path, n_pages):
    """L-08 锚点：任意任务数 figure 步骤恒只发一条 completed（由循环后统一发）"""
    mod = importlib.import_module("subgraphs.subgraph3.nodes.figure_extractor")

    monkeypatch.setattr(mod, "call_qwen_figure_detect",
                        lambda image, page, target_entity, property_spec: {"page": page, "figures": []})
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path)

    out = mod.figure_extractor({
        "paper_image_paths": {"BIB": _write_page_images(tmp_path, n_pages)},
        "target_entity": "M31",
        "property_spec": [],
        "query_id": "t-fig",
    })

    assert out["figure_evidence"] == []
    evs = _steps(captured_events, "extraction", "figure")
    assert evs, "figure 步骤未发任何事件"
    completed = [e for e in evs if e["status"] == "completed"]
    assert len(completed) == 1, f"figure 步骤应恒单条 completed，实际 {len(completed)} 条: {evs}"
    # completed 必须是最后一条（running 之后统一收尾）
    assert evs[-1]["status"] == "completed"
    # 循环内只发 running
    assert all(e["status"] == "running" for e in evs[:-1]), f"循环内出现非 running 状态: {evs}"
    assert completed[0]["progress"] == {"completed": n_pages, "total": n_pages}
    assert completed[0]["data"] == {"figures": 0}
