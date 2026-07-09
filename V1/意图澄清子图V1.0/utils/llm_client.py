"""
LLM调用统一封装
"""
from typing import Optional, Any
import json
from openai import OpenAI
import logging
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# 全局客户端（使用兼容OpenAI接口的QWEN）
# 注意：实际使用时需要配置正确的API key和base_url
client = OpenAI(
    api_key="sk-ws-H.EMEREIX.0cHI.MEYCIQCG51Pbp-XLPWpQ5XIT_Sw0I8x5JO48UNirZrNA5wmVjwIhALOGvIYHpvNtaJn6JezHJx7anxlA72jD_WlFaUiBjxXT",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"  # QWEN兼容接口
)

DEFAULT_MODEL = "qwen3.7-plus"  # Qwen3.7-Plus模型


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
        temperature: 温度参数（0.0-2.0）
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
) -> dict:
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
        logger.debug(f"Calling LLM (structured) with model={model}")

        # 使用JSON模式（OpenAI兼容接口）
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            timeout=timeout,
            response_format={"type": "json_object"}  # 强制JSON输出
        )

        content = response.choices[0].message.content

        # 解析JSON
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {content}")
            raise ValueError(f"LLM returned invalid JSON: {e}")

        # 如果提供了Pydantic模型，进行验证
        if response_format:
            try:
                validated = response_format(**result)
                result = validated.model_dump()
            except ValidationError as e:
                logger.error(f"JSON validation failed: {e}")
                raise ValueError(f"LLM response doesn't match schema: {e}")

        logger.debug(f"Structured response: {result}")
        return result

    except Exception as e:
        logger.error(f"Structured LLM call failed: {e}", exc_info=True)
        raise
