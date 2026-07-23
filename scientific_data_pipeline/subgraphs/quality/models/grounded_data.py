"""
grounded_data.py

GroundedData（顶层容器）Pydantic v2 模型。

grounded_data 是提取子图产出、清洗子图消费的核心 JSON。
格式一经确定即作为前后端接口契约，V1 不可更改。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator, field_validator

from subgraphs.quality.models.source import Source
from subgraphs.quality.models.record import Record


class GroundedData(BaseModel):
    """带溯源锚定的结构化科学数据。

    提取子图的最终产物，供下游清洗子图消费。
    """

    schema_version: Literal["1.1.0"] = Field(
        default="1.1.0",
        description="接口版本号，用于前后端兼容校验。V1.1 固定 '1.1.0'。",
    )

    sources: list[Source] = Field(
        default_factory=list,
        description="本次提取涉及的所有源文献。",
    )

    records: list[Record] = Field(
        default_factory=list,
        description="成功提取的数据记录列表。每行一条，独立溯源。",
    )

    # ==========================================================
    # 便利方法
    # ==========================================================

    def get_source(self, source_id: str) -> Source | None:
        """按 source_id 查找源文献。"""
        for s in self.sources:
            if s.source_id == source_id:
                return s
        return None

    def get_records_by_source(self, source_id: str) -> list[Record]:
        """获取某个源文献的所有提取记录。"""
        return [r for r in self.records if r.source_id == source_id]

    def get_records_by_field(self, field_name: str) -> list[Record]:
        """获取某个字段的所有提取记录。"""
        return [r for r in self.records if r.field_name == field_name]

    @property
    def field_names(self) -> set[str]:
        """返回所有记录中出现的字段名集合。"""
        return {r.field_name for r in self.records}

    @model_validator(mode="after")
    def _validate_cross_model(self):
        """校验 source_id 外键和 record_id 唯一性。"""
        source_ids = {s.source_id for s in self.sources}
        record_ids_seen: set[str] = set()

        for rec in self.records:
            # 外键校验
            if rec.source_id not in source_ids:
                raise ValueError(
                    f"Record '{rec.record_id}' 的 source_id '{rec.source_id}' "
                    f"在 sources 列表中不存在。"
                )
            # 唯一性校验
            if rec.record_id in record_ids_seen:
                raise ValueError(
                    f"Record ID '{rec.record_id}' 重复出现。"
                )
            record_ids_seen.add(rec.record_id)

        return self

    @property
    def record_count(self) -> int:
        """提取记录总数。"""
        return len(self.records)

    @property
    def source_count(self) -> int:
        """源文献数量。"""
        return len(self.sources)
