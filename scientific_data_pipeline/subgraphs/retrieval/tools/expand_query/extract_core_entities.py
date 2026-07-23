"""从意图参数中提取核心实体和属性"""

from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


def extract_core_entities(intent_params) -> dict[str, Any]:
    """
    从意图参数中提取核心实体、属性和条件

    Args:
        intent_params: 意图参数对象（包含entities, properties, conditions）

    Returns:
        包含entities, properties, conditions的字典
    """
    # 提取entities
    if hasattr(intent_params, 'entities'):
        entities = intent_params.entities
    elif isinstance(intent_params, dict):
        entities = intent_params.get('entities', [])
    else:
        entities = []

    # 确保是列表
    if isinstance(entities, str):
        entities = [entities]
    elif not isinstance(entities, list):
        entities = []

    # 提取properties
    if hasattr(intent_params, 'properties'):
        properties = intent_params.properties
    elif isinstance(intent_params, dict):
        properties = intent_params.get('properties', [])
    else:
        properties = []

    # 确保是列表
    if isinstance(properties, str):
        properties = [properties]
    elif not isinstance(properties, list):
        properties = []

    # 提取conditions
    if hasattr(intent_params, 'conditions'):
        conditions = intent_params.conditions
    elif isinstance(intent_params, dict):
        conditions = intent_params.get('conditions', {})
    else:
        conditions = {}

    # 确保是字典
    if not isinstance(conditions, dict):
        conditions = {}

    logger.debug(f"Extracted: {len(entities)} entities, {len(properties)} properties")

    return {
        "entities": entities,
        "properties": properties,
        "conditions": conditions
    }
