"""子图3（多模态提取）接口契约 — 主图 ↔ 子图3

Input：主图投影给子图3 的键
Output：子图3 结果中主图消费的键（paper_records / processing_summary /
       error_log；子图私有键如 paper_image_paths 由 Pydantic 忽略）
"""

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict


class Sg3Input(BaseModel):
    """主图 → 子图3 的输入契约"""

    model_config = ConfigDict(extra="ignore")

    query_id: str
    """查询唯一标识符（UUID）"""

    target_entity: str
    """目标天体名称"""

    entity_type: str = "Unknown"
    """SIMBAD otype（写入 paper records 的 entity_type）"""

    requested_properties: List[str] = []
    """用户请求的物理性质列表"""

    property_spec: List[Dict[str, Any]] = []
    """PropertySpec：标准性质列表（VLM prompt 白名单约束）"""

    paper_sources: List[Dict[str, Any]] = []
    """论文元数据列表"""

    download_paths: List[Dict[str, Any]] = []
    """成功下载的 PDF 列表（含用户手动上传，已合并）"""


class Sg3Output(BaseModel):
    """子图3 → 主图的输出契约（主图消费的字段全集）"""

    model_config = ConfigDict(extra="ignore")

    paper_records: List[Dict[str, Any]] = []
    """论文提取记录（带 bbox 溯源）"""

    processing_summary: Dict[str, Any] = {}
    """处理统计（total/processed/failed/records）"""

    figure_evidence: List[Dict[str, Any]] = []
    """与查询相关的论文图表证据（独立通路，供前端展示，不进质量管线）"""

    error_log: List[Dict[str, Any]] = []
    """子图内部产生的错误（增量）"""
