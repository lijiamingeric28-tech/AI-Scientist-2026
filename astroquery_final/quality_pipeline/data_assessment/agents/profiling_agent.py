"""
profiling_agent.py — Stage 1: ProfilingAgent

职责: 只做数据画像（Profile），绝不做质量判断。
- 不调用 LLM
- 不修改数据
- 不生成 route_decision
- 只写 ReportState.quality.profile 和 WorkflowState
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from ...quality_state import QualityGraphState
from ...utils.logger import get_logger

logger = get_logger(__name__)

# ==========================================================
# Tool 1: DatasetProfiler
# ==========================================================

def _dataset_profiler(data: dict[str, Any]) -> dict[str, Any]:
    records = data.get("records", [])
    sources = data.get("sources", [])
    return {
        "record_count": len(records),
        "source_count": len(sources),
        "field_count": len({r.get("field_name") for r in records}),
        "metadata_exists": bool(sources),
    }


# ==========================================================
# Tool 2: SchemaProfiler
# ==========================================================

def _schema_profiler(data: dict[str, Any], target_schema: dict[str, Any] | None) -> dict[str, Any]:
    actual_fields = sorted({r.get("field_name", "") for r in data.get("records", [])})
    expected = []
    if target_schema:
        expected = sorted(f.get("name", "") for f in target_schema.get("fields", []) if f.get("name"))

    return {
        "expected_fields": expected,
        "actual_fields": actual_fields,
        "missing_fields": [f for f in expected if f not in actual_fields],
        "extra_fields": [f for f in actual_fields if f not in expected],
    }


# ==========================================================
# Tool 3: FieldProfiler
# ==========================================================

def _field_profiler(data: dict[str, Any]) -> list[dict[str, Any]]:
    records = data.get("records", [])
    field_groups: dict[str, list[Any]] = {}
    for r in records:
        fn = r.get("field_name", "unknown")
        field_groups.setdefault(fn, []).append(r.get("field_value"))

    stats = []
    for fn, vals in sorted(field_groups.items()):
        from ...tools._parse_utils import is_numeric, parse_numeric
        numeric_vals = [parse_numeric(v) for v in vals if is_numeric(v)]
        null_count = sum(1 for v in vals if v is None)
        sample = vals[:5]

        stat = {
            "field": fn,
            "dtype": "numeric" if numeric_vals else "string",
            "count": len(vals),
            "null_ratio": round(null_count / len(vals), 4) if vals else 0.0,
            "unique_ratio": round(len(set(str(v) for v in vals)) / len(vals), 4) if vals else 0.0,
            "sample_values": sample,
        }
        if numeric_vals:
            stat["min"] = min(numeric_vals)
            stat["max"] = max(numeric_vals)
            stat["mean"] = round(sum(numeric_vals) / len(numeric_vals), 2)
        stats.append(stat)

    return stats


# ==========================================================
# Tool 4: SourceProfiler
# ==========================================================

def _source_profiler(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.get("sources", [])
    types: dict[str, int] = {}
    for s in sources:
        t = s.get("source_type", "unknown")
        types[t] = types.get(t, 0) + 1

    return {
        "total_sources": len(sources),
        "source_types": list(types.keys()),
        "source_distribution": types,
        "source_names": [s.get("title", "")[:80] for s in sources[:10]],
    }


# ==========================================================
# Tool 5: MetadataProfiler
# ==========================================================

def _metadata_profiler(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.get("sources", [])
    # V3.1: paper + database 字段联合检查
    paper_fields = ("doi", "title", "authors", "year", "journal", "access_path")
    db_fields = ("description", "research_methodology", "waveband", "research_content",
                 "bibcode", "vizier_table_id", "reference_paper", "observation_facility")
    all_meta_fields = paper_fields + db_fields

    fields_present: dict[str, int] = {}
    for s in sources:
        for key in all_meta_fields:
            if s.get(key):
                fields_present[key] = fields_present.get(key, 0) + 1

    return {
        "total_sources": len(sources),
        "metadata_completeness": {k: f"{v}/{len(sources)}" for k, v in fields_present.items()},
        "fields_present": sorted(fields_present.keys()),
    }


# ==========================================================
# ProfilingAgent
# ==========================================================

class ProfilingAgent:
    """Stage 1: Data Profiling — 只观测，不判断。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ds = state.get("data_state", {})
        ctx = state.get("context_state", {})
        wf = state.get("workflow_state", {})

        input_data = ds.get("input_data", {})
        target_schema = ctx.get("target_schema")

        tool_count = 0
        errors = []

        # ── 执行 5 个 Tool ──
        try:
            dataset_summary = _dataset_profiler(input_data); tool_count += 1
        except Exception as e:
            dataset_summary = {}; errors.append(f"DatasetProfiler: {e}")

        try:
            schema_summary = _schema_profiler(input_data, target_schema); tool_count += 1
        except Exception as e:
            schema_summary = {}; errors.append(f"SchemaProfiler: {e}")

        try:
            field_statistics = _field_profiler(input_data); tool_count += 1
        except Exception as e:
            field_statistics = []; errors.append(f"FieldProfiler: {e}")

        try:
            source_summary = _source_profiler(input_data); tool_count += 1
        except Exception as e:
            source_summary = {}; errors.append(f"SourceProfiler: {e}")

        try:
            metadata_summary = _metadata_profiler(input_data); tool_count += 1
        except Exception as e:
            metadata_summary = {}; errors.append(f"MetadataProfiler: {e}")

        # ── 执行状态 ──
        if len(errors) >= 3:
            status = "Failed"
        elif errors:
            status = "Retry"
        else:
            status = "Success"

        # ── P3: 语义类型推断 (Phase 3: 显式 research_domain, 不再依赖线程全局) ──
        try:
            from ...tools.assessment.semantic_type import infer_all_fields
            semantic_types = infer_all_fields(
                input_data.get("records", []),
                research_domain=ctx.get("research_domain"),
            )
            tool_count += 1
        except Exception as e:
            semantic_types = {}
            errors.append(f"SemanticTypeInferrer: {e}")

        # ── 检测物理不可行的值 ──
        out_of_range_count = 0
        for fn, st in semantic_types.items():
            if st.get("out_of_range"):
                out_of_range_count += 1

        # ── P1: 分布分析 ──
        try:
            from ...tools.assessment.distribution import profile_field_distributions
            distributions = profile_field_distributions(input_data.get("records", []))
            tool_count += 1
        except Exception as e:
            distributions = {}
            errors.append(f"DistributionProfiler: {e}")

        # ── P2: 异常值检测 ──
        try:
            from ...tools.assessment.outlier import detect_all_fields
            outliers = detect_all_fields(input_data.get("records", []))
            tool_count += 1
        except Exception as e:
            outliers = {}
            errors.append(f"OutlierDetector: {e}")

        profile = {
            "dataset_summary": dataset_summary,
            "schema_summary": schema_summary,
            "field_statistics": field_statistics,
            "source_summary": source_summary,
            "metadata_summary": metadata_summary,
            "semantic_types": semantic_types,
            "distributions": distributions,
            "outliers": outliers,
            "out_of_range_count": out_of_range_count,
        }

        elapsed = round(time.time() - t0, 3)
        tc = wf.get("tool_call_count", 0) + tool_count

        logger.info("[ProfilingAgent] %d records, %d fields, %d tools, %.2fs%s",
                    dataset_summary.get("record_count", 0),
                    dataset_summary.get("field_count", 0),
                    tool_count, elapsed,
                    f", errors={len(errors)}" if errors else "")

        return {
            "report_state": {"quality": {"profile": profile}},
            "workflow_state": {
                "current_node": "profiling",
                "execution_status": status,
                "tool_call_count": tc,
                "last_error": "; ".join(errors) if errors else None,
                "workflow_history": [{
                    "agent": "ProfilingAgent", "stage": "Profiling",
                    "status": status,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{tool_count} tools, {dataset_summary.get('record_count',0)} records"
                }],
            },
        }
