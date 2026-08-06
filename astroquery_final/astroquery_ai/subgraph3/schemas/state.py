"""State schema definition for the extraction subgraph."""

from typing import TypedDict, Optional, List, Dict, NotRequired
from PIL import Image


class ExtractionState(TypedDict):
    """
    Multimodal extraction subgraph state definition.

    This state flows through three nodes:
    1. pdf_batch_converter: PDF → images
    2. vlm_batch_extractor: images → raw extractions
    3. result_builder: raw extractions → paper_records
    """

    # ===== Input fields (from Node 2) =====
    query_id: str
    """Query unique identifier (UUID)"""

    target_entity: str
    """Target celestial object name (e.g., "M31")"""

    entity_type: NotRequired[str]
    """SIMBAD otype (e.g., "AGN", "GlC", "SB*") — 写入 paper records 的 entity_type"""

    requested_properties: NotRequired[List[str]]
    """
    List of physical properties requested by user.
    Used for VLM prompt construction.
    Default: []
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
    Successfully downloaded PDF paths (from Node 2).
    Each element: {"bibcode": "...", "local_path": "...", "file_size_mb": ...}
    """

    # ===== PDF conversion results =====
    paper_image_paths: NotRequired[Dict[str, List[str]]]
    """
    PDF to image conversion results (file paths for streaming).
    Format: {bibcode: ["/path/to/page1.png", "/path/to/page2.png", ...]}
    """

    conversion_status: NotRequired[str]
    """
    PDF conversion status.
    Values: "pending" | "running" | "completed" | "failed"
    """

    conversion_failed: NotRequired[List[Dict]]
    """
    List of failed conversions.
    Format: [{"bibcode": "...", "reason": "..."}]
    """

    # ===== VLM extraction progress =====
    extraction_status: NotRequired[str]
    """
    Extraction status.
    Values: "pending" | "running" | "completed" | "failed"
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
    List of failed extractions.
    Format: [{"bibcode": "...", "reason": "..."}]
    """

    # ===== BBox annotation progress =====
    bbox_annotation_status: NotRequired[str]
    """
    BBox annotation status.
    Values: "pending" | "running" | "completed" | "failed"
    """

    bbox_annotation_progress: NotRequired[Dict]
    """
    BBox annotation progress.
    Format: {"completed": 150, "total": 200, "current_key": "2016Natur.531..202S_0"}
    """

    bbox_annotation_failed: NotRequired[List[Dict]]
    """
    List of failed bbox annotations.
    Format: [{"key": "bibcode_idx", "reason": "...", "timestamp": "..."}]
    """

    # ===== Output fields (passed to main graph) =====
    paper_records: NotRequired[List[Dict]]
    """
    Paper extraction records (final format).
    Each record conforms to GROUNDED_DATA_V2_FINAL_SPEC.
    """

    processing_summary: NotRequired[Dict]
    """
    Processing statistics.
    Format: {
        "total_papers": 35,
        "processed_papers": 35,
        "failed_papers": 0,
        "total_records_extracted": 142
    }
    """

    # ===== Error log =====
    error_log: NotRequired[List[Dict]]
    """
    Error log list.
    Format: [{"node": "vlm_batch_extractor", "error": "...", "timestamp": "..."}, ...]
    """
