"""主图状态定义

主图状态是三个子图状态的"超集投影"：
- 子图各自的 TypedDict 保持原样不动（不改子图代码）
- 主图只声明**跨子图流转**的字段，子图内部工作字段不上浮

关键设计决定
-----------
1. error_log 统一为 Annotated[List[Dict], add]
   子图 2 声明了 add reducer，子图 3 声明的是普通 list。主图必须取 add，
   否则并行分支写入会互相覆盖。包装节点负责只返回"增量"而非全量列表，
   避免 add reducer 把已累积内容重复累加。

2. 嵌套输出结构（database_results / paper_results）由包装节点组装
   子图 2 的 result_aggregator 只 return {"retrieval_timestamp": ...}，
   嵌套结构原先仅存在于其 main.py:save_output()。适配层把这段逻辑接过来。
"""

from operator import add
from typing import Annotated, Dict, List, Optional, TypedDict
try:
    from typing import NotRequired  # Python 3.11+
except ImportError:  # pragma: no cover — Python 3.10
    from typing_extensions import NotRequired


class MainGraphState(TypedDict):
    """主图全局状态"""

    # ===== 入口输入 =====
    user_query: str
    """用户原始自然语言问题（主图入口，必填）"""

    query_id: NotRequired[str]
    """全局查询唯一标识（UUID），主图入口生成，贯穿三个子图"""

    extra_pdfs: NotRequired[List[str]]
    """
    用户手动上传的 PDF 绝对路径列表（可选）
    与 Node 2 自动下载的论文合并后一起进 Node 3
    """

    # ===== Node 1 输出：澄清结果 =====
    target_entity: NotRequired[Optional[str]]
    """澄清后的天体名称"""

    requested_properties: NotRequired[List[str]]
    """用户请求的物理性质列表，空列表表示"全部" """

    entity_type_hint: NotRequired[str]
    """天体类型提示，全系统固定 "unknown" """

    user_confirmed: NotRequired[bool]
    """用户是否确认澄清参数"""

    clarification_status: NotRequired[str]
    """"confirmed" | "modified" | "failed" | "cancelled" """

    query_type: NotRequired[str]
    """"astronomical" | "greeting" | "exit" | "invalid" """

    conversation_history: NotRequired[List[Dict]]
    """完整对话历史，用于追溯"""

    # ===== Node 2 输出：检索结果（嵌套结构，由适配层组装）=====
    database_results: NotRequired[Dict]
    """
    数据库检索结果
    {"sources": [...], "records": [...], "query_summary": {...}}
    """

    paper_results: NotRequired[Dict]
    """
    论文检索结果
    {"sources": [...], "download_paths": [...], "failed_downloads": [...],
     "query_summary": {...}}
    注意：download_paths 是从子图 2 的 downloaded_papers 改名而来，
    以对齐子图 3 的输入契约。
    """

    # ===== P1 输出：性质标准化 =====
    simbad_info: NotRequired[Dict]
    """SIMBAD 解析信息（main_id / otype / otypes / sp_type / ra / dec）"""

    property_spec: NotRequired[List[Dict]]
    """
    PropertySpec：标准性质列表（系统中枢）
    格式：[{property_id, name_cn, unit, category, ucd, description}, ...]
    这是全系统的字段名白名单和标准单位表
    """

    target_schema: NotRequired[Dict]
    """
    子图 4 消费的 target_schema
    格式：{"fields": [{name, standard_unit, semantic_type, ucd, description}, ...]}
    """

    retrieval_timestamp: NotRequired[str]
    """检索完成时间戳"""

    supplementary_sources: NotRequired[List[Dict]]
    """补充材料 sources（source_type="supplementary"，来自 CDS J/ 表）"""

    supplementary_records: NotRequired[List[Dict]]
    """补充材料 records（与 database records 同构，provenance.source_kind="supplement"）"""

    # ===== Node 3 输出：论文提取结果 =====
    paper_records: NotRequired[List[Dict]]
    """论文提取记录（带 bbox 溯源）"""

    processing_summary: NotRequired[Dict]
    """Node 3 处理统计"""

    # ===== Figure 证据通道（H-01 fix）=====
    figure_evidence: NotRequired[List[Dict]]
    """
    Figure 证据列表（独立通路：extraction_node 产出 → aggregator 写入
    final_output.figure_evidence，直接展示用，不进质量管线）。
    必须声明，否则 LangGraph 对未声明通道写日志丢弃，aggregator 恒读空列表。
    """

    # ===== 最终输出 =====
    final_output: NotRequired[Dict]
    """
    下游消费的最终结构
    {"schema_version": "2.0.0", "sources": [...], "records": [...]}
    """

    # ===== quality 节点输出 =====
    quality_report: NotRequired[Dict]
    """
    质量管线完整输出状态（quality_node 返回，quality_finalize 并入 final_output）。
    必须声明，否则 LangGraph 会丢弃该键，quality_finalize 永远读到 None →
    final_output.quality_report 恒为 no_quality_report（Phase 4 断链修复）。
    """

    # ===== 全局错误日志 =====
    error_log: NotRequired[Annotated[List[Dict], add]]
    """
    跨子图累积的错误日志
    格式：[{"node": "...", "error": "...", "timestamp": "..."}]
    """
