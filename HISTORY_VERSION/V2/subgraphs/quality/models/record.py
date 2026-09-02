"""
record.py

Record（提取记录）与 Provenance（溯源锚点）Pydantic v2 模型。
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """溯源锚点——描述数据在源文献中的物理位置。

    前端据此在原文 PDF 上高亮定位。
    """

    page: Optional[int] = Field(
        default=None,
        description="PDF 页码（1-based）。若无法确定则为 None。",
    )

    bbox: Optional[list[float]] = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="边界框 [x0, y0, x1, y1]，单位 pt。"
        "前端据此在原文 PDF 上画框。若无法确定则为 None。",
    )


class Record(BaseModel):
    """单条数据提取记录。

    对应 grounded_data.records[] 中的每一项。
    提取失败的字段不会出现（不传 null record）。
    """

    record_id: str = Field(
        ...,
        description="本条记录全局唯一标识。格式: {source_id}_{field_name}_{n}。",
    )

    source_id: str = Field(
        ...,
        description="外键 → sources[].source_id。",
    )

    # V1.1: 实体信息（与子图3 schema v1.1.0 对齐）
    entity_type: str = Field(
        ...,
        description="实体类型（如 alloy, supernova, exoplanet_host_star）。",
    )

    entity_name: str = Field(
        ...,
        description="实体名称（如 Al-7075, SN1987A）。",
    )

    field_name: str = Field(
        ...,
        description="科学字段名，使用 snake_case（如 yield_strength）。",
    )

    field_value: Union[float, int, str] = Field(
        ...,
        description="提取值。number 或 string，不含 None。",
    )

    field_unit: Optional[str] = Field(
        default=None,
        description="单位（如 MPa、K、wt%）。若字段无量纲则为 None。",
    )

    trace_id: str = Field(
        ...,
        description="溯源 ID，对应 hard_mapping_dict 的 key。"
        "格式: {doc_short_id}_p{page}_{type}{id}_{row_id}。",
    )

    provenance: Provenance = Field(
        default_factory=Provenance,
        description="物理溯源坐标（页码 + bbox）。",
    )

    extraction_method: Literal["llm_text", "llm_table", "vlm_text"] = Field(
        ...,
        description="提取方式：llm_text（文字段落提取）/ llm_table（表格提取）/ vlm_text（VLM视觉提取）。",
    )
