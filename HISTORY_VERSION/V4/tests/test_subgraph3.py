"""子图3（多模态提取）characterization 测试 — 全 mock 离线

锁定：图装配 + 空 PDF 输入短路路径（不触发 PyMuPDF/dashscope）。
"""

import pytest

from subgraphs.subgraph3.graph import create_extraction_subgraph

SG3_INPUT = {
    "query_id": "test-3",
    "target_entity": "M31",
    "download_paths": [],
    "paper_sources": [],
}


def test_subgraph3_compiles():
    """图可编译，节点集合完整"""
    graph = create_extraction_subgraph()
    nodes = {n for n in graph.get_graph().nodes if not n.startswith("__")}
    assert nodes == {
        "pdf_batch_converter",
        "vlm_batch_extractor",
        "bbox_batch_annotator",
        "figure_extractor",
        "result_builder",
    }


def test_empty_pdfs_zero_external():
    """空 PDF 列表 → 全链路短路，零 VLM 调用，paper_records 为空结构"""
    graph = create_extraction_subgraph()
    result = graph.invoke(dict(SG3_INPUT))

    assert result["conversion_status"] == "completed"
    assert result["paper_image_paths"] == {}
    assert result["raw_extractions"] == {}
    assert result["paper_records"] == []
    summary = result["processing_summary"]
    assert summary["total_papers"] == 0
    assert summary["processed_papers"] == 0
    assert summary["total_records_extracted"] == 0


def test_figure_extractor_empty_input():
    """figure_extractor 空页面 → figure_evidence 空列表（不写盘）"""
    from subgraphs.subgraph3.nodes.figure_extractor import figure_extractor

    out = figure_extractor({
        "paper_image_paths": {},
        "target_entity": "M31",
        "query_id": "test-fig",
    })
    assert out == {"figure_evidence": []}


def test_figure_extractor_saves_relevant_only(tmp_path, monkeypatch):
    """mock VLM：相关图被裁剪保存并写入 evidence，不相关图被丢弃"""
    import importlib

    from PIL import Image

    # nodes/__init__.py 把 figure_extractor 导出为函数，必须 importlib 取模块
    fe_mod = importlib.import_module("subgraphs.subgraph3.nodes.figure_extractor")

    # 测试页面图（100x200 白图）
    page_img = Image.new("RGB", (100, 200), "white")
    page_path = tmp_path / "page1.png"
    page_img.save(page_path)

    # mock VLM：页1 两张图，1 相关 1 不相关
    # 注意：节点经 `from ..utils.figure_client import ...` 绑定，须 patch 节点模块属性
    def fake_detect(image, page, target_entity, property_spec):
        # 2026-08-11 契约: 去掉 high/medium/low 分级, 只留 is_relevant + reason
        return {"page": page, "figures": [
            {"bbox": [10, 20, 400, 300], "caption": "Fig. 1.",
             "description": "赫罗图", "is_relevant": True,
             "reason": "展示目标天体数据"},
            {"bbox": [500, 20, 900, 300], "caption": "Fig. 2.",
             "description": "示意图", "is_relevant": False,
             "reason": "无关"},
        ]}

    monkeypatch.setattr(fe_mod, "call_qwen_figure_detect", fake_detect)
    # 输出目录重定向到 tmp（避免污染真实 output/）
    monkeypatch.setattr(fe_mod, "OUTPUT_ROOT", tmp_path)

    out = fe_mod.figure_extractor({
        "paper_image_paths": {"FAKE_BIBCODE": [str(page_path)]},
        "target_entity": "M31",
        "property_spec": [{"property_id": "distance", "name_cn": "距离", "unit": "Mpc"}],
        "query_id": "test-fig",
    })

    evidence = out["figure_evidence"]
    assert len(evidence) == 1, f"应只保存 1 张相关图: {evidence}"
    assert evidence[0]["source_id"] == "FAKE_BIBCODE"
    assert evidence[0]["page"] == 1
    # 2026-08-11: relevance 分级已移除, reason 统一进 relevance_reason
    assert evidence[0]["relevance_reason"] == "展示目标天体数据"
    assert "relevance" not in evidence[0]
    assert evidence[0]["caption"] == "Fig. 1."
    # 图片文件真的落盘
    saved = tmp_path / evidence[0]["image_path"]
    assert saved.exists(), f"图片未保存: {saved}"
    assert saved.stat().st_size > 0
    # 路径是相对 output 根的
    assert evidence[0]["image_path"].startswith("figures/test-fig/")


def test_missing_pdf_recorded_as_failure(tmp_path):
    """PDF 路径不存在 → pdf_to_images 抛异常 → 记入 conversion_failed，不中断"""
    graph = create_extraction_subgraph()
    result = graph.invoke({
        "query_id": "test-3",
        "target_entity": "M31",
        "download_paths": [
            {
                "bibcode": "FAKE_BIBCODE_1",
                "local_path": str(tmp_path / "nonexistent.pdf"),
            }
        ],
        "paper_sources": [],
    })

    assert result["conversion_status"] == "completed"
    assert result["paper_image_paths"] == {}
    assert len(result["conversion_failed"]) == 1
    assert result["conversion_failed"][0]["bibcode"] == "FAKE_BIBCODE_1"
    assert result["paper_records"] == []
