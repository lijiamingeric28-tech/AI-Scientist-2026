"""
grounded_data V1.1 Pydantic模型定义
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Union


class Source(BaseModel):
    """源文献信息"""
    source_id: str = Field(..., description="源文献全局唯一标识")
    source_type: str = Field(default="paper", description="V1.1固定为paper")
    doi: Optional[str] = Field(None, description="DOI")
    title: str = Field(..., description="文献标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    year: Optional[int] = Field(None, description="出版年份")
    journal: Optional[str] = Field(None, description="期刊/会议名称")
    access_path: str = Field(..., description="PDF URL或本地路径")
    retrieval_priority: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="检索优先级评分，归一化到 [0, 1] 区间"
    )


class Provenance(BaseModel):
    """溯源信息"""
    page: Optional[int] = Field(None, description="PDF页码（1-based）")
    bbox: Optional[list[float]] = Field(
        None,
        min_length=4,
        max_length=4,
        description="边界框 [x0, y0, x1, y1]（矩形左上角和右下角坐标）"
    )


class Record(BaseModel):
    """数据记录"""
    record_id: str = Field(..., description="全局唯一标识")
    source_id: str = Field(..., description="外键 → sources[].source_id")

    # 实体信息（V1.1新增）
    entity_type: str = Field(..., description="实体类别（如FRB, supernova, alloy）")
    entity_name: str = Field(..., description="实体名称（如FRB 20180301A）")

    # 字段信息（遵循设计文档标准命名）
    field_name: str = Field(..., description="字段名称（snake_case）")
    field_value: Union[float, int, str] = Field(..., description="字段值")
    field_unit: Optional[str] = Field(None, description="单位")

    # 溯源信息
    trace_id: str = Field(..., description="溯源ID")
    provenance: Provenance = Field(
        default_factory=Provenance,
        description="溯源坐标"
    )
    extraction_method: str = Field(..., description="提取方式（vlm_text, vlm_table, ocr_text）")


class GroundedData(BaseModel):
    """grounded_data V1.1顶层容器"""
    schema_version: str = Field(default="1.1.0", description="接口版本号")
    sources: list[Source] = Field(default_factory=list, description="源文献列表")
    records: list[Record] = Field(default_factory=list, description="数据记录列表")
