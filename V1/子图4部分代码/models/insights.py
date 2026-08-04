"""
insights.py — DataInsights 输出模型 (V3.4)

LLM 主观洞察生成的 Pydantic v2 输出模型。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceSource(BaseModel):
    """洞察证据来源。"""
    type: Literal["data", "knowledge_base"] = Field(
        description="data=数据上下文 (context_snippet/字段); knowledge_base=知识库条目",
    )
    ref: str = Field(
        description="引用: 'context_snippet' / 'kb:NE2001_model'",
    )


class FieldInsight(BaseModel):
    """Node 1 输出 — 单个字段的领域洞察。"""
    entity_type: str = Field(default="", description="实体类型 (FRB/Galaxy/Star...)")
    entity_name: str = Field(default="", description="实体名称")
    field_name: str = Field(description="字段名 (标准名或 DB 原始列名)")
    source_type: str = Field(default="paper", description="来源类型: paper / database")
    observation: str = Field(description="数据事实描述 (确定性: 值范围/来源数/差异)")
    interpretation: str = Field(description="LLM 解读 (结合知识库)")
    cause_hypotheses: list[str] = Field(default_factory=list, description="差异原因假设")
    typical_range: str | None = Field(default=None, description="已知典型范围")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="洞察置信度")
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    kb_references: list[str] = Field(default_factory=list, description="知识库引用 ['kb:xxx']")


class CrossFieldRelationship(BaseModel):
    """Node 2 输出 — 跨字段物理关系。"""
    field_a: str = Field(description="字段 A")
    field_b: str = Field(description="字段 B")
    relationship_type: Literal["physical_law", "correlation", "conditional", "no_relationship"] = Field(
        description="关系类型",
    )
    description: str = Field(description="关系描述")
    data_evidence: str = Field(default="insufficient_data",
                               description="sufficient_data / insufficient_data")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    kb_references: list[str] = Field(default_factory=list)


class DataUsageRecommendation(BaseModel):
    """Node 3 输出 — 数据使用建议。"""
    overall_grade: str = Field(default="unknown", description="整体评级")
    suitable_use_cases: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommended_caveats: list[str] = Field(default_factory=list)
    low_confidence_records: list[dict] = Field(
        default_factory=list,
        description="确定性: paper records extraction_confidence < 0.7",
    )
    coverage_gaps: list[str] = Field(
        default_factory=list,
        description="确定性: per_entity_missing 聚合",
    )


class DataInsightsReport(BaseModel):
    """Node 4 输出 — 完整洞察报告。"""
    research_domain: str = Field(default="", description="研究领域")
    generated_at: str = Field(default="", description="生成时间 ISO 8601")
    field_insights: list[FieldInsight] = Field(default_factory=list)
    cross_field_relationships: list[CrossFieldRelationship] = Field(default_factory=list)
    usage_recommendations: DataUsageRecommendation = Field(
        default_factory=DataUsageRecommendation,
    )
    overall_narrative: str = Field(default="", description="3-5 句综合叙述")
    insufficient_context_fields: list[str] = Field(
        default_factory=list,
        description="缺失的关键输入字段 (诊断用)",
    )
