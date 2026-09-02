"""批次 B9「前端 agent 展示与性能」回归测试 — L-10（全 mock 离线）。

L-10: supplementary_query 表级验证无 substatus → 前端卡 2 只有进度条没有
      "正在验证表 X" 中间文字（D6-6，WEB_DESIGN.md 5.4 数据可用性对照）。
      锚点：表验证开始时发 supplementary/find 事件且 data.substatus 非空。
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


def test_supplementary_table_verification_emits_substatus(captured_events, monkeypatch, tmp_path):
    """L-10 锚点：表验证开始时发 substatus「正在验证表 X」。"""
    mod = importlib.import_module("subgraphs.subgraph2.nodes.supplementary_query")

    monkeypatch.setattr(mod, "guess_j_tables", lambda bibcode: ["J/ApJ/930/14", "J/ApJ/930/15"])
    monkeypatch.setattr(mod, "_catalog_real_exists", lambda c: True)
    monkeypatch.setattr(
        mod, "_load_table_meta",
        lambda tid: {"title": "t", "description": "d", "columns": ["a", "b"]})
    monkeypatch.setattr(
        mod, "_llm_judge_table",
        lambda meta, entity: {"table_class": "irrelevant", "valid": True})
    # 缓存目录隔离（避免写真实 subgraphs/subgraph2/data/supplementary/）
    monkeypatch.setattr(mod, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(mod, "_CACHE_FILE", tmp_path / "cache" / "table_meta_cache.json")

    state = {
        "paper_sources": [{"source_id": "2023ApJ..930...14A"}],
        "simbad_aliases": ["M13"],
        "target_entity": "M13",
        "query_id": "q9test",
        "property_spec": [],
    }
    mod.supplementary_query(state)

    finds = [e for e in captured_events if e.get("step") == "supplementary/find"]
    assert finds, "应发出 supplementary/find 事件"
    substatus = [
        e["data"].get("substatus") for e in finds
        if e.get("data") and e["data"].get("substatus")
    ]
    assert substatus, "表验证应携带 substatus（data.substatus）"
    assert any("正在验证表" in s for s in substatus), \
        f"substatus 应为「正在验证表 X」，got {substatus}"
