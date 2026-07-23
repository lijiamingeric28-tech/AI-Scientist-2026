"""
LLM调用统一封装

支持OpenAI兼容接口（如通义千问）
"""

from typing import Optional, Dict, Any
import json
import logging
import os
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)

# 全局客户端（延迟初始化）
_client: Optional[OpenAI] = None

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3.7-plus")


def _get_client() -> OpenAI:
    """获取或初始化OpenAI客户端（延迟初始化）"""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

        if not api_key:
            raise ValueError(
                "Missing OPENAI_API_KEY. Please set it in environment variables or .env file."
            )

        _client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"OpenAI client initialized with base_url={base_url}")

    return _client


def call_llm(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: int = 30
) -> str:
    """
    统一的LLM文本生成调用

    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词（可选）
        model: 模型名称
        temperature: 温度参数（0-1）
        max_tokens: 最大生成token数
        timeout: 超时时间（秒）

    Returns:
        LLM生成的文本

    Raises:
        TimeoutError: 调用超时
        ValueError: API返回错误
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        logger.debug(f"Calling LLM with model={model}, prompt length={len(prompt)}")

        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )

        content = response.choices[0].message.content
        logger.debug(f"LLM response length: {len(content)}")

        return content

    except Exception as e:
        logger.error(f"LLM call failed: {e}", exc_info=True)
        raise


def call_llm_structured(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    timeout: int = 30,
    response_format: Optional[type[BaseModel]] = None
) -> dict[str, Any]:
    """
    统一的LLM结构化输出调用

    使用JSON模式确保LLM返回有效的JSON格式

    Args:
        prompt: 用户提示词（应包含输出格式说明）
        system_prompt: 系统提示词
        model: 模型名称
        temperature: 温度参数
        timeout: 超时时间（秒）
        response_format: Pydantic模型类（可选，用于验证）

    Returns:
        解析后的JSON字典

    Raises:
        TimeoutError: 调用超时
        ValueError: JSON解析失败或格式校验失败
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        logger.debug(f"Calling LLM (JSON mode) with model={model}")

        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            timeout=timeout,
            response_format={"type": "json_object"}  # 强制JSON输出
        )

        content = response.choices[0].message.content
        logger.debug(f"LLM response: {content[:100]}...")

        # 解析JSON
        data = json.loads(content)

        # 如果提供了Pydantic模型，进行验证
        if response_format:
            try:
                validated = response_format(**data)
                return validated.model_dump()
            except ValidationError as e:
                logger.error(f"Validation failed: {e}")
                raise ValueError(f"Invalid response format: {e}")

        return data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        raise ValueError(f"LLM returned invalid JSON: {content}")
    except Exception as e:
        logger.error(f"LLM call failed: {e}", exc_info=True)
        raise
