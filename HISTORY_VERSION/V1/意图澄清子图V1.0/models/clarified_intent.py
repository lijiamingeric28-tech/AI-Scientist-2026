"""
ClarifiedIntent 模型定义

意图澄清子图的最终输出，包含用户真实意图的结构化抽象。
"""

from pydantic import BaseModel, Field


class ClarifiedIntent(BaseModel):
    """
    用户真实意图的结构化抽象 - 领域无关、字段泛化

    经过 Agent A 解析 + Agent B 追问 + Agent C 确认后，
    输出用户真实意图的干净抽象。下游检索子图用它构建查询策略，
    清洗子图的 Data Quality Assessment Agent 用它判断提取到的数据是否符合用户预期。
    """

    entities: list[str] = Field(
        default_factory=list,
        description="用户查询的目标实体。如 ['Al-7075', 'Ti-6Al-4V'] 或 ['SN 1987A']",
    )

    properties: list[str] = Field(
        default_factory=list,
        description="用户关心的属性/字段。如 ['yield_strength', 'tensile_strength', 'elongation']",
    )

    conditions: dict[str, str] = Field(
        default_factory=dict,
        description="用户指定的约束条件，key-value 形式。如 {'temperature': '200-400°C', 'year': '2015-2025'}",
    )
