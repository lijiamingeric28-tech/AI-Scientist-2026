"""工具函数模块"""

import json
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional
from openai import OpenAI

from ..state import IntentClarificationState
from ..config import config

logger = logging.getLogger(__name__)


def get_llm_client() -> OpenAI:
    """创建LLM客户端"""
    return OpenAI(
        base_url=config.llm['base_url'],
        api_key=config.llm['api_key']
    )


def classify_query_type(user_input: str) -> str:
    """
    分类查询类型

    使用规则 + LLM 的混合方式

    Args:
        user_input: 用户输入文本

    Returns:
        str: "astronomical" | "greeting" | "exit" | "invalid"
    """
    logger.debug(f"[classify_query_type] 输入: {user_input}")

    # 1. 规则检测：退出意图
    exit_keywords = config.exit_keywords
    if any(kw in user_input.lower() for kw in exit_keywords):
        logger.info("[classify_query_type] 检测到退出意图")
        return "exit"

    # 2. 规则检测：寒暄
    greeting_keywords = config.greeting_keywords
    if any(kw in user_input.lower() for kw in greeting_keywords) and len(user_input) < 15:
        logger.info("[classify_query_type] 检测到寒暄")
        return "greeting"

    # 3. LLM 检测：是否为天文学查询
    prompt = f"""判断以下用户输入是否为天文学相关查询。

用户输入：{user_input}

天文学相关查询包括：
- 查询天体的物理性质（恒星、星系、星团等）
- 提到天体名称（M31, NGC 224, Gaia DR3等）
- 询问天文观测数据
- 提到天文学术语（红移、视差、光度、星等、距离、金属丰度、温度、质量等）
- 即使没有提到具体天体名称，但询问的是天文物理量（如"距离是多少"、"红移多少"、"金属丰度"等）

天文学相关示例：
- "M31的距离"
- "距离是多少" （询问天文距离）
- "红移" （天文术语）
- "这个星系的质量"

非天文学查询示例：
- "今天天气怎么样"
- "帮我写一段代码"
- "什么是人工智能"
- "两地之间的距离" （地理距离，非天文）

请回答：
- "yes" 如果是天文学查询或询问天文物理量
- "no" 如果是完全无关的查询

只需回答 yes 或 no。"""

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=config.llm['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=config.llm['temperature'],
            max_tokens=10
        )

        result = response.choices[0].message.content.strip().lower()
        logger.debug(f"[classify_query_type] LLM响应: {result}")

        if "yes" in result:
            logger.info("[classify_query_type] 判定为天文学查询")
            return "astronomical"
        else:
            logger.info("[classify_query_type] 判定为非天文学查询")
            return "invalid"

    except Exception as e:
        logger.error(f"[classify_query_type] LLM调用失败: {e}")
        raise


def extract_entity_and_properties(
    user_input: str,
    chat_history: List[dict]
) -> dict:
    """
    使用 LLM 提取天体名称和性质列表

    Args:
        user_input: 用户输入
        chat_history: 对话历史

    Returns:
        dict: {
            "target_entity": str | None,
            "requested_properties": List[str]
        }
    """
    logger.debug(f"[extract_entity_and_properties] 输入: {user_input}")

    # 格式化对话历史
    history_text = ""
    for msg in chat_history[-6:]:  # 只保留最近3轮对话
        role = msg.get("role", "")
        content = msg.get("content", "")
        history_text += f"{role}: {content}\n"

    prompt = f"""你是一个天文学查询解析助手。从用户输入中提取以下信息：

1. **天体名称**（target_entity）：
   - 可以是标准名称：M31, NGC 224, IC 1101
   - 可以是通俗名称：仙女座星系, 室女A星系
   - 可以是星表标识符：Gaia DR3 5854013331201520640, 2MASS J12345678+0123456
   - **用户用中文或口语表达天体名时，必须翻译成英文官方标识符**：
     仙女座大星系 -> M31, 半人马座A -> NGC 5128, 草帽星系 -> M104, 昴星团 -> Pleiades
   - 输入已经是规范标识符（NGC/M/IC/HD/HIP/Gaia 等开头）时，原样输出，不要改写
   - 无法翻译时，输出用户原始输入
   - 如果没有找到，返回 null

2. **物理性质列表**（requested_properties）：
   - **保留用户原始表达**，不做任何翻译或标准化（例：用户说"距离"就输出"距离"，说"distance"就输出"distance"）
   - 标准化工作由后续性质标准化节点（P1）完成
   - 如果用户说"全部"、"所有"或类似表达，返回空列表 []
   - 如果用户直接回车或跳过，返回空列表 []
   - 如果没有提到具体性质，返回空列表 []

对话历史：
{history_text}

最新用户输入：{user_input}

请以严格的 JSON 格式返回（不要包含任何其他文本）：
{{
    "target_entity": "天体名称或null",
    "requested_properties": ["distance", "metallicity"] 或 []
}}

示例1：
用户输入："M31的距离和金属丰度"
返回：{{"target_entity": "M31", "requested_properties": ["距离", "金属丰度"]}}

示例2：
用户输入："仙女座星系"
返回：{{"target_entity": "M31", "requested_properties": []}}

示例3：
用户输入："全部"
返回：{{"target_entity": null, "requested_properties": []}}"""

    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=config.llm['model'],
            messages=[{"role": "user", "content": prompt}],
            temperature=config.llm['temperature'],
            max_tokens=config.llm['max_tokens']
        )

        response_text = response.choices[0].message.content
        logger.debug(f"[extract_entity_and_properties] LLM响应: {response_text}")

        # 提取 JSON 部分（防止 LLM 返回额外文本）
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(response_text)

        logger.info(f"[extract_entity_and_properties] 提取结果: {result}")

        return {
            "target_entity": result.get("target_entity"),
            "requested_properties": result.get("requested_properties", [])
        }

    except Exception as e:
        logger.error(f"[extract_entity_and_properties] 提取失败: {e}")
        raise


def get_latest_user_input(state: IntentClarificationState) -> str:
    """
    获取最新的用户输入

    Args:
        state: 当前状态

    Returns:
        str: 最新用户输入
    """
    chat_history = state.get("chat_history", [])

    if not chat_history:
        return state["user_query"]

    # 从后往前找第一条用户消息
    for msg in reversed(chat_history):
        if msg.get("role") == "user":
            return msg.get("content", "")

    # 如果没有找到，返回原始查询
    return state["user_query"]


def update_chat_history(
    state: IntentClarificationState,
    user_input: str
) -> None:
    """
    更新对话历史（仅在 initial_parse 中调用）

    Args:
        state: 当前状态
        user_input: 用户输入
    """
    chat_history = state.get("chat_history", [])

    # 只在首次调用时添加用户输入
    if not chat_history:
        chat_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })
        state["chat_history"] = chat_history


def format_chat_history(chat_history: List[dict]) -> str:
    """
    格式化对话历史为字符串

    Args:
        chat_history: 对话历史列表

    Returns:
        str: 格式化后的字符串
    """
    result = []
    for msg in chat_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        result.append(f"{role}: {content}")
    return "\n".join(result)
