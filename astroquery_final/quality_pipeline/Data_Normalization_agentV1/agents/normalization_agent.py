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
from ...quality_state import QualityGraphState
from ...utils.logger import get_logger
logger = get_logger(__name__)

# Base Tool 注册表
_BASE_TOOLS = {}

# AST 白名单: 允许的节点类型
_ALLOWED_AST_NODES = {
    ast.Module, ast.FunctionDef, ast.Return, ast.Assign, ast.Expr,
    ast.Call, ast.Name, ast.Load, ast.Store, ast.Constant, ast.arg,
    ast.arguments, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
    ast.If, ast.For, ast.While, ast.Attribute, ast.Subscript, ast.Index,
    ast.List, ast.Dict, ast.Tuple, ast.Set,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
    ast.comprehension, ast.Slice, ast.UAdd, ast.USub, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Mod, ast.Pow, ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
    ast.And, ast.Or, ast.Not, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Pass, ast.Break, ast.Continue, ast.Try, ast.ExceptHandler,
    ast.Raise, ast.Assert, ast.Import, ast.ImportFrom, ast.alias,
    ast.JoinedStr, ast.FormattedValue, ast.Lambda, ast.IfExp,
    ast.AugAssign, ast.AnnAssign, ast.keyword, ast.Starred,
    ast.withitem, ast.With, ast.Yield, ast.YieldFrom,
    # V3.1: 常见数据清洗操作符
    ast.FloorDiv, ast.BitAnd, ast.BitOr, ast.LShift, ast.RShift,
    ast.Invert, ast.Del, ast.Delete,
}

# 允许的模块白名单 (Import/ImportFrom 只能白名单)
_ALLOWED_MODULES = {"math", "re", "json", "copy", "datetime", "collections", "itertools",
                    "functools", "typing", "statistics", "decimal", "fractions", "hashlib",
                    "logging", "warnings",
                    "base64", "uuid", "string", "textwrap", "itertools", "operator"}


def _lazy_load_tools():
    if not _BASE_TOOLS:
        from ...tools.normalization.schema_mapping import map_to_target_schema
        from ...tools.normalization.field_standardizer import standardize_field_values
        from ...tools.normalization.unit_converter import convert_units
        from ...tools.normalization.missing_value_handler import handle_missing_values
        from ...tools.normalization.duplicate_handler import handle_duplicates
        from ...tools.normalization.format_standardizer import standardize_format
        _BASE_TOOLS.update({
            "schema_mapping": map_to_target_schema,
            "field_standardizer": standardize_field_values,
            "unit_converter": convert_units,
            "missing_value_handler": handle_missing_values,
            "duplicate_handler": handle_duplicates,
            "format_standardizer": standardize_format,
        })


def _apply_conflict_action(action: dict, records: list[dict]) -> list[dict]:
    """V3.5: 应用 Conflict/HumanReview 动作 (human_replace / annotate / normalize_unit)。

    human_replace: 对指定 record_ids 替换 field_value 为目标值。
    annotate:      对记录添加 annotation (不修改值)。
    normalize_unit: 单位统一 (to_unit 应用)。
    Returns: 修改日志列表。
    """
    logs = []
    action_type = action.get("action", "normalize")
    field = action.get("field", action.get("field_name", ""))
    new_value = action.get("new_value")
    to_unit = action.get("to_unit")
    record_ids = action.get("record_ids") or []
    en = action.get("entity_name", "")
    et = action.get("entity_type", "")

    for rec in records:
        rid = rec.get("record_id", "")
        # 按 record_ids 过滤 (为空则匹配 entity+field)
        if record_ids and rid not in record_ids:
            continue
        if en and rec.get("entity_name") != en:
            continue
        if field and rec.get("field_name") != field:
            continue

        if action_type == "human_replace" and new_value is not None:
            before = rec.get("field_value")
            rec["field_value"] = new_value
            rec["_human_replaced"] = True
            logs.append({
                "record_id": rid, "field": field,
                "before": str(before), "after": str(new_value),
                "action": "human_replace",
                "reason": action.get("reason", "Human decision"),
            })
        elif action_type == "annotate":
            rec["_annotation"] = action.get("reason", "annotated")
            logs.append({
                "record_id": rid, "field": field,
                "action": "annotate",
                "reason": action.get("reason", ""),
            })
        elif action_type in ("normalize_unit", "normalize") and to_unit:
            if rec.get("field_unit") and rec["field_unit"] != to_unit:
                before = rec.get("field_unit")
                rec["field_unit"] = to_unit
                logs.append({
                    "record_id": rid, "field": field,
                    "before": before, "after": to_unit,
                    "action": "normalize_unit",
                    "reason": action.get("reason", "Unit normalization"),
                })
    return logs


def _make_sandbox() -> dict:
    """创建独立的安全沙箱 (V3.1 fix: 每 source 一个, 避免并发共享污染)。"""
    safe_builtins = {
        "True": True, "False": False, "None": None,
        "__import__": __import__,  # 允许 import 语句 (模块安全由 AST 白名单保证)
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "filter": filter, "float": float, "int": int,
        "isinstance": isinstance, "len": len, "list": list, "map": map,
        "max": max, "min": min, "print": print, "range": range,
        "round": round, "set": set, "sorted": sorted, "str": str,
        "sum": sum, "tuple": tuple, "type": type, "zip": zip,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
    }
    return {
        "__builtins__": safe_builtins,
        "json": json, "copy": copy,
        "math": __import__("math"), "re": __import__("re"),
        "datetime": __import__("datetime"), "collections": __import__("collections"),
    }


def _execute_one_source(sid: str, by_src: dict, records: list[dict],
                        ctx: dict | None = None) -> dict:
    """执行单个 source 的全部工具 (在独立线程中运行, V3.1: 独立 sandbox)。

    ctx: 上下文配置 (target_schema / standard_units / semantic_types) — V3.2 fix:
         传入 _execute_base, 不再使用空配置。
    """
    _lazy_load_tools()
    srecs = [r for r in records if r.get("source_id") == sid]
    result = {"source_id": sid, "total": 0, "records": srecs,
              "base_logs": [], "adapted_logs": [], "generated_logs": [], "errors": [],
              "tool_count": 0,
              # V2: per-entity tracking
              "per_entity_mods": {}, "entities_in_source": []}

    if not srecs:
        result["total"] = -1  # empty marker
        return result

    # V2: collect entities in this source
    entities_seen = set()
    for r in srecs:
        et = r.get("entity_type", "") or ""
        en = r.get("entity_name", "") or ""
        if en:
            elabel = f"{et}:{en}" if et else en
            entities_seen.add(elabel)
    result["entities_in_source"] = sorted(entities_seen)

    agent = NormalizationAgent()

    # V3.5 fix: Conflict/HumanReview 动作执行 (human_replace/annotate) — 先于 Base Tools
    for action in by_src.get("conflict_actions", []) or []:
        if action.get("source_id") not in ("", sid, None):
            continue
        logs = _apply_conflict_action(action, srecs)
        if logs:
            result["base_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1

    # Layer 1: Base Tools (V3.2 fix: 传入 context 配置)
    for tool_name in by_src.get("base", []):
        r = agent._execute_base(tool_name, srecs, ctx)
        if r:
            logs = r.get("log", r.get("mapping_log", r.get("modification_log", r.get("conversion_log", []))))
            result["base_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1
            # V4 fix: 单位转换失败 (unconverted) 汇入 errors —
            # 此前被丢弃, quality_summary 的 has_unconverted_units 因此失真
            for uc in r.get("unconverted", []) or []:
                if isinstance(uc, dict) and uc.get("kind") in ("missing_unit", "no_target_unit", "no_conversion_rule"):
                    result["errors"].append({
                        "source_id": sid, "tool": tool_name,
                        "kind": "unconverted_unit",
                        "error": uc.get("reason", ""),
                        "record_id": uc.get("record_id"), "field": uc.get("field"),
                    })
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

    # Layer 3: Generated Tools (V3.1 fix: 每 source 独立 sandbox, 避免并发函数名覆盖)
    sandbox_globals = _make_sandbox()
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

    # V2: aggregate per-entity modification counts
    all_logs = result["base_logs"] + result["adapted_logs"] + result["generated_logs"]
    for log_entry in all_logs:
        if isinstance(log_entry, dict):
            rid = log_entry.get("record_id", "")
            # find matching record to extract entity info
            for rec in srecs:
                if rec.get("record_id") == rid:
                    et = rec.get("entity_type", "") or ""
                    en = rec.get("entity_name", "") or "unknown"
                    elabel = f"{et}:{en}" if et else en
                    result["per_entity_mods"][elabel] = result["per_entity_mods"].get(elabel, 0) + 1
                    break

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

        # ══════════════════════════════════════════════════
        # V2.3: 并行执行所有 source 的工具
        # V3.1 fix: 沙箱由 _execute_one_source 内部创建 (每 source 独立), 移除共享 sandbox
        # V3.2 fix: 传递 context 配置 (target_schema/standard_units/semantic_types)
        # ══════════════════════════════════════════════════
        ctx_state = state.get("context_state", {})
        profile = (rs.get("quality") or {}).get("profile", {})
        ctx = {
            "target_schema": ctx_state.get("target_schema"),
            "standard_units": ctx_state.get("standard_units") or {},
            "semantic_types": profile.get("semantic_types") or {},
        }
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
                f = executor.submit(_execute_one_source, sid, by_src, records, ctx)
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
                        # V3.2 fix: 完整保存 per-entity 统计 (不再只存 total)
                        per_source[sid] = {
                            "total": r["total"],
                            "per_entity_mods": r.get("per_entity_mods", {}),
                            "entities_in_source": r.get("entities_in_source", []),
                        }
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

        # V3.2 fix: 工具 log → 逐记录 TraceEvent (record_id/field/before/after/tool/reason)
        for tool, log_list in [("base", mods["base"]), ("adapted", mods["adapted"]),
                               ("generated", mods["generated"])]:
            for entry in log_list:
                if not isinstance(entry, dict):
                    continue
                rid = entry.get("record_id") or entry.get("id")
                if not rid:
                    continue
                data_trace.append({
                    "record_id": rid,
                    "source_id": entry.get("source_id", ""),
                    "field": entry.get("field", entry.get("field_name", "")),
                    "before": entry.get("before", entry.get("original", entry.get("original_value"))),
                    "after": entry.get("after", entry.get("new", entry.get("new_value"))),
                    "tool": entry.get("tool", tool),
                    "reason": entry.get("reason", entry.get("action", entry.get("mapped", ""))),
                    "timestamp": datetime.datetime.now().isoformat(),
                })

        total = sum(len(v) for v in [mods["base"], mods["adapted"], mods["generated"]])
        # V2: aggregate per-entity mods across all sources
        per_entity_mods_all: dict[str, int] = {}
        per_source_entities: dict[str, list] = {}
        for sid, ps_result in per_source.items():
            if isinstance(ps_result, dict):
                pem = ps_result.get("per_entity_mods", {})
                for elabel, count in pem.items():
                    per_entity_mods_all[elabel] = per_entity_mods_all.get(elabel, 0) + count
                per_source_entities[sid] = ps_result.get("entities_in_source", [])

        norm["modifications"] = {
            "total": total,
            "by_layer": {"base": len(mods["base"]), "adapted": len(mods["adapted"]),
                         "generated": len(mods["generated"])},
            "details": mods,
            "per_source": per_source,
            "errors": mods["errors"],
            # V2: per-entity breakdown
            "per_entity_modifications": per_entity_mods_all,
            "per_source_entities": per_source_entities,
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

    def _execute_base(self, tool_name, records, ctx=None):
        """V3.2 fix: 使用 context_state 配置 (target_schema/standard_units/semantic_types)。"""
        try:
            fn = _BASE_TOOLS.get(tool_name)
            if not fn:
                return None
            ctx = ctx or {}
            target_schema = ctx.get("target_schema")
            standard_units = ctx.get("standard_units") or {}
            semantic_types = ctx.get("semantic_types") or {}
            if tool_name == "schema_mapping":
                return fn(records, {}, target_schema)
            elif tool_name == "unit_converter":
                # V4 fix: 传入显式 target_schema (领域标准单位), 兜底领域配置加载
                return fn(records, [], standard_units, semantic_types, target_schema)
            elif tool_name == "missing_value_handler":
                return fn(records, strategy="mark", standard_units=standard_units)
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
            # V3.1 fix: 模板固定生成 def tool(...), 兼容 LLM 声明的 tool_name
            fn = sandbox_globals.get(gen["tool_name"]) or sandbox_globals.get("tool")
            if not fn:
                return None
            return fn(records)
        except Exception as e:
            logger.error("[ToolExec] Generated '%s' failed: %s", gen.get("tool_name", "?"), e)
            return None


def _append_trace(data_trace: list, sid: str, tool: str, reason: str,
                  entity_type: str = "", entity_name: str = ""):
    """追加 data_trace 记录 (V2.1 + V2 entity fields)。"""
    entry = {
        "source_id": sid, "tool": tool, "reason": reason,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if entity_type:
        entry["entity_type"] = entity_type
    if entity_name:
        entry["entity_name"] = entity_name
    data_trace.append(entry)


# 危险函数名黑名单 (即使 AST 节点在白名单中也拒绝)
_FORBIDDEN_FUNCTIONS = {"eval", "exec", "compile", "open",
                        "getattr", "setattr", "delattr", "globals", "locals",
                        "breakpoint", "input",
                        # 防止沙箱逃逸: 显式调用 __import__ 或 __subclasses__ 链
                        "__import__", "__subclasses__", "__class__",
                        "__bases__", "__mro__", "__subclasshook__",
                        "__init_subclass__"}


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
