"""schemas/ — JSON Schema"""
from __future__ import annotations

import json, os

def load_schema(filename="grounded_data_v1.json") -> dict:
    schema_dir = os.path.dirname(__file__)
    with open(os.path.join(schema_dir, filename), "r", encoding="utf-8") as f:
        return json.load(f)

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ==========================================================
# Assessment Agent — Decision Reasoning 输出
# ==========================================================

class AssessmentDecision(BaseModel):
    """LLM 对数据质量评估后的路由决策。"""

    route: Literal["Normalization", "Conflict", "Export", "HumanReview"] = Field(
        description="推荐的路由目标。优先级: Conflict > Normalization > Export。"
    )

    reasoning: str = Field(
        description="决策理由。说明为什么选择这个路由。"
    )

    critical_issues: list[str] = Field(
        default_factory=list,
        description="需要紧急处理的关键问题列表。",
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="对该路由决策的置信度 (0-1)。",
    )


# ==========================================================
# Normalization Agent — Planning 输出
# ==========================================================

class NormalizationPlan(BaseModel):
    """LLM 制定的规范化任务计划。"""

    tasks: list[str] = Field(
        description="需要执行的规范化任务列表。可选值: "
        "schema_mapping, field_standardization, unit_conversion, "
        "missing_value_handling, duplicate_handling"
    )

    field_standardizations: list[dict] = Field(
        default_factory=list,
        description="字段标准化建议。每项含 field_name, action, reason。",
    )

    unit_conversions_needed: list[dict] = Field(
        default_factory=list,
        description="需要单位转换的字段。每项含 field_name, from_unit, to_unit。",
    )

    reasoning: str = Field(
        description="制定此计划的整体理由。"
    )


class NormalizationValidation(BaseModel):
    """LLM 对规范化后数据的校验结果。"""

    is_valid: bool = Field(
        description="规范化后数据是否满足要求。"
    )

    remaining_issues: list[str] = Field(
        default_factory=list,
        description="仍然存在的遗留问题。",
    )

    needs_conflict_analysis: bool = Field(
        default=False,
        description="是否需要进一步冲突分析。",
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="校验结果置信度。",
    )


# ==========================================================
# Conflict Agent — Resolution Reasoning 输出
# ==========================================================

class ConflictResolution(BaseModel):
    """LLM 对单个冲突的解决方案。"""

    conflict_id: str = Field(
        default="",
        description="冲突标识符。",
    )

    field_name: str = Field(
        description="冲突涉及的字段名。",
    )

    decision: Literal["keep_a", "keep_b", "keep_average", "keep_both", "human_required"] = Field(
        description="解决策略: keep_a(保留来源A的值), keep_b(保留来源B的值), "
        "keep_average(取均值), keep_both(保留两者并标记), human_required(人工介入)。"
    )

    reasoning: str = Field(
        description="决策推理过程。"
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="决策置信度 (0-1)。低于 0.7 应升级为人工介入。",
    )

    suggested_value: Optional[float] = Field(
        default=None,
        description="建议采纳的数值（若 keep_average 则为均值）。",
    )


class ConflictResolutionResult(BaseModel):
    """LLM 对所有冲突的综合解决结果。"""

    resolutions: list[ConflictResolution] = Field(
        default_factory=list,
        description="每个冲突的解决方案。",
    )

    overall_summary: str = Field(
        description="冲突解决的总体摘要。"
    )

    needs_human_review: bool = Field(
        description="是否有任何冲突需要人工介入。",
    )

    auto_resolved_count: int = Field(
        default=0,
        description="自动解决的冲突数。",
    )

    human_required_count: int = Field(
        default=0,
        description="需要人工的冲突数。",
    )


# ==========================================================
# Export Agent — Output Validation 输出
# ==========================================================

class ExportValidation(BaseModel):
    """LLM 对最终输出质量的校验结果。"""

    is_valid: bool = Field(
        description="输出是否通过校验。"
    )

    issues: list[str] = Field(
        default_factory=list,
        description="发现的问题列表。"
    )

    data_quality_comment: str = Field(
        default="",
        description="对数据整体质量的简短评语。",
    )

    recommendations: list[str] = Field(
        default_factory=list,
        description="给用户的建议。",
    )

    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="校验置信度。",
    )
