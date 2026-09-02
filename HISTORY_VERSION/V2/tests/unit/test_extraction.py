"""
提取子图单元测试

测试内容：
1. Graph编译测试
2. 各节点的基本功能测试（Mock VLM/OCR）
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from subgraphs.extraction.graph import create_extraction_graph, compile_extraction_graph
from subgraphs.extraction.state import ExtractionState
from subgraphs.extraction.nodes import (
    prepare_and_prompt_node,
    vlm_extract_node,
    ocr_extract_node,
    fidelity_validation_node,
    format_output_node
)
from shared.models.paper_metadata import PaperMetadata


# ==========================================
# Graph 编译测试
# ==========================================

def test_create_extraction_graph():
    """测试创建提取子图"""
    graph = create_extraction_graph()
    assert graph is not None
    assert hasattr(graph, 'nodes')


def test_compile_extraction_graph():
    """测试编译提取子图"""
    compiled_graph = compile_extraction_graph()
    assert compiled_graph is not None


# ==========================================
# Agent 1: prepare_and_prompt 测试
# ==========================================

@pytest.fixture
def mock_intent_params():
    """模拟意图参数"""
    mock_intent = Mock()
    mock_intent.entities = ["FRB", "fast radio burst"]
    mock_intent.properties = ["dispersion measure", "DM"]
    return mock_intent


@pytest.fixture
def mock_papers():
    """模拟论文列表"""
    paper1 = PaperMetadata(
        id="W001",
        title="Test Paper 1",
        doi="10.1000/test1",
        authors=["Author A"],
        year=2023,
        journal="Test Journal",
        local_path="/path/to/paper1.pdf",
        download_status="success",
        score=85.0
    )
    paper2 = PaperMetadata(
        id="W002",
        title="Test Paper 2",
        doi="10.1000/test2",
        authors=["Author B"],
        year=2024,
        journal="Test Journal",
        local_path="/path/to/paper2.pdf",
        download_status="success",
        score=90.0
    )
    return [paper1, paper2]


@patch('subgraphs.extraction.nodes.prepare_and_prompt.call_vlm_api')
def test_prepare_and_prompt_node_success(mock_vlm_api, mock_intent_params, mock_papers):
    """测试准备与Prompt生成节点 - 成功场景"""
    # Mock VLM API返回
    mock_vlm_api.return_value = '{"entity_type": "FRB", "property_name": "dispersion_measure"}'

    state = ExtractionState(
        intent_params=mock_intent_params,
        filtered_papers=mock_papers
    )

    result = prepare_and_prompt_node(state)

    # 验证输出
    assert "normalized_params" in result
    assert result["normalized_params"]["entity_type"] == "FRB"
    assert result["normalized_params"]["property_name"] == "dispersion_measure"
    assert "extraction_prompt" in result
    assert "extraction_tasks" in result
    assert len(result["extraction_tasks"]) == 2


@patch('subgraphs.extraction.nodes.prepare_and_prompt.call_vlm_api')
def test_prepare_and_prompt_node_fallback(mock_vlm_api, mock_intent_params, mock_papers):
    """测试准备与Prompt生成节点 - 降级场景"""
    # Mock VLM API失败
    mock_vlm_api.side_effect = Exception("API Error")

    state = ExtractionState(
        intent_params=mock_intent_params,
        filtered_papers=mock_papers
    )

    result = prepare_and_prompt_node(state)

    # 验证降级逻辑
    assert "normalized_params" in result
    assert result["normalized_params"]["entity_type"] == "FRB"
    assert result["normalized_params"]["property_name"] == "dispersion measure"


# ==========================================
# Agent 2: vlm_extract 测试
# ==========================================

@pytest.fixture
def mock_extraction_tasks():
    """模拟提取任务列表"""
    return [
        {
            "paper_id": "W001",
            "pdf_path": "/path/to/paper1.pdf",
            "paper_title": "Test Paper 1",
            "max_pages": None
        }
    ]


@patch('subgraphs.extraction.nodes.vlm_extract.pdf_to_images')
@patch('subgraphs.extraction.nodes.vlm_extract.image_to_base64')
@patch('subgraphs.extraction.nodes.vlm_extract.call_vlm_api')
def test_vlm_extract_node_success(mock_vlm_api, mock_img_to_base64, mock_pdf_to_images, mock_extraction_tasks):
    """测试VLM提取节点 - 成功场景"""
    # Mock PDF转图像
    mock_pdf_to_images.return_value = [Mock()]
    mock_img_to_base64.return_value = "base64_image_data"

    # Mock VLM API返回
    mock_vlm_api.return_value = '''[
        {
            "entity_name": "FRB 20180301A",
            "property_value": "550.1",
            "property_unit": "pc/cm^3",
            "source_page": "3",
            "extract_reason": "Found in Table 1"
        }
    ]'''

    state = ExtractionState(
        extraction_tasks=mock_extraction_tasks,
        extraction_prompt="Extract FRB data..."
    )

    result = vlm_extract_node(state)

    # 验证输出
    assert "vlm_results" in result
    assert "vlm_stats" in result
    assert len(result["vlm_results"]) == 1
    assert result["vlm_results"][0]["status"] == "success"
    assert len(result["vlm_results"][0]["observations"]) == 1
    assert result["vlm_stats"]["total_pdfs"] == 1
    assert result["vlm_stats"]["success_pdfs"] == 1


@patch('subgraphs.extraction.nodes.vlm_extract.pdf_to_images')
def test_vlm_extract_node_pdf_conversion_failed(mock_pdf_to_images, mock_extraction_tasks):
    """测试VLM提取节点 - PDF转换失败"""
    # Mock PDF转换失败
    mock_pdf_to_images.return_value = []

    state = ExtractionState(
        extraction_tasks=mock_extraction_tasks,
        extraction_prompt="Extract FRB data..."
    )

    result = vlm_extract_node(state)

    # 验证错误处理
    assert result["vlm_results"][0]["status"] == "error"
    assert "PDF conversion failed" in result["vlm_results"][0]["error"]


# ==========================================
# Agent 3: ocr_extract 测试
# ==========================================

@pytest.fixture
def mock_vlm_results():
    """模拟VLM提取结果"""
    return [
        {
            "paper_id": "W001",
            "pdf_path": "/path/to/paper1.pdf",
            "status": "success",
            "observations": [
                {
                    "entity_name": "FRB 20180301A",
                    "property_value": "550.1",
                    "property_unit": "pc/cm^3",
                    "source_page": "3",
                    "extract_reason": "Found in Table 1"
                }
            ]
        }
    ]


@patch('subgraphs.extraction.nodes.ocr_extract.pdf_to_base64_page')
@patch('subgraphs.extraction.nodes.ocr_extract.call_ocr_api')
def test_ocr_extract_node_success(mock_ocr_api, mock_pdf_to_base64, mock_vlm_results):
    """测试OCR提取节点 - 成功场景"""
    # Mock PDF转base64
    mock_pdf_to_base64.return_value = "base64_page_data"

    # Mock OCR API返回
    mock_ocr_api.return_value = {
        "words_info": [
            {"text": "FRB 20180301A", "location": [100, 200, 300, 250]},
            {"text": "550.1", "location": [400, 200, 450, 250]}
        ]
    }

    state = ExtractionState(
        vlm_results=mock_vlm_results
    )

    result = ocr_extract_node(state)

    # 验证输出
    assert "ocr_results" in result
    assert "ocr_stats" in result
    assert len(result["ocr_results"]) == 1
    assert result["ocr_stats"]["total_pages"] == 1
    assert result["ocr_stats"]["success_pages"] == 1


def test_ocr_extract_node_no_pages(mock_vlm_results):
    """测试OCR提取节点 - 无需OCR的页面"""
    # VLM结果中没有source_page
    mock_vlm_results[0]["observations"][0]["source_page"] = ""

    state = ExtractionState(
        vlm_results=mock_vlm_results
    )

    result = ocr_extract_node(state)

    # 验证输出
    assert result["ocr_stats"]["total_pages"] == 0


# ==========================================
# Agent 4: fidelity_validation 测试
# ==========================================

@pytest.fixture
def mock_ocr_results():
    """模拟OCR结果"""
    return {
        "/path/to/paper1.pdf__page_3": [
            {"text": "FRB 20180301A", "location": [100, 200, 300, 250, 300, 300, 100, 300]},
            {"text": "550.1", "location": [400, 200, 450, 250, 450, 300, 400, 300]}
        ]
    }


def test_fidelity_validation_node_success(mock_vlm_results, mock_ocr_results):
    """测试忠实度验证节点 - 成功场景"""
    state = ExtractionState(
        vlm_results=mock_vlm_results,
        ocr_results=mock_ocr_results
    )

    result = fidelity_validation_node(state)

    # 验证输出
    assert "verified_records" in result
    assert "failed_records" in result
    assert "verification_rate" in result
    assert len(result["verified_records"]) == 1
    assert result["verification_rate"] == 1.0


def test_fidelity_validation_node_no_ocr_data(mock_vlm_results):
    """测试忠实度验证节点 - 缺少OCR数据"""
    state = ExtractionState(
        vlm_results=mock_vlm_results,
        ocr_results={}
    )

    result = fidelity_validation_node(state)

    # 验证输出
    assert len(result["verified_records"]) == 0
    assert len(result["failed_records"]) == 1
    assert result["verification_rate"] == 0.0


# ==========================================
# Agent 5: format_output 测试
# ==========================================

@pytest.fixture
def mock_verified_records():
    """模拟验证通过的记录"""
    return [
        {
            "paper_id": "W001",
            "observation": {
                "entity_name": "FRB 20180301A",
                "property_value": "550.1",
                "property_unit": "pc/cm^3",
                "source_page": "3"
            },
            "verification": {
                "verified": True,
                "entity_verification": {"found": True, "match_score": 100, "bbox": [100, 200, 300, 250, 300, 300, 100, 300]},
                "property_verification": {"found": True, "match_score": 100, "bbox": [400, 200, 450, 250, 450, 300, 400, 300]}
            }
        }
    ]


@patch('subgraphs.extraction.nodes.format_output.generate_extraction_report')
def test_format_output_node_success(mock_generate_report, mock_verified_records, mock_papers):
    """测试格式化输出节点 - 成功场景"""
    # Mock报告生成
    mock_generate_report.return_value = "/path/to/report.md"

    state = ExtractionState(
        verified_records=mock_verified_records,
        filtered_papers=mock_papers,
        normalized_params={"entity_type": "FRB", "property_name": "dispersion_measure"},
        vlm_stats={"total_pdfs": 2, "success_pdfs": 2, "failed_pdfs": 0, "total_observations": 1, "elapsed_time": 10.0},
        ocr_stats={"total_pages": 1, "success_pages": 1, "failed_pages": 0, "elapsed_time": 5.0},
        failed_records=[],
        verification_rate=1.0
    )

    result = format_output_node(state)

    # 验证输出
    assert "grounded_data" in result
    assert result["grounded_data"]["schema_version"] == "1.1.0"
    assert len(result["grounded_data"]["sources"]) == 1
    assert len(result["grounded_data"]["records"]) == 1

    # 验证source结构
    source = result["grounded_data"]["sources"][0]
    assert source["source_id"] == "W001"
    assert source["source_type"] == "paper"
    assert source["title"] == "Test Paper 1"

    # 验证record结构
    record = result["grounded_data"]["records"][0]
    assert record["entity_type"] == "FRB"
    assert record["entity_name"] == "FRB 20180301A"
    assert record["field_name"] == "dispersion_measure"
    assert record["field_value"] == 550.1
    assert record["field_unit"] == "pc/cm^3"
    assert record["provenance"]["page"] == 3
    assert record["extraction_method"] == "vlm_text"


def test_format_output_node_bbox_conversion(mock_verified_records, mock_papers):
    """测试格式化输出节点 - bbox转换"""
    from subgraphs.extraction.nodes.format_output import convert_bbox_8_to_4

    # 测试正常转换
    bbox_8 = [100, 200, 300, 200, 300, 300, 100, 300]
    bbox_4 = convert_bbox_8_to_4(bbox_8)
    assert bbox_4 == [100, 200, 300, 300]

    # 测试空输入
    assert convert_bbox_8_to_4(None) is None
    assert convert_bbox_8_to_4([]) is None
    assert convert_bbox_8_to_4([1, 2, 3]) is None


# ==========================================
# 集成测试
# ==========================================

@patch('subgraphs.extraction.nodes.prepare_and_prompt.call_vlm_api')
@patch('subgraphs.extraction.nodes.vlm_extract.pdf_to_images')
@patch('subgraphs.extraction.nodes.vlm_extract.image_to_base64')
@patch('subgraphs.extraction.nodes.vlm_extract.call_vlm_api')
@patch('subgraphs.extraction.nodes.ocr_extract.pdf_to_base64_page')
@patch('subgraphs.extraction.nodes.ocr_extract.call_ocr_api')
@patch('subgraphs.extraction.nodes.format_output.generate_extraction_report')
def test_full_pipeline(
    mock_report, mock_ocr_api, mock_pdf_to_base64,
    mock_vlm_api_extract, mock_img_to_base64, mock_pdf_to_images,
    mock_vlm_api_normalize, mock_intent_params, mock_papers
):
    """测试完整的提取流程"""
    # Mock所有外部调用
    mock_vlm_api_normalize.return_value = '{"entity_type": "FRB", "property_name": "dispersion_measure"}'
    mock_pdf_to_images.return_value = [Mock()]
    mock_img_to_base64.return_value = "base64_image"
    mock_vlm_api_extract.return_value = '''[{
        "entity_name": "FRB 20180301A",
        "property_value": "550.1",
        "property_unit": "pc/cm^3",
        "source_page": "3",
        "extract_reason": "Found in Table 1"
    }]'''
    mock_pdf_to_base64.return_value = "base64_page"
    mock_ocr_api.return_value = {
        "words_info": [
            {"text": "FRB 20180301A", "location": [100, 200, 300, 250, 300, 300, 100, 300]},
            {"text": "550.1", "location": [400, 200, 450, 250, 450, 300, 400, 300]}
        ]
    }
    mock_report.return_value = "/path/to/report.md"

    # 初始化State
    state = ExtractionState(
        intent_params=mock_intent_params,
        filtered_papers=mock_papers
    )

    # 执行完整流程
    state = prepare_and_prompt_node(state)
    state = vlm_extract_node(state)
    state = ocr_extract_node(state)
    state = fidelity_validation_node(state)
    state = format_output_node(state)

    # 验证最终输出
    assert "grounded_data" in state
    assert state["grounded_data"]["schema_version"] == "1.1.0"
    assert len(state["grounded_data"]["sources"]) > 0
    assert len(state["grounded_data"]["records"]) > 0
    assert state["verification_rate"] > 0
