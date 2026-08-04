"""
planning_agent.py — Stage 2: ToolPlanningAgent (V2.3)

核心创新: LLM 根据数据问题自动规划工具链:
  Layer 1: 选择 Base Tools (6个确定性工具)
  Layer 2: 生成 Adapted Tools (规则注入自定义参数)
  Layer 3: 生成 Custom Tools (LLM 动态编写 Python 函数)

V2.3: per-source 并行规划 (Layer 3 LLM 调用并行化)。
"""
from __future__ import annotations
import datetime, time, json, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from quality_state import QualityGraphState
from utils.logger import get_logger
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


# ── V4 fix: 领域感知 standard_unit 查询 ──
# infer_semantic_type 返回 dict 无 standard_unit 键 (semantic_type.py:74-82),
# 导致 adapted 单位参数恒空。改为从 target_schema (context 优先, 领域配置兜底)
# 按字段名 + 别名构建映射, 兼容 entity-aware key ("{entity}:{name}/{field}")。
def _build_schema_std_unit_map(state: QualityGraphState) -> dict[str, str]:
    """构建 {field_name.lower(): standard_unit} + 别名映射 (只读, 线程安全)。"""
    from configs import load_domain_schema_config
    schema = (state.get("context_state", {}).get("target_schema")
              or load_domain_schema_config("target_schema"))
    m: dict[str, str] = {}
    for f in (schema or {}).get("fields", []):
        u = f.get("standard_unit")
        if f.get("name") and u:
            m[str(f["name"]).lower()] = u
            for a in f.get("aliases", []) or []:
                m[str(a).lower()] = u
    return m

# V3.1: 预编译的安全代码模板 — LLM 只填 business logic，不生成 boilerplate
_TOOL_CODE_TEMPLATE = '''
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
to insert into a pre-existing Python function template.

The template ALREADY handles:
- Empty input, None values, missing keys — use _safe_get() for safety
- Type checking — use _is_numeric() and _to_number()
- Return format — {"data": records, "log": _log, "summary": _summary}

=== YOUR JOB ===
Write ONLY the code that goes between LLM_GENERATED_LOGIC_START and LLM_GENERATED_LOGIC_END.
This code runs INSIDE a function — do NOT write def, import, return, or class statements.
Just write plain transformation logic (for loops, if statements, variable assignments).
Do NOT use: eval, exec, compile, open, getattr, setattr, del, __import__, os, sys, subprocess, return.
Use _safe_get(rec, "field_name") instead of rec["field_name"].

=== HOW TO MODIFY RECORDS ===
To modify a field value:
  val = _safe_get(rec, "field_name")
  new_val = ...transform val...
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
- CRITICAL: NEVER append new records to `records` and NEVER remove records.
  The records list length MUST stay unchanged. Missing fields are handled by
  Assessment, NOT by creating placeholder records.

Return JSON with ONLY these keys:
{"tool_name": "short_descriptive_name", "tool_code": "...the business logic code...",
  "confidence": 0.9, "reasoning": "one sentence explaining the approach"}"""


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
                    # V3.5 fix: 透传 conflict_actions (HumanReview/Conflict 动作)
                    "conflict_actions": src_info.get("conflict_actions") or [],
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

        # V3.5 fix: 透传 conflict_actions (HumanReview/Conflict 动作) 到 by_source
        for sid, src_info in sources_to_process.items():
            c_actions = src_info.get("conflict_actions") or []
            if c_actions and sid in source_plans:
                source_plans[sid]["conflict_actions"] = c_actions

        # Step 2: 并行 Layer 3 LLM (只对 needs_custom 的 source)
        # ── V3.0: 收集上次失败信息回传给 LLM, 每 source 最多 1 次生成 ──
        prev_mods = norm.get("modifications", {}) or {}
        prev_errors = prev_mods.get("errors", [])

        llm_sources = [
            (sid, plan) for sid, plan in source_plans.items()
            if self._find_unresolved(plan, sources_info.get(sid, {})).get("needs_custom")
        ]
        if llm_sources:
            logger.info("[ToolPlan] Layer 3 LLM generation for %d sources (parallel)", len(llm_sources))
            with ThreadPoolExecutor(max_workers=min(n_workers, len(llm_sources))) as executor:
                llm_futs = {}
                for sid, plan in llm_sources:
                    # V3.0: 如果该 source 已有 generated tool (来自上轮 retry), 跳过
                    if plan.get("generated"):
                        logger.info("[ToolPlan] %s: already has generated tool, skipping (max 1 attempt)", sid[:20])
                        continue
                    unresolved = self._find_unresolved(plan, sources_info.get(sid, {}))
                    profile = self._get_source_profile(state, sid)  # V3.1: field statistics
                    # V3.0: 收集上次失败的生成工具错误信息
                    prev_failures_for_sid = [
                        e for e in prev_errors
                        if e.get("source_id") == sid
                    ]
                    f = executor.submit(self._llm_generate_tool, sid, unresolved, profile, prev_failures_for_sid)
                    llm_futs[f] = sid
                for future in as_completed(llm_futs):
                    sid = llm_futs[future]
                    try:
                        custom = future.result()
                        if custom:
                            source_plans[sid]["generated"] = [custom]
                            llm_count += 1
                            logger.info("[ToolPlan] %s: generated tool=%s (conf=%.2f)",
                                        sid[:20], custom["tool_name"], custom.get("confidence", 0))
                    except Exception as e:
                        logger.warning("[ToolPlan] Layer3 generation failed for %s: %s", sid, e)

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
            conflict_fields = list(set(c.get("field_name", "?") for c in conflicts_detail))
            issues.append(f"{conflict_count} cross-source conflicts in fields: {conflict_fields}")
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
        from tools._parse_utils import is_numeric, parse_numeric
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

    def _llm_generate_tool(self, sid, unresolved, records_sample, prev_failures=None):
        """LLM 生成自定义 Python 工具 (V3.1: 模板注入, 安全沙箱兼容)。"""
        from utils.llm import get_llm, set_agent_context
        set_agent_context("normalization")

        records, field_profile = records_sample
        profile_str = json.dumps(field_profile, indent=2, ensure_ascii=False)
        issues_str = "\n".join(f"  - {iss}" for iss in unresolved["issues"])

        # 分层采样: 首/中/尾各一条, 最大覆盖字段多样性
        n = len(records)
        sample_indices = [0, n // 2, n - 1] if n >= 3 else list(range(n))
        sample_indices = sorted(set(i for i in sample_indices if 0 <= i < n))
        sample_str = json.dumps([
            {k: str(v)[:100] for k, v in records[i].items() if k != "provenance"}
            for i in sample_indices
        ], indent=2, ensure_ascii=False)

        retry_context = ""
        if prev_failures:
            retry_context = "\n".join(
                f"  - {f.get('tool','?')}: {f.get('error','unknown')}"
                for f in prev_failures
            )
            retry_context = f"\nPREVIOUS ERRORS (fix these):\n{retry_context}\n"

        prompt = f"""Source id={sid[:40]} has {len(unresolved['issues'])} issues:

{issues_str}

ALL FIELDS ({len(field_profile)} total, with statistics):
{profile_str}

SAMPLE RECORDS ({len(sample_indices)}/{len(records)} records, showing field diversity):
{sample_str}
{retry_context}
Write ONLY the business logic to insert into the template between
LLM_GENERATED_LOGIC_START and LLM_GENERATED_LOGIC_END.

The template ALREADY provides: re, math, json, copy, defaultdict, Counter,
_safe_get(), _is_numeric(), _to_number(). Records are in variable `records`.
Append log entries to `_log`, set `_summary`. Do NOT write imports or return.

Return JSON with: tool_name, tool_code (business logic only), confidence (0-1), reasoning."""

        llm = get_llm(temperature=0.0)
        resp = llm.invoke([{"role": "system", "content": _TOOL_GEN_SYSTEM},
                           {"role": "user", "content": prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if not m:
            return None
        llm_data = json.loads(m.group(0))
        llm_logic = llm_data.get("tool_code", "")
        if not llm_logic or len(llm_logic.strip()) < 10:
            return None

        # V3.1: 安全后处理
        import re as _re
        # 移除 LLM 可能误加的危险语句
        llm_logic = _re.sub(r'^\s*(import|from)\s+\S+.*$', '# removed import', llm_logic, flags=_re.MULTILINE)
        llm_logic = _re.sub(r'^\s*return\b.*$', '# removed return', llm_logic, flags=_re.MULTILINE)
        llm_logic = _re.sub(r'^\s*def\s+\S+.*$', '# removed def', llm_logic, flags=_re.MULTILINE)
        llm_logic = _re.sub(r'^\s*class\s+\S+.*$', '# removed class', llm_logic, flags=_re.MULTILINE)
        # 统一缩进: LLM 输出缩进不一致, 归一化到函数体 4 空格
        llm_lines = llm_logic.split('\n')
        # 找到最小缩进（忽略空行和注释行）
        min_indent = min(
            (len(l) - len(l.lstrip()) for l in llm_lines if l.strip() and not l.strip().startswith('#')),
            default=0
        )
        # 需要补的缩进量: 函数体需要 4 空格
        indent_delta = 4 - min_indent
        indented = []
        for line in llm_lines:
            if line.strip():
                indented.append(' ' * indent_delta + line)
            else:
                indented.append(line)
        llm_logic = '\n'.join(indented)

        # V3.1: 注入模板 — LLM 只写 business logic, boilerplate 由我们提供
        full_code = _TOOL_CODE_TEMPLATE.replace("{LLM_CODE}", llm_logic)

        # AST 校验 (模板代码始终通过, 仅检查 LLM 部分是否有编译错误)
        try:
            compile(full_code, "<sandbox>", "exec")
        except SyntaxError as e:
            logger.warning("[ToolPlan] Generated code has syntax error: %s", e)
            return None

        # Dry-run: 在真实 sandbox 中执行 3 条分层样本
        tool_name = llm_data.get("tool_name", f"custom_{sid[:10]}")
        try:
            import copy as _cp
            # 用真实执行 sandbox (与 normalization_agent 完全一致)
            from Data_Normalization_agentV1.agents.normalization_agent import NormalizationAgent
            agent = NormalizationAgent()
            # 构造最小 state 以复用 sandbox 设置
            dummy_state = {
                "data_state": {"current_data": {"records": []}},
                "report_state": {}, "workflow_state": {},
            }
            agent.run(dummy_state)  # 初始化 _BASE_TOOLS, 但不执行
            # 直接构造 sandbox (对齐 normalization_agent.run 175-180 行)
            sandbox = {
                "__builtins__": {
                    "True": True, "False": False, "None": None, "__import__": __import__,
                    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
                    "enumerate": enumerate, "filter": filter, "float": float, "int": int,
                    "isinstance": isinstance, "len": len, "list": list, "map": map,
                    "max": max, "min": min, "print": print, "range": range,
                    "round": round, "set": set, "sorted": sorted, "str": str,
                    "sum": sum, "tuple": tuple, "type": type, "zip": zip,
                    "Exception": Exception, "ValueError": ValueError,
                    "TypeError": TypeError, "KeyError": KeyError,
                    "IndexError": IndexError, "AttributeError": AttributeError,
                },
                "json": json, "copy": _cp,
                "math": __import__("math"), "re": __import__("re"),
                "datetime": __import__("datetime"),
                "collections": __import__("collections"),
                "itertools": __import__("itertools"),
                "statistics": __import__("statistics"),
            }
            test_records = _cp.deepcopy([records[i] for i in sample_indices])
            exec(compile(full_code, "<sandbox>", "exec"), sandbox)
            fn = sandbox.get("tool")
            if fn is None:
                logger.warning("[ToolPlan] Dry-run: function not found")
                return None
            result = fn(test_records)
            if not isinstance(result, dict) or "data" not in result:
                logger.warning("[ToolPlan] Dry-run: invalid return format")
                return None
            # V3.3 fix: 记录数一致性 — Normalization 工具只允许修改, 禁止增删记录
            # (LLM 曾为"缺失字段"创建 *_missing 占位记录, 属错误行为)
            if len(result.get("data", [])) != len(test_records):
                logger.warning("[ToolPlan] Dry-run: record count changed "
                               "%d -> %d (tools must not add/remove records)",
                               len(test_records), len(result.get("data", [])))
                return None
            logger.info("[ToolPlan] Dry-run PASSED: %d records -> %d records, log=%d",
                       len(test_records), len(result.get("data", [])),
                       len(result.get("log", [])))
        except Exception as e:
            logger.warning("[ToolPlan] Dry-run FAILED: %s", e)
            return None

        return {"tool_name": tool_name, "tool_code": full_code,
                "confidence": llm_data.get("confidence", 0.5),
                "source_id": sid, "reasoning": llm_data.get("reasoning", "")}

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
