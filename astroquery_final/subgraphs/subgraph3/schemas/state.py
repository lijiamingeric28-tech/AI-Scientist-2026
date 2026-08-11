"""提取子图状态定义。"""

from operator import add
from typing import Annotated, TypedDict, Optional, List, Dict
from typing_extensions import NotRequired 
from PIL import Image


class ExtractionState(TypedDict):
    """
    多模态提取子图状态定义。

    状态流经三个节点：
    1. pdf_batch_converter: PDF → 图片
    2. vlm_batch_extractor: 图片 → 原始提取结果
    3. result_builder: 原始提取结果 → paper_records
    """

    # ===== 输入字段（来自子图2）=====
    query_id: str
    """查询唯一标识符（UUID）"""

    target_entity: str
    """目标天体名称（如 "M31"）"""

    entity_type: NotRequired[str]
    """SIMBAD otype（如 "AGN"、"GlC"、"SB*"）— 写入 paper records 的 entity_type"""

    requested_properties: NotRequired[List[str]]
    """
    用户请求的物理性质列表。
    用于 VLM prompt 构建。
    默认：[]
    """

    property_spec: NotRequired[List[Dict]]
    """
    PropertySpec：标准性质列表（从 P1 传入）
    格式：[{property_id, name_cn, unit, category, ucd, description}, ...]
    用于 VLM prompt 白名单约束
    """

    paper_sources: List[Dict]
    """
    Paper metadata list (from Node 2).
    Each element contains: bibcode, doi, title, authors, access_path, etc.
    """

    download_paths: List[Dict]
    """
    成功下载的 PDF 路径列表（来自子图2）。
    每个元素：{"bibcode": "...", "local_path": "...", "file_size_mb": ...}
    """

    # ===== PDF 转换结果 =====
    paper_image_paths: NotRequired[Dict[str, List[str]]]
    """
    PDF 转图片结果（文件路径，流式处理）。
    格式：{bibcode: ["/path/to/page1.png", "/path/to/page2.png", ...]}
    """

    conversion_status: NotRequired[str]
    """
    PDF conversion status.
    Values: "pending" | "running" | "completed" | "failed"
    """

    conversion_failed: NotRequired[List[Dict]]
    """
    转换失败的列表。
    格式：[{"bibcode": "...", "reason": "..."}]
    """

    # ===== VLM 提取进度 =====
    extraction_status: NotRequired[str]
    """
    提取状态。
    取值："pending" | "running" | "completed" | "failed"
    """

    extraction_progress: NotRequired[Dict]
    """
    Extraction progress.
    Format: {"completed": 15, "total": 35, "current_paper": "2016Natur.531..202S"}
    """

    raw_extractions: NotRequired[Dict[str, Dict]]
    """
    Raw VLM extraction results.
    Format: {bibcode: {"extractions": [...]}}
    """

    extraction_failed: NotRequired[List[Dict]]
    """
    提取失败的列表。
    格式：[{"bibcode": "...", "reason": "..."}]
    """

    # ===== BBox 标注进度 =====
    bbox_annotation_status: NotRequired[str]
    """
    BBox 标注状态。
    取值："pending" | "running" | "completed" | "failed"
    """

    bbox_annotation_progress: NotRequired[Dict]
    """
    BBox annotation progress.
    Format: {"completed": 150, "total": 200, "current_key": "2016Natur.531..202S_0"}
    """

    bbox_annotation_failed: NotRequired[List[Dict]]
    """
    BBox 标注失败的列表。
    格式：[{"key": "bibcode_idx", "reason": "...", "timestamp": "..."}]
    """

    # ===== 输出字段（传给主图）=====
    paper_records: NotRequired[List[Dict]]
    """
    论文提取记录（最终格式）。
    每条记录符合 GROUNDED_DATA_V2_FINAL_SPEC。
    """

    processing_summary: NotRequired[Dict]
    """
    处理统计。
    格式：{
        "total_papers": 35,
        "processed_papers": 35,
        "failed_papers": 0,
        "total_records_extracted": 142
    }
    """

    # ===== 错误日志 =====
    error_log: NotRequired[Annotated[List[Dict], add]]
    """
    错误日志列表（Phase 2: 统一 Annotated[add] reducer，与主图/子图2 一致）。
    格式：[{"node": "vlm_batch_extractor", "error": "...", "timestamp": "..."}, ...]
    """

    # ===== Figure 证据（独立通路，不进质量管线）=====
    figure_evidence: NotRequired[List[Dict]]
    """
    与查询相关的论文图表证据（figure_extractor 产出，供前端直接展示）。
    格式：[{"source_id", "page", "figure_index", "caption", "description",
           "relevance_reason", "image_path"}, ...]
    （2026-08-11: 去掉 high/medium/low 分级 relevance 字段，reason 统一进 relevance_reason）
    """
