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

def _merge_dict(left: dict | None, right: dict | None) -> dict:
    """
    LangGraph reducer：将 right 合并到 left 中。

    对于每个 key:
    - 若两侧值均为 dict → 递归合并
    - 若两侧值均为 list → 拼接 (如 workflow_history, data_trace)
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
            result[k] = list(result[k]) + list(v)
        else:
            result[k] = v
    return result


# ==========================================================
# 执行状态字面量
# ==========================================================

ExecutionStatus = Literal["Success", "Retry", "Failed", "HumanReview"]
RouteDecision = Literal["Normalization", "Conflict", "Export", "HumanReview", ""]


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


class ReportState(TypedDict, total=False):
    """Report State — 各 Agent 生成的报告。"""
    quality: dict[str, Any] | None
    """Quality Report"""
    conflict: dict[str, Any] | None
    """Conflict Resolution Report"""
    normalization: dict[str, Any] | None
    """Normalization Report"""


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
# 初始状态工厂函数
# ==========================================================

def make_initial_state(input_grounded_data: dict[str, Any]) -> QualityGraphState:
    """
    从 grounded_data 创建 Quality 子图的初始状态。

    Args:
        input_grounded_data: 提取子图输出的 grounded_data JSON。

    Returns:
        初始化后的 QualityGraphState。
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    return QualityGraphState(
        context_state={
            "research_domain": "",
            "target_schema": {},
            "standard_units": {},
            "quality_rules": {},
            "clarified_intent": {},
        },
        data_state={
            "input_data": copy.deepcopy(input_grounded_data),
            "current_data": copy.deepcopy(input_grounded_data),
            "human_modified_data": None,
            "data_trace": [],
        },
        report_state={
            "quality": None,
            "conflict": None,
            "normalization": None,
        },
        workflow_state={
            "current_node": "assessment",
            "execution_status": "Success",
            "iteration_counter": 0,
            "retry_counter": 0,
            "route_decision": "",
            "workflow_history": [],
            # V1.1 运行信息
            "run_id": str(uuid.uuid4()),
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
            # V1.1 版本信息
            "schema_version": "grounded_data_v1",
            "export_format": "json",
        },
    )
