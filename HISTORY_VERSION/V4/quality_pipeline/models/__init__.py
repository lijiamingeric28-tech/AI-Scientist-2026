"""
models/ — Pydantic v2 数据模型

接口契约：前后部分共享，改前需沟通。
"""

from .source import Source
from .record import Record, Provenance
from .grounded_data import GroundedData
from .insights import (
    EvidenceSource,
    FieldInsight,
    CrossFieldRelationship,
    DataUsageRecommendation,
    DataInsightsReport,
)

__all__ = [
    "Source",
    "Record",
    "Provenance",
    "GroundedData",
    "EvidenceSource",
    "FieldInsight",
    "CrossFieldRelationship",
    "DataUsageRecommendation",
    "DataInsightsReport",
]
