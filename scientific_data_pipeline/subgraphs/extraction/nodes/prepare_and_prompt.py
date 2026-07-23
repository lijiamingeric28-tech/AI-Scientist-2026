"""
Agent 1: Prepare_and_Prompt_Node
准备与Prompt生成
"""

import json
import logging
from subgraphs.extraction.state import ExtractionState
from config.prompts.extraction import NORMALIZATION_PROMPT, NORMALIZATION_SCHEMA, generate_vlm_prompt
from subgraphs.extraction.tools import call_vlm_api

logger = logging.getLogger(__name__)


def prepare_and_prompt_node(state: ExtractionState) -> ExtractionState:
    """
    Agent 1: 准备与Prompt生成

    职责:
    1. 使用LLM规范化intent_params
    2. 生成VLM Prompt
    3. 构建提取任务队列
    """
    logger.info("=" * 80)
    logger.info("[Agent 1] Prepare_and_Prompt_Node started")
    logger.info("=" * 80)

    intent_params = state["intent_params"]
    papers = state["filtered_papers"]

    logger.info(f"[Agent 1] Input intent_params: {intent_params}")
    logger.info(f"[Agent 1] Received {len(papers)} filtered papers")

    # Step 1: 使用LLM规范化参数
    logger.info("[Agent 1][Step 1] Starting intent normalization with LLM")
    normalized_params = normalize_intent_with_llm(intent_params)

    logger.info(f"[Agent 1][Step 1] Normalization completed:")
    logger.info(f"  - entity_type: {normalized_params['entity_type']}")
    logger.info(f"  - property_name: {normalized_params['property_name']}")

    # Step 2: 生成VLM Prompt
    logger.info("[Agent 1][Step 2] Generating VLM extraction prompt")
    extraction_prompt = generate_vlm_prompt(
        normalized_params["entity_type"],
        normalized_params["property_name"]
    )
    logger.debug(f"[Agent 1][Step 2] Generated prompt length: {len(extraction_prompt)} chars")

    # Step 3: 构建任务队列
    logger.info("[Agent 1][Step 3] Building extraction task queue")
    tasks = []
    skipped = 0

    for paper in papers:
        # PaperMetadata是Pydantic模型，使用属性访问
        if paper.download_status == "success" and paper.local_path:
            tasks.append({
                "paper_id": paper.id,
                "pdf_path": paper.local_path,
                "paper_title": paper.title,
                "max_pages": None  # 处理所有页
            })
            logger.debug(f"  Task added: {paper.id} | {paper.title[:50]}...")
        else:
            skipped += 1

    logger.info(f"[Agent 1][Step 3] Task queue built: {len(tasks)} tasks, {skipped} papers skipped")

    # 更新State
    state["normalized_params"] = normalized_params
    state["extraction_prompt"] = extraction_prompt
    state["extraction_tasks"] = tasks

    logger.info("[Agent 1] Prepare_and_Prompt_Node completed")
    logger.info("=" * 80)

    return state


def normalize_intent_with_llm(intent_params) -> dict:
    """
    使用LLM规范化intent参数

    Args:
        intent_params: ClarifiedIntent对象或字典

    Returns:
        {
            "entity_type": str,
            "property_name": str
        }
    """
    # 提取entities和properties（兼容字典和Pydantic对象）
    if isinstance(intent_params, dict):
        # 如果是字典，直接访问键
        entities = intent_params.get('entities', [])
        properties = intent_params.get('properties', [])
    else:
        # 如果是Pydantic对象，访问属性
        entities = intent_params.entities if hasattr(intent_params, 'entities') else []
        properties = intent_params.properties if hasattr(intent_params, 'properties') else []

    logger.debug(f"[Normalize] Raw entities: {entities}")
    logger.debug(f"[Normalize] Raw properties: {properties}")

    # 构建Prompt
    prompt = NORMALIZATION_PROMPT.format(
        entities=", ".join(entities) if entities else "unknown",
        properties=", ".join(properties) if properties else "unknown"
    )

    logger.debug(f"[Normalize] Calling LLM for normalization")

    # 调用LLM
    content = [{"type": "text", "text": prompt}]

    try:
        result_text = call_vlm_api(content, schema=NORMALIZATION_SCHEMA)
        normalized = json.loads(result_text)

        logger.info(f"[Normalize] Success: entity_type={normalized['entity_type']}, property_name={normalized['property_name']}")
        return normalized

    except Exception as e:
        logger.error(f"[Normalize] LLM call failed: {e}")
        logger.warning(f"[Normalize] Falling back to direct use of first entity/property")

        # 降级：直接使用第一个entity/property
        fallback = {
            "entity_type": entities[0] if entities else "unknown",
            "property_name": properties[0] if properties else "unknown"
        }
        logger.info(f"[Normalize] Fallback result: {fallback}")
        return fallback
