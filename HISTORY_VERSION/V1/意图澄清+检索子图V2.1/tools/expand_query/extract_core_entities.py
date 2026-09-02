"""
从ClarifiedIntent中提取核心实体和属性
"""

from models.clarified_intent import ClarifiedIntent
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


def extract_core_entities(intent_params: ClarifiedIntent) -> Dict[str, any]:
    """
    从ClarifiedIntent中提取核心实体和属性

    Args:
        intent_params: 意图澄清子图输出的结构化参数

    Returns:
        {
            "entities": ["Al-7075", "Al-6061"],
            "properties": ["yield_strength", "tensile_strength"],
            "conditions": {"temperature": "200-400°C", "year": "2015-2025"}
        }

    Raises:
        ValueError: intent_params格式错误
    """
    try:
        entities = intent_params.entities if intent_params.entities else []
        properties = intent_params.properties if intent_params.properties else []
        conditions = intent_params.conditions if intent_params.conditions else {}

        logger.debug(f"Extracted {len(entities)} entities, {len(properties)} properties")

        return {
            "entities": entities,
            "properties": properties,
            "conditions": conditions
        }

    except Exception as e:
        logger.error(f"Failed to extract core entities: {e}")
        raise ValueError(f"Invalid intent_params format: {e}")
