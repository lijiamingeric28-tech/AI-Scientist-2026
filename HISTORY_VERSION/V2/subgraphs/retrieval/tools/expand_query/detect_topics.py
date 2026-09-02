"""使用LLM检测查询对应的OpenAlex Topics"""

from typing import List
import logging
from shared.utils.llm_client import call_llm
from config.prompts.retrieval import TOPIC_DETECTION_PROMPT, ASTRONOMY_TOPICS

logger = logging.getLogger(__name__)

def detect_topics_with_llm(
    user_query: str,
    entities: list[str],
    properties: list[str]
) -> list[str]:
    """
    使用LLM检测最相关的1-3个Topic ID

    Args:
        user_query: 用户原始查询
        entities: 实体列表
        properties: 属性列表

    Returns:
        Topic ID列表（如["T12450", "T11323"]），如果无法确定则返回空列表
    """
    # 构建Topic描述
    topic_descriptions = []
    for topic_id, info in ASTRONOMY_TOPICS.items():
        keywords_str = ", ".join(info["keywords"][:8])  # 只显示前8个关键词
        topic_descriptions.append(
            f"- {topic_id}: {info['name']}\n"
            f"  关键词: {keywords_str}\n"
            f"  说明: {info['description']}"
        )

    topics_text = "\n".join(topic_descriptions)

    prompt = TOPIC_DETECTION_PROMPT(user_query, entities, properties, topics_text)

    try:
        response = call_llm(prompt, temperature=0.0)

        # 解析响应
        response = response.strip()

        # 检查是否无法确定
        if not response or "UNKNOWN" in response.upper() or "无法确定" in response or "不确定" in response:
            logger.info("LLM无法确定具体Topic，将使用Subfield过滤")
            return []

        # 提取Topic ID
        topic_ids = []
        for part in response.split(","):
            part = part.strip()
            if part.startswith("T") and part[1:].isdigit():
                if part in ASTRONOMY_TOPICS:
                    topic_ids.append(part)
                else:
                    logger.warning(f"LLM返回了无效的Topic ID: {part}")

        if topic_ids:
            logger.info(f"LLM推荐Topics: {topic_ids}")
        else:
            logger.info("LLM未返回有效Topic ID，将使用Subfield过滤")

        return topic_ids[:3]  # 最多3个

    except Exception as e:
        logger.error(f"Topic检测失败: {e}")
        return []  # 失败时降级到Subfield
