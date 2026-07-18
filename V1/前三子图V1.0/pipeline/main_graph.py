"""
主Graph定义

连接所有子图的主流程
"""

from langgraph.graph import StateGraph, END
from state.main_state import MainState
from pipeline.intent.graph import create_intent_clarification_graph
from pipeline.retrieval.graph import create_retrieval_graph
from pipeline.extraction.graph import create_extraction_graph
import logging

logger = logging.getLogger(__name__)


def create_main_graph():
    """
    创建主流程Graph

    流程：
    1. 意图澄清
    2. 文献检索
    3. 数据提取（V2.0新增）
    4. (未来) 数据清洗

    Returns:
        编译后的主Graph
    """
    # 创建主Graph
    graph = StateGraph(MainState)

    # 添加子图节点
    graph.add_node("intent_clarification", create_intent_subgraph_node())
    graph.add_node("retrieval", create_retrieval_subgraph_node())
    graph.add_node("extraction", create_extraction_subgraph_node())  # 新增

    # 定义流程
    graph.set_entry_point("intent_clarification")
    graph.add_edge("intent_clarification", "retrieval")
    graph.add_edge("retrieval", "extraction")  # 新增
    graph.add_edge("extraction", END)

    # 编译
    return graph.compile()


def create_intent_subgraph_node():
    """创建意图澄清子图的包装节点"""
    intent_graph = create_intent_clarification_graph()

    def intent_node(state: MainState) -> MainState:
        """意图澄清子图节点"""
        intent_input = {
            "original_query": state["user_query"]
        }

        if "auto_confirm" in state:
            intent_input["auto_confirm"] = state["auto_confirm"]

        intent_output = intent_graph.invoke(intent_input)

        logger.info(f"[主Graph] 意图澄清输出的所有字段: {list(intent_output.keys())}")

        clarified_intent = None
        possible_keys = ["clarified_intent", "extracted_parameters", "final_parameters"]

        for key in possible_keys:
            if key in intent_output:
                clarified_intent = intent_output[key]
                logger.info(f"[主Graph] 找到意图参数，字段名: {key}")
                break

        if not clarified_intent and "extracted_parameters" in intent_output:
            clarified_intent = intent_output["extracted_parameters"]

        if clarified_intent:
            from models.clarified_intent import ClarifiedIntent

            entities = clarified_intent.get("entities", [])
            properties = clarified_intent.get("properties", [])
            conditions = clarified_intent.get("conditions", {})

            state["intent_params"] = ClarifiedIntent(
                entities=entities,
                properties=properties,
                conditions=conditions
            )
        else:
            logger.error(f"[主Graph] 未找到意图参数")
            from models.clarified_intent import ClarifiedIntent
            state["intent_params"] = ClarifiedIntent(
                entities=[],
                properties=[],
                conditions={}
            )

        return state

    return intent_node


def create_retrieval_subgraph_node():
    """创建检索子图的包装节点"""
    retrieval_graph = create_retrieval_graph()

    def retrieval_node(state: MainState) -> MainState:
        """检索子图节点"""
        logger.info(f"[主Graph] 进入检索子图")

        retrieval_input = {
            "intent_params": state["intent_params"]
        }

        retrieval_output = retrieval_graph.invoke(retrieval_input)

        state["expanded_queries"] = retrieval_output.get("expanded_queries")
        state["papers"] = retrieval_output.get("papers")
        state["citation_papers"] = retrieval_output.get("citation_papers")
        state["filtered_papers"] = retrieval_output.get("filtered_papers")

        logger.info(f"[主Graph] 检索子图完成")

        return state

    return retrieval_node


def create_extraction_subgraph_node():
    """创建提取子图的包装节点（V2.0新增）"""
    extraction_graph = create_extraction_graph()

    def extraction_node(state: MainState) -> MainState:
        """提取子图节点"""
        logger.info(f"[主Graph] 进入提取子图")

        # 过滤：只保留下载成功的papers
        filtered_papers = state.get("filtered_papers", [])
        logger.info(f"[主Graph] 收到 {len(filtered_papers)} 篇papers")

        # 只保留download_status="success"且有local_path的paper
        valid_papers = [
            p for p in filtered_papers
            if p.download_status == "success" and p.local_path
        ]

        skipped_count = len(filtered_papers) - len(valid_papers)
        if skipped_count > 0:
            logger.info(f"[主Graph] 过滤掉 {skipped_count} 篇下载失败/跳过的papers")
        logger.info(f"[主Graph] 实际处理 {len(valid_papers)} 篇已下载的papers")

        if not valid_papers:
            logger.warning(f"[主Graph] 没有可提取的papers，跳过提取子图")
            state["grounded_data"] = {
                "schema_version": "1.1.0",
                "sources": [],
                "records": []
            }
            state["verification_rate"] = 0.0
            state["extraction_report"] = "No valid papers for extraction"
            return state

        # 准备输入
        extraction_input = {
            "intent_params": state["intent_params"],
            "filtered_papers": valid_papers
        }

        # 执行提取子图
        extraction_output = extraction_graph.invoke(extraction_input)

        # 更新主State
        state["grounded_data"] = extraction_output["grounded_data"]
        state["verification_rate"] = extraction_output["verification_rate"]
        state["extraction_report"] = extraction_output.get("extraction_report", "")

        logger.info(f"[主Graph] 提取子图完成，验证率: {state['verification_rate']*100:.1f}%")

        return state

    return extraction_node
