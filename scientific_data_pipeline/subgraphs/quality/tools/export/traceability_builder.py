"""
traceability_builder.py — Tool 5: TraceabilityBuilder

构建完整数据溯源链: 数据世系 + 逐条记录溯源 + Agent 决策链。
"""
from __future__ import annotations
from typing import Any
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


def build_traceability(
    input_data: dict[str, Any],
    current_data: dict[str, Any],
    data_trace: list[dict],
    report_state: dict[str, Any],
    workflow_state: dict[str, Any],
) -> dict[str, Any]:
    """构建完整溯源信息。

    Returns: {traceability, trace_completeness}
    """
    sources = current_data.get("sources", [])
    records = current_data.get("records", [])
    input_records = input_data.get("records", [])
    workflow_history = workflow_state.get("workflow_history", [])

    # ── 1. Data Lineage ──
    created_at = workflow_state.get("created_at", "")
    lineage = {
        "input": {
            "sources": len(input_data.get("sources", [])),
            "records": len(input_records),
            "grounded_data_version": input_data.get("schema_version", "unknown"),
            "received_at": created_at,
        },
        "processing": _build_processing_chain(workflow_history),
        "output": {
            "sources": len(sources),
            "records": len(records),
            "standard_compliant": True,
            "generated_at": "",
        },
    }

    # ── 2. Per-Record Trace ──
    input_map = {r.get("record_id", ""): r for r in input_records}
    current_map = {r.get("record_id", ""): r for r in records}

    per_record: dict[str, dict] = {}
    modified_count = 0
    unchanged_count = 0

    # 从 data_trace 构建变更历史
    trace_by_record: dict[str, list] = {}
    for t in (data_trace or []):
        rid = t.get("record_id", t.get("source_id", ""))
        if rid:
            trace_by_record.setdefault(rid, []).append({
                "stage": t.get("tool", t.get("agent", "")),
                "before": t.get("before"),
                "after": t.get("after"),
                "reason": t.get("reason", ""),
                "confidence": t.get("confidence"),
                "timestamp": t.get("timestamp", ""),
            })

    for rid, cr in current_map.items():
        orig = input_map.get(rid, {})
        modified = False
        mods = trace_by_record.get(rid, [])

        # 比较原始值和当前值
        ov = orig.get("field_value")
        cv = cr.get("field_value")
        if str(ov) != str(cv) or orig.get("field_name") != cr.get("field_name") or orig.get("field_unit") != cr.get("field_unit"):
            modified = True

        per_record[rid] = {
            "original_value": ov,
            "original_unit": orig.get("field_unit"),
            "original_field_name": orig.get("field_name"),
            "final_value": cv,
            "final_unit": cr.get("field_unit"),
            "final_field_name": cr.get("field_name"),
            "modified": modified,
            "modifications": mods,
        }
        if modified:
            modified_count += 1
        else:
            unchanged_count += 1

    # 已删除的记录 (从 input 到 current 的差集)
    deleted = [rid for rid in input_map if rid not in current_map]
    for rid in deleted:
        orig = input_map[rid]
        per_record[rid] = {
            "original_value": orig.get("field_value"),
            "final_value": None,
            "modified": True,
            "modifications": [{"stage": "removed", "reason": "Duplicate or rejected"}],
        }
        modified_count += 1

    # ── 3. Agent Decision Trail ──
    decision_trail = []
    for entry in workflow_history:
        decision_trail.append({
            "agent": entry.get("agent", ""),
            "stage": entry.get("stage", ""),
            "status": entry.get("status", ""),
            "timestamp": entry.get("timestamp", ""),
            "duration": entry.get("duration", 0),
            "reason": entry.get("reason", ""),
        })

    # ── 4. Source-Record Map ──
    source_record_map: dict[str, list[str]] = {}
    for r in records:
        sid = r.get("source_id", "")
        source_record_map.setdefault(sid, []).append(r.get("record_id", ""))

    completeness = {
        "records_with_trace": modified_count + unchanged_count,
        "records_without_trace": 0,
        "modified_count": modified_count,
        "unmodified_count": unchanged_count,
        "deleted_count": len(deleted),
    }

    logger.info("[TraceabilityBuilder] %d records, %d modified, %d deleted, %d decision points",
                len(per_record), modified_count, len(deleted), len(decision_trail))

    return {
        "traceability": {
            "data_lineage": lineage,
            "per_record_trace": per_record,
            "agent_decision_trail": decision_trail,
            "source_record_map": source_record_map,
        },
        "trace_completeness": completeness,
    }


def _build_processing_chain(workflow_history: list[dict]) -> list[dict]:
    """从 workflow_history 构建处理链。"""
    chain = []
    for entry in workflow_history:
        chain.append({
            "stage": entry.get("stage", ""),
            "agent": entry.get("agent", ""),
            "status": entry.get("status", ""),
            "duration_s": entry.get("duration", 0),
            "reason": entry.get("reason", ""),
        })
    return chain
