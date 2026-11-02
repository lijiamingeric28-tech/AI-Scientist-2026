"""工具函数模块"""

import json
import re
import time
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


def _keyword_hit(text_lower: str, kw_lower: str) -> bool:
    """整词/整句关键词匹配 — 修复子串误判 (R1-E10)。

    原实现 `kw in user_input` 是子串匹配: 退出词/寒暄词的子串会命中正常查询
    (如 'NGC224' 之类含数字短词的天体标识), 导致天文查询被误判为退出/寒暄。

    匹配策略 (按宽松度递增):
    1. 输入 strip 后与关键词精确相等 → 命中
    2. 输入以关键词开头且长度接近 (尾随 ≤2 个语气词/标点, 如 "退出吧"、"bye.")
       → 命中
    3. 关键词作为独立 token 出现: 前后必须是边界 (字符串首尾 / 空白 / 非
       汉字非 ASCII 字母数字的标点) → 命中; 嵌入词内 (如 "我想退出" 中
       "退出" 前有汉字) 不算独立 token, 交给 LLM 判定
    """
    text = text_lower.strip()
    kw = kw_lower.strip()
    if not text or not kw:
        return False
    if text == kw:
        return True
    if text.startswith(kw) and len(text) - len(kw) <= 2:
        return True
    # 独立 token: 前后均不是汉字/ASCII 字母数字/下划线 (即边界或标点)
    return re.search(rf"(?<![\w一-鿿]){re.escape(kw)}(?![\w一-鿿])", text) is not None


# 寒暄尾部允许的纯语气词/标点字符 (L-04)
_PARTICLE_CHARS = set("呀啊哦啦哈呢吧吗诶嗯哟哦！!？?~～。，,、… ")

# H-06: LLM 调用指数退避重试延迟 (初始调用后最多重试 2 次: 0.5s / 1s)
_RETRY_DELAYS = (0.5, 1.0)


def _is_greeting_exact(text_lower: str, kw_lower: str) -> bool:
    """寒暄精确门限 (L-04): 输入 strip 后精确等于关键词, 或关键词后仅剩
    语气词/标点; 含实义内容的输入 (如 "你好 M31 的距离是多少") 不判寒暄,
    交给 LLM 分类。

    替代旧实现 `_keyword_hit + len<15`: 独立 token 前缀命中会把含问候语的
    真实天文查询确定性误判为 greeting, 导致实体解析被跳过、用户被迫重输。
    """
    text = text_lower.strip()
    kw = kw_lower.strip()
    if not text or not kw:
        return False
    if text == kw:
        return True
    if text.startswith(kw):
        return all(c in _PARTICLE_CHARS for c in text[len(kw):])
    return False


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

    # 1. 规则检测：退出意图 (R1-E10: 整词匹配, 非子串)
    exit_keywords = config.exit_keywords
    user_lower = (user_input or "").lower()
    if any(_keyword_hit(user_lower, kw) for kw in exit_keywords):
        logger.info("[classify_query_type] 检测到退出意图")
        return "exit"

    # 2. 规则检测：寒暄 (L-04: 精确门限 — 仅整句等于关键词或仅剩语气词/标点,
    #    不再用 len<15 前缀命中, 避免 "你好 M31 的距离是多少" 被误判寒暄)
    greeting_keywords = config.greeting_keywords
    if any(_is_greeting_exact(user_lower, kw) for kw in greeting_keywords):
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

    # H-06: 指数退避重试 (初始调用 + 2 次重试: 0.5s / 1s), 重试耗尽回退
    # "astronomical" 走 ask_entity 追问, 避免单次瞬时故障静默丢弃整次查询
    last_error = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            client = get_llm_client()
            response = client.chat.completions.create(
                model=config.llm['model'],
                messages=[{"role": "user", "content": prompt}],
                temperature=config.llm['temperature'],
                max_tokens=10
            )

            content = response.choices[0].message.content
            # M-07: 判空 — None/空串回退保守路径 (astronomical 走 ask_entity 追问而非 invalid)
            if content is None or not content.strip():
                logger.warning("[classify_query_type] LLM 返回空响应, 保守回退 astronomical")
                return "astronomical"

            result = content.strip().lower()
            logger.debug(f"[classify_query_type] LLM响应: {result}")

            # M-07: 显式枚举合法值 (词边界正则), 无法识别时保守回退 astronomical
            if re.search(r"\byes\b", result):
                logger.info("[classify_query_type] 判定为天文学查询")
                return "astronomical"
            if re.search(r"\bno\b", result):
                logger.info("[classify_query_type] 判定为非天文学查询")
                return "invalid"

            logger.warning(f"[classify_query_type] LLM 响应无法识别: {result!r}, 保守回退 astronomical")
            return "astronomical"

        except Exception as e:
            last_error = e
            logger.warning(f"[classify_query_type] 第 {attempt + 1} 次 LLM 调用失败: {e}")
            if attempt < len(_RETRY_DELAYS):
                time.sleep(_RETRY_DELAYS[attempt])

    # H-06: 重试耗尽回退 astronomical
    logger.error(f"[classify_query_type] LLM 调用重试耗尽, 回退 astronomical: {last_error}")
    return "astronomical"


def _parse_extract_json(response_text) -> dict:
    """H-07: extract 的 JSON 多层解析回退。

    解析链:
    1. response_text 为 None/空 → 直接返回空 dict (不再尝试解析)
    2. 剥 BOM / markdown fence (```json ... ```) / 前后空白
    3. json.loads 全量解析
    4. 失败用 json.JSONDecoder().raw_decode 定位首个完整对象,
       容忍 LLM 在对象后附加的解释文本/花括号
    5. 全部失败抛 ValueError (由调用方重试/降级)
    """
    if response_text is None:
        return {}
    text = response_text.strip().lstrip("").strip()
    if not text:
        return {}
    # 剥 markdown fence
    fence_match = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # raw_decode 定位首个完整 JSON 对象 (跳过前导文本, 忽略尾随文本)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"无法解析 LLM JSON 输出: {response_text!r}")


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

    # H-07: 解析失败重试时强调严格 JSON 的 prompt
    strict_prompt = prompt + """

【重要】请只输出 JSON 对象本身：
1. 不要使用 markdown 代码块（``` 或 ```json）
2. 不要包含任何解释性文字、注释或尾随说明
3. 所有键名必须使用英文双引号
4. 输出必须是完整的 JSON 对象，以 { 开头以 } 结尾，不要附加任何其他内容"""

    # H-06: 指数退避重试 (初始调用 + 2 次重试: 0.5s / 1s);
    # H-07: 解析失败后 (attempt > 0) 使用强调严格 JSON 的 prompt 重试
    last_error = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            client = get_llm_client()
            response = client.chat.completions.create(
                model=config.llm['model'],
                messages=[{"role": "user", "content": strict_prompt if attempt > 0 else prompt}],
                temperature=config.llm['temperature'],
                max_tokens=config.llm['max_tokens']
            )

            response_text = response.choices[0].message.content
            logger.debug(f"[extract_entity_and_properties] LLM响应: {response_text}")

            # H-07: 多层 JSON 解析回退 (fence/前后空白 → loads → raw_decode)
            result = _parse_extract_json(response_text)
            if not result:
                # response_text 为 None/空 → 直接返回空, 转 ask_entity 追问
                logger.warning("[extract_entity_and_properties] LLM 返回空响应, 返回空结果")
                return {"target_entity": None, "requested_properties": []}

            logger.info(f"[extract_entity_and_properties] 提取结果: {result}")

            # M-08: 输出类型校验 — requested_properties 必须 list 且元素 str,
            # target_entity 必须 str, 不符置默认值记 warning
            requested_properties = result.get("requested_properties", [])
            if not isinstance(requested_properties, list) or not all(
                isinstance(p, str) for p in requested_properties
            ):
                logger.warning(
                    f"[extract_entity_and_properties] requested_properties 类型非法: "
                    f"{requested_properties!r}, 置空列表"
                )
                requested_properties = []

            target_entity = result.get("target_entity")
            if not isinstance(target_entity, str):
                logger.warning(
                    f"[extract_entity_and_properties] target_entity 类型非法: "
                    f"{target_entity!r}, 置 None"
                )
                target_entity = None

            return {
                "target_entity": target_entity,
                "requested_properties": requested_properties,
            }

        except Exception as e:
            last_error = e
            logger.warning(f"[extract_entity_and_properties] 第 {attempt + 1} 次尝试失败: {e}")
            if attempt < len(_RETRY_DELAYS):
                time.sleep(_RETRY_DELAYS[attempt])

    # H-06: 重试耗尽返回空 dict 转追问而非 raise
    logger.error(f"[extract_entity_and_properties] 重试耗尽, 返回空结果: {last_error}")
    return {"target_entity": None, "requested_properties": []}


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
