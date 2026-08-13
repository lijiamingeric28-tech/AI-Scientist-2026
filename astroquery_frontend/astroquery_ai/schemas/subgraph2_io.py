"""子图2（并行检索）接口契约 — 主图 ↔ 子图2

Input：主图投影给子图2 的键（含适配层从 P1 simbad_info 预填充的 simbad_* 键）
Output：子图2 结果中主图消费的键。主图侧的嵌套契约
       （database_results / paper_results / simbad_info）由包装节点组装，
       不在本契约内 —— 那是主图 state 的结构，不是子图接口。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class Sg2Input(BaseModel):
    """主图 → 子图2 的输入契约"""

    model_config = ConfigDict(extra="ignore")

    query_id: str
    """查询唯一标识符（UUID）"""

    target_entity: str
    """天体名称（必填）"""

    requested_properties: List[str] = []
    """用户请求的物理性质列表"""

    property_spec: List[Dict[str, Any]] = []
    """PropertySpec：标准性质列表（从 P1 传入）"""

    simbad_info: Dict[str, Any] = {}
    """SIMBAD 解析信息（从 P1 传入）"""

    # ── 适配层从 P1 simbad_info 预填充的扁平键（B2 收敛产物）──
    simbad_status: str = "failed"
    """SIMBAD 查询状态："success" | "failed" | "ambiguous" """

    simbad_main_id: Optional[str] = None
    """SIMBAD 主标识符"""

    simbad_aliases: List[str] = []
    """所有别名列表"""

    simbad_object_type: Optional[str] = None
    """SIMBAD 返回的天体类型"""

    simbad_coordinates: Optional[Dict[str, Any]] = None
    """天体坐标 {"ra", "dec", "frame": "ICRS", "epoch": "J2000"}"""

    simbad_resolved_at: str = ""
    """SIMBAD 解析时间戳"""


class Sg2Output(BaseModel):
    """子图2 → 主图的输出契约（主图消费的字段全集）"""

    model_config = ConfigDict(extra="ignore")

    # 数据库路
    database_query_status: str = "pending"
    catalog_progress: Dict[str, Any] = {}
    successful_catalogs: List[str] = []
    failed_catalogs: List[str] = []
    database_sources: List[Dict[str, Any]] = []
    database_records: List[Dict[str, Any]] = []

    # 论文路
    ads_search_status: str = "pending"
    ads_query_string: str = ""
    ads_query_strings: List[str] = []
    """逐性质 ADS 查询串列表（按性质分开检索，合并去重后 papers 跨性质去重）"""
    ads_total_found: int = 0
    ads_papers_metadata: List[Dict[str, Any]] = []
    unpaywall_query_status: str = "pending"
    unpaywall_results: Dict[str, List[Dict[str, Any]]] = {}
    pdf_download_status: str = "pending"
    pdf_download_progress: Dict[str, Any] = {}
    download_paths: List[Dict[str, Any]] = []
    """成功下载的论文列表（原名 downloaded_papers，Phase 2 统一）"""
    failed_downloads: List[Dict[str, Any]] = []
    paper_sources: List[Dict[str, Any]] = []

    # 补充材料
    supplementary_sources: List[Dict[str, Any]] = []
    supplementary_records: List[Dict[str, Any]] = []

    # SIMBAD 透传（适配层预填充后子图内可能改写）
    simbad_status: str = "failed"
    simbad_main_id: Optional[str] = None
    simbad_aliases: List[str] = []
    simbad_object_type: Optional[str] = None
    simbad_coordinates: Optional[Dict[str, Any]] = None
    simbad_resolved_at: str = ""

    # 汇总与错误
    retrieval_timestamp: str = ""
    error_log: List[Dict[str, Any]] = []
