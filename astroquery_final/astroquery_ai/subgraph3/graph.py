"""提取子图的 LangGraph 定义。"""

from langgraph.graph import StateGraph, END
from .schemas.state import ExtractionState
from .nodes import (
    pdf_batch_converter,
    vlm_batch_extractor,
    bbox_batch_annotator,
    figure_extractor,
    result_builder,
)
from .utils.logger import get_logger


logger = get_logger(__name__)


def create_extraction_subgraph(checkpointer=None) -> StateGraph:
    """
    Create the multimodal extraction subgraph.
    Phase 4c: checkpointer 可选（HITL interrupt 支持）。

    Flow:
        START
          ↓
        pdf_batch_converter (PDF → images)
          ↓
        vlm_batch_extractor (VLM extraction, no bbox)
          ↓
        bbox_batch_annotator (BBox annotation with qwen3.7-flash)
          ↓
        figure_extractor (图检测 + 相关性筛选, 独立通路; 节点内页级 100 并发)
          ↓
        result_builder (build paper_records + figure_evidence)
          ↓
        END

    注：figure_extractor 串行在 bbox 之后（不与全量 state 返回节点并行，
    避免 LangGraph 并行写 key 冲突）；其内部页级并发不受影响。

    Returns:
        Compiled StateGraph object
    """
    logger.info("Creating Extraction Subgraph")

    # 1. 创建 StateGraph
    graph = StateGraph(ExtractionState)

    # 2. 添加全部节点
    graph.add_node("pdf_batch_converter", pdf_batch_converter)
    graph.add_node("vlm_batch_extractor", vlm_batch_extractor)
    graph.add_node("bbox_batch_annotator", bbox_batch_annotator)
    graph.add_node("figure_extractor", figure_extractor)
    graph.add_node("result_builder", result_builder)

    # 3. 设置入口点
    graph.set_entry_point("pdf_batch_converter")

    # 4. 添加边（数据提取链路 + figure 证据链路，汇合到 result_builder）
    graph.add_edge("pdf_batch_converter", "vlm_batch_extractor")
    graph.add_edge("vlm_batch_extractor", "bbox_batch_annotator")
    graph.add_edge("bbox_batch_annotator", "figure_extractor")
    graph.add_edge("figure_extractor", "result_builder")
    graph.add_edge("result_builder", END)

    # 5. 编译图
    logger.info("Compiling graph...")
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info("Extraction Subgraph created successfully!")

    return compiled_graph


if __name__ == "__main__":
    # 测试图创建
    graph = create_extraction_subgraph()
    logger.info("Graph created and compiled successfully!")
