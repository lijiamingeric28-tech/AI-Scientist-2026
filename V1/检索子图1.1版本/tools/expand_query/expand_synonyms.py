"""
使用LLM扩展同义词和变体
"""

from typing import List, Dict
import logging
from tools.common.retry import retry_on_failure
from utils.llm_client import call_llm_structured

logger = logging.getLogger(__name__)

SYNONYM_EXPANSION_PROMPT = """
你是科学文献检索专家。用户想要检索以下实体和属性的学术论文。

目标实体（材料、化合物、天体等）：
{entities}

目标属性（力学性能、物理常数等）：
{properties}

领域：{domain}

请为每个实体和属性生成同义词、变体、缩写和相关术语，用于扩展学术文献检索范围。

要求：
1. 实体变体：包括别名、不同命名规范、标准编号、常见缩写
2. 属性变体：包括全称、缩写、符号、不同语言表达
3. 只生成学术界常用的术语，不要猜测或发明
4. 每个术语最多生成5个变体

输出JSON格式：
{{
    "expanded_entities": ["原实体1", "变体1", "变体2", ...],
    "expanded_properties": ["原属性1", "变体1", "变体2", ...]
}}

示例：
输入：entities=["Al-7075"], properties=["yield_strength"]
输出：
{{
    "expanded_entities": ["Al-7075", "aluminum 7075", "AA7075", "7075铝合金", "7075 alloy"],
    "expanded_properties": ["yield strength", "YS", "σy", "屈服强度", "yield stress"]
}}
"""


@retry_on_failure(max_attempts=2, timeout=60)
def expand_synonyms(
    entities: List[str],
    properties: List[str],
    domain: str = "materials_science"
) -> Dict[str, List[str]]:
    """
    使用LLM扩展同义词和变体

    Args:
        entities: 目标实体列表
        properties: 目标属性列表
        domain: 领域（默认材料科学）

    Returns:
        {
            "expanded_entities": [...],
            "expanded_properties": [...]
        }

    Raises:
        TimeoutError: 调用超时
        ValueError: LLM返回格式错误

    Fallback:
        如果连续2次失败，返回原词：
        {
            "expanded_entities": entities,
            "expanded_properties": properties
        }
    """
    try:
        prompt = SYNONYM_EXPANSION_PROMPT.format(
            entities=", ".join(entities),
            properties=", ".join(properties),
            domain=domain
        )

        logger.debug(f"Calling LLM for synonym expansion")

        result = call_llm_structured(
            prompt=prompt,
            temperature=0.5,
            timeout=60
        )

        expanded_entities = result.get("expanded_entities", entities)
        expanded_properties = result.get("expanded_properties", properties)

        logger.info(f"Expanded to {len(expanded_entities)} entity variants, {len(expanded_properties)} property variants")

        return {
            "expanded_entities": expanded_entities,
            "expanded_properties": expanded_properties
        }

    except Exception as e:
        logger.error(f"Synonym expansion failed: {e}")
        # Fallback: 返回原词
        logger.warning("Using original terms as fallback")
        return {
            "expanded_entities": entities,
            "expanded_properties": properties
        }
