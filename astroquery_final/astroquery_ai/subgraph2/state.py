"""状态定义模块"""

from typing import TypedDict, Optional, NotRequired, List, Dict, Annotated
from operator import add


class RetrievalState(TypedDict):
    """
    并行检索子图的状态定义
    """

    # ===== 输入字段（从 Node 1 传入） =====
    query_id: str
    """查询唯一标识符（UUID）"""

    target_entity: str
    """天体名称（必填）"""

    requested_properties: NotRequired[List[str]]
    """
    用户希望查询的物理性质列表（可选）
    用于论文检索的查询构建
    默认：[]
    """

    property_spec: NotRequired[List[Dict]]
    """
    PropertySpec：标准性质列表（从 P1 传入）
    格式：[{property_id, name_cn, unit, category, ucd, description}, ...]
    用于数据库列名映射
    """

    simbad_info: NotRequired[Dict]
    """
    SIMBAD 解析信息（从 P1 传入）
    格式：{main_id, otype(紧凑码), otypes, sp_type, ra, dec}（TAP P1 产出，无 ALIASES 键）
    注意：别名一律走本子图 simbad_resolver 产出的 simbad_aliases 键，
    不要读 simbad_info["ALIASES"]（P1 请求不含 ids 参数，该键不存在，见审计 A1）。
    另注：当前图仍以 simbad_resolver 为入口做二次解析，与下方旧注释"替代"矛盾，待 B2 收敛。
    """

    # ===== SIMBAD 解析结果 =====
    simbad_status: NotRequired[str]
    """
    SIMBAD 查询状态
    可选值："success" | "failed" | "ambiguous"
    """

    simbad_main_id: NotRequired[Optional[str]]
    """SIMBAD 主标识符"""

    simbad_aliases: NotRequired[List[str]]
    """所有别名列表"""

    simbad_object_type: NotRequired[Optional[str]]
    """SIMBAD 返回的天体类型"""

    simbad_coordinates: NotRequired[Optional[Dict]]
    """天体坐标 {"ra": ..., "dec": ..., "frame": "ICRS", "epoch": "J2000"}"""

    simbad_resolved_at: NotRequired[str]
    """SIMBAD 解析时间戳"""

    # ===== 数据库查询进度 =====
    database_query_status: NotRequired[str]
    """
    数据库查询状态
    可选值："pending" | "running" | "completed" | "failed"
    """

    catalog_progress: NotRequired[Dict]
    """
    星表查询进度
    格式：{"completed": 5, "total": 22, "current_catalog": "Gaia DR3"}
    """

    successful_catalogs: NotRequired[List[str]]
    """成功查询的星表名称列表"""

    failed_catalogs: NotRequired[List[str]]
    """查询失败的星表名称列表"""

    # ===== 数据库查询结果 =====
    database_sources: NotRequired[List[Dict]]
    """
    数据库 sources 列表
    每个元素对应一个星表的元数据
    """

    database_records: NotRequired[List[Dict]]
    """
    数据库 records 列表
    每个 record 是一个物理量（EAV 模型）
    """

    # ===== 论文检索进度 =====
    ads_search_status: NotRequired[str]
    """
    ADS 查询状态
    可选值："pending" | "running" | "completed" | "failed" | "skipped"
    """

    ads_query_string: NotRequired[str]
    """ADS 查询字符串（用于记录）"""

    ads_total_found: NotRequired[int]
    """ADS 返回的论文总数"""

    ads_papers_metadata: NotRequired[List[Dict]]
    """
    ADS 返回的论文元数据列表（前50篇）
    每个元素包含：bibcode, doi, title, authors, year, journal, abstract, keyword, score, citation_count
    """

    # ===== Unpaywall 查询进度 =====
    unpaywall_query_status: NotRequired[str]
    """
    Unpaywall 查询状态
    可选值："pending" | "running" | "completed" | "failed"
    """

    unpaywall_results: NotRequired[Dict[str, List[Dict]]]
    """
    Unpaywall 查询结果
    格式：{doi: [{"url": "...", "source": "unpaywall_best_pdf", ...}, ...]}
    """

    # ===== PDF 下载进度 =====
    pdf_download_status: NotRequired[str]
    """
    PDF 下载状态
    可选值："pending" | "running" | "completed" | "failed"
    """

    pdf_download_progress: NotRequired[Dict]
    """
    PDF 下载进度
    格式：{"completed": 15, "total": 50, "current_paper": "2016Natur.531..202S"}
    """

    download_paths: NotRequired[List[Dict]]
    """
    成功下载的论文列表（Phase 2 统一：原 downloaded_papers，对齐主图/子图3 契约）
    每个元素：{"bibcode": "...", "local_path": "...", "file_size_mb": ..., "download_source": "..."}
    """

    failed_downloads: NotRequired[List[Dict]]
    """
    下载失败的论文列表（记录但不传给 Node 3）
    每个元素：{"bibcode": "...", "doi": "...", "title": "...", "reason": "Unpaywall: not OA"}
    """

    # ===== 论文 sources 构建 =====
    paper_sources: NotRequired[List[Dict]]
    """
    论文 sources 列表（仅包含成功下载的）
    每个元素对应一篇论文的元数据
    """

    # ===== 补充材料（CDS J/ 表，P4） =====
    supplementary_sources: NotRequired[List[Dict]]
    """
    补充材料 sources（source_type="supplementary"）
    每个元素含 cds_table_id、parent_bibcode 等
    """

    supplementary_records: NotRequired[List[Dict]]
    """
    补充材料 records（CDS 表数据，EAV 模型）
    与 database records 同构，provenance.source_kind="supplement"
    """

    # ===== 错误日志（使用Annotated允许并行节点都添加错误） =====
    error_log: NotRequired[Annotated[List[Dict], add]]
    """
    错误日志列表
    格式：[{"node": "simbad_resolver", "error": "...", "timestamp": "..."}, ...]
    """

    # ===== 输出字段（传递给下游） =====
    retrieval_timestamp: NotRequired[str]
    """检索完成时间戳"""
