"""hybrid_grounder 混合定位器测试 (2026-08-24)。

覆盖: 正文矢量定位 (数值/多候选消歧/科学计数法变体)、表格宏定位、
以及兜底不返回 None 的零数据丢弃契约。
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subgraphs.subgraph3.utils.hybrid_grounder import (  # noqa: E402
    _value_candidates,
    ground_fallback,
    ground_table_vector,
    ground_via_vector,
    hybrid_ground,
)


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory) -> str:
    """合成单页 PDF: 正文含两处数值 (消歧) + 一张带标题的表格。"""
    p = tmp_path_factory.mktemp("hg") / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100),
                     "The distance to the Pleiades is 134.8 +/- 1.7 pc.")
    page.insert_text((50, 140),
                     "A different cluster is at 134.8 pc as well, far away.")
    page.insert_text((50, 200), "Table 1. Cluster parameters.")
    rows = ["Parameter  Value", "Age       120 +/- 20 Myr", "Distance   134.8 pc"]
    for i, row in enumerate(rows):
        page.insert_text((60, 220 + i * 20), row)
    doc.save(p)
    doc.close()
    return str(p)


def test_value_candidates_cover_sci_and_time_variants():
    cands = _value_candidates("1.2e8 ± 2e7", "yr")
    joined = "|".join(cands)
    assert "1.2e8" in cands
    assert "120 Myr" in cands or "120 Myr" in joined
    assert "1.2×108" in cands  # 科学计数上标变体
    # 负号变体
    cands2 = _value_candidates("-0.03", "dex")
    assert "−0.03" in cands2 or any("−" in c for c in cands2)


def test_vector_grounding_exact_and_disambiguation(sample_pdf):
    # 唯一值: 精确命中
    r = ground_via_vector(sample_pdf, 1, "120", "Myr",
                          "Age 120 +/- 20 Myr")
    assert r is not None and r["bbox_source"] == "vector"
    assert len(r["bbox_2d"]) == 4
    # 多候选: 上下文消歧 (两个 134.8, 应选与上下文同行的第一个)
    r1 = ground_via_vector(sample_pdf, 1, "134.8", "pc",
                           "The distance to the Pleiades is 134.8 +/- 1.7 pc.")
    r2 = ground_via_vector(sample_pdf, 1, "134.8", "pc",
                           "A different cluster is at 134.8 pc as well")
    assert r1 and r2
    y1 = r1["bbox_2d"][1] + r1["bbox_2d"][3]
    y2 = r2["bbox_2d"][1] + r2["bbox_2d"][3]
    assert y1 < y2  # 第一个在上, 第二个在下


def test_table_grounding_full_table(sample_pdf):
    r = ground_table_vector(sample_pdf, 1, "Table 1. Cluster parameters.")
    assert r is not None and r["bbox_source"] == "full_table"
    b = r["bbox_2d"]
    assert b[1] < b[3] and b[0] < b[2]
    # 整表框必须盖住表格行 (y 范围从标题到表格底)
    assert (b[3] - b[1]) / 1000 * 842 >= 60  # 至少 60pt 高


def test_hybrid_never_returns_none(sample_pdf):
    # 数值文本层不存在时也必须返回可用的 4 元组 bbox (零数据丢弃契约)
    out = hybrid_ground(sample_pdf, 1, "999.999", "pc", "no context at all",
                        "Pleiades", call_vlm=None, extraction_method="text")
    assert out["bbox_2d"] is not None and len(out["bbox_2d"]) == 4
    assert out["bbox_source"] in ("vector", "full_table", "vlm_crop", "fallback")


def test_hybrid_table_track_routing(sample_pdf):
    # vlm_table 记录必须走表格轨 (宏定位) 而非数值微观定位
    out = hybrid_ground(sample_pdf, 1, "120", "Myr",
                        "Table 1. Cluster parameters.",
                        "Pleiades", call_vlm=None, extraction_method="vlm_table")
    assert out["bbox_source"] == "full_table"


def test_fallback_paragraph_box(sample_pdf):
    r = ground_fallback(sample_pdf, 1, "Table 1. Cluster parameters.")
    assert r is not None and r["bbox_source"] == "fallback"
    assert r["bbox_2d"][1] < r["bbox_2d"][3]
