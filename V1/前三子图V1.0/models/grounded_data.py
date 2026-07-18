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
    authors: List[str] = Field(default_factory=list, description="作者列表")
    year: Optional[int] = Field(None, description="出版年份")
    journal: Optional[str] = Field(None, description="期刊/会议名称")
    access_path: str = Field(..., description="PDF URL或本地路径")
    retrieval_priority: Optional[float] = Field(None, description="检索优先级评分")


class Provenance(BaseModel):
    """溯源信息"""
    page: Optional[int] = Field(None, description="PDF页码（1-based）")
    bbox: Optional[List[float]] = Field(None, description="边界框 [x0, y0, x1, y1]")


class Record(BaseModel):
    """数据记录"""
    record_id: str = Field(..., description="全局唯一标识")
    source_id: str = Field(..., description="外键 → sources[].source_id")
    
    # 实体信息（V1.1新增）
    entity_type: str = Field(..., description="实体类别（如FRB, supernova, alloy）")
    entity_name: str = Field(..., description="实体名称（如FRB 20180301A）")
    
    # 属性信息
    property_name: str = Field(..., description="属性名称（snake_case）")
    property_value: Union[float, str] = Field(..., description="属性值")
    property_unit: Optional[str] = Field(None, description="单位")
    
    # 溯源信息
    trace_id: str = Field(..., description="溯源ID")
    provenance: Provenance = Field(..., description="溯源坐标")
    extraction_method: str = Field(..., description="提取方式（vlm_text, vlm_table, ocr_text）")


class GroundedData(BaseModel):
    """grounded_data V1.1顶层容器"""
    schema_version: str = Field(default="1.1.0", description="接口版本号")
    sources: List[Source] = Field(..., description="源文献列表")
    records: List[Record] = Field(..., description="数据记录列表")
