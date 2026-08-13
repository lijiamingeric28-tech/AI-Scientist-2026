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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
# P0 (c): 沙箱 SSOT — 常量/工厂/校验统一收纳于 quality_pipeline/sandbox/sandbox_common.py,
# 此处 re-export 保持既有 import 路径兼容 (tests/test_sandbox_security.py 等不破)
from quality_pipeline.sandbox.sandbox_common import (  # noqa: F401 — re-export
    _ALLOWED_AST_NODES, _ALLOWED_MODULES, _FORBIDDEN_FUNCTIONS,
    _SANDBOX_TIMEOUT_SEC, _SANDBOX_MAX_LOG_ENTRIES, _MODULE_GLOBALS,
    _safe_import, _make_sandbox, _validate_code_ast, _validate_generated_result,
    # P1 (f): confidence 契约共享常量与自检验证 (与 planning 同源, identity 测试守护)
    _CONFIDENCE_EXEC_THRESHOLD, _verify_self_check, _compute_effective_confidence,
    # P2 (h): no-op 检测 (执行端全量 0 修改 → kind=noop)
    _detect_noop,
)
logger = get_logger(__name__)

# Base Tool 注册表
_BASE_TOOLS = {}


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
    # P3 (层 A): mode=="ops" 走确定性 ops 执行器 (execute_ops, 不进沙箱),
    # confidence 不设 <0.7 门槛; mode=="code" 走原沙箱路径 (M-16 门槛保留)
    sandbox_globals = _make_sandbox()
    for gen in by_src.get("generated", []):
        if gen.get("source_id") != sid:
            continue
        is_ops = gen.get("mode") == "ops"
        if not is_ops:
            # M-16 fix: 低置信生成工具不落地 — 跳过执行, 记 errors 待人工审核
            # (CLAUDE.md Layer 3 契约: confidence<0.7 需人工审核)
            try:
                confidence = float(gen.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            # P1 (f): 阈值引用共享常量 (planning/exec 同源, 禁止任一侧硬编码漂移)
            if confidence < _CONFIDENCE_EXEC_THRESHOLD:
                result["errors"].append({
                    "source_id": sid, "tool": gen.get("tool_name", "?"),
                    "kind": "low_confidence",
                    "confidence": confidence,
                    "error": (f"generated tool confidence {confidence} < "
                              f"{_CONFIDENCE_EXEC_THRESHOLD}, requires human review"),
                })
                continue
        prev_err_count = len(result["errors"])
        if is_ops:
            r = agent._execute_ops(gen, srecs, ctx, result["errors"])
        else:
            r = agent._execute_generated(gen, srecs, sandbox_globals, result["errors"])
        if r:
            logs = r.get("log", [])
            result["generated_logs"].extend(logs)
            result["total"] += len(logs)
            result["tool_count"] += 1
            if "data" in r:
                srecs = r["data"]
        else:
            # P2 (g)1: 结构化错误 — _execute_generated 已记录具体 kind 时不重复追加
            if len(result["errors"]) == prev_err_count:
                result["errors"].append({"source_id": sid, "tool": gen.get("tool_name", "?"),
                                         "kind": "exec_error",
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

        result = {"data_state": {"current_data": data, "data_trace": data_trace},
                  "report_state": {"normalization": norm},
                  "workflow_state": {"current_node": "normalization", "execution_status": "Success",
                                     "tool_call_count": wf.get("tool_call_count", 0) + tc,
                                     "workflow_history": [{"agent": "ToolExecutorAgent", "stage": "ToolExecution",
                                          "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                                          "duration": elapsed,
                                          "reason": f"{total} mods (PARALLEL, base={len(mods['base'])} adapted={len(mods['adapted'])} generated={len(mods['generated'])})"}]}}
        # 2026-08-13 兜底：执行器已拦截工具结果环，此处双保险 — 检出环/超深则
        # 整个结果剥环重建（循环引用替换 <cycle>，超深替换 <deep>，正常修改保留），
        # 保证任何环来源都进不了 checkpoint（记录路径便于定位环的写入方）
        bad = _find_cyclic_or_deep(result)
        if bad:
            logger.error("[ToolExec] 兜底检出循环/超深数据 (path=%s, kind=%s)，返回状态已剥环重建",
                         bad[0], bad[1])
            result = _strip_cycles(result)
        return result

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

    def _execute_generated(self, gen, records, sandbox_globals, error_sink=None):
        """V2.1: 安全沙箱执行 — AST 白名单 + 空 __builtins__

        H-12 fix: exec 与 fn 调用在线程中执行并设硬超时 + 输出大小上限,
        超时/超限判生成失败 (回退 Base Tools)。
        M-19 fix: 全量执行复现 dry-run 的记录数/字段键集合稳定性校验,
        不满足则丢弃结果并记错误 (在深拷贝上执行, 校验通过才采纳)。
        P2 (g)(h): error_sink 可选错误收集列表 (调用方传 result["errors"]),
        失败路径写入结构化对象 {source_id, tool, kind, error, line?};
        执行端 no-op 检测 (全量 0 修改 → kind=noop, 无 unverifiable 概念);
        边界: 数据变但 log 空 → 采纳 + kind=missing_log 非阻断错误。
        """
        def _fail(kind, message, line=None):
            if error_sink is not None:
                entry = {"source_id": gen.get("source_id", ""),
                         "tool": gen.get("tool_name", "?"),
                         "kind": kind, "error": message}
                if line is not None:
                    entry["line"] = line
                error_sink.append(entry)
            return None

        try:
            code = gen.get("tool_code", "")
            if not code:
                return _fail("exec_error", "generated tool has no tool_code")

            # ── V2.1: AST 安全校验 (H-12: 含死循环静态防护) ──
            verdict = _validate_code_ast(code)
            if not verdict:
                logger.warning("[ToolExec] Generated code blocked: AST validation failed")
                return _fail("ast_blocked", verdict.get("message", ""),
                             verdict.get("line"))

            # H-12 fix: 编译 + exec 在线程中执行, 硬超时
            def _exec_code():
                exec(compile(code, "<sandbox>", "exec"), sandbox_globals)  # nosec B102 — AST 白名单沙箱

            exec_outcome = _run_with_timeout(_exec_code)
            if not exec_outcome["ok"]:
                logger.warning("[ToolExec] Generated '%s' exec timed out/failed",
                               gen.get("tool_name", "?"))
                return _fail("exec_timeout" if isinstance(exec_outcome["error"], TimeoutError)
                             else "exec_error", str(exec_outcome["error"]))

            # V3.1 fix: 模板固定生成 def tool(...), 兼容 LLM 声明的 tool_name
            fn = sandbox_globals.get(gen["tool_name"]) or sandbox_globals.get("tool")
            if not fn:
                return _fail("exec_error", "generated function not found in sandbox")

            # M-19 fix: 在深拷贝上执行, 校验通过才采纳 (失败可安全丢弃, 不改原记录)
            records_copy = copy.deepcopy(records)
            outcome = _run_with_timeout(fn, (records_copy,))
            if not outcome["ok"]:
                logger.error("[ToolExec] Generated '%s' failed: %s",
                             gen.get("tool_name", "?"), outcome["error"])
                return _fail("exec_timeout" if isinstance(outcome["error"], TimeoutError)
                             else "exec_error", str(outcome["error"]))
            result = outcome["result"]
            # P0 (c): 共享不变量门 — 与 planning dry-run 同一 _validate_generated_result
            # (invalid_format / record_count_changed / key_set_changed / log_too_large)
            check = _validate_generated_result(records, result, _SANDBOX_MAX_LOG_ENTRIES)
            if not check["ok"]:
                logger.warning("[ToolExec] Generated '%s': rejected (kind=%s): %s",
                               gen.get("tool_name", "?"), check["kind"], check["message"])
                return _fail(check["kind"], check["message"])
            # P2 (h): 执行端 no-op 检测 — 全量 0 修改 → kind=noop 失败对象 → 丢弃
            # (无 unverifiable 概念 — 目标问题必存在否则不会规划 Layer 3)
            if _detect_noop(records, result)["noop"]:
                logger.warning("[ToolExec] Generated '%s': no-op on full data (rejected)",
                               gen.get("tool_name", "?"))
                return _fail("noop", "generated tool made zero modifications on full data")
            # P1 (f): self_check 验证 (M-19 键集合检查之后, 与 planning dry-run 共用
            # _verify_self_check) — 失败 → effective confidence ×0.3 (exec 只消费
            # effective; planning 侧已在注册时算好 effective, 此处做审计兜底)
            self_check_data = gen.get("self_check")
            self_check_ok = True
            if self_check_data:
                sc = _verify_self_check(result, self_check_data, records)
                self_check_ok = sc["ok"]
                if not sc["ok"]:
                    logger.warning("[ToolExec] Generated '%s': self_check FAILED (%d): %s",
                                   gen.get("tool_name", "?"), len(sc["failed"]),
                                   str(sc["failed"][:2])[:200])
            try:
                conf = float(gen.get("confidence") or 0)
            except (TypeError, ValueError):
                conf = 0.0
            result["effective_confidence"] = _compute_effective_confidence(conf, self_check_ok)
            # P2 (h): 边界 — 数据变但 log 空 → 采纳 + 非阻断错误 (缺审计轨迹需人工可见)
            if not (result.get("log") or []):
                if error_sink is not None:
                    error_sink.append({
                        "source_id": gen.get("source_id", ""),
                        "tool": gen.get("tool_name", "?"),
                        "kind": "missing_log",
                        "error": "data modified but log is empty (traceability gap)",
                    })
            # 2026-08-13 根治：工具返回数据环/深度检测 — 有环或超深则丢弃
            #（否则环进入子图状态，checkpointer ormsgpack 序列化炸整条管线）
            bad = _find_cyclic_or_deep(result)
            if bad:
                logger.error("[ToolExec] Generated '%s': 检出循环/超深数据 (path=%s, kind=%s), 丢弃该工具结果",
                             gen.get("tool_name", "?"), bad[0], bad[1])
                return _fail("cyclic_data", f"cyclic/deep data at {bad[0]} (kind={bad[1]})")
            return result
        except Exception as e:
            logger.error("[ToolExec] Generated '%s' failed: %s", gen.get("tool_name", "?"), e)
            return _fail("exec_error", str(e))

    def _execute_ops(self, gen, records, ctx=None, error_sink=None):
        """P3 (层 A): 模板驱动 ops 执行 — 确定性执行器, 不进沙箱。

        execute_ops 内部已做逐 op 不变量门 (kind=op_invariant_failed 结构化失败);
        此处复用共享 _validate_generated_result 门 + _detect_noop (与 code 路径
        同一 SSOT), 边界: 数据变但 log 空 → 采纳 + kind=missing_log 非阻断错误。
        """
        def _fail(kind, message, line=None):
            if error_sink is not None:
                entry = {"source_id": gen.get("source_id", ""),
                         "tool": gen.get("tool_name", "?"),
                         "kind": kind, "error": message}
                if line is not None:
                    entry["line"] = line
                error_sink.append(entry)
            return None

        try:
            from quality_pipeline.tools.normalization.op_executor import (
                execute_ops, OpSpec,
            )
            raw_ops = gen.get("ops") or []
            if not raw_ops:
                return _fail("exec_error", "ops entry has no ops")
            try:
                specs = [op if isinstance(op, OpSpec) else OpSpec.model_validate(op)
                         for op in raw_ops]
            except Exception as e:  # noqa: BLE001 — 契约失败即结构化错误
                return _fail("exec_error", f"invalid op spec: {e}")
            ctx = ctx or {}
            result = execute_ops(
                records, specs,
                research_domain=ctx.get("research_domain"),
                semantic_types=ctx.get("semantic_types"),
                target_schema=ctx.get("target_schema"),
                standard_units=ctx.get("standard_units"),
            )
            # 不变量违规 — 确定性执行器理论上不应触发 (防御纵深), 结构化失败
            if result.get("kind") == "op_invariant_failed":
                return _fail("op_invariant_failed",
                             f"{result.get('op', '?')}: {result.get('message', '')}")
            # 共享不变量门 (invalid_format / record_count_changed / key_set_changed
            # / log_too_large) — 与 _execute_generated 同一 _validate_generated_result
            check = _validate_generated_result(records, result, _SANDBOX_MAX_LOG_ENTRIES)
            if not check["ok"]:
                return _fail(check["kind"], check["message"])
            # 执行端 no-op 检测 — 全量 0 修改 → kind=noop 拒绝 (无 unverifiable 概念)
            if _detect_noop(records, result)["noop"]:
                return _fail("noop", "ops made zero modifications on full data")
            # 边界 — 数据变但 log 空 → 采纳 + 非阻断错误 (缺审计轨迹需人工可见)
            if not (result.get("log") or []):
                if error_sink is not None:
                    error_sink.append({
                        "source_id": gen.get("source_id", ""),
                        "tool": gen.get("tool_name", "?"),
                        "kind": "missing_log",
                        "error": "data modified but ops log is empty (traceability gap)",
                    })
            # 2026-08-13 根治：与 _execute_generated 同款环/深度检测 — 有环则丢弃
            bad = _find_cyclic_or_deep(result)
            if bad:
                logger.error("[ToolExec] Ops '%s': 检出循环/超深数据 (path=%s, kind=%s), 丢弃该工具结果",
                             gen.get("tool_name", "?"), bad[0], bad[1])
                return _fail("cyclic_data", f"cyclic/deep data at {bad[0]} (kind={bad[1]})")
            return result
        except Exception as e:
            logger.error("[ToolExec] Ops '%s' failed: %s", gen.get("tool_name", "?"), e)
            return _fail("exec_error", str(e))


# 2026-08-13 根治：工具返回数据环/深度检测 — LLM 生成的工具代码可能把 records
# 列表嵌入记录字段形成循环引用（deepcopy 保留环），LangGraph checkpointer 用
# ormsgpack 序列化时抛 "Recursion limit reached" 使整条质量管线瘫痪
#（任务 7601ee09 / 23ccc187 实测：ormsgpack 深度 >400 层或循环引用均抛该错）。
# 检测函数返回首个问题路径；None = 干净。ancestors 为祖先链集合（出栈即移除），
# 只报真环，兄弟节点的相同对象不算环。
_STRUCT_MAX_DEPTH = 100  # ormsgpack 实测 ~400 层炸，留 4 倍余量


def _find_cyclic_or_deep(obj, max_depth: int = _STRUCT_MAX_DEPTH):
    """返回 (path, kind) 首个超深/循环引用；无问题返回 None。
    kind: 'depth'（嵌套超 _STRUCT_MAX_DEPTH）| 'cycle'（循环引用）。
    path 形如 records[3].parent，便于定位是哪个工具写入的脏数据。"""
    ancestors = set()

    def walk(x, depth: int, path: str):
        if depth > max_depth:
            return (path or "<root>", "depth")
        oid = id(x)
        if oid in ancestors:
            return (path or "<root>", "cycle")
        ancestors.add(oid)
        try:
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(v, (dict, list)):
                        r = walk(v, depth + 1, f"{path}.{k}")
                        if r:
                            return r
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    if isinstance(v, (dict, list)):
                        r = walk(v, depth + 1, f"{path}[{i}]")
                        if r:
                            return r
        finally:
            ancestors.discard(oid)
        return None

    return walk(obj, 0, "")


def _strip_cycles(obj, max_depth: int = _STRUCT_MAX_DEPTH):
    """重建结构为无环副本：循环引用替换为 "<cycle>"、超深引用替换为 "<deep>"。

    兜底防线 — 源头（planning_agent layer3.attempts 深拷贝）修好前/修好后的
    双保险：任何环进了返回状态，LangGraph checkpointer 序列化必炸，剥环后
    正常字段（工具修改等）全部保留，仅环引用被替换。
    """
    ancestors = set()

    def build(x, depth: int):
        if depth > max_depth:
            return "<deep>"
        if isinstance(x, dict):
            if id(x) in ancestors:
                return "<cycle>"
            ancestors.add(id(x))
            out = {k: (build(v, depth + 1) if isinstance(v, (dict, list)) else v)
                   for k, v in x.items()}
            ancestors.discard(id(x))
            return out
        if isinstance(x, list):
            if id(x) in ancestors:
                return "<cycle>"
            ancestors.add(id(x))
            out = [build(v, depth + 1) if isinstance(v, (dict, list)) else v for v in x]
            ancestors.discard(id(x))
            return out
        return x

    return build(obj, 0)


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
