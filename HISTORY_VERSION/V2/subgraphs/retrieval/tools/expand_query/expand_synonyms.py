"""使用LLM扩展同义词（支持中英文翻译）"""

from typing import List, Dict
import json
import logging
from shared.utils.llm_client import call_llm_structured
from config.prompts.retrieval import SYNONYM_EXPANSION_PROMPT

logger = logging.getLogger(__name__)


def expand_synonyms(
    entities: list[str],
    properties: list[str],
    domain: str = "astronomy"
) -> dict[str, list[str]]:
    """
    使用LLM扩展实体和属性的同义词，并自动翻译中文到英文

    Args:
        entities: 实体列表
        properties: 属性列表
        domain: 领域（默认astronomy）

    Returns:
        包含expanded_entities和expanded_properties的字典
    """
    prompt = SYNONYM_EXPANSION_PROMPT(entities, properties, domain)

    try:
        result = call_llm_structured(prompt, temperature=0.3)

        expanded_entities = result.get("expanded_entities", entities)
        expanded_properties = result.get("expanded_properties", properties)

        logger.info(f"同义词扩展完成: {len(expanded_entities)} entities, {len(expanded_properties)} properties")

        return {
            "expanded_entities": expanded_entities,
            "expanded_properties": expanded_properties
        }

    except Exception as e:
        logger.error(f"同义词扩展失败: {e}，使用原始输入")
        return {
            "expanded_entities": entities,
            "expanded_properties": properties
        }
