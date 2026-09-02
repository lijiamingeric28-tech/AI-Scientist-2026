"""
简化版意图澄清

V1.0暂时使用简单的规则解析，不使用LLM
未来可以替换为完整的意图澄清子图
"""

import logging
import re
from state.main_state import MainState
from models.clarified_intent import ClarifiedIntent

logger = logging.getLogger(__name__)


def simple_intent_clarification(state: MainState) -> MainState:
    """
    简化版意图澄清

    使用规则提取查询中的实体、属性和条件

    Args:
        state: 主State

    Returns:
        更新后的State（包含intent_params）
    """
    logger.info("=" * 70)
    logger.info("[意图澄清] 开始解析用户查询")

    user_query = state["user_query"]
    logger.info(f"用户查询: {user_query}")

    # 提取实体（材料名称）
    entities = extract_entities(user_query)
    logger.info(f"提取实体: {entities}")

    # 提取属性
    properties = extract_properties(user_query)
    logger.info(f"提取属性: {properties}")

    # 提取条件
    conditions = extract_conditions(user_query)
    logger.info(f"提取条件: {conditions}")

    # 创建ClarifiedIntent
    intent_params = ClarifiedIntent(
        entities=entities if entities else ["aluminum alloy"],  # 默认值
        properties=properties if properties else ["mechanical properties"],  # 默认值
        conditions=conditions
    )

    # 更新State
    state["intent_params"] = intent_params

    logger.info("[意图澄清] 完成")
    logger.info("=" * 70)

    return state


def extract_entities(query: str) -> list:
    """提取实体（材料名称）"""
    entities = []

    # 常见材料模式
    patterns = [
        r'(?:Al|aluminum|铝合金)[\s-]*(\d{4})',  # Al-7075, aluminum 7075
        r'Ti[\s-]*(\d{1,2}Al[\s-]*\d{1,2}V)',    # Ti-6Al-4V
        r'(?:steel|钢|stainless steel)[\s-]*(\d+)', # steel 304
        r'(?:copper|铜|Cu)[\s-]*(\d+)',          # Cu-Ni
    ]

    for pattern in patterns:
        matches = re.findall(pattern, query, re.IGNORECASE)
        for match in matches:
            if 'Al' in query or 'aluminum' in query.lower() or '铝' in query:
                entities.append(f"Al-{match}")
                entities.append(f"aluminum {match}")
            elif 'Ti' in query:
                entities.append(f"Ti-{match}")

    # 去重
    return list(set(entities)) if entities else []


def extract_properties(query: str) -> list:
    """提取属性（力学性能等）"""
    properties = []

    property_keywords = {
        'yield strength': ['屈服强度', 'yield strength', 'YS', 'σy'],
        'tensile strength': ['抗拉强度', 'tensile strength', 'UTS', 'σb'],
        'elongation': ['延伸率', 'elongation', '伸长率'],
        'hardness': ['硬度', 'hardness', 'HV', 'HB'],
        'elastic modulus': ['弹性模量', 'elastic modulus', "Young's modulus"],
    }

    for prop_name, keywords in property_keywords.items():
        for keyword in keywords:
            if keyword.lower() in query.lower():
                properties.append(prop_name)
                break

    return list(set(properties)) if properties else []


def extract_conditions(query: str) -> dict:
    """提取条件（温度、年份等）"""
    conditions = {}

    # 提取年份
    year_match = re.search(r'(\d{4})[\s-]*(?:年|to|至|-)[\s-]*(\d{4})', query)
    if year_match:
        conditions["year"] = f"{year_match.group(1)}-{year_match.group(2)}"
    else:
        # 默认近10年
        conditions["year"] = "2015-2025"

    # 提取温度
    temp_patterns = [
        r'(\d+)[\s-]*(?:°C|℃|degrees)',
        r'(\d+)[\s-]*(?:to|至|-)[\s-]*(\d+)[\s-]*(?:°C|℃)',
        r'(?:高温|elevated temperature|high temperature)',
    ]

    for pattern in temp_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            if len(match.groups()) == 1:
                conditions["temperature"] = f"{match.group(1)}°C"
            elif len(match.groups()) == 2:
                conditions["temperature"] = f"{match.group(1)}-{match.group(2)}°C"
            else:
                conditions["temperature"] = "elevated temperature"
            break

    return conditions
