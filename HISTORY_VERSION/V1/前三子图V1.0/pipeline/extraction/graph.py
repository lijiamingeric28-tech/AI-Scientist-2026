"""
提取子图 Graph 定义
"""

from langgraph.graph import StateGraph, END
from state.extraction_state import ExtractionState
from pipeline.extraction.agents import (
    prepare_and_prompt_agent,
    vlm_extract_agent,
    ocr_extract_agent,
    fidelity_validation_agent,
    format_output_agent
)


def create_extraction_graph():
    """
    创建提取子图的Graph
    
    流程：
    prepare_and_prompt → vlm_extract → ocr_extract → 
    fidelity_validation → format_output → END
    
    Returns:
        编译后的Graph对象
    """
    # 创建Graph
    graph = StateGraph(ExtractionState)
    
    # 添加Node（5个Agent）
    graph.add_node("prepare_and_prompt", prepare_and_prompt_agent)
    graph.add_node("vlm_extract", vlm_extract_agent)
    graph.add_node("ocr_extract", ocr_extract_agent)
    graph.add_node("fidelity_validation", fidelity_validation_agent)
    graph.add_node("format_output", format_output_agent)
    
    # 添加Edge（顺序执行）
    graph.set_entry_point("prepare_and_prompt")
    graph.add_edge("prepare_and_prompt", "vlm_extract")
    graph.add_edge("vlm_extract", "ocr_extract")
    graph.add_edge("ocr_extract", "fidelity_validation")
    graph.add_edge("fidelity_validation", "format_output")
    graph.add_edge("format_output", END)
    
    # 编译Graph
    return graph.compile()
