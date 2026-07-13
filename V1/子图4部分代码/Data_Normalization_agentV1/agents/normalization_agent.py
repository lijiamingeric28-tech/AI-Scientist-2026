"""
normalization_agent.py — Stage 3: ToolExecutorAgent (V2.3)

按 tool_registry 分层执行:
  Layer 1: Base Tools (6个确定性工具)
  Layer 2: Adapted Tools (LLM 注入参数的 Base Tools)
  Layer 3: Generated Tools (LLM 动态生成的 Python 函数, sandbox 执行)

V2.3: 并行执行 — 多个 source 的工具执行并发处理。
"""
from __future__ import annotations
import datetime, time, copy, json, ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
logger = get_logger(__name__)

# Base Tool 注册表
_BASE_TOOLS = {}

# AST 白名单: 允许的节点类型
_ALLOWED_AST_NODES = {
    ast.Module, ast.FunctionDef, ast.Return, ast.Assign, ast.Expr,
    ast.Call, ast.Name, ast.Load, ast.Store, ast.Constant, ast.arg,
    ast.arguments, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
    ast.If, ast.For, ast.While, ast.Attribute, ast.Subscript, ast.Index,
    ast.List, ast.Dict, ast.Tuple, ast.Set, ast.ListComp, ast.DictComp,
    ast.comprehension, ast.Slice, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Mod, ast.Pow, ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
    ast.And, ast.Or, ast.Not, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Pass, ast.Break, ast.Continue, ast.Try, ast.ExceptHandler,
    ast.Raise, ast.Assert, ast.Import, ast.ImportFrom, ast.alias,
    ast.JoinedStr, ast.FormattedValue, ast.Lambda, ast.IfExp,
    ast.AugAssign, ast.AnnAssign, ast.keyword, ast.Starred,
    ast.withitem, ast.With, ast.Yield, ast.YieldFrom,
}

# 允许的模块白名单 (Import/ImportFrom 只能白名单)
_ALLOWED_MODULES = {"math", "re", "json", "copy", "datetime", "collections", "itertools",
                    "functools", "typing", "statistics", "decimal", "fractions", "hashlib",
                    "base64", "uuid", "string", "textwrap", "itertools", "operator"}


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


def _execute_one_source(sid: str, by_src: dict, records: list[dict], sandbox_globals: dict) -> dict:
    """执行单个 source 的全部工具 (在独立线程中运行)。"""
    _lazy_load_tools()
    srecs = [r for r in records if r.get("source_id") == sid]
    result = {"source_id": sid, "total": 0, "records": srecs,
              "base_logs": [], "adapted_logs": [], "generated_logs": [], "errors": [],
              "tool_count": 0}

    if not srecs:
        result["total"] = -1  # empty marker
        return result

    agent = NormalizationAgent()

    # Layer 1: Base Tools
    for tool_name in by_src.get("base", []):
        r = agent._execute_base(tool_name, srecs)
        if r:
            logs = r.get("log", r.get("mapping_log", r.get("modification_log", r.get("conversion_log", []))))
            result["base_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1
            if "data" in r:
                srecs = r["data"]

    # Layer 2: Adapted Tools
    for adapt in by_src.get("adapted", []):
        r = agent._execute_adapted(adapt, srecs)
        if r:
            logs = r.get("log", [])
            result["adapted_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1
            if "data" in r:
                srecs = r["data"]

    # Layer 3: Generated Tools
    for gen in by_src.get("generated", []):
        if gen.get("source_id") != sid:
            continue
        r = agent._execute_generated(gen, srecs, sandbox_globals)
        if r:
            logs = r.get("log", [])
            result["generated_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1
            if "data" in r:
                srecs = r["data"]
        else:
            result["errors"].append({"source_id": sid, "tool": gen.get("tool_name", "?"),
                                     "error": "generated tool execution failed"})

    result["records"] = srecs
    return result


class NormalizationAgent:
    """Stage 3: ToolExecutorAgent — V2.3 并行执行。"""

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

        # ── 安全沙箱 ──
        safe_builtins = {
            "True": True, "False": False, "None": None,
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "filter": filter, "float": float, "int": int,
            "isinstance": isinstance, "len": len, "list": list, "map": map,
            "max": max, "min": min, "print": print, "range": range,
            "round": round, "set": set, "sorted": sorted, "str": str,
            "sum": sum, "tuple": tuple, "type": type, "zip": zip,
            "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
            "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
        }
        sandbox_globals = {
            "__builtins__": safe_builtins,
            "json": json, "copy": copy,
            "math": __import__("math"), "re": __import__("re"),
            "datetime": __import__("datetime"), "collections": __import__("collections"),
        }

        # ══════════════════════════════════════════════════
        # V2.3: 并行执行所有 source 的工具
        # ══════════════════════════════════════════════════
        mods = {"base": [], "adapted": [], "generated": [], "errors": []}
        per_source = {}
        tc = 0
        data_trace = list(ds.get("data_trace", []))

        n_sources = len(registry)
        n_workers = min(8, max(1, n_sources))
        logger.info("[ToolExec] Processing %d sources with %d workers (PARALLEL)", n_sources, n_workers)

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {}
            for sid, by_src in registry.items():
                f = executor.submit(_execute_one_source, sid, by_src, records, sandbox_globals)
                futures[f] = sid

            for future in as_completed(futures):
                sid = futures[future]
                try:
                    r = future.result()
                    if r["total"] == -1:
                        per_source[sid] = {"total": 0, "note": "empty"}
                    else:
                        mods["base"].extend(r["base_logs"])
                        mods["adapted"].extend(r["adapted_logs"])
                        mods["generated"].extend(r["generated_logs"])
                        mods["errors"].extend(r["errors"])
                        per_source[sid] = {"total": r["total"]}
                        tc += r["tool_count"]
                        # 回写该 source 的记录
                        records = [rec for rec in records if rec.get("source_id") != sid] + r["records"]
                        _append_trace(data_trace, sid, "parallel", f"tools executed")
                except Exception as e:
                    logger.error("[ToolExec] Source %s failed: %s", sid, e)
                    mods["errors"].append({"source_id": sid, "error": str(e)})
                    per_source[sid] = {"total": 0, "note": "failed"}

        # 回写 data
        data["records"] = records
        data["_modified"] = True

        total = sum(len(v) for v in [mods["base"], mods["adapted"], mods["generated"]])
        norm["modifications"] = {
            "total": total,
            "by_layer": {"base": len(mods["base"]), "adapted": len(mods["adapted"]),
                         "generated": len(mods["generated"])},
            "details": mods,
            "per_source": per_source,
            "errors": mods["errors"],
        }

        elapsed = round(time.time() - t0, 3)
        logger.info("[ToolExec] %d mods across %d sources (PARALLEL, %.2fs)",
                    total, n_sources, elapsed)

        return {"data_state": {"current_data": data, "data_trace": data_trace},
                "report_state": {"normalization": norm},
                "workflow_state": {"current_node": "normalization", "execution_status": "Success",
                                   "tool_call_count": wf.get("tool_call_count", 0) + tc,
                                   "workflow_history": [{"agent": "ToolExecutorAgent", "stage": "ToolExecution",
                                        "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                                        "duration": elapsed,
                                        "reason": f"{total} mods (PARALLEL, base={len(mods['base'])} adapted={len(mods['adapted'])} generated={len(mods['generated'])})"}]}}

    def _execute_base(self, tool_name, records):
        try:
            fn = _BASE_TOOLS.get(tool_name)
            if not fn:
                return None
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
            params = dict(adapt.get("custom_params", {}))
            return base_fn(records, **params)
        except Exception as e:
            logger.error("[ToolExec] Adapted '%s/%s' failed: %s", adapt.get("base_tool"), adapt.get("adaptation"), e)
            return None

    def _execute_generated(self, gen, records, sandbox_globals):
        """V2.1: 安全沙箱执行 — AST 白名单 + 空 __builtins__"""
        try:
            code = gen.get("tool_code", "")
            if not code:
                return None

            # ── V2.1: AST 安全校验 ──
            if not _validate_code_ast(code):
                logger.warning("[ToolExec] Generated code blocked: AST validation failed")
                return None

            compiled = compile(code, "<sandbox>", "exec")
            exec(compiled, sandbox_globals)
            fn = sandbox_globals.get(gen["tool_name"])
            if not fn:
                return None
            return fn(records)
        except Exception as e:
            logger.error("[ToolExec] Generated '%s' failed: %s", gen.get("tool_name", "?"), e)
            return None


def _append_trace(data_trace: list, sid: str, tool: str, reason: str):
    """追加 data_trace 记录 (V2.1)。"""
    data_trace.append({
        "source_id": sid, "tool": tool, "reason": reason,
        "timestamp": datetime.datetime.now().isoformat(),
    })


# 危险函数名黑名单 (即使 AST 节点在白名单中也拒绝)
_FORBIDDEN_FUNCTIONS = {"eval", "exec", "compile", "__import__", "open",
                        "getattr", "setattr", "delattr", "globals", "locals",
                        "breakpoint", "input"}


def _validate_code_ast(code: str) -> bool:
    """AST 白名单校验: 拒绝含危险节点的代码 (V2.1)。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        # 拒绝非白名单节点类型
        if type(node) not in _ALLOWED_AST_NODES:
            logger.warning("[Sandbox] Blocked AST node: %s", type(node).__name__)
            return False

        # 对 Import/ImportFrom 校验模块白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod not in _ALLOWED_MODULES:
                    logger.warning("[Sandbox] Blocked import: %s", alias.name)
                    return False
        if isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod not in _ALLOWED_MODULES:
                    logger.warning("[Sandbox] Blocked import from: %s", node.module)
                    return False

        # 对函数调用校验危险函数名
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name and func_name in _FORBIDDEN_FUNCTIONS:
                logger.warning("[Sandbox] Blocked function call: %s()", func_name)
                return False

    return True

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
