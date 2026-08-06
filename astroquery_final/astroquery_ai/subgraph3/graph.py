"""LangGraph definition for the extraction subgraph."""

from langgraph.graph import StateGraph, END
from .schemas.state import ExtractionState
from .nodes import pdf_batch_converter, vlm_batch_extractor, bbox_batch_annotator, result_builder
from .utils.logger import get_logger


logger = get_logger(__name__)


def create_extraction_subgraph() -> StateGraph:
    """
    Create the multimodal extraction subgraph.

    Flow:
        START
          ↓
        pdf_batch_converter (PDF → images)
          ↓
        vlm_batch_extractor (VLM extraction, no bbox)
          ↓
        bbox_batch_annotator (BBox annotation with qwen3.7-flash)
          ↓
        result_builder (build paper_records)
          ↓
        END

    Returns:
        Compiled StateGraph object
    """
    logger.info("Creating Extraction Subgraph")

    # 1. Create StateGraph
    graph = StateGraph(ExtractionState)

    # 2. Add all nodes
    graph.add_node("pdf_batch_converter", pdf_batch_converter)
    graph.add_node("vlm_batch_extractor", vlm_batch_extractor)
    graph.add_node("bbox_batch_annotator", bbox_batch_annotator)
    graph.add_node("result_builder", result_builder)

    # 3. Set entry point
    graph.set_entry_point("pdf_batch_converter")

    # 4. Add edges (sequential execution)
    graph.add_edge("pdf_batch_converter", "vlm_batch_extractor")
    graph.add_edge("vlm_batch_extractor", "bbox_batch_annotator")
    graph.add_edge("bbox_batch_annotator", "result_builder")
    graph.add_edge("result_builder", END)

    # 5. Compile graph
    logger.info("Compiling graph...")
    compiled_graph = graph.compile()

    logger.info("Extraction Subgraph created successfully!")

    return compiled_graph


if __name__ == "__main__":
    # Test graph creation
    graph = create_extraction_subgraph()
    logger.info("Graph created and compiled successfully!")
