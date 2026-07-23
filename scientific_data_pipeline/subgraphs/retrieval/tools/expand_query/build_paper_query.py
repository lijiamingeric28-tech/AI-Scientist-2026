"""构建OpenAlex API查询参数"""

from typing import List, Dict, Any
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def build_paper_query(
    expanded_entities: list[str],
    expanded_properties: list[str],
    conditions: dict[str, str],
    domain: str = "astronomy",
    user_query: str = "",
    topic_ids: list[str] = None
) -> dict[str, Any]:
    """
    构建OpenAlex API查询参数（修复版）

    Args:
        expanded_entities: 扩展后的实体列表
        expanded_properties: 扩展后的属性列表
        conditions: 查询条件（如时间范围）
        domain: 领域
        user_query: 用户原始查询
        topic_ids: LLM推荐的Topic ID列表（可选）

    Returns:
        OpenAlex API查询参数字典

    Raises:
        ValueError: 实体列表为空
    """
    logger.info("构建OpenAlex API查询参数（修复版）")

    # 验证输入
    if not expanded_entities:
        raise ValueError(f"实体列表为空，无法构建查询。原始: {expanded_entities}")

    # ===== 限制扩展数量，避免查询过长 =====
    # 只取前3个最重要的变体（通常第一个是原词，后面是最常用的同义词）
    limited_entities = expanded_entities[:3]
    limited_properties = expanded_properties[:3] if expanded_properties else []

    logger.info(f"限制查询项: entities={len(expanded_entities)}->{len(limited_entities)}, properties={len(expanded_properties)}->{len(limited_properties)}")

    # ===== 构建查询字符串 =====
    # 使用OR逻辑连接实体
    entities_query = " OR ".join([f'"{e}"' for e in limited_entities])

    # 如果有属性，使用AND连接
    if limited_properties:
        properties_query = " OR ".join([f'"{p}"' for p in limited_properties])
        search_query = f"({entities_query}) AND ({properties_query})"
    else:
        search_query = f"({entities_query})"

    logger.info(f"搜索查询: {search_query}")

    # ===== 构建过滤条件 =====
    filter_dict = {}

    # Topic过滤（优先）或Subfield过滤（降级）
    if topic_ids and len(topic_ids) > 0:
        # 使用Topic过滤（更精确）- OR逻辑
        topic_filter = "|".join(topic_ids)
        filter_dict["topics.id"] = topic_filter
        logger.info(f"使用Topic过滤: {topic_filter}")
    else:
        # 降级到Subfield 3103（天文学）
        filter_dict["topics.subfield.id"] = "3103"
        logger.info("使用Subfield过滤: 3103 (Astronomy)")

    # ===== 时间过滤 =====
    time_range = conditions.get("时间范围", "")
    if time_range:
        # 解析"最近X年内"
        if "最近" in time_range and "年" in time_range:
            match = re.search(r'(\d+)', time_range)
            if match:
                years = int(match.group(1))
                current_year = datetime.now().year
                start_year = current_year - years
                filter_dict["publication_year"] = f"{start_year}-{current_year}"
                logger.info(f"应用时间过滤: {start_year}-{current_year}")
        # 解析具体年份范围
        elif "-" in time_range:
            match = re.search(r'(\d{4})\s*-\s*(\d{4})', time_range)
            if match:
                start_year = match.group(1)
                end_year = match.group(2)
                filter_dict["publication_year"] = f"{start_year}-{end_year}"
                logger.info(f"应用时间过滤: {start_year}-{end_year}")

    # ===== 其他质量过滤 =====
    # 排除撤稿论文
    filter_dict["is_retracted"] = "false"

    # 最小引用数（排除影响力极低的论文）
    filter_dict["cited_by_count"] = ">4"

    logger.info(f"过滤条件: {filter_dict}")

    # ===== 返回完整查询参数 =====
    return {
        "search": search_query,
        "filter": filter_dict,
        "per_page": 100,
        "sort": "cited_by_count:desc"  # 按引用数降序排序
    }
