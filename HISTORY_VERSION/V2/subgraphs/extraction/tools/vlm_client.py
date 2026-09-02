"""
VLM API 客户端
"""

import json
import logging
import os
from openai import OpenAI
from typing import List, Dict

logger = logging.getLogger(__name__)


def get_vlm_client():
    """获取VLM客户端"""
    # 从环境变量读取
    api_key = os.getenv('OPENAI_API_KEY') or os.getenv('QWEN_API_KEY')
    base_url = os.getenv('OPENAI_BASE_URL') or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    if not api_key:
        raise ValueError("API key not found. Please set OPENAI_API_KEY or QWEN_API_KEY environment variable")

    return OpenAI(
        api_key=api_key,
        base_url=base_url
    )


def call_vlm_api(content: list[Dict], schema: Dict = None) -> str:
    """
    调用VLM API

    Args:
        content: 消息内容列表（包含图像和文本）
        schema: Structured Output Schema（可选）

    Returns:
        VLM返回的JSON字符串
    """
    from config.prompts.extraction import VLM_EXTRACTION_SCHEMA
    from config.constants import VLM_MODEL, VLM_MAX_TOKENS, VLM_TEMPERATURE

    client = get_vlm_client()

    # 构建请求参数
    request_params = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": VLM_MAX_TOKENS,
        "temperature": VLM_TEMPERATURE
    }

    # 添加Structured Output（如果提供）
    if schema:
        request_params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "scientific_observations",
                "strict": True,
                "schema": schema
            }
        }

    try:
        response = client.chat.completions.create(**request_params)
        result = response.choices[0].message.content
        logger.debug(f"VLM调用成功，返回长度: {len(result)}")
        return result

    except Exception as e:
        logger.error(f"VLM调用失败: {e}")
        raise
