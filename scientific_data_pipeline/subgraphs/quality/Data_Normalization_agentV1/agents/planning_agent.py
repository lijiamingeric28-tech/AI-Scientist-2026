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
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.logger import get_logger
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

# 可用于 LLM 参考的 Base Tool 签名
_BASE_TOOL_SIGNATURES = """
Available Python functions (signature and purpose):
1. schema_mapping(records, field_mappings) - Rename fields: {"old_name": "new_name"}
2. field_standardizer(records, custom_rules=None) - Clean ~≈<> prefixes, trim strings
3. unit_converter(records, conversions, semantic_types) - Convert units (MPa↔GPa, K↔°C)
4. missing_value_handler(records, strategy="mark", fill_value=None) - Handle None/empty values
5. duplicate_handler(records) - Remove exact+semantic duplicates, filter rejected records
6. format_standardizer(records) - Normalize numeric/string formats

Return format: {"data": updated_records, "log": [...], "summary": "..."}
"""

_TOOL_GEN_SYSTEM = """You are a scientific data normalization expert and Python programmer.
Generate a Python function to fix a specific data issue.

Requirements:
- Function signature: def tool(records: list[dict]) -> dict
- Return: {"data": updated_records, "log": [...modifications...], "summary": "..."}
- Handle edge cases (empty input, unexpected types, None values)
- Do NOT import os, sys, subprocess, socket, requests, or any network/file modules
- Use only: math, re, json, copy, datetime, collections
- Fit in <100 lines
- Add docstring explaining what it does

Return JSON: {"tool_name": "...", "tool_code": "...", "confidence": 0.9, "reasoning": "..."}"""


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
            tool_registry = {"base_tools": list(_CONDITION_TOOL_MAP.values()),
                             "adapted_tools": [], "generated_tools": [],
                             "by_source": {sid: {"base": list(_CONDITION_TOOL_MAP.values()),
                                                  "adapted": [], "generated": []}
                                           for sid in sources_to_process}}
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
        source_plans: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futs = {}
            for sid, src_info in sources_to_process.items():
                f = executor.submit(
                    self._plan_layers_1_2,
                    sid, src_info, sources_info, semantic_types
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

        # Step 2: 并行 Layer 3 LLM (只对 needs_custom 的 source)
        llm_sources = [
            (sid, plan) for sid, plan in source_plans.items()
            if self._find_unresolved(plan, sources_info.get(sid, {})).get("needs_custom")
        ]
        if llm_sources:
            logger.info("[ToolPlan] Layer 3 LLM generation for %d sources (parallel)", len(llm_sources))
            with ThreadPoolExecutor(max_workers=min(n_workers, len(llm_sources))) as executor:
                llm_futs = {}
                for sid, plan in llm_sources:
                    unresolved = self._find_unresolved(plan, sources_info.get(sid, {}))
                    sample = self._get_sample(state, sid, 5)
                    f = executor.submit(self._llm_generate_tool, sid, unresolved, sample)
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
    def _plan_layers_1_2(self, sid, src_info, sources_info, semantic_types):
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
            adaptations = self._rule_plan_adaptations(sid, src_quality, semantic_types, base_tasks, conditions)
        except Exception as e:
            logger.warning("[ToolPlan] Adaptation failed for %s: %s", sid, e)
        return {"base": base_tasks, "adapted": adaptations, "generated": []}

    # ── Layer 2: Rule-Based Adaptations (V2.1: 确定性规则注入参数) ──
    def _rule_plan_adaptations(self, sid, src_quality, semantic_types, base_tasks, conditions):
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
            for fn, status in unit_status.items():
                if isinstance(status, str) and "inconsistent" in status:
                    st = semantic_types.get(fn, {})
                    std_unit = st.get("standard_unit") if isinstance(st, dict) else None
                    if std_unit:
                        conversions.append({"field": fn, "to": std_unit})
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

        needs_custom = score >= 1
        if needs_custom:
            logger.info("[ToolPlan] Layer 3 triggered: score=%d, %d issue categories",
                        score, len(issues))

        return {"needs_custom": needs_custom, "issues": issues, "score": score}

    def _get_sample(self, state, sid, n):
        """获取 source 的前 n 条 sample records。"""
        data = state.get("data_state", {}).get("current_data", {})
        records = [r for r in data.get("records", []) if r.get("source_id") == sid]
        return records[:n]

    def _llm_generate_tool(self, sid, unresolved, records_sample):
        """LLM 生成自定义 Python 工具函数 (V2.1: 通用化 prompt)。"""
        from subgraphs.quality.utils.llm import get_llm, set_agent_context
        set_agent_context("normalization")

        # 构建详细的 sample (含字段名、值、单位、溯源状态)
        sample_str = json.dumps([
            {
                "record_id": r.get("record_id", ""),
                "field_name": r.get("field_name", ""),
                "field_value": str(r.get("field_value", ""))[:80],
                "field_unit": r.get("field_unit"),
                "has_provenance": bool(r.get("provenance")),
            }
            for r in records_sample[:5]
        ], indent=2, ensure_ascii=False)

        issues_str = "\n".join(f"  - {iss}" for iss in unresolved["issues"])

        prompt = f"""This source (id={sid[:40]}) has {len(unresolved['issues'])} unresolved data quality issues:

{issues_str}

Sample records (first 5 of {len(records_sample)}):
{sample_str}

{_BASE_TOOL_SIGNATURES}

Analyze the issues and the sample data. Generate a custom Python function that fixes
the specific problems in this data. The function should:
- Handle edge cases (empty input, unexpected types, None values)
- Work on the records in-place OR return updated records via result['data']
- Be robust: if a fix cannot be applied safely, skip it and log the reason

Return JSON with: tool_name, tool_code, confidence (0-1), reasoning."""

        llm = get_llm(temperature=0.0)
        resp = llm.invoke([{"role": "system", "content": _TOOL_GEN_SYSTEM},
                           {"role": "user", "content": prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        code = data.get("tool_code", "")
        confidence = data.get("confidence", 0.5)

        # ── V2.1: AST 白名单安全检查 ──
        try:
            from Data_Normalization_agentV1.agents.normalization_agent import _validate_code_ast
        except ImportError:
            _validate_code_ast = _validate_code_simple_fallback
        if not _validate_code_ast(code):
            logger.warning("[ToolPlan] Generated code blocked: AST validation failed")
            return None

        return {"tool_name": data.get("tool_name", f"custom_{sid[:10]}"),
                "tool_code": code, "confidence": confidence,
                "source_id": sid, "reasoning": data.get("reasoning", "")}

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
