"""
数据模型模块 - 接口契约

本模块定义了系统各子图之间传递数据的标准格式。
这些模型使用 Pydantic v2 定义，确保类型安全和数据验证。

主要模型：
- ClarifiedIntent: 意图澄清子图的输出
- Source: 源文献元数据
- Record: 单条提取记录
- GroundedData: 提取子图最终输出（包含 sources 和 records）
"""

from models.clarified_intent import ClarifiedIntent
from models.source import Source
from models.record import Record, Provenance
from models.grounded_data import GroundedData

__all__ = [
    "ClarifiedIntent",
    "Source",
    "Record",
    "Provenance",
    "GroundedData",
]
