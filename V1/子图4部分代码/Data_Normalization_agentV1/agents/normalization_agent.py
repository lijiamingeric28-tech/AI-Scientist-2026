"""
normalization_agent.py — Stage 3: ToolExecutorAgent (V2.0)

按 tool_registry 分层执行:
  Layer 1: Base Tools (6个确定性工具)
  Layer 2: Adapted Tools (LLM 注入参数的 Base Tools)
  Layer 3: Generated Tools (LLM 动态生成的 Python 函数, sandbox 执行)
"""
from __future__ import annotations
import datetime, time, copy, json
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)

# Base Tool 注册表
_BASE_TOOLS = {}

def _lazy_load_tools():
    if not _BASE_TOOLS:
        from tools.normalization.schema_mapping import map_to_target_schema
        from tools.normalization.field_standardizer import standardize_field_values
        from tools.normalization.unit_converter import convert_units
        from tools.normalization.missing_value_handler import handle_missing_values
        from tools.normalization.duplicate_handler import handle_duplicates
        from tools.normalization.format_standardizer import standardize_format
        _BASE_TOOLS.update({
            "schema_mapping": map_to_target_schema,
            "field_standardizer": standardize_field_values,
            "unit_converter": convert_units,
            "missing_value_handler": handle_missing_values,
            "duplicate_handler": handle_duplicates,
            "format_standardizer": standardize_format,
        })


class NormalizationAgent:
    """Stage 3: ToolExecutorAgent — 3层工具执行 (V2.0)。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        _lazy_load_tools()
        t0 = time.time()
        ds = state.get("data_state", {}); rs = state.get("report_state", {}); wf = state.get("workflow_state", {})
        data = ds.get("current_data", ds.get("input_data", {}))
        records = list(data.get("records", []))
        norm = dict(rs.get("normalization", {}) or {})
        registry = norm.get("tool_registry", {}).get("by_source", {})

        if not registry:
            return {"report_state": {"normalization": norm},
                    "workflow_state": {"current_node": "normalization", "execution_status": "Success"}}

        mods = {"base": [], "adapted": [], "generated": [], "errors": []}
        per_source = {}
        tc = wf.get("tool_call_count", 0)
        sandbox_globals = {"__builtins__": __builtins__, "json": json, "copy": copy,
                           "math": __import__("math"), "re": __import__("re"),
                           "datetime": __import__("datetime"), "collections": __import__("collections")}

        for sid, by_src in registry.items():
            srecs = [r for r in records if r.get("source_id") == sid]
            if not srecs:
                per_source[sid] = {"total": 0, "note": "empty"}
                continue

            src_mods = 0
            # ── Layer 1: Base Tools ──
            for tool_name in by_src.get("base", []):
                result = self._execute_base(tool_name, srecs)
                if result:
                    mods["base"].extend(result.get("log", result.get("mapping_log",
                                    result.get("modification_log", result.get("conversion_log", [])))))
                    src_mods += len(result.get("log", result.get("mapping_log",
                                    result.get("modification_log", result.get("conversion_log", [])))))
                    tc += 1

            # ── Layer 2: Adapted Tools ──
            for adapt in by_src.get("adapted", []):
                result = self._execute_adapted(adapt, srecs)
                if result:
                    mods["adapted"].extend(result.get("log", []))
                    src_mods += len(result.get("log", []))
                    tc += 1

            # ── Layer 3: Generated Tools (sandbox) ──
            for gen in by_src.get("generated", []):
                if gen.get("source_id") != sid:
                    continue
                result = self._execute_generated(gen, srecs, sandbox_globals)
                if result:
                    mods["generated"].extend(result.get("log", []))
                    src_mods += len(result.get("log", []))
                else:
                    mods["errors"].append({"source_id": sid, "tool": gen.get("tool_name", "?"),
                                           "error": "generated tool execution failed"})
                tc += 1

            per_source[sid] = {"total": src_mods}

        total = sum(len(v) for v in [mods["base"], mods["adapted"], mods["generated"]])
        norm["modifications"] = {
            "total": total,
            "by_layer": {"base": len(mods["base"]), "adapted": len(mods["adapted"]),
                         "generated": len(mods["generated"])},
            "details": mods,
            "per_source": per_source,
            "errors": mods["errors"],
        }

        history = list(wf.get("workflow_history", []))
        history.append({"agent": "ToolExecutorAgent", "stage": "ToolExecution", "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(), "duration": round(time.time()-t0, 3),
                        "reason": f"{total} mods (base={len(mods['base'])} adapted={len(mods['adapted'])} generated={len(mods['generated'])})"})
        logger.info("[ToolExec] %d mods across %d sources (base=%d, adapted=%d, generated=%d)",
                    total, len(per_source), len(mods["base"]), len(mods["adapted"]), len(mods["generated"]))

        return {"data_state": {"current_data": data},
                "report_state": {"normalization": norm},
                "workflow_state": {"current_node": "normalization", "execution_status": "Success",
                                   "tool_call_count": tc, "workflow_history": history}}

    def _execute_base(self, tool_name, records):
        try:
            fn = _BASE_TOOLS.get(tool_name)
            if not fn:
                return None
            # 为需要额外参数的 tool 提供默认值
            if tool_name == "schema_mapping":
                return fn(records, {})
            elif tool_name == "unit_converter":
                return fn(records, [])
            elif tool_name == "missing_value_handler":
                return fn(records, strategy="mark")
            else:
                return fn(records)
        except Exception as e:
            logger.error("[ToolExec] Base '%s' failed: %s", tool_name, e)
            return None

    def _execute_adapted(self, adapt, records):
        try:
            base_fn = _BASE_TOOLS.get(adapt["base_tool"])
            if not base_fn:
                return None
            params = adapt.get("custom_params", {})
            return base_fn(records, **params)
        except Exception as e:
            logger.error("[ToolExec] Adapted '%s/%s' failed: %s", adapt.get("base_tool"), adapt.get("adaptation"), e)
            return None

    def _execute_generated(self, gen, records, sandbox_globals):
        try:
            code = gen.get("tool_code", "")
            if not code:
                return None
            exec(code, sandbox_globals)
            fn = sandbox_globals.get(gen["tool_name"])
            if not fn:
                return None
            return fn(records)
        except Exception as e:
            logger.error("[ToolExec] Generated '%s' failed: %s", gen.get("tool_name", "?"), e)
            return None
