"""
提取子图定义

流程：
prepare_and_prompt → vlm_extract → ocr_extract →
fidelity_validation → format_output → END
"""

from langgraph.graph import StateGraph, END
from .state import ExtractionState
from .nodes import (
    prepare_and_prompt_node,
    vlm_extract_node,
    ocr_extract_node,
    fidelity_validation_node,
    format_output_node
)


def create_extraction_graph() -> StateGraph:
    """
    创建提取子图的Graph

    流程：
    prepare_and_prompt → vlm_extract → ocr_extract →
    fidelity_validation → format_output → END

    Returns:
        StateGraph对象
    """
    graph = StateGraph(ExtractionState)

    # 添加5个节点
    graph.add_node("prepare_and_prompt", prepare_and_prompt_node)
    graph.add_node("vlm_extract", vlm_extract_node)
    graph.add_node("ocr_extract", ocr_extract_node)
    graph.add_node("fidelity_validation", fidelity_validation_node)
    graph.add_node("format_output", format_output_node)

    # 设置顺序流程
    graph.set_entry_point("prepare_and_prompt")
    graph.add_edge("prepare_and_prompt", "vlm_extract")
    graph.add_edge("vlm_extract", "ocr_extract")
    graph.add_edge("ocr_extract", "fidelity_validation")
    graph.add_edge("fidelity_validation", "format_output")
    graph.add_edge("format_output", END)

    return graph


def compile_extraction_graph():
    """
    编译提取子图

    Returns:
        编译后的Graph对象
    """
    return create_extraction_graph().compile()
