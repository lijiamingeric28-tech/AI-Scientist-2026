"""
主Graph定义

连接所有子图的主流程
"""

from langgraph.graph import StateGraph, END
from state.main_state import MainState
from pipeline.intent.graph import create_intent_clarification_graph
from pipeline.retrieval.graph import create_retrieval_graph
import logging

logger = logging.getLogger(__name__)


def create_main_graph():
    """
    创建主流程Graph

    流程：
    1. 意图澄清（完整版）
    2. 文献检索
    3. (未来) 数据提取
    4. (未来) 数据清洗

    Returns:
        编译后的主Graph
    """
    # 创建主Graph
    graph = StateGraph(MainState)

    # 添加子图节点
    graph.add_node("intent_clarification", create_intent_subgraph_node())
    graph.add_node("retrieval", create_retrieval_subgraph_node())

    # 定义流程
    graph.set_entry_point("intent_clarification")
    graph.add_edge("intent_clarification", "retrieval")
    graph.add_edge("retrieval", END)

    # 编译
    return graph.compile()


def create_intent_subgraph_node():
    """
    创建意图澄清子图的包装节点
    """
    intent_graph = create_intent_clarification_graph()

    def intent_node(state: MainState) -> MainState:
        """意图澄清子图节点"""
        # 准备意图澄清子图的输入
        intent_input = {
            "original_query": state["user_query"]
        }

        # 传递自动确认标志（如果存在）
        if "auto_confirm" in state:
            intent_input["auto_confirm"] = state["auto_confirm"]

        # 执行意图澄清子图
        intent_output = intent_graph.invoke(intent_input)

        logger.info(f"[主Graph] 意图澄清输出的所有字段: {list(intent_output.keys())}")

        # 尝试多种可能的字段名
        clarified_intent = None

        # 可能的字段名列表
        possible_keys = ["clarified_intent", "extracted_parameters", "final_parameters"]

        for key in possible_keys:
            if key in intent_output:
                clarified_intent = intent_output[key]
                logger.info(f"[主Graph] 找到意图参数，字段名: {key}, 内容: {clarified_intent}")
                break

        # 如果还是没找到，直接从extracted_parameters获取
        if not clarified_intent and "extracted_parameters" in intent_output:
            extracted = intent_output["extracted_parameters"]
            logger.info(f"[主Graph] 使用extracted_parameters: {extracted}")
            clarified_intent = extracted

        # 转换为 ClarifiedIntent 模型
        if clarified_intent:
            from models.clarified_intent import ClarifiedIntent

            # 处理可能的字段名差异
            entities = clarified_intent.get("entities", [])
            properties = clarified_intent.get("properties", [])
            conditions = clarified_intent.get("conditions", {})

            logger.info(f"[主Graph] 提取参数: entities={entities}, properties={properties}, conditions={conditions}")

            state["intent_params"] = ClarifiedIntent(
                entities=entities,
                properties=properties,
                conditions=conditions
            )
        else:
            logger.error(f"[主Graph] 未找到任何意图参数！完整输出: {intent_output}")
            # 如果没有澄清结果，使用空的默认值
            from models.clarified_intent import ClarifiedIntent
            state["intent_params"] = ClarifiedIntent(
                entities=[],
                properties=[],
                conditions={}
            )

        logger.info(f"[主Graph] 最终intent_params: {state['intent_params']}")

        return state

    return intent_node


def create_retrieval_subgraph_node():
    """
    创建检索子图的包装节点
    """
    retrieval_graph = create_retrieval_graph()

    def retrieval_node(state: MainState) -> MainState:
        """检索子图节点"""

        logger.info(f"[主Graph] 传递给检索子图的intent_params: {state.get('intent_params')}")

        # 准备检索子图的输入
        retrieval_input = {
            "intent_params": state["intent_params"]
        }

        # 执行检索子图
        retrieval_output = retrieval_graph.invoke(retrieval_input)

        # 更新主State
        state["expanded_queries"] = retrieval_output.get("expanded_queries")
        state["papers"] = retrieval_output.get("papers")
        state["citation_papers"] = retrieval_output.get("citation_papers")
        state["filtered_papers"] = retrieval_output.get("filtered_papers")

        return state

    return retrieval_node
