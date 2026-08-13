"""
quality_state.py

LangGraph State definition for the Quality Module (Sub-Graph 4).

采用嵌套 TypedDict 分层设计（与设计文档 4.2a 一致），
通过 Annotated + 自定义 reducer 实现嵌套字典的部分合并。

QualityGraphState
├── context_state     — 由意图澄清子图传入
├── data_state        — 数据流 (DataState)
├── report_state      — 各 Agent 生成的报告 (ReportState)
├── workflow_state    — 流程控制 (WorkflowState)
└── output_state      — 最终输出 (OutputState)

V1.1 优化:
  - TypedDict 真正参与类型检查（不再用 dict[str, Any] 泛化）
  - WorkflowHistory / DataTrace 使用强类型 TypedDict
  - WorkflowState 增加运行统计字段
  - OutputState 增加版本信息
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict


# ==========================================================
# 嵌套字典合并 Reducer
# ==========================================================

# ── 拼接模式列表 (如 workflow_history, data_trace) ──
_LIST_APPEND_KEYS = {"workflow_history", "data_trace", "issues", "base_logs",
                       "adapted_logs", "generated_logs", "errors", "variances",
                       "anomalies", "annotations", "anomaly_flags",
                       "variance_cause_evidence", "annotation_suggestions",
                       # V3.5 fix: 各阶段导出文件累积 (Export + Insights), 不互相覆盖
                       "exported_files"}


def _merge_dict(left: dict | None, right: dict | None) -> dict:
    """
    LangGraph reducer：将 right 合并到 left 中。

    对于每个 key:
    - 若两侧值均为 dict → 递归合并
    - 若两侧值均为 list 且 key 在拼接白名单 → 拼接 (如 workflow_history)
    - 若两侧值均为 list 且 key 不在白名单 → right 覆盖 left (如 records, sources)
    - 否则 → right 覆盖 left
    """
    if left is None:
        return right or {}
    if right is None:
        return left or {}
    result = dict(left)
    for k, v in right.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge_dict(result[k], v)
        elif k in result and isinstance(result[k], list) and isinstance(v, list):
            if k in _LIST_APPEND_KEYS:
                # V4 fix: 编译子图作为主图节点时, 子图 final-state 携带
                # "父历史前缀 + 本子图新条目" 的完整列表, 整段追加会重复。
                # 按 dict 全等去重 — 重复条目是同一批 dict 透传 (时间戳一致),
                # 真正的新条目不会被误删。
                result[k] = list(result[k]) + [e for e in v if e not in result[k]]
            else:
                result[k] = v  # V3.0: 非拼接列表直接覆盖 (如 records, sources)
        else:
            result[k] = v
    return result


# ==========================================================
# 执行状态字面量
# ==========================================================

ExecutionStatus = Literal["Success", "Retry", "Failed", "HumanReview"]
# V3.5 fix: 补全 "Assessment" (HumanReview E→A 实际返回)
RouteDecision = Literal["Assessment", "Normalization", "Conflict", "Export", "HumanReview", ""]


# ==========================================================
# 子 State TypedDict
# ==========================================================

class ContextState(TypedDict, total=False):
    """Context State — 由意图澄清 + 提取子图传入。"""
    research_domain: str
    target_schema: dict[str, Any]
    standard_units: dict[str, str]
    quality_rules: dict[str, Any]
    clarified_intent: dict[str, Any]
    # P2-1: SIMBAD otype 实体类型覆盖 (source_id → otype; 无 source 级时 "default" 键)
    entity_type_overrides: dict[str, Any]


class DataState(TypedDict, total=False):
    """Data State — 数据流。"""
    input_data: dict[str, Any]
    """提取子图传入的 grounded_data，只读。"""
    current_data: dict[str, Any]
    """当前 Workflow 正在处理的数据。"""
    human_modified_data: dict[str, Any] | None
    """人工修改后的数据快照，V1 可为 None。"""
    data_trace: list[TraceRecord]
    """数据处理轨迹。"""
    # V2: entity-aware indexing
    entity_index: dict[str, list[str]] | None
    """实体→记录映射: {(entity_type, entity_name): [record_id, ...]}。
    在 Agent 初始化时从 records 构建，后续 tool 可直接使用，避免反复分组。"""


class ReportState(TypedDict, total=False):
    """Report State — 各 Agent 生成的报告。"""
    quality: dict[str, Any] | None
    """Quality Report"""
    conflict: dict[str, Any] | None
    """Conflict Resolution Report"""
    normalization: dict[str, Any] | None
    """Normalization Report"""
    export: dict[str, Any] | None
    """Export Report (V3.1: 各 Export Agent 写入 organized_data/formatted_data/metadata/traceability/validation)"""
    insights: dict[str, Any] | None
    """Insights Report (V3.4: 各洞察节点累积 field_insights/relationships/recommendations)"""


class WorkflowState(TypedDict, total=False):
    """Workflow State — 流程控制。"""
    current_node: str
    """当前正在执行的 Agent 名称。"""
    execution_status: ExecutionStatus
    """当前 Agent 的执行状态。"""
    iteration_counter: int
    """Normalization↔Conflict 循环次数，最大 3 次。"""
    retry_counter: int
    """当前节点重试次数，最大 3 次。"""
    route_decision: RouteDecision
    """下一节点路由决策。"""
    workflow_history: list[WorkflowRecord]
    """Agent 调用顺序、关键决策及状态变化。"""

    # ── V3.3: 显式阶段状态机 ──
    phase: str
    """当前阶段: assessment / normalization / conflict / human_review / export / done"""
    loop_round: int
    """C→B→C 循环轮次 (替代 _loop_count)"""
    from_conflict: bool
    """最近一次 Normalization 是否由 Conflict 触发 (C→B 标记, 替代 _from_conflict)"""
    loop_source: str
    """H2 fix: gate 记录的本轮来源节点 (normalization_graph/conflict_graph)。
    loop_controller 据此区分读 resolution_report (C 本轮) 还是 wf.route_decision (B 本轮)。"""
    force_export: bool
    """循环超限强制导出 (替代 _force_export)"""
    next_route: str
    """loop_controller 决策的下一路由 (替代 _next_route)"""

    # ── V3.3: 每节点重试计数 ──
    # M-02 fix: 允许 None — dispatch 边界用 None 重置 (走 _merge_dict 覆盖分支,
    # {} 会被递归合并残留旧计数), 读取点统一用 (wf.get("retry_by_node") or {})
    retry_by_node: dict[str, int] | None
    """{node: count} — 每个子图节点的重试次数 (替代全局 retry_counter); None 表示已重置"""

    # ── V3.3: 来源处理队列 ──
    pending_sources: dict[str, list[str]]
    """{route: [source_ids]} — 待处理来源队列: Normalization/Conflict/Export/HumanReview"""
    completed_sources: list[str]
    """已处理完成的来源列表"""

    # ── V1.1 新增: 运行信息 ──
    run_id: str
    """整个 Workflow 唯一 ID (UUID)。"""
    graph_version: str
    """图版本号，如 'V1.0'。"""
    created_at: str
    """Workflow 创建时间 (ISO 8601)。"""
    last_error: str | None
    """最近一次错误信息，无则为 None。"""
    llm_call_count: int
    """整个 Workflow 累计 LLM 调用次数。"""
    tool_call_count: int
    """整个 Workflow 累计 Tool 调用次数。"""

    # ── Human Review 打断标记 (内部使用) ──
    __human_review_needed__: bool
    __human_review_data__: Any
    __human_review_decision__: Any


class OutputState(TypedDict, total=False):
    """Output State — 最终输出。"""
    structured_data: dict[str, Any] | None
    """最终结构化数据 (csv, csv_wide, json, row_count, column_count)。"""
    metadata: dict[str, Any] | None
    """数据说明。"""
    traceability: dict[str, Any] | None
    """数据溯源信息。"""
    quality_summary: dict[str, Any] | None
    """质量摘要。"""
    insights: dict[str, Any] | None
    """V3.4: 完整 DataInsightsReport (LLM 主观洞察)。"""

    # ── V3.1: 实际写入的文件导出信息 ──
    exported_files: list[str] | None
    """导出到磁盘的文件路径列表。"""
    output_dir: str | None
    """输出目录。"""

    # ── V3.2: export 校验闸门输出 ──
    consumable: bool | None
    """V3.2: 数据是否可消费（校验通过=true；校验失败时 quarantine=true 且 consumable=false）。"""
    quarantine: bool | None
    """V3.2: export 校验失败标记（export_generation 写入，非静默产出）。"""

    # ── P2-3: 人工审核辅助 ──
    human_review_support: dict[str, Any] | None
    """P2-3: 人工审核辅助信息（human_review_agent 用确定性组件生成，0 LLM）。"""

    # ── V1.1 新增: 版本信息 ──
    schema_version: str
    """输出所遵循的 Schema 版本，如 'grounded_data_v1'。"""
    export_format: str
    """导出格式，如 'json' / 'csv' / 'xlsx'。默认 'json'。"""


# ==========================================================
# 强类型历史记录 TypedDict
# ==========================================================

class WorkflowRecord(TypedDict, total=False):
    """
    Workflow 历史中的单条记录。

    记录每个 Agent 节点的执行轨迹。
    """
    agent: str
    """当前 Agent 名称，如 'AssessmentAgent'。"""
    stage: str
    """当前 Stage 名称，如 'QualityAssessment'。"""
    status: str
    """执行结果: Success / Retry / Failed。"""
    timestamp: str
    """ISO 8601 时间戳。"""
    duration: float
    """耗时（秒）。"""
    reason: str
    """进入该节点的原因，如 'Need normalization'。"""


class TraceRecord(TypedDict, total=False):
    """
    数据修改追踪中的单条记录。

    记录某一条数据被哪个工具、如何修改。
    """
    field: str
    """被修改的字段名，如 'temperature'。"""
    before: Any
    """修改前的值。"""
    after: Any
    """修改后的值。"""
    agent: str
    """执行修改的 Agent，如 'NormalizationAgent'。"""
    tool: str
    """执行修改的工具，如 'UnitConverter'。"""
    reason: str
    """修改原因，如 'Standard Unit Conversion'。"""
    confidence: float
    """修改的可信度 (0-1)。"""
    # V2: entity-aware traceability
    entity_type: str
    """被修改记录所属的实体类型，如 'FRB'。"""
    entity_name: str
    """被修改记录所属的实体名称，如 'FRB 20180916B'。"""


# ==========================================================
# 顶层 QualityGraphState — 嵌套 + Annotated Reducer
# ==========================================================

class QualityGraphState(TypedDict, total=False):
    """
    Quality 子图全局状态（嵌套结构）。

    每个子状态使用 Annotated[TypedDict, _merge_dict] 确保
    LangGraph 节点返回的部分嵌套字典被正确合并而非覆盖。
    """

    context_state: Annotated[ContextState, _merge_dict]
    """上下文状态（只读引用）。"""

    data_state: Annotated[DataState, _merge_dict]
    """数据状态。"""

    report_state: Annotated[ReportState, _merge_dict]
    """报告状态。"""

    workflow_state: Annotated[WorkflowState, _merge_dict]
    """工作流控制状态。"""

    output_state: Annotated[OutputState, _merge_dict]
    """最终输出状态。"""


# ==========================================================
# V2: 实体索引构建
# ==========================================================

def _build_entity_index(records: list[dict]) -> dict[str, list[str]]:
    """从 records 构建实体→记录映射。

    Returns: {label: [record_id, ...]}
        label = f"{entity_type}:{entity_name}" 或 "__global__"
    """
    index: dict[str, list[str]] = {}
    for rec in records:
        et = rec.get("entity_type", "") or ""
        en = rec.get("entity_name", "") or ""
        elabel = f"{et}:{en}" if (et and en) else (en if en else "__global__")
        index.setdefault(elabel, []).append(rec.get("record_id", ""))
    return index


# ==========================================================
# 初始状态工厂函数
# ==========================================================

def make_initial_state(input_grounded_data: dict[str, Any],
                       run_id: str | None = None) -> QualityGraphState:
    """
    从 grounded_data 创建 Quality 子图的初始状态。

    Args:
        input_grounded_data: 提取子图输出的 grounded_data JSON。
        run_id: 运行标识。M-18：Web 任务由 quality_adapter 透传 query_id
                （= task_id），使导出目录与任务绑定（output/{task_id[:8]}/）；
                缺省保持随机 UUID（CLI 行为不变）。

    Returns:
        初始化后的 QualityGraphState。
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # V3.0: 从 grounded_data 推断领域 (可通过 context_state 覆盖)
    domain = input_grounded_data.get("research_domain", "")
    if domain:
        from .configs import set_research_domain
        set_research_domain(domain)

    # V4 fix: standard_units 从领域 target_schema 回填 —
    # 此前恒为空, unit_converter 无目标单位 → 单位转换全部静默跳过
    # Phase 3: 显式 research_domain 传入, 不再依赖 set_research_domain 全局
    try:
        from .configs import load_domain_schema_config
        _schema_cfg = load_domain_schema_config("target_schema", research_domain=domain)
        standard_units = {
            f.get("name"): f.get("standard_unit")
            for f in (_schema_cfg or {}).get("fields", [])
            if f.get("name") and f.get("standard_unit")
        }
    except Exception:
        standard_units = {}

    return QualityGraphState(
        context_state={
            # V3.1 fix: 领域显式写入 State, 不再依赖线程全局
            "research_domain": domain,
            "target_schema": {},
            "standard_units": standard_units,
            "quality_rules": {},
            "clarified_intent": {},
        },
        data_state={
            "input_data": copy.deepcopy(input_grounded_data),
            "current_data": copy.deepcopy(input_grounded_data),
            "human_modified_data": None,
            "data_trace": [],
            # V2: entity_index — 从 records 构建实体→记录映射
            "entity_index": _build_entity_index(input_grounded_data.get("records", [])),
        },
        report_state={
            "quality": None,
            "conflict": None,
            "normalization": None,
            "export": None,  # V3.1 fix: Export Agent 写入 organized_data/formatted_data/...
            "insights": None,  # V3.4: 洞察节点累积
        },
        workflow_state={
            "current_node": "assessment",
            "execution_status": "Success",
            "iteration_counter": 0,
            "retry_counter": 0,
            "route_decision": "",
            "workflow_history": [],
            # V3.3: 显式阶段状态机
            "phase": "assessment",
            "loop_round": 0,
            "from_conflict": False,
            "force_export": False,
            "next_route": "",
            # V3.3: 每节点重试计数
            "retry_by_node": {},
            # V3.3: 来源处理队列
            "pending_sources": {
                "Normalization": [], "Conflict": [],
                "Export": [], "HumanReview": [],
            },
            "completed_sources": [],
            # V1.1 运行信息
            "run_id": run_id or str(uuid.uuid4()),
            "graph_version": "V1.0",
            "created_at": now_iso,
            "last_error": None,
            "llm_call_count": 0,
            "tool_call_count": 0,
            # Human Review
            "__human_review_needed__": False,
            "__human_review_data__": None,
            "__human_review_decision__": None,
        },
        output_state={
            "structured_data": None,
            "metadata": None,
            "traceability": None,
            "quality_summary": None,
            "insights": None,  # V3.4: DataInsightsReport
            # V3.1: 文件导出信息
            "exported_files": [],
            "output_dir": None,
            # V1.1 版本信息
            "schema_version": "2.0.0",
            "export_format": "json",
        },
    )
