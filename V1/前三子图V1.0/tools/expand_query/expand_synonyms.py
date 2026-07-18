"""使用LLM扩展同义词（支持中英文翻译）"""

from typing import List, Dict
import json
import logging
from utils.llm_client import call_llm_structured

logger = logging.getLogger(__name__)


def expand_synonyms(
    entities: List[str],
    properties: List[str],
    domain: str = "astronomy"
) -> Dict[str, List[str]]:
    """
    使用LLM扩展实体和属性的同义词，并自动翻译中文到英文

    Args:
        entities: 实体列表
        properties: 属性列表
        domain: 领域（默认astronomy）

    Returns:
        包含expanded_entities和expanded_properties的字典
    """
    prompt = f"""你是{domain}领域的专家。请为以下实体和属性生成同义词扩展，包括：
1. 英文同义词、缩写、全称
2. 如果输入是中文，必须翻译为对应的英文术语
3. 相关的技术术语和变体

输入：
实体（entities）: {entities}
属性（properties）: {properties}

要求：
- 保留原始词汇
- 添加同义词、缩写、全称
- **中文词汇必须翻译为英文**（OpenAlex只支持英文）
- 单复数变体
- 专业术语的标准写法

示例1（天文学）：
输入：entities=["快速射电暴"], properties=["色散量"]
输出：
{{
    "expanded_entities": ["快速射电暴", "FRB", "fast radio burst", "fast radio bursts", "fast radio transient"],
    "expanded_properties": ["色散量", "dispersion measure", "DM", "dispersion", "DM value"]
}}

示例2（天文学）：
输入：entities=["FRB"], properties=["red shift"]
输出：
{{
    "expanded_entities": ["FRB", "fast radio burst", "fast radio bursts", "fast radio transient"],
    "expanded_properties": ["red shift", "redshift", "z", "cosmological redshift"]
}}

请严格按照JSON格式输出，不要添加其他文字：
"""

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
