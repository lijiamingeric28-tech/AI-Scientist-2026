"""
主图包装器

职责：
    为子图提供State转换和封装，使子图可以集成到主图中

包装器列表：
    - create_intent_wrapper: 意图澄清子图包装器
    - create_retrieval_wrapper: 检索子图包装器（待实现）
    - create_extraction_wrapper: 提取子图包装器（待实现）
    - create_quality_wrapper: 质量控制子图包装器（待实现）
"""

from typing import Callable
import logging

from main_graph.state import MainState

logger = logging.getLogger(__name__)


def create_intent_wrapper() -> Callable:
    """
    创建意图澄清子图的包装器

    State转换：
        MainState.user_query → IntentState.original_query
        MainState.query_context → IntentState.query_context
        IntentState.clarified_intent → MainState.intent_params
        IntentState.compromise_flag → MainState.compromise_flag

    Returns:
        包装后的节点函数
    """
    from subgraphs.intent_clarification.graph import compile_intent_clarification_graph

    logger.info("Compiling intent clarification subgraph")
    intent_graph = compile_intent_clarification_graph()
    logger.info("Intent clarification subgraph compiled successfully")

    def intent_wrapper_node(state: MainState) -> MainState:
        """意图澄清包装节点"""
        logger.info("=" * 70)
        logger.info("Entering Intent Clarification Subgraph")
        logger.info("=" * 70)

        # 1. MainState → IntentState
        logger.debug("Converting MainState to IntentState")
        intent_input = {
            "original_query": state["user_query"],
            "query_context": state.get("query_context", {}),
            "_auto_confirm": True  # 主图中默认使用自动确认模式
        }
        logger.info(f"Input to subgraph: original_query='{intent_input['original_query']}'")

        # 2. 调用子图
        logger.info("Invoking intent clarification subgraph...")
        intent_output = intent_graph.invoke(intent_input)
        logger.info("Intent clarification subgraph completed")

        # 3. IntentState → MainState
        logger.debug("Converting IntentState back to MainState")

        # 使用clarified_intent作为主要输出
        clarified_intent = intent_output.get("clarified_intent", {})
        state["intent_params"] = clarified_intent
        state["compromise_flag"] = intent_output.get("compromise_flag", False)

        # 保留query_context，确保传递给下游子图
        # state["query_context"] 已经存在，无需重新设置

        logger.info(f"Output from subgraph: intent_params={clarified_intent}")
        logger.info(f"Compromise flag: {state['compromise_flag']}")
        logger.info(f"Query context preserved: {state.get('query_context', {})}")

        logger.info("=" * 70)
        logger.info("Exiting Intent Clarification Subgraph")
        logger.info("=" * 70)

        return state

    return intent_wrapper_node


def create_retrieval_wrapper() -> Callable:
    """
    创建检索子图的包装器

    State转换：
        MainState.intent_params → RetrievalState.intent_params
        MainState.user_query → RetrievalState.user_query
        RetrievalState.filtered_papers → MainState.papers

    Returns:
        包装后的节点函数
    """
    from subgraphs.retrieval.graph import create_retrieval_graph
    from config.constants import ENABLE_CITATION_EXPANSION

    logger.info("Compiling retrieval subgraph")
    # 使用配置文件中的引用扩展开关
    retrieval_graph = create_retrieval_graph(enable_citation_expansion=ENABLE_CITATION_EXPANSION)
    logger.info(f"Retrieval subgraph compiled (citation_expansion={ENABLE_CITATION_EXPANSION})")

    def retrieval_wrapper_node(state: MainState) -> MainState:
        """检索子图包装节点"""
        logger.info("=" * 70)
        logger.info("Entering Retrieval Subgraph")
        logger.info("=" * 70)

        # 1. MainState → RetrievalState
        logger.debug("Converting MainState to RetrievalState")
        retrieval_input = {
            "intent_params": state["intent_params"],
            "user_query": state.get("user_query", ""),
            "query_context": state.get("query_context", {})  # 传递query_context
        }
        logger.info(f"Input to subgraph: intent_params={retrieval_input['intent_params']}")

        # 2. 调用子图
        logger.info("Invoking retrieval subgraph...")
        retrieval_output = retrieval_graph.invoke(retrieval_input)
        logger.info("Retrieval subgraph completed")

        # 3. RetrievalState → MainState
        logger.debug("Converting RetrievalState back to MainState")

        # 使用filtered_papers作为主要输出
        filtered_papers = retrieval_output.get("filtered_papers", [])
        state["papers"] = filtered_papers

        logger.info(f"Output from subgraph: {len(filtered_papers)} papers retrieved")

        # 统计下载成功的论文
        if filtered_papers:
            success_count = sum(1 for p in filtered_papers if p.download_status == "success")
            logger.info(f"Successfully downloaded: {success_count}/{len(filtered_papers)} papers")

        logger.info("=" * 70)
        logger.info("Exiting Retrieval Subgraph")
        logger.info("=" * 70)

        return state

    return retrieval_wrapper_node


def create_extraction_wrapper() -> Callable:
    """
    创建提取子图的包装器

    State转换：
        MainState.intent_params → ExtractionState.intent_params
        MainState.papers → ExtractionState.filtered_papers
        ExtractionState.grounded_data → MainState.grounded_data
        ExtractionState.verification_rate → MainState.verification_rate
        ExtractionState.extraction_report → MainState.extraction_report

    Returns:
        包装后的节点函数
    """
    from subgraphs.extraction.graph import compile_extraction_graph

    logger.info("Compiling extraction subgraph")
    extraction_graph = compile_extraction_graph()
    logger.info("Extraction subgraph compiled successfully")

    def extraction_wrapper_node(state: MainState) -> MainState:
        """提取子图包装节点"""
        logger.info("=" * 70)
        logger.info("Entering Extraction Subgraph")
        logger.info("=" * 70)

        # 1. MainState → ExtractionState
        logger.debug("Converting MainState to ExtractionState")
        extraction_input = {
            "intent_params": state["intent_params"],
            "filtered_papers": state["papers"]
        }
        logger.info(f"Input to subgraph: {len(extraction_input['filtered_papers'])} papers")

        # 2. 调用子图
        logger.info("Invoking extraction subgraph...")
        extraction_output = extraction_graph.invoke(extraction_input)
        logger.info("Extraction subgraph completed")

        # 3. ExtractionState → MainState
        logger.debug("Converting ExtractionState back to MainState")

        state["grounded_data"] = extraction_output["grounded_data"]
        state["verification_rate"] = extraction_output["verification_rate"]
        state["extraction_report"] = extraction_output["extraction_report"]

        logger.info(f"Output from subgraph:")
        logger.info(f"  - Sources: {len(extraction_output['grounded_data']['sources'])}")
        logger.info(f"  - Records: {len(extraction_output['grounded_data']['records'])}")
        logger.info(f"  - Verification rate: {extraction_output['verification_rate']*100:.1f}%")

        logger.info("=" * 70)
        logger.info("Exiting Extraction Subgraph")
        logger.info("=" * 70)

        return state

    return extraction_wrapper_node


def create_quality_wrapper() -> Callable:
    """
    创建质检子图的包装器

    State转换：
        MainState.grounded_data → QualityGraphState.data_state.input_data
        MainState.intent_params → QualityGraphState.context_state.clarified_intent
        QualityGraphState.output_state.final_data → MainState.final_output
        QualityGraphState.output_state.quality_report → MainState.quality_summary

    Returns:
        包装后的节点函数
    """
    from subgraphs.quality.graph import compile_quality_graph

    logger.info("Compiling quality subgraph")
    quality_graph = compile_quality_graph()
    logger.info("Quality subgraph compiled successfully")

    def quality_wrapper_node(state: MainState) -> MainState:
        """质检子图包装节点"""
        logger.info("=" * 70)
        logger.info("Entering Quality Subgraph")
        logger.info("=" * 70)

        # 1. MainState → QualityGraphState
        logger.debug("Converting MainState to QualityGraphState")

        # 构建质检子图的输入
        quality_input = {
            "context_state": {
                "clarified_intent": state.get("intent_params", {}),
                "research_domain": "astronomy",  # 默认天文领域
            },
            "data_state": {
                "input_data": state.get("grounded_data", {}),
                "current_data": state.get("grounded_data", {}),
                "data_trace": [],
            },
            "report_state": {},
            "workflow_state": {
                "current_node": "start",
                "execution_status": "Success",
                "iteration_counter": 0,
                "retry_counter": 0,
                "route_decision": "",
                "workflow_history": [],
                "run_id": "",
                "graph_version": "1.0",
            },
            "output_state": {},
        }

        # 记录输入统计
        input_data = quality_input["data_state"]["input_data"]
        records_count = len(input_data.get("records", [])) if input_data else 0
        sources_count = len(input_data.get("sources", [])) if input_data else 0

        logger.info(f"Input to subgraph:")
        logger.info(f"  - Sources: {sources_count}")
        logger.info(f"  - Records: {records_count}")

        # 2. 调用子图
        logger.info("Invoking quality subgraph...")
        quality_output = quality_graph.invoke(quality_input)
        logger.info("Quality subgraph completed")

        # 3. QualityGraphState → MainState
        logger.debug("Converting QualityGraphState back to MainState")

        # 提取输出
        output_state = quality_output.get("output_state", {})
        report_state = quality_output.get("report_state", {})

        # structured_data的结构是: {json: {sources, records}, csv: "...", ...}
        structured_data = output_state.get("structured_data", {})

        # 从structured_data.json中提取真正的grounded_data格式数据
        json_data = structured_data.get("json", {})

        state["final_output"] = {
            "sources": json_data.get("sources", []),
            "records": json_data.get("records", []),
            "schema_version": "1.1.0",
        }

        state["quality_summary"] = {
            "quality_report": report_state.get("quality"),
            "conflict_report": report_state.get("conflict"),
            "normalization_report": report_state.get("normalization"),
            "export_path": output_state.get("export_path", ""),
            "row_count": structured_data.get("row_count", 0),
            "column_count": structured_data.get("column_count", 0),
        }

        # 记录输出统计
        final_data = state.get("final_output", {})
        final_records_count = len(final_data.get("records", [])) if final_data else 0
        final_sources_count = len(final_data.get("sources", [])) if final_data else 0

        logger.info(f"Output from subgraph:")
        logger.info(f"  - Final sources: {final_sources_count}")
        logger.info(f"  - Final records: {final_records_count}")
        logger.info(f"  - Filtered: {records_count - final_records_count} records")

        logger.info("=" * 70)
        logger.info("Exiting Quality Subgraph")
        logger.info("=" * 70)

        return state

    return quality_wrapper_node


def create_quality_wrapper() -> Callable:
    """
    创建Quality子图的wrapper

    输入: MainState（包含grounded_data）
    输出: MainState（添加final_output和quality_summary）
    """
    from subgraphs.quality.graph import compile_quality_graph
    from subgraphs.quality.state import QualityGraphState

    quality_graph = compile_quality_graph()

    def quality_wrapper(state: MainState) -> MainState:
        """Quality子图的wrapper函数"""
        logger.info("Executing quality control subgraph")

        # 1. MainState → QualityGraphState
        grounded_data = state.get("grounded_data", {})
        intent_params = state.get("intent_params", {})

        quality_input: QualityGraphState = {
            "context_state": {
                "clarified_intent": intent_params,
                "research_domain": "astronomy",
            },
            "data_state": {
                "input_data": grounded_data,
                "current_data": grounded_data,
                "data_trace": [],
            },
            "report_state": {},
            "workflow_state": {
                "current_node": "start",
                "execution_status": "Success",
                "iteration_counter": 0,
                "retry_counter": 0,
                "route_decision": "",
                "workflow_history": [],
            },
            "output_state": {},
        }

        # 2. 调用Quality子图
        logger.info("Invoking quality subgraph")
        quality_output = quality_graph.invoke(quality_input)

        # 3. QualityGraphState → MainState
        logger.info("Converting quality output back to MainState")

        output_state = quality_output.get("output_state", {})
        report_state = quality_output.get("report_state", {})

        # structured_data的结构是: {json: {sources, records}, csv: "...", ...}
        structured_data = output_state.get("structured_data", {})
        json_data = structured_data.get("json", {})

        state["final_output"] = {
            "sources": json_data.get("sources", []),
            "records": json_data.get("records", []),
            "schema_version": "1.1.0",
        }

        state["quality_summary"] = {
            "quality_report": report_state.get("quality"),
            "conflict_report": report_state.get("conflict"),
            "normalization_report": report_state.get("normalization"),
            "export_path": output_state.get("export_path", ""),
            "row_count": structured_data.get("row_count", 0),
            "column_count": structured_data.get("column_count", 0),
        }

        logger.info("Quality subgraph completed successfully")
        return state

    return quality_wrapper
