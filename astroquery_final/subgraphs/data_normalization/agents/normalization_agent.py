"""
normalization_agent.py — Stage 3: ToolExecutorAgent (V2.3)

按 tool_registry 分层执行:
  Layer 1: Base Tools (6个确定性工具)
  Layer 2: Adapted Tools (LLM 注入参数的 Base Tools)
  Layer 3: Generated Tools (LLM 动态生成的 Python 函数, sandbox 执行)

V2.3: 并行执行 — 多个 source 的工具执行并发处理。
"""
from __future__ import annotations
import datetime
import time
import copy
import json
import ast
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
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

# H-12 fix: 沙箱硬超时 (秒) 与输出大小上限 — LLM 生成的 while True 死循环
# 不再挂死整条管线; 超时/超限判生成失败, 回退 Base Tools。
_SANDBOX_TIMEOUT_SEC = 8.0
_SANDBOX_MAX_LOG_ENTRIES = 50000


def _run_with_timeout(target, args=(), timeout=None) -> dict:
    """在独立 daemon 线程执行并等待, 超时返回失败 (H-12 fix)。

    超时后放弃该线程 (daemon 随进程退出, 不 join — interrupt 不保证立即
    停止, 但节点可继续); 调用方据此判生成失败并回退 Base Tools。
    timeout=None 时取调用时刻的 _SANDBOX_TIMEOUT_SEC (支持测试中调参)。
    """
    if timeout is None:
        timeout = _SANDBOX_TIMEOUT_SEC
    outcome = {"ok": False, "error": None, "result": None}

    def _worker():
        try:
            outcome["result"] = target(*args)
            outcome["ok"] = True
        except Exception as e:  # noqa: BLE001 — 沙箱异常即失败, 由调用方记录
            outcome["error"] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        outcome["error"] = TimeoutError(f"Sandbox execution exceeded {timeout}s")
    return outcome


def _lazy_load_tools():
    if not _BASE_TOOLS:
        from quality_pipeline.tools.normalization.schema_mapping import map_to_target_schema
        from quality_pipeline.tools.normalization.field_standardizer import standardize_field_values
        from quality_pipeline.tools.normalization.unit_converter import convert_units
        from quality_pipeline.tools.normalization.missing_value_handler import handle_missing_values
        from quality_pipeline.tools.normalization.duplicate_handler import handle_duplicates
        from quality_pipeline.tools.normalization.format_standardizer import standardize_format
        _BASE_TOOLS.update({
            "schema_mapping": map_to_target_schema,
            "field_standardizer": standardize_field_values,
            "unit_converter": convert_units,
            "missing_value_handler": handle_missing_values,
            "duplicate_handler": handle_duplicates,
            "format_standardizer": standardize_format,
        })


def _apply_conflict_ction(action: dict, records: list[dict],
                          ctx: dict | None = None) -> tuple[list, list]:
    """V3.5: 应用 Conflict/HumanReview 动作 (human_replace / annotate / normalize_unit)。

    human_replace: 对指定 record_ids 替换 field_value 为目标值。
    annotate:      对记录添加 annotation (不修改值)。
    normalize_unit: 单位统一 (to_unit 应用)。

    H-03 fix: normalize_unit 同步换算数值 (from_unit→to_unit), 不再只改单位
    标签; 无换算规则/量纲不匹配时记入 errors (kind=unconverted_unit) 而非
    重贴标签产出值/单位配对的伪数据。
    Returns: (修改日志列表, 错误列表)。
    """
    logs = []
    errors = []
    action_type = action.get("action", "normalize")
    field = action.get("field", action.get("field_name", ""))
    new_value = action.get("new_value")
    to_unit = action.get("to_unit")
    record_ids = action.get("record_ids") or []
    en = action.get("entity_name", "")
    et = action.get("entity_type", "")

    # M1 fix: 无 new_value 的 human_replace 不能静默跳过 — 记 warning 便于排查
    # (上游 adopt_source_a/b 的源无 value 时 selected_value=None, 用户决策会丢)
    if action_type == "human_replace" and new_value is None:
        logger.warning("[ToolExec] human_replace 无 new_value, 动作被跳过: %s",
                       action.get("reason", "")[:80])

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
                from_unit = action.get("from_unit") or rec["field_unit"]
                # H-03 fix: 调用 unit_converter 按 from_unit→to_unit 换算数值
                conv_fn = _BASE_TOOLS.get("unit_converter")
                try:
                    conv = conv_fn(
                        [rec],
                        unit_conversions=[{"field": field, "to": to_unit}],
                        standard_units=(ctx or {}).get("standard_units") or {},
                        semantic_types=(ctx or {}).get("semantic_types") or {},
                        target_schema=(ctx or {}).get("target_schema"),
                        research_domain=(ctx or {}).get("research_domain"),
                    )
                except Exception as e:
                    errors.append({
                        "record_id": rid, "field": field,
                        "kind": "unconverted_unit",
                        "error": f"normalize_unit conversion failed: {e}",
                    })
                    continue
                if conv.get("unconverted") or rec.get("field_unit") != to_unit:
                    # 无换算规则/量纲不匹配/非数值 — 保持原值原单位, 记 error
                    first = (conv.get("unconverted") or [{}])[0]
                    errors.append({
                        "record_id": rid, "field": field,
                        "kind": "unconverted_unit",
                        "from_unit": from_unit, "to_unit": to_unit,
                        "error": first.get("reason", "no conversion rule"),
                    })
                    continue
                before = rec.get("field_unit")
                logs.append({
                    "record_id": rid, "field": field,
                    "before": str(before), "after": to_unit,
                    "action": "normalize_unit",
                    "reason": action.get("reason", "Unit normalization"),
                })
    return logs, errors


def _safe_import(name, *args, **kwargs):
    """受限 import 包装器 (C1 fix): 仅允许白名单模块, 防沙箱逃逸。

    exec 的 import 语句经 __builtins__['__import__'] 解析, 直接删除会让
    `import math` 等报错; 此包装器是 AST 白名单之外的第二道运行时防线。
    """
    base = name.split(".")[0]
    if base not in _ALLOWED_MODULES:
        raise ImportError(f"[Sandbox] Module '{name}' not allowed")
    return __import__(name, *args, **kwargs)


def _make_sandbox() -> dict:
    """创建独立的安全沙箱 (V3.1 fix: 每 source 一个, 避免并发共享污染)。

    C1 fix: 不再裸暴露 __import__ 与 type (逃逸链: __import__→os.system /
    type.__subclasses__→任意类); __import__ 由 _safe_import 白名单包装器接管。
    """
    safe_builtins = {
        "True": True, "False": False, "None": None,
        "__import__": _safe_import,  # C1 fix: 白名单包装器 (第二道防线)
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "filter": filter, "float": float, "int": int,
        "isinstance": isinstance, "len": len, "list": list, "map": map,
        "max": max, "min": min, "print": print, "range": range,
        "round": round, "set": set, "sorted": sorted, "str": str,
        "sum": sum, "tuple": tuple, "zip": zip,  # C1: 移除 type (逃逸链起点)
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

    agent = NormalizationAgent(research_domain=(ctx or {}).get("research_domain"))

    # V3.5 fix: Conflict/HumanReview 动作执行 (human_replace/annotate) — 先于 Base Tools
    for action in by_src.get("conflict_ctions", []) or []:
        if action.get("source_id") not in ("", sid, None):
            continue
        logs, cerrors = _apply_conflict_ction(action, srecs, ctx)
        if logs:
            result["base_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1
        if cerrors:
            result["errors"].extend(cerrors)

    # Layer 1: Base Tools (V3.2 fix: 传入 context 配置)
    for tool_name in by_src.get("base", []):
        r = agent._execute_base(tool_name, srecs, ctx)
        if r:
            # M-15 fix: 日志提取表扩展覆盖 marked_issues/format_log/duplicate_ids/
            # rejected_ids — 缺失值/格式/去重工具的修改记录不再无声消失
            logs = r.get("log", r.get("mapping_log", r.get("modification_log", r.get("conversion_log", []))))
            if not logs:
                logs = []
                logs.extend(e for e in r.get("marked_issues", []) or [] if isinstance(e, dict))
                logs.extend(e for e in r.get("format_log", []) or [] if isinstance(e, dict))
                logs.extend({"record_id": rid, "field": "", "action": "removed_duplicate"}
                            for rid in r.get("duplicate_ids", []) or [] if rid)
                logs.extend({"record_id": rid, "field": "", "action": "removed_rejected"}
                            for rid in r.get("rejected_ids", []) or [] if rid)
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
        else:
            # M-17 fix: _execute_base 失败 (返回 None) 也要记入 errors —
            # 此前工具异常静默跳过, modifications.errors 恒空, 报告失真
            result["errors"].append({"source_id": sid, "tool": tool_name,
                                     "error": "base tool execution failed"})

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
        # M-16 fix: 低置信生成工具不落地 — 跳过执行, 记 errors 待人工审核
        # (CLAUDE.md Layer 3 契约: confidence<0.7 需人工审核)
        try:
            confidence = float(gen.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.7:
            result["errors"].append({
                "source_id": sid, "tool": gen.get("tool_name", "?"),
                "kind": "low_confidence",
                "confidence": confidence,
                "error": f"generated tool confidence {confidence} < 0.7, requires human review",
            })
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
    # L-14 fix: 预建 {record_id: (entity_type, entity_name)} 索引, 再对日志 O(L) 查表
    # (此前每条日志线性扫描全部 srecs, O(L×R) 二次复杂度)
    entity_index: dict[str, tuple[str, str]] = {}
    for rec in srecs:
        rid = rec.get("record_id", "")
        if rid:
            entity_index[rid] = (rec.get("entity_type", "") or "",
                                 rec.get("entity_name", "") or "unknown")
    all_logs = result["base_logs"] + result["adapted_logs"] + result["generated_logs"]
    for log_entry in all_logs:
        if isinstance(log_entry, dict):
            rid = log_entry.get("record_id", "")
            if rid not in entity_index:
                continue
            et, en = entity_index[rid]
            elabel = f"{et}:{en}" if et else en
            result["per_entity_mods"][elabel] = result["per_entity_mods"].get(elabel, 0) + 1

    result["records"] = srecs
    return result


class NormalizationAgent:
    """Stage 3: ToolExecutorAgent — V2.3 并行执行。"""

    def __init__(self, research_domain: str | None = None):
        # Phase 3 显式化: 领域经 run(state) → ctx → 本实例 → 工具函数,
        # 不再依赖线程全局 set_research_domain (保留全局仅作 LLM 工具路径兜底)
        self.research_domain = research_domain or ""

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
        # Phase 3 显式化: research_domain 随 ctx 传入工作线程
        self.research_domain = ctx_state.get("research_domain", "") or ""
        ctx = {
            "target_schema": ctx_state.get("target_schema"),
            "standard_units": ctx_state.get("standard_units") or {},
            "semantic_types": profile.get("semantic_types") or {},
            "research_domain": self.research_domain,
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
                        _append_trace(data_trace, sid, "parallel", "tools executed")
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
                # Phase 3: 显式 research_domain, 空串回退全局兜底
                return fn(records, [], standard_units, semantic_types, target_schema,
                          research_domain=self.research_domain or None)
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
            # Phase 3: unit_converter 的 adapted 调用显式补 research_domain
            if adapt.get("base_tool") == "unit_converter" and "research_domain" not in params:
                params["research_domain"] = self.research_domain or None
            return base_fn(records, **params)
        except Exception as e:
            logger.error("[ToolExec] Adapted '%s/%s' failed: %s", adapt.get("base_tool"), adapt.get("adaptation"), e)
            return None

    def _execute_generated(self, gen, records, sandbox_globals):
        """V2.1: 安全沙箱执行 — AST 白名单 + 空 __builtins__

        H-12 fix: exec 与 fn 调用在线程中执行并设硬超时 + 输出大小上限,
        超时/超限判生成失败 (回退 Base Tools)。
        M-19 fix: 全量执行复现 dry-run 的记录数/字段键集合稳定性校验,
        不满足则丢弃结果并记错误 (在深拷贝上执行, 校验通过才采纳)。
        """
        try:
            code = gen.get("tool_code", "")
            if not code:
                return None

            # ── V2.1: AST 安全校验 (H-12: 含死循环静态防护) ──
            if not _validate_code_ast(code):
                logger.warning("[ToolExec] Generated code blocked: AST validation failed")
                return None

            # H-12 fix: 编译 + exec 在线程中执行, 硬超时
            def _exec_code():
                exec(compile(code, "<sandbox>", "exec"), sandbox_globals)  # nosec B102 — AST 白名单沙箱

            if not _run_with_timeout(_exec_code)["ok"]:
                logger.warning("[ToolExec] Generated '%s' exec timed out/failed",
                               gen.get("tool_name", "?"))
                return None

            # V3.1 fix: 模板固定生成 def tool(...), 兼容 LLM 声明的 tool_name
            fn = sandbox_globals.get(gen["tool_name"]) or sandbox_globals.get("tool")
            if not fn:
                return None

            # M-19 fix: 在深拷贝上执行, 校验通过才采纳 (失败可安全丢弃, 不改原记录)
            records_copy = copy.deepcopy(records)
            outcome = _run_with_timeout(fn, (records_copy,))
            if not outcome["ok"]:
                logger.error("[ToolExec] Generated '%s' failed: %s",
                             gen.get("tool_name", "?"), outcome["error"])
                return None
            result = outcome["result"]
            if not isinstance(result, dict) or "data" not in result:
                logger.warning("[ToolExec] Generated '%s': invalid return format",
                               gen.get("tool_name", "?"))
                return None
            data = result.get("data", [])
            # M-19 fix: 记录数一致性 — Normalization 工具只允许修改, 禁止增删记录
            if len(data) != len(records):
                logger.warning("[ToolExec] Generated '%s': record count changed "
                               "%d -> %d (rejected)", gen.get("tool_name", "?"),
                               len(records), len(data))
                return None
            # M-19 fix: 字段键集合校验 — 禁止新增/删除字段键
            for orig, new in zip(records, data):
                if not isinstance(new, dict) or set(new.keys()) != set(orig.keys()):
                    logger.warning("[ToolExec] Generated '%s': field key set changed (rejected)",
                                   gen.get("tool_name", "?"))
                    return None
            # H-12 fix: 输出大小上限 (log 条数)
            logs = result.get("log", [])
            if len(logs) > _SANDBOX_MAX_LOG_ENTRIES:
                logger.warning("[ToolExec] Generated '%s': log too large (%d entries, rejected)",
                               gen.get("tool_name", "?"), len(logs))
                return None
            return result
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

        # C1 fix: 任意 ast.Name (Load 上下文) 命中黑名单即拒绝 — 杀死别名赋值逃逸
        # (e.g. `_imp = __import__` 中 __import__ 是 Name Load, 旧检查只查 Call 漏掉它)
        if isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_FUNCTIONS:
                logger.warning("[Sandbox] Blocked name reference: %s", node.id)
                return False

        # H-12 fix: 死循环静态防护 — While 循环体无 break 即拒绝 (保守方案),
        # 与 _run_with_timeout 硬超时互为双保险 (break 存在但永不触达时由超时兜底)
        if isinstance(node, ast.While):
            if not any(isinstance(n, ast.Break) for n in ast.walk(node)):
                logger.warning("[Sandbox] Blocked unbounded while loop (no break)")
                return False

        # C1 fix: 任何 dunder 属性访问拒绝 — 杀死属性链逃逸
        # (x.__class__.__mro__ / type.__subclasses__ / obj.__getattribute__ 等),
        # 白名单例外: __name__ (模板代码中仅作可读属性使用)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr != "__name__":
                logger.warning("[Sandbox] Blocked dunder attribute: %s", node.attr)
                return False

        # 对函数调用校验危险函数名 (保留原检查, 与 Name/Attribute 检查互为冗余)
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
