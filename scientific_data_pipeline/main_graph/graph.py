"""
主图定义

职责：
    组装所有子图，构建完整的科学数据管道

流程：
    用户查询 → 意图澄清 → 论文检索 → 数据提取 → 质量控制 → 输出结果
"""

from langgraph.graph import StateGraph, END
import logging

from main_graph.state import MainState
from main_graph.wrappers import (
    create_intent_wrapper,
    create_retrieval_wrapper,
    create_extraction_wrapper,
    create_quality_wrapper
)

logger = logging.getLogger(__name__)


def create_main_pipeline() -> StateGraph:
    """
    创建主图管道

    Returns:
        未编译的StateGraph对象
    """
    logger.info("Creating main pipeline graph")

    graph = StateGraph(MainState)

    # 添加意图澄清节点
    logger.info("Adding intent clarification subgraph")
    graph.add_node("intent", create_intent_wrapper())

    # 添加检索节点
    logger.info("Adding retrieval subgraph")
    graph.add_node("retrieval", create_retrieval_wrapper())

    # 添加提取节点
    logger.info("Adding extraction subgraph")
    graph.add_node("extraction", create_extraction_wrapper())

    # 添加质检节点
    logger.info("Adding quality subgraph")
    graph.add_node("quality", create_quality_wrapper())

    # 完整流程：意图澄清 → 检索 → 提取 → 质检
    graph.set_entry_point("intent")
    graph.add_edge("intent", "retrieval")
    graph.add_edge("retrieval", "extraction")
    graph.add_edge("extraction", "quality")
    graph.add_edge("quality", END)

    # TODO: 完整流程（待其他子图迁移后启用）
    # graph.set_entry_point("intent")
    # graph.add_edge("intent", "retrieval")
    # graph.add_edge("retrieval", "extraction")
    # graph.add_edge("extraction", "quality")
    # graph.add_edge("quality", END)

    logger.info("Main pipeline graph created successfully")

    return graph


def compile_main_pipeline():
    """
    编译主图管道

    Returns:
        编译后的可执行Graph对象
    """
    logger.info("Compiling main pipeline")
    compiled_graph = create_main_pipeline().compile()
    logger.info("Main pipeline compiled successfully")
    return compiled_graph
