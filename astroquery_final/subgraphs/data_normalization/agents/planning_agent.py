"""
planning_agent.py — Stage 2: ToolPlanningAgent (V2.3)

核心创新: LLM 根据数据问题自动规划工具链:
  Layer 1: 选择 Base Tools (6个确定性工具)
  Layer 2: 生成 Adapted Tools (规则注入自定义参数)
  Layer 3: 生成 Custom Tools (LLM 动态编写 Python 函数)

V2.3: per-source 并行规划 (Layer 3 LLM 调用并行化)。
"""
from __future__ import annotations
import datetime
import time
import json
import re
import ast
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from pydantic import ValidationError
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger
# P2 (g): 反馈闭环共享常量 — kind 枚举 / 修复预算 (与 validation 三态门同源)
from quality_pipeline.sandbox.sandbox_common import (
    _MAX_REPAIR_ROUNDS, _KIND_RETRY_ONCE, _KIND_NO_RETRY,
    _detect_noop, _sample_has_target_issue,
)
logger = get_logger(__name__)

# Condition → Base Tool 映射
_CONDITION_TOOL_MAP = {
    "alias_fields":       "schema_mapping",
    "extra_fields":       "schema_mapping",
    "format_issues":      "field_standardizer",
    "unit_inconsistency": "unit_converter",
    "missing_units":      "missing_value_handler",
    "missing_provenance": "missing_value_handler",
    "completeness_low":   "missing_value_handler",
    "duplicate_records":  "duplicate_handler",
    "general":            "format_standardizer",
}

# P2 (g)5: 致命执行失败 kind — 已注册工具在 exec 端失败 (非 low_confidence/missing_log),
# 说明该工具在真实数据上不可用 → 清空 generated 重新生成 (预算内)。
# low_confidence → 人工审核不重生成; missing_log → 非阻断已采纳不重生成。
_FATAL_REGEN_KINDS = frozenset({
    "exec_error", "exec_timeout", "noop", "key_set_changed",
    "record_count_changed", "log_too_large", "invalid_format",
})


def _render_repair_context(prev_failures) -> str:
    """P2 (g)4: 修复轮反馈渲染 — {kind} @ line {line}: {error} + 上一版完整 code。

    输入为结构化失败对象列表 ({source_id, tool, kind, error, line?, code?}),
    输出为注入 prompt 的 PREVIOUS ERRORS 段 (含代码块, 供 LLM 定位修复)。
    """
    if not prev_failures:
        return ""
    parts = []
    for f in prev_failures:
        if not isinstance(f, dict):
            continue
        kind = f.get("kind", "?")
        line = f.get("line")
        loc = f" @ line {line}" if line is not None else ""
        error = str(f.get("error", f.get("message", "unknown")))[:300]
        parts.append(f"- [{kind}{loc}] {error}")
        code = f.get("code")
        if code:
            parts.append(f"```python\n{code}\n```")
    if not parts:
        return ""
    return "\nPREVIOUS ERRORS (fix these):\n" + "\n".join(parts) + "\n"


# ── V4 fix: 领域感知 standard_unit 查询 ──
# infer_semantic_type 返回 dict 无 standard_unit 键 (semantic_type.py:74-82),
# 导致 adapted 单位参数恒空。改为从 target_schema (context 优先, 领域配置兜底)
# 按字段名 + 别名构建映射, 兼容 entity-aware key ("{entity}:{name}/{field}")。
def _build_schema_std_unit_map(state: QualityGraphState) -> dict[str, str]:
    """构建 {field_name.lower(): standard_unit} + 别名映射 (只读, 线程安全)。"""
    from quality_pipeline.configs import load_domain_schema_config
    # Phase 3: 显式 research_domain (从 state), 兜底全局
    domain = state.get("context_state", {}).get("research_domain")
    schema = (state.get("context_state", {}).get("target_schema")
              or load_domain_schema_config("target_schema", research_domain=domain))
    m: dict[str, str] = {}
    for f in (schema or {}).get("fields", []):
        u = f.get("standard_unit")
        if f.get("name") and u:
            m[str(f["name"]).lower()] = u
            for a in f.get("aliases", []) or []:
                m[str(a).lower()] = u
    return m

# V3.1: 预编译的安全代码模板 — LLM 只填 business logic，不生成 boilerplate
_TOOL_CODE_TEMPLATE = r'''
def tool(records):
    """Auto-generated data cleaning tool. See summary for details."""
    import re, math, json, copy
    from collections import defaultdict, Counter
    from itertools import chain, groupby
    from statistics import mean, median, stdev

    def _safe_get(rec, key, default=None):
        """防御性取值，处理 None/缺失/非dict。"""
        if not isinstance(rec, dict):
            return default
        return rec.get(key, default)

    # CRITICAL: 只允许修改现有 records, 禁止 append/新增/删除记录。
    # records 列表长度必须保持不变 (dry-run 会校验)。

    def _is_numeric(val):
        """判断值是否为数值（含字符串形式的数字）。"""
        if isinstance(val, (int, float)):
            return True
        if isinstance(val, str):
            return bool(re.match(r"^-?\d+\.?\d*(?:[eE][+-]?\d+)?$", val.strip()))
        return False

    def _to_number(val):
        """安全转换为 int 或 float。"""
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            s = val.strip()
            try:
                return int(s) if "." not in s and "e" not in s.lower() else float(s)
            except (ValueError, TypeError):
                return val
        return val

    _log = []
    _summary = ""
    # ============================================================
    # 业务逻辑（由 LLM 填写，可使用上述 helper 函数和 _log, _summary, records）
    # ============================================================
    # LLM_GENERATED_LOGIC_START
{LLM_CODE}
    # LLM_GENERATED_LOGIC_END
    # ============================================================

    return {"data": records, "log": _log, "summary": _summary}
'''

_TOOL_GEN_SYSTEM = """You are a scientific data cleaning expert. Write ONLY the business logic
to insert into a pre-existing Python function template (P1 d: schema-in-prompt).

The template ALREADY handles:
- Empty input, None values, missing keys — use _safe_get() for safety
- Type checking — use _is_numeric() and _to_number()
- Return format — {"data": records, "log": _log, "summary": _summary}

=== AVAILABLE ENVIRONMENT (inside the sandbox) ===
Builtins: True/False/None, abs, all, any, bool, dict, enumerate, filter, float,
int, isinstance, len, list, map, max, min, print, range, round, set, sorted,
str, sum, tuple, zip, reversed, next, iter, type, repr, format, issubclass,
callable, id, hash, frozenset, bytes, bytearray, complex, divmod, pow, ord, chr,
Exception, ValueError, TypeError, KeyError, IndexError, AttributeError,
StopIteration, RuntimeError, ZeroDivisionError, OverflowError,
ArithmeticError, LookupError
Modules: math, re, json, copy, datetime, collections, itertools, functools,
typing, statistics, decimal, fractions, hashlib, warnings, base64, uuid,
string, textwrap  (NOT operator/logging/numpy)
Helpers (already defined): _safe_get(rec, key, default), _is_numeric(v),
_to_number(v); _log (list) and _summary (str) are initialized.

=== YOUR JOB ===
Write ONLY the code that goes between LLM_GENERATED_LOGIC_START and
LLM_GENERATED_LOGIC_END. This code runs INSIDE a function — do NOT write
top-level def, import, return, or class statements.

=== 8 HARD CONSTRAINTS (checked by the executor, violation = rejection) ===
1. Records count MUST stay unchanged — NEVER append/remove records
2. Field key set MUST stay unchanged — NEVER add/remove record keys
3. No import/return/class statements in the logic (nested helper defs allowed)
4. No dangerous calls: eval/exec/compile/open/getattr/setattr/delattr/
   __import__/input/globals/locals/breakpoint
5. while loops MUST be bounded — constant-false condition, or bounded counter
   (e.g. while i < N: i += 1), or an explicit break; NEVER while True without break
6. Append exactly one _log entry per modified record
7. Set _summary to a one-sentence description of what was done
8. Use 4-space indentation (no tabs)

=== HOW TO MODIFY RECORDS ===
  val = _safe_get(rec, "field_name")
  new_val = ...transform val...
  if new_val != val:            # write back ONLY when the value actually changes
      rec["field_name"] = new_val
      _log.append({"record_id": _safe_get(rec,"record_id","?"), "field": "field_name",
                   "action": "transform", "before": str(val), "after": str(new_val)})

=== DATA-DRIVEN RULES ===
- Use _is_numeric(v) to check if v needs conversion, NOT hardcoded field names
- Use re.match(pattern, str(v)) for pattern matching
- For field renames: use a mapping dict {"old": "new"} and check _safe_get(rec, "field_name")
- If unsure whether a fix is safe, SKIP it — don't guess
- CRITICAL: records are dicts, rec["key"] = new_value is fine.
  rec["key"]["sub"] = x is WRONG — field_value is a string/int/float, not a dict.
  To modify: rec["field_name"] = new_value (assign to top-level key directly)
- provenance is READ-ONLY — never modify it or its inner keys
- Empty-string field_unit means the record is missing its unit

=== OUTPUT CONTRACT (strict JSON object, NO markdown fences, NO extra keys) ===
{
  "tool_name": "short_descriptive_name",
  "tool_code": "the business logic code (LLM_GENERATED_LOGIC_START/END content)",
  "confidence": 0.9,   // REQUIRED 0-1 — self-estimated signal, NOT an exam score;
                        // never raise it when asked to fix
  "self_check": {
    "assertions": [{"field": "field_name", "assert": "<enum>", "expected": ...}],
    "sample_predictions": [{"record_id": "...", "field": "...", "before": <value>, "after": <value>}]
  },
  "reasoning": "one sentence explaining the approach"
}
assert enum: no_tilde_prefix | all_numeric | no_nan | all_str | trimmed |
no_empty_str | unit_present | unit_equals | value_equals | changed |
record_count_unchanged | key_set_unchanged
sample_predictions.before MUST equal the real input value of that record
(sample records are provided in the user message) — mismatch is rejected."""


# ══════════════════════════════════════════════════════════════
# P0 (e): 后处理管线 — 锚定 JSON 提取 / marker 分割 / AST 手术 / 缩进降级
# (替换旧裸正则 r'{.*}' + 行正则消毒 + min_indent 负 delta 缩进逻辑;
#  对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(e))
# ══════════════════════════════════════════════════════════════

_LLM_LOGIC_START_MARKER = "# LLM_GENERATED_LOGIC_START"
_LLM_LOGIC_END_MARKER = "# LLM_GENERATED_LOGIC_END"


def _extract_json_object(text):
    """锚定 JSON 提取: 剥 markdown fence → 从第一个 { 起括号平衡扫描取首个完整对象。

    尾随文本 (prose) 自然丢弃; 失败返回 (None, error_message), 调用方据此返回
    结构化失败 {kind: "parse_error", message} 而非静默 None。
    """
    if not isinstance(text, str) or not text.strip():
        return None, "empty LLM response"
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z]*\s*", "", stripped)
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
    first = stripped.find("{")
    if first < 0:
        return None, "no JSON object found in LLM response"
    # 括号平衡扫描 (字符串/转义感知), 取首个完整对象; 尾随文本自然丢弃
    depth = 0
    in_str = False
    escaped = False
    for i in range(first, len(stripped)):
        ch = stripped[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj_text = stripped[first:i + 1]
                try:
                    return json.loads(obj_text), None
                except json.JSONDecodeError as e:
                    return None, f"invalid JSON object: {e}"
    return None, "unbalanced braces: no complete JSON object in LLM response"


def _extract_business_logic(code):
    """marker 分割: START/END 之间取逻辑 (END 缺失到串尾); 无 marker 且有
    'def tool(' → AST 手术取首个 FunctionDef.body; 否则整段 (容忍侧)。"""
    if not isinstance(code, str):
        return ""
    if _LLM_LOGIC_START_MARKER in code:
        rest = code.split(_LLM_LOGIC_START_MARKER, 1)[1]
        if _LLM_LOGIC_END_MARKER in rest:
            rest = rest.split(_LLM_LOGIC_END_MARKER, 1)[0]
        return rest
    if "def tool(" in code:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "tool":
                return ast.unparse(node.body)
        return code
    return code


def _indent_into_function(code):
    """统一 4 空格前缀 — 模板 {LLM_CODE} 位于函数体上下文, 顶层语句需 4 空格基准缩进。"""
    return "\n".join(("    " + line) if line.strip() else line
                     for line in code.split("\n"))


def _surgical_clean_logic(logic):
    """AST 手术: expandtabs(4) → 仅删模块级 ast.Return (嵌套 FunctionDef 内
    的 return 保留) → ast.unparse 重渲染 (自动 4 空格归一) → 统一 4 空格前缀。

    不再做任何行正则删除 (import/def/class 保留, 非白名单 import 由
    _validate_code_ast 统一拒绝)。ast.parse 失败时走缩进降级路径
    (textwrap.dedent + 非空行统一 4 空格前缀, 替代旧 min_indent/负 delta)。
    """
    try:
        tree = ast.parse(logic.expandtabs(4))
    except SyntaxError:
        return _indent_fallback_logic(logic)
    tree.body = [n for n in tree.body if not isinstance(n, ast.Return)]
    return _indent_into_function(ast.unparse(tree))


def _indent_fallback_logic(logic):
    """缩进降级路径: textwrap.dedent 消除公共缩进 → 非空行统一 4 空格前缀。"""
    dedented = textwrap.dedent(logic.expandtabs(4))
    return "\n".join(("    " + line) if line.strip() else line
                     for line in dedented.split("\n"))


# ══════════════════════════════════════════════════════════════
# P1 (d): Schema 感知 Prompt — 字段 Schema 块 + golden few-shot 选取
# (对应 docs/NORMALIZATION_LAYER3_OPTIMIZATION.md §6(d))
# ══════════════════════════════════════════════════════════════

def _build_schema_block(target_schema, field_profile) -> str:
    """构建【字段 Schema】JSON 块 — target_schema 与字段统计合并 (P1 d)。

    每字段: key / inferred_type / types_seen / missing_rate / sample_values /
    sample_units / numeric_range / target_schema_required / schema_type /
    standard_unit / criticality / aliases。target_schema 取自 ctx/context_state
    (可能为 None — 各 schema 项相应缺省, 不崩溃)。
    """
    schema_fields: list[dict] = []
    if isinstance(target_schema, dict):
        for f in target_schema.get("fields", []) or []:
            if isinstance(f, dict) and f.get("name"):
                schema_fields.append(f)
    name_to_schema = {str(f["name"]).lower(): f for f in schema_fields}
    alias_to_schema: dict[str, dict] = {}
    for f in schema_fields:
        for a in f.get("aliases", []) or []:
            alias_to_schema[str(a).lower()] = f

    block = {}
    for fn, p in sorted((field_profile or {}).items()):
        if not isinstance(p, dict):
            continue
        sfield = name_to_schema.get(str(fn).lower()) or alias_to_schema.get(str(fn).lower())
        types = p.get("types") or {}
        count = p.get("count") or 0
        block[fn] = {
            "inferred_type": "numeric" if types.get("numeric") else "string",
            "types_seen": types,
            "missing_rate": round((p.get("null_count") or 0) / count, 4) if count else None,
            "sample_values": (p.get("sample_values") or [])[:3],
            "sample_units": (p.get("sample_units") or [])[:3],
            "numeric_range": p.get("numeric_range"),
            "target_schema_required": sfield is not None,
            "schema_type": (sfield or {}).get("type"),
            "standard_unit": (sfield or {}).get("standard_unit"),
            "criticality": (sfield or {}).get("criticality"),
            "aliases": (sfield or {}).get("aliases") or [],
        }
    return json.dumps(block, indent=2, ensure_ascii=False)


_FEW_SHOT_SELECT_COUNT = 3
_FEW_SHOT_EXAMPLES_CACHE: list | None = None


def _load_tool_examples() -> list:
    """加载 quality_pipeline/configs/tool_examples.yaml 的 golden few-shot (模块级缓存)。"""
    global _FEW_SHOT_EXAMPLES_CACHE
    if _FEW_SHOT_EXAMPLES_CACHE is None:
        try:
            from quality_pipeline.configs import load_yaml
            data = load_yaml("tool_examples.yaml") or {}
            _FEW_SHOT_EXAMPLES_CACHE = list(data.get("examples") or [])
        except Exception as e:
            logger.warning("[ToolPlan] tool_examples.yaml load failed: %s", e)
            _FEW_SHOT_EXAMPLES_CACHE = []
    return _FEW_SHOT_EXAMPLES_CACHE


def _render_few_shots(issues_text) -> str:
    """按 issue 关键词匹配选取 ≤3 条 golden 示例, 渲染为 prompt 段 (P1 d)。

    关键词命中优先 (score 降序), 未命中示例按序补齐至 3 条; 渲染仅输出
    输出契约键 (tool_name/tool_code/confidence/self_check/reasoning)。
    """
    examples = _load_tool_examples()
    if not examples:
        return ""
    issues_lower = (issues_text or "").lower()
    scored = []
    for idx, ex in enumerate(examples):
        kws = [str(k).lower() for k in (ex.get("keywords") or [])]
        score = sum(1 for k in kws if k and k in issues_lower)
        scored.append((score, idx, ex))
    scored.sort(key=lambda t: (-t[0], t[1]))  # score 降序 → 原序补齐
    picked = [ex for _, _, ex in scored][:_FEW_SHOT_SELECT_COUNT]

    lines = []
    for i, ex in enumerate(picked, 1):
        contract = {
            "tool_name": ex.get("tool_name", ""),
            "tool_code": ex.get("tool_code", ""),
            "confidence": ex.get("confidence"),
            "self_check": ex.get("self_check") or {},
            "reasoning": ex.get("reasoning", ""),
        }
        lines.append(f"示例 {i} ({ex.get('name', '')}):\n"
                     + json.dumps(contract, indent=2, ensure_ascii=False))
    return "\n\n".join(lines)


class PlanningAgent:
    """Stage 2: ToolPlanningAgent — LLM 驱动的工具规划 (V2.0)。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {}); wf = state.get("workflow_state", {})
        norm = dict(rs.get("normalization", {}) or {})
        quality = rs.get("quality", {}) or {}
        sp = norm.get("source_plan", {}); trigger = sp.get("trigger_source", "quality_report")
        sources_to_process = sp.get("sources_to_normalize", {})

        # ── Conflict Report → 全量 Base Tools ──
        if trigger == "conflict_report":
            by_source = {}
            for sid, src_info in sources_to_process.items():
                by_source[sid] = {
                    "base": list(_CONDITION_TOOL_MAP.values()),
                    "adapted": [], "generated": [],
                    # V3.5 fix: 透传 conflict_ctions (HumanReview/Conflict 动作)
                    "conflict_ctions": src_info.get("conflict_ctions") or [],
                }
            tool_registry = {"base_tools": list(_CONDITION_TOOL_MAP.values()),
                             "adapted_tools": [], "generated_tools": [],
                             "by_source": by_source}
            norm["tool_registry"] = tool_registry
            norm["planning_method"] = "full_normalization"
            return self._build_return(norm, wf, t0, "full_normalization", len(sources_to_process))

        # ── Quality Report → LLM 增强规划 ──
        tool_registry = {"base_tools": [], "adapted_tools": [], "generated_tools": [],
                         "by_source": {}}
        sources_info = quality.get("sources", {})
        profile = quality.get("profile", {})
        semantic_types = profile.get("semantic_types", {})
        llm_count = wf.get("llm_call_count", 0)

        # ══════════════════════════════════════════════════
        # V2.3: 并行规划 (Layer 1+2 快速确定性, Layer 3 LLM 并行)
        # ══════════════════════════════════════════════════
        n_workers = min(8, max(1, len(sources_to_process)))
        logger.info("[ToolPlan] Planning %d sources with %d workers (PARALLEL)", len(sources_to_process), n_workers)

        # Step 1: 快速并行 Layer 1+2 (确定性, 无需 LLM)
        # V4 fix: schema 标准单位映射 (只读, 线程安全)
        std_map = _build_schema_std_unit_map(state)
        source_plans: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futs = {}
            for sid, src_info in sources_to_process.items():
                f = executor.submit(
                    self._plan_layers_1_2,
                    sid, src_info, sources_info, semantic_types, std_map
                )
                futs[f] = sid
            for future in as_completed(futs):
                sid = futs[future]
                try:
                    source_plans[sid] = future.result()
                except Exception as e:
                    logger.warning("[ToolPlan] Planning Layer1+2 failed for %s: %s", sid, e)
                    source_plans[sid] = {"base": ["field_standardizer", "format_standardizer"],
                                         "adapted": [], "generated": []}

        # V3.5 fix: 透传 conflict_ctions (HumanReview/Conflict 动作) 到 by_source
        for sid, src_info in sources_to_process.items():
            c_actions = src_info.get("conflict_ctions") or []
            if c_actions and sid in source_plans:
                source_plans[sid]["conflict_ctions"] = c_actions

        # P2 (g)5: 复用上轮已注册的 generated tools — validation Retry 后
        # tool_registry 重建, 需把上轮注册/成功的工具带进新计划 (否则重试轮
        # 丢失已生效工具); 失败工具的清除/重生成由下方 Layer 3 决策处理
        prev_registry = (norm.get("tool_registry") or {}).get("by_source", {}) or {}
        for sid, plan in source_plans.items():
            prev_gen = (prev_registry.get(sid) or {}).get("generated") or []
            if prev_gen and not plan.get("generated"):
                plan["generated"] = list(prev_gen)

        # Step 2: 并行 Layer 3 LLM (只对 needs_custom 的 source)
        # ── P2 (g): 反馈闭环 — 跨轮 prev_failures = modifications.errors ∪
        # layer3.attempts; 失败对象逐条入 layer3.attempts; 修复预算 repair_left
        # 跨轮持久, 每 source ≤ 1+MAX_REPAIR_ROUNDS 次 LLM 调用 ──
        prev_mods = norm.get("modifications", {}) or {}
        prev_errors = prev_mods.get("errors", [])
        layer3 = dict(norm.get("layer3", {}) or {})
        layer3_attempts = list(layer3.get("attempts", []) or [])
        repair_left = dict(layer3.get("repair_left", {}) or {})
        succeeded = dict(layer3.get("succeeded", {}) or {})

        llm_sources = [
            (sid, plan) for sid, plan in source_plans.items()
            if self._find_unresolved(plan, sources_info.get(sid, {})).get("needs_custom")
        ]
        if llm_sources:
            logger.info("[ToolPlan] Layer 3 LLM generation for %d sources (parallel)", len(llm_sources))
            with ThreadPoolExecutor(max_workers=min(n_workers, len(llm_sources))) as executor:
                llm_futs = {}
                for sid, plan in llm_sources:
                    # P2 (g)5: 修复"已注册失败工具永不重生成" —
                    #   layer3.succeeded 命中 → 复用 (skip);
                    #   prev_failures 含致命 kind 且 repair_left>0 → 清空 generated 重新生成;
                    #   其余已注册 → skip
                    if sid in succeeded:
                        logger.info("[ToolPlan] %s: tool succeeded in previous round, reusing", sid[:20])
                        continue
                    if plan.get("generated"):
                        prev_failures_for_sid = [
                            e for e in prev_errors if e.get("source_id") == sid
                        ]
                        fatal = [e for e in prev_failures_for_sid
                                 if e.get("kind") in _FATAL_REGEN_KINDS]
                        if fatal and repair_left.get(sid, 0) > 0:
                            logger.info("[ToolPlan] %s: registered tool failed (kind=%s), regenerating",
                                        sid[:20], fatal[0].get("kind"))
                            plan["generated"] = []
                        else:
                            logger.info("[ToolPlan] %s: already has generated tool, skipping (max 1 attempt)", sid[:20])
                            continue
                    unresolved = self._find_unresolved(plan, sources_info.get(sid, {}))
                    profile = self._get_source_profile(state, sid)  # V3.1: field statistics
                    # P2 (g)3: 跨轮 prev_failures = modifications.errors ∪ layer3.attempts
                    prev_failures_for_sid = [
                        e for e in prev_errors if e.get("source_id") == sid
                    ] + [
                        e for e in layer3_attempts if e.get("source_id") == sid
                    ]
                    if sid not in repair_left:
                        repair_left[sid] = _MAX_REPAIR_ROUNDS
                    # P2 (g)4: 修复循环外包 (每 source 独立计时, 预算内 ≤3 次 LLM)
                    f = executor.submit(self._llm_generate_tool_repair_loop, sid, unresolved,
                                        profile, prev_failures_for_sid, plan,
                                        state.get("context_state", {}).get("target_schema"),
                                        repair_left.get(sid, _MAX_REPAIR_ROUNDS))
                    llm_futs[f] = sid
                for future in as_completed(llm_futs):
                    sid = llm_futs[future]
                    try:
                        custom = future.result()
                        if not custom:
                            continue
                        attempts_done = custom.get("attempts") or []
                        layer3_attempts.extend(attempts_done)
                        llm_count += custom.get("llm_calls", 1)
                        repair_left[sid] = max(0, repair_left.get(sid, 0)
                                               - custom.get("repair_consumed", 0))
                        if not custom.get("kind"):
                            source_plans[sid]["generated"] = [custom]
                            succeeded[sid] = custom["tool_name"]
                            logger.info("[ToolPlan] %s: generated tool=%s (conf=%.2f, %d attempt(s))",
                                        sid[:20], custom["tool_name"], custom.get("confidence", 0),
                                        len(attempts_done))
                        else:
                            # P2 (g)2: 结构化失败 (kind 枚举) — 不注册, 记录原因
                            logger.warning("[ToolPlan] %s: layer3 rejected (kind=%s): %s",
                                           sid[:20], custom.get("kind"),
                                           custom.get("error", custom.get("message", "")))
                    except Exception as e:
                        logger.warning("[ToolPlan] Layer3 generation failed for %s: %s", sid, e)

        # P2 (g)2: layer3 反馈闭环写入 — 失败对象列表 / 剩余修复预算 / 已成功工具。
        # 不写 modifications.errors — normalization.run 同轮会用全新 mods dict 覆盖。
        norm["layer3"] = {"attempts": layer3_attempts, "repair_left": repair_left,
                          "succeeded": succeeded}

        # Step 3: 汇总到 tool_registry
        for sid, plan in source_plans.items():
            tool_registry["by_source"][sid] = plan
            for t in plan["base"]:
                if t not in tool_registry["base_tools"]:
                    tool_registry["base_tools"].append(t)
            tool_registry["adapted_tools"].extend(plan["adapted"])
            tool_registry["generated_tools"].extend(plan["generated"])

        norm["tool_registry"] = tool_registry
        norm["planning_method"] = "llm_enhanced" if llm_count > wf.get("llm_call_count", 0) else "rule_engine"

        logger.info("[ToolPlan] %d sources: base=%d adapted=%d generated=%d",
                    len(sources_to_process),
                    len(tool_registry["base_tools"]),
                    len(tool_registry["adapted_tools"]),
                    len(tool_registry["generated_tools"]))

        return self._build_return(norm, wf, t0, norm["planning_method"],
                                   len(sources_to_process), llm_count)

    # ── V2.3: Layer 1+2 快速规划 (独立函数, 供并行调用) ──
    def _plan_layers_1_2(self, sid, src_info, sources_info, semantic_types, std_map=None):
        """并行安全: 只读 state, 返回 plan dict (不修改实例状态)。"""
        conditions = src_info.get("conditions", [])
        src_quality = sources_info.get(sid, {})
        # Layer 1
        base_tasks = []
        for c in conditions:
            task = _CONDITION_TOOL_MAP.get(c.get("condition", ""))
            if task and task not in base_tasks:
                base_tasks.append(task)
        if not base_tasks:
            base_tasks = ["field_standardizer", "format_standardizer"]
        # Layer 2
        adaptations = []
        try:
            adaptations = self._rule_plan_adaptations(sid, src_quality, semantic_types, base_tasks, conditions, std_map)
        except Exception as e:
            logger.warning("[ToolPlan] Adaptation failed for %s: %s", sid, e)
        return {"base": base_tasks, "adapted": adaptations, "generated": []}

    # ── Layer 2: Rule-Based Adaptations (V2.1: 确定性规则注入参数) ──
    def _rule_plan_adaptations(self, sid, src_quality, semantic_types, base_tasks, conditions, std_map=None):
        """确定性规则为 Base Tools 生成自定义参数 (非 LLM)。"""
        adaptations = []
        completness = src_quality.get("completeness", {})
        fmt = src_quality.get("format", {})
        consistency = src_quality.get("consistency", {})

        # schema_mapping: 注入 extra_fields → field_mappings
        if "schema_mapping" in base_tasks:
            extra = set(completness.get("present_fields", [])) - set(completness.get("expected_fields", []))
            if extra:
                # V2.1 fix: schema_mapping 参数名是 field_mappings (不是 extra_aliases)
                adaptations.append({"base_tool": "schema_mapping", "adaptation": "add_extra_aliases",
                                    "custom_params": {"field_mappings": {e: e for e in extra}},
                                    "reasoning": f"Extra fields detected: {sorted(extra)}"})

        # unit_converter: 自动推断目标单位
        if "unit_converter" in base_tasks:
            unit_status = consistency.get("unit_consistency", {})
            conversions = []
            for key, status in unit_status.items():
                if isinstance(status, str) and "inconsistent" in status:
                    # V2: key 可能是 "entity_name/field_name" 格式, 提取纯 field_name
                    pure_fn = key.split("/")[-1] if "/" in key else key
                    # V4 fix: 从 schema 标准单位映射查询 (含别名), 不再依赖
                    # infer_semantic_type 返回的 dict (其无 standard_unit 键, 恒为空)
                    std_unit = None
                    if std_map:
                        std_unit = std_map.get(pure_fn.lower())
                    if std_unit:
                        conversions.append({"field": pure_fn, "to": std_unit, "entity_key": key})
            if conversions:
                adaptations.append({"base_tool": "unit_converter", "adaptation": "auto_target_units",
                                    "custom_params": {"unit_conversions": conversions},
                                    "reasoning": f"Auto-inferred target units: {conversions}"})

        # missing_value_handler: 根据完整度选择策略
        if "missing_value_handler" in base_tasks:
            score = completness.get("score", 1.0)
            strategy = "drop" if score < 0.5 else ("fill_default" if score < 0.8 else "mark")
            if strategy != "mark":
                adaptations.append({"base_tool": "missing_value_handler", "adaptation": "override_strategy",
                                    "custom_params": {"strategy": strategy},
                                    "reasoning": f"Completeness={score:.2f} → strategy={strategy}"})

        return adaptations

    # ── Layer 3: LLM Generated Tool ──
    def _find_unresolved(self, by_src, src_quality):
        """
        判断是否需要 Layer 3 自定义工具 (V2.1 redesigned).

        采用评分制: 每个未解决问题 +1 分, 累积 >=1 分即触发 LLM 工具生成。
        不再硬编码特定单位/字段, 而是基于质量评估报告中的客观指标。
        """
        issues = []
        score = 0

        completeness = src_quality.get("completeness", {})
        consistency = src_quality.get("consistency", {})
        fmt = src_quality.get("format", {})
        conflict_risk = src_quality.get("conflict_risk", {})

        # ── 维度1: 单位问题 ──
        # 1a: 单位不一致 (同一字段多个单位混用)
        unit_status = consistency.get("unit_consistency", {})
        for fn, status in unit_status.items():
            if isinstance(status, str) and "inconsistent" in status:
                issues.append(f"Unit inconsistency in '{fn}': {status}")
                score += 1

        # 1b: 缺失单位的数值记录
        missing_units = completeness.get("records_missing_unit", 0)
        if missing_units > 0:
            present_fields = completeness.get("present_fields", [])
            issues.append(
                f"{missing_units} numeric records missing units "
                f"(fields: {present_fields[:5]})")
            score += 1

        # ── 维度2: 格式问题 ──
        fmt_issues = fmt.get("total_issues", 0)
        if fmt_issues > 0:
            issues.append(f"{fmt_issues} format issues (e.g. ~prefix, NaN, non-numeric strings)")
            score += 1

        # ── 维度3: Schema 缺口 ──
        # 3a: 数据中有的字段不在 target_schema 中
        extra_fields = set(completeness.get("present_fields", [])) - set(completeness.get("expected_fields", []))
        if extra_fields:
            issues.append(f"Extra fields not in target schema: {sorted(extra_fields)[:5]}")
            score += 1

        # 3b: target_schema 中的字段在数据中缺失
        missing_expected = completeness.get("missing_expected_fields", [])
        if missing_expected:
            issues.append(f"Expected fields missing from data: {missing_expected[:5]}")
            score += 1

        # ── 维度4: 溯源缺失 ──
        missing_prov = completeness.get("records_missing_provenance", 0)
        if missing_prov > 0:
            issues.append(f"{missing_prov} records missing provenance (page/bbox)")
            score += 1

        # ── 维度5: 完整性不足 ──
        comp_score = completeness.get("score", 1.0)
        if comp_score < 0.85:
            issues.append(f"Low completeness score ({comp_score:.2f}) — may need custom fill/repair")
            score += 1

        # ── 维度6: 跨来源冲突 ──
        conflict_count = conflict_risk.get("conflict_count", 0)
        if conflict_count > 0:
            conflicts_detail = conflict_risk.get("conflicts", [])
            conflict_ields = list(set(c.get("field_name", "?") for c in conflicts_detail))
            issues.append(f"{conflict_count} cross-source conflicts in fields: {conflict_ields}")
            score += 1

        # ── 维度7: 复合问题 ──
        # 多种问题同时存在时加分 (问题叠加意味着需要更智能的处理)
        base_issue_dimensions = sum([
            missing_units > 0,
            fmt_issues > 0,
            bool(extra_fields),
            bool(missing_expected),
            missing_prov > 0,
            comp_score < 0.85,
            conflict_count > 0,
        ])
        if base_issue_dimensions >= 2:
            issues.append(
                f"Multiple overlapping issue dimensions ({base_issue_dimensions}): "
                f"units={missing_units>0} format={fmt_issues>0} "
                f"schema_gap={bool(extra_fields or missing_expected)} "
                f"provenance={missing_prov>0} completeness={comp_score<0.85} "
                f"conflicts={conflict_count>0}")
            score += 1

        needs_custom = score >= 2  # V3.0: 至少 2 个维度有问题才触发 LLM (减少不必要 LLM 调用)
        if needs_custom:
            logger.info("[ToolPlan] Layer 3 triggered: score=%d, %d issue categories",
                        score, len(issues))

        return {"needs_custom": needs_custom, "issues": issues, "score": score}

    def _get_source_profile(self, state, sid):
        """获取 source 的完整字段统计 profile (替代只送5条sample)。"""
        data = state.get("data_state", {}).get("current_data", {})
        records = [r for r in data.get("records", []) if r.get("source_id") == sid]
        return records, self._build_field_profile(records)

    def _build_field_profile(self, records):
        """构建字段级统计 profile — LLM 能看到所有字段的类型/范围/样例。"""
        from quality_pipeline.tools._parse_utils import is_numeric, parse_numeric
        from collections import Counter
        field_groups: dict[str, list] = {}
        for r in records:
            field_groups.setdefault(r.get("field_name", "?"), []).append(r)

        profile = {}
        for fn, group in sorted(field_groups.items()):
            values = [r.get("field_value") for r in group]
            units = [r.get("field_unit") for r in group if r.get("field_unit")]
            nums = [parse_numeric(v) for v in values if is_numeric(v)]
            types = Counter(
                "numeric" if is_numeric(v) else "string" for v in values
            )
            profile[fn] = {
                "count": len(group),
                "types": dict(types),
                "sample_values": values[:3],
                "sample_units": list(set(units))[:3],
                "null_count": sum(1 for v in values if v is None),
                "numeric_range": f"[{min(nums):.4g}, {max(nums):.4g}]" if nums else None,
                "has_provenance": sum(1 for r in group if r.get("provenance")) / len(group),
            }
        return profile

    def _layer3_fail(self, sid, kind, error, line=None, tool="?", code=None):
        """P2 (g)1: 结构化失败对象 — {source_id, tool, kind, error, line?}。

        带上一版完整 code (供修复轮渲染); code 仅存在于生成后的失败路径
        (syntax_error/ast_blocked/dry-run 类), parse_error/契约类失败无 code。
        """
        fail = {"source_id": sid, "tool": tool, "kind": kind, "error": error}
        if line is not None:
            fail["line"] = line
        if code:
            fail["code"] = code
        return fail

    def _llm_review_self_check(self, llm, failed_details, tool_name,
                               records_before, result) -> dict:
        """LLM 语义复审 (L3 泛化): 程序化 self_check 失败时判定差异是
        "可接受的表示差异"(数值格式/前缀符号/精度, 如 '~770' vs 770、
        '1,200' vs 1200、'5.0' vs 5) 还是代码真实错误。

        仅当程序化校验失败时触发 1 次 LLM 调用 (预算外成本可控);
        解析失败/异常 → 默认不可接受 (安全侧)。
        """
        try:
            import json as _json
            samples_in = _json.dumps(records_before[:3], ensure_ascii=False,
                                     default=str)[:1200]
            samples_out = _json.dumps((result.get("data") or [])[:3],
                                      ensure_ascii=False, default=str)[:1200]
            review_prompt = (
                "你是代码自检审查员。LLM 生成的清洗工具执行后, 程序化 self_check 断言失败。\n"
                "失败详情: " + _json.dumps(failed_details, ensure_ascii=False)[:800] + "\n"
                "工具名: " + str(tool_name) + "\n"
                "样本输入(前3条): " + samples_in + "\n"
                "样本输出(前3条): " + samples_out + "\n"
                "判定这些失败是否属于可接受的表示差异 (数值格式/前缀符号/精度/类型表示, "
                "如 '~770' vs 770、'1,200' vs 1200、'5.0' vs 5), 而非代码逻辑真实错误。\n"
                "只输出 JSON: {\"acceptable\": true/false, \"reason\": \"一句话\"}"
            )
            resp = llm.invoke([{"role": "system",
                                "content": "你是严格的代码自检审查员, 只输出 JSON。"},
                               {"role": "user", "content": review_prompt}])
            content = resp.content if hasattr(resp, "content") else str(resp)
            data, err = _extract_json_object(content)
            if err or not isinstance(data, dict):
                return {"acceptable": False, "reason": f"review parse failed: {err}"}
            return {"acceptable": bool(data.get("acceptable")),
                    "reason": str(data.get("reason", ""))}
        except Exception as e:
            return {"acceptable": False, "reason": f"review error: {e}"}

    def _llm_generate_tool_repair_loop(self, sid, unresolved, records_sample,
                                       prev_failures=None, plan=None, target_schema=None,
                                       repair_budget=None):
        """P2 (g)4: 修复循环 — 外包 attempt 循环, 每 source ≤ 1+MAX_REPAIR_ROUNDS 次 LLM 调用。

        - 每轮失败对象 (结构化 {source_id, tool, kind, error, line?, code?}) 渲染进
          retry_context ({kind} @ line {line}: {error} + 上一版完整 code)
        - 按 kind 重试预算: noop/键集合/记录数/log/self_check_failed 重试一次即止;
          low_confidence 不可重试 (0 次); 其余 ≤ MAX_REPAIR_ROUNDS
        - 修复轮不重发 few-shot (few_shots 仅首轮)
        - 跨轮预算: repair_budget 由 run() 传入 layer3.repair_left[sid], 本轮失败
          消耗的修复轮次经 repair_consumed 返回, run() 据此递减 (跨轮持久)

        Returns: 成功 → {tool_name, tool_code, confidence, ..., attempts, llm_calls,
                         repair_consumed}; 预算耗尽 → 最后一个失败对象 + 同附键。
        """
        if repair_budget is None:
            repair_budget = _MAX_REPAIR_ROUNDS
        attempts_done: list = []
        retry_context = _render_repair_context(prev_failures or [])
        few_shots = True
        max_rounds = 1 + _MAX_REPAIR_ROUNDS
        calls = 0
        for round_i in range(1, max_rounds + 1):
            # 修复预算: 第 round_i 轮是第 (round_i - 1) 次修复 (第 1 轮为初始生成),
            # 已消耗修复数不得超过跨轮持久预算 layer3.repair_left[sid]
            if round_i > 1 and (round_i - 1) > repair_budget:
                break
            res = self._llm_generate_tool(sid, unresolved, records_sample,
                                          plan=plan, target_schema=target_schema,
                                          retry_context=retry_context, few_shots=few_shots)
            calls = round_i
            if not res.get("kind"):
                res["attempts"] = attempts_done
                res["llm_calls"] = calls
                res["repair_consumed"] = max(0, calls - 1)
                return res
            attempts_done.append(res)
            kind = res.get("kind")
            if kind in _KIND_NO_RETRY:
                break
            if kind in _KIND_RETRY_ONCE and round_i > 1:
                break
            if round_i >= max_rounds:
                break
            few_shots = False  # 修复轮不重发 few-shot
            retry_context = _render_repair_context(attempts_done)
        last = attempts_done[-1]
        last["attempts"] = attempts_done
        last["llm_calls"] = calls
        last["repair_consumed"] = max(0, calls - 1)
        return last

    def _llm_generate_tool(self, sid, unresolved, records_sample,
                           plan=None, target_schema=None,
                           retry_context="", few_shots=True):
        """LLM 生成自定义 Python 工具 (V3.1: 模板注入, 安全沙箱兼容; P1: schema prompt
        + confidence 契约; P2: 结构化失败对象 + dry-run no-op 检测)。

        retry_context: 修复轮反馈文本 (由 _llm_generate_tool_repair_loop 渲染传入);
        few_shots: 仅首轮注入 golden 示例 (修复轮不重发)。

        Returns:
            成功: {tool_name, tool_code, confidence, llm_confidence, self_check,
                   source_id, reasoning} (无 "kind" 键)
            失败: 结构化对象 {source_id, tool, kind, error, line?, code?}
        """
        from quality_pipeline.utils.llm import get_llm, set_agent_context
        set_agent_context("normalization")

        records, field_profile = records_sample
        issues_str = "\n".join(f"  - {iss}" for iss in unresolved["issues"])

        # P1 (d): 字段 Schema 块 — target_schema + 字段统计合并 (主要信息源,
        # 替代原"3 条截断样本即全部信息"的猜键名模式)
        schema_block = _build_schema_block(target_schema, field_profile)

        # 分层采样: 首/中/尾各一条, 最大覆盖字段多样性 (保留 3 条原始样本)
        n = len(records)
        sample_indices = [0, n // 2, n - 1] if n >= 3 else list(range(n))
        sample_indices = sorted(set(i for i in sample_indices if 0 <= i < n))
        sample_str = json.dumps([
            {k: str(v)[:100] for k, v in records[i].items() if k != "provenance"}
            for i in sample_indices
        ], indent=2, ensure_ascii=False)

        # P1 (d): 记录形态契约 — 键集合 (含 _raw_field), provenance 只读,
        # field_value 已数值化, 空串单位=缺单位
        key_set = sorted({k for r in records for k in (r.keys() if isinstance(r, dict) else [])})
        shape_contract = (
            "执行时每条记录是 dict, 键集合: "
            f"{key_set[:30]}{' ...' if len(key_set) > 30 else ''}\n"
            "- provenance 字段只读, 禁止修改 (含其内部键)\n"
            "- field_value 已数值化 (str/int/float 形态, 无 ~ ≈ < > 前缀, 不含单位)\n"
            "- 空串 field_unit 表示该记录缺失单位\n"
            "- 只修改顶层键 (rec[\"field_value\"] / rec[\"field_unit\"]), "
            "禁止 rec[\"field_value\"][\"sub\"] 嵌套修改"
        )

        # P1 (d): golden few-shot — 按 issue 关键词匹配选取 3 条注入 (仅首轮, P2 g4)
        few_shot_block = ""
        if few_shots:
            few_shot_text = _render_few_shots(issues_str)
            few_shot_block = (f"【Golden 示例】(输出契约与代码风格参照):\n{few_shot_text}\n\n"
                              if few_shot_text else "")

        # P2 (g)4: 修复轮反馈由外层循环渲染传入 ({kind} @ line {line}: {error} + code)
        retry_context = retry_context or ""

        output_contract = (
            '{"tool_name": "...", "tool_code": "...", "confidence": 0-1, '
            '"self_check": {"assertions": [{"field": "...", "assert": "<enum>", '
            '"expected": ...}], "sample_predictions": [{"record_id": "...", '
            '"field": "...", "before": <值>, "after": <变换后值>}]}, "reasoning": "..."}'
        )
        hard_checks = (
            "1. 记录数不变 — 禁止 append/删除 records 元素\n"
            "2. 字段键集合不变 — 禁止新增/删除记录键\n"
            "3. log 上限 — 每条修改恰好追加一条 _log; 零修改 (no-op) 会被拒绝\n"
            "4. self_check 逐条验证 — sample_predictions 的 before 必须与真实输入一致,\n"
            "   after 必须与真实输出一致; assertions 与代码实际效果一致\n"
            "5. while 必须有界 — 常量假条件 / 有界计数器 (i < N + i += 1) / break 三选一\n"
            "6. confidence 必填 (0-1) — 缺失/非数值/越界直接判失败 (无默认值)"
        )

        # P3 (层 A): ops 优先路径 prompt 段 — op 目录 + 规则 + "无法表达时输出自由代码路径"
        ops_path_block = (
            "【操作规格路径（优先）】\n"
            "优先输出结构化操作规格 (ops), 不要写 Python 代码 — 确定性执行器, 无需 self_check:\n"
            '{"ops": [{"op": "<操作>", "field": "<字段>", ...}], "confidence": 0-1, "reasoning": "..."}\n'
            "操作目录 (按顺序应用到所有记录, 每 op 后校验记录数/键集合不变):\n"
            '  - strip_prefix: 剥离数值前缀并数值化, 如 "~770" → 770 (prefixes 缺省 ~≈<>≤≥)\n'
            "  - numeric_convert: 字符串数值转数值类型 (整数形态转 int, 幂等)\n"
            "  - trim: 去首尾空白\n"
            "  - unit_normalize: 单位转换 (field_unit → to 目标单位, 值同步换算; 无规则记错误)\n"
            "  - drop_suffix: 去除值末尾的 suffix 子串\n"
            "  - replace_substring: 将值中的 old 子串替换为 new\n"
            "  - mark_missing_unit: 为缺单位的数值记录补标签 (unit 或默认 unknown)\n"
            "规则: ops 最多 8 条; 只修改已有键 (field_value/field_unit), 不增删记录/键;\n"
            "confidence 必填 (0-1)。无法用上述 ops 表达变换时, 才输出自由代码路径\n"
            "(tool_name/tool_code/self_check 契约, 见下方【输出格式】)。\n\n"
        )

        prompt = f"""Source id={sid[:40]} has {len(unresolved['issues'])} issues:

{issues_str}

【字段 Schema】({len(field_profile)} fields — target schema 合并字段统计):
{schema_block}

【记录形态契约】
{shape_contract}

【样本记录】({len(sample_indices)}/{len(records)} records):
{sample_str}

{few_shot_block}【执行端硬性校验清单】(代码将逐一通过以下检查, 任一不满足即被拒绝):
{hard_checks}

{ops_path_block}【输出格式】严格 JSON 对象 (禁止 markdown fence, 禁止多余键):
{output_contract}
{retry_context}"""

        llm = get_llm(temperature=0.0)
        resp = llm.invoke([{"role": "system", "content": _TOOL_GEN_SYSTEM},
                           {"role": "user", "content": prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)
        # P0 (e): 锚定 JSON 提取 (剥 fence → 首个完整对象), 失败返回结构化错误
        llm_data, parse_error = _extract_json_object(content)
        if parse_error:
            return self._layer3_fail(sid, "parse_error", parse_error)

        # ── P3 (层 A): ops 优先路径 — 先试 OpSpecResponse (确定性执行器,
        # 不进沙箱); 校验失败且响应含 tool_code → 走自由代码路径 (层 B);
        # 两者皆非 → 契约失败 (parse_error, 可修复) ──
        from quality_pipeline.tools.normalization.op_executor import OpSpecResponse
        try:
            ops_model = OpSpecResponse.model_validate(llm_data)
        except ValidationError:
            ops_model = None
        if ops_model is not None:
            ops_payload = [op.model_dump() for op in ops_model.ops]
            tool_name = f"ops_{ops_model.ops[0].op}" if ops_model.ops else "ops"
            logger.info("[ToolPlan] %s: ops path (mode=ops, %d ops, conf=%.2f)",
                        sid[:20], len(ops_payload), ops_model.confidence)
            # ops 路径 confidence 不设 <0.7 门槛 — 确定性执行器无低置信风险
            return {"mode": "ops", "tool_name": tool_name, "ops": ops_payload,
                    "confidence": ops_model.confidence,
                    "reasoning": ops_model.reasoning or "", "source_id": sid}
        if not (isinstance(llm_data, dict) and llm_data.get("tool_code")):
            return self._layer3_fail(
                sid, "parse_error",
                "LLM response is neither a valid ops spec (OpSpecResponse) "
                "nor a tool_code contract")

        # P1 (f): Pydantic 严格契约校验 — tool_name/tool_code/confidence 必填,
        # self_check 结构校验; 失败映射 kind (parse_error / confidence_invalid /
        # self_check_invalid) — 不再有默认 confidence 0.5
        from quality_pipeline.sandbox.sandbox_common import (
            _parse_tool_response, _verify_self_check, _compute_effective_confidence,
        )
        parsed = _parse_tool_response(llm_data)
        if not parsed["ok"]:
            logger.warning("[ToolPlan] %s: layer3 contract rejected (kind=%s): %s",
                           sid[:20], parsed["kind"], parsed["message"])
            return self._layer3_fail(sid, parsed["kind"], parsed["message"])
        model = parsed["model"]
        llm_logic = model.tool_code
        tool_name = model.tool_name
        self_check = model.self_check

        # P0 (e): marker 分割 → 提取业务逻辑 (容忍侧, 与模板契约共用 marker)
        llm_logic = _extract_business_logic(llm_logic)
        # P0 (e): AST 手术 — 仅删模块级 return, ast.unparse 归一 4 空格;
        # 不再做任何行正则删除 (非白名单 import 由 _validate_code_ast 统一拒绝);
        # ast.parse 失败走缩进降级路径 (dedent + 4 空格前缀)
        llm_logic = _surgical_clean_logic(llm_logic)

        # V3.1: 注入模板 — LLM 只写 business logic, boilerplate 由我们提供
        full_code = _TOOL_CODE_TEMPLATE.replace("{LLM_CODE}", llm_logic)

        # AST 校验 (模板代码始终通过, 仅检查 LLM 部分是否有编译错误)
        try:
            compile(full_code, "<sandbox>", "exec")
        except SyntaxError as e:
            logger.warning("[ToolPlan] Generated code has syntax error: %s", e)
            return self._layer3_fail(sid, "syntax_error", str(e),
                                     line=getattr(e, "lineno", None),
                                     tool=tool_name, code=full_code)

        # C1 fix: dry-run 前必须过与执行端一致的 AST 白名单校验 (SSOT sandbox_common)
        # H-12 fix: dry-run 同样走硬超时 (exec + 调用), 防死循环挂死规划节点
        from quality_pipeline.sandbox.sandbox_common import (
            _make_sandbox, _validate_code_ast, _validate_generated_result,
            _SANDBOX_MAX_LOG_ENTRIES,
        )
        verdict = _validate_code_ast(full_code)
        if not verdict:
            logger.warning("[ToolPlan] Generated code blocked: AST validation failed")
            return self._layer3_fail(sid, "ast_blocked", verdict.get("message", ""),
                                     line=verdict.get("line"), tool=tool_name,
                                     code=full_code)

        # Dry-run: 在真实 sandbox 中执行 L1/L2 处理后的 3 条分层样本
        try:
            import copy as _cp
            from subgraphs.data_normalization.agents.normalization_agent import (
                NormalizationAgent, _run_with_timeout, _lazy_load_tools,
            )
            # P0 (c): SSOT 沙箱 (与执行端同一工厂, itertools/statistics 等
            # _ALLOWED_MODULES 全量自动注入 — 不再手写 dict, 杜绝两侧漂移)
            sandbox = _make_sandbox()
            test_records = _cp.deepcopy([records[i] for i in sample_indices])

            # P0 (c): dry-run 输入 = L1/L2 处理后的样本形态 (执行端真实输入,
            # 含 schema_mapping 的 _raw_field 与数值化后的 field_value);
            # 工具异常时 _execute_base/_execute_adapted 内部降级返回 None, 样本保持原状
            _lazy_load_tools()
            agent = NormalizationAgent()
            for tool_name_ in (plan or {}).get("base", []):
                r = agent._execute_base(tool_name_, test_records)
                if r and "data" in r:
                    test_records = r["data"]
            for adapt in (plan or {}).get("adapted", []):
                r = agent._execute_adapted(adapt, test_records)
                if r and "data" in r:
                    test_records = r["data"]

            # H-12 fix: exec + fn 调用在独立线程中执行并设硬超时,
            # 超时/异常统一判 dry-run 失败 (回退 Base Tools)
            # P1 (f): 工具函数原地改写 records 列表 — 先深拷贝快照作为
            # records_before (M-19 门与 self_check before 比对的数据源),
            # 与 _execute_generated 的 records_copy 语义一致
            dry_run_before = _cp.deepcopy(test_records)

            def _dry_run_worker():
                exec(compile(full_code, "<sandbox>", "exec"), sandbox)  # nosec B102 — AST 白名单沙箱
                fn = sandbox.get("tool")
                if fn is None:
                    raise RuntimeError("[ToolPlan] Dry-run: function not found")
                return fn(test_records)

            outcome = _run_with_timeout(_dry_run_worker)
            if not outcome["ok"]:
                # P2 (g)1: 结构化失败 — 超时 vs 其他运行时异常分 kind
                kind = ("exec_timeout" if isinstance(outcome["error"], TimeoutError)
                        else "dry_run_failed")
                logger.warning("[ToolPlan] Dry-run FAILED (kind=%s): %s", kind, outcome["error"])
                return self._layer3_fail(sid, kind, str(outcome["error"]),
                                         tool=tool_name, code=full_code)
            # P0 (c): 共享不变量门 — 与 _execute_generated 同一 _validate_generated_result
            # (invalid_format / record_count_changed / key_set_changed / log_too_large)
            check = _validate_generated_result(dry_run_before, outcome["result"],
                                               _SANDBOX_MAX_LOG_ENTRIES)
            if not check["ok"]:
                logger.warning("[ToolPlan] Dry-run REJECTED (kind=%s): %s",
                               check["kind"], check["message"])
                return self._layer3_fail(sid, check["kind"], check["message"],
                                         tool=tool_name, code=full_code)
            # P2 (h): dry-run no-op 检测 — 先 unverifiable 预检 (样本无目标问题 →
            # 放行不判 noop, 防样本与全量形态差异误拒); 有目标问题且零修改 → 拒绝
            if _sample_has_target_issue(issues_str, test_records) \
                    and _detect_noop(dry_run_before, outcome["result"])["noop"]:
                logger.warning("[ToolPlan] %s: dry-run no-op rejected", sid[:20])
                return self._layer3_fail(
                    sid, "noop",
                    "dry-run made zero modifications while sample has target issue",
                    tool=tool_name, code=full_code)
            # P1 (f): self_check 验证 (M-19 键集合检查之后, 与 _execute_generated 共用
            # _verify_self_check) — P2 (g): 失败 → 结构化失败 (kind=self_check_failed,
            # 重试一次即止), 不再以 effective ×0.3 静默放行 (自检与真实行为不符 = 幻觉)
            self_check_ok = True
            if self_check:
                sc = _verify_self_check(outcome["result"], self_check, dry_run_before)
                self_check_ok = sc["ok"]
                if not sc["ok"]:
                    logger.warning("[ToolPlan] %s: self_check FAILED (%d): %s",
                                   sid[:20], len(sc["failed"]),
                                   str(sc["failed"][:2])[:200])
                    # L3 泛化: 程序化失败 → LLM 语义复审 (可接受表示差异 vs 真实错误)
                    review = self._llm_review_self_check(
                        llm, sc["failed"], tool_name, dry_run_before,
                        outcome["result"])
                    if review.get("acceptable"):
                        logger.warning(
                            "[ToolPlan] %s: self_check FAILED but LLM review "
                            "ACCEPTED (%s)", sid[:20],
                            str(review.get("reason"))[:80])
                        self_check_ok = True
                    else:
                        return self._layer3_fail(
                            sid, "self_check_failed",
                            "self_check mismatch: " + str(sc["failed"][:2])[:200]
                            + (f" (LLM review: {review.get('reason')}"
                               if review.get("reason") else ""),
                            tool=tool_name, code=full_code)
            effective_confidence = _compute_effective_confidence(model.confidence,
                                                                 self_check_ok)
            logger.info("[ToolPlan] Dry-run PASSED: %d records, log=%d (conf %.2f -> %.2f)",
                        len(test_records), len(outcome["result"].get("log", [])),
                        model.confidence, effective_confidence)
        except Exception as e:
            # full_code 在本 try 块之前已定义 (模板注入后)
            logger.warning("[ToolPlan] Dry-run FAILED: %s", e)
            return self._layer3_fail(sid, "dry_run_failed", str(e),
                                     tool=tool_name, code=full_code)

        return {"tool_name": tool_name, "tool_code": full_code,
                "confidence": effective_confidence,
                "llm_confidence": model.confidence,
                "self_check": self_check.model_dump(by_alias=True) if self_check else None,
                "source_id": sid, "reasoning": model.reasoning or ""}

    def _build_return(self, norm, wf, t0, method, n_sources, llm_count=None):
        # V2.1 fix: 只返回新增的单条 history, 不携带旧列表 (避免重复累积)
        ret = {"report_state": {"normalization": norm},
               "workflow_state": {"current_node": "planning", "execution_status": "Success",
                                  "workflow_history": [{
                                      "agent": "ToolPlanningAgent", "stage": "ToolPlanning",
                                      "status": "Success",
                                      "timestamp": datetime.datetime.now().isoformat(),
                                      "duration": round(time.time()-t0, 3),
                                      "reason": f"{n_sources} sources planned (method={method})",
                                  }]}}
        if llm_count is not None:
            ret["workflow_state"]["llm_call_count"] = llm_count
        return ret


def _validate_code_simple_fallback(code: str) -> bool:
    """简易回退安全检查: 字符串黑名单 (当 AST 校验不可用时)。"""
    forbidden = ("import os", "import sys", "import subprocess", "import socket",
                 "import requests", "os.", "sys.", "subprocess.", "socket.",
                 "__import__", "compile(", "exec(", "eval(", "open(",
                 "shutil", "pathlib", "glob", "fnmatch")
    code_lower = code.lower()
    for kw in forbidden:
        if kw in code_lower:
            logger.warning("[ToolPlan] Blocked unsafe pattern: %s", kw)
            return False
    return True
