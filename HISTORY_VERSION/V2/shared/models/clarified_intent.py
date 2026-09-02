"""
意图澄清模型

意图澄清子图的输出，作为检索子图的输入
"""

from pydantic import BaseModel, Field
from typing import List, Dict


class ClarifiedIntent(BaseModel):
    """
    意图澄清子图的输出，作为检索子图的输入
    """

    entities: list[str] = Field(..., description="材料实体列表，如['Al-7075', 'aluminum 7075']")
    properties: list[str] = Field(..., description="性能属性列表，如['yield_strength', 'YS']")
    conditions: dict[str, str] = Field(default_factory=dict, description="条件约束，如{'year': '2015-2025', 'temperature': '200-400°C'}")

    class Config:
        extra = "allow"
