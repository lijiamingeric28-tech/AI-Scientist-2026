"""
planning_agent.py — Stage 2: ToolPlanningAgent (V2.0)

核心创新: LLM 根据数据问题自动规划工具链:
  Layer 1: 选择 Base Tools (6个确定性工具)
  Layer 2: 生成 Adapted Tools (LLM 注入自定义参数)
  Layer 3: 生成 Custom Tools (LLM 动态编写 Python 函数)
"""
from __future__ import annotations
import datetime, time, json, re
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

        for sid, src_info in sources_to_process.items():
            conditions = src_info.get("conditions", [])
            src_quality = sources_info.get(sid, {})
            by_src = {"base": [], "adapted": [], "generated": []}

            # ── Layer 1: Base Tools ──
            base_tasks = []
            for c in conditions:
                task = _CONDITION_TOOL_MAP.get(c.get("condition", ""))
                if task and task not in base_tasks:
                    base_tasks.append(task)
            if not base_tasks:
                base_tasks = ["field_standardizer", "format_standardizer"]
            by_src["base"] = base_tasks

            # ── Layer 2: LLM Adapted Tools ──
            try:
                adaptations = self._llm_plan_adaptations(
                    sid, src_quality, semantic_types, base_tasks, conditions)
                by_src["adapted"] = adaptations
                if adaptations:
                    llm_count += 1
                    logger.info("[ToolPlan] %s: %d adaptations", sid[:20], len(adaptations))
            except Exception as e:
                logger.warning("[ToolPlan] Adaptation failed for %s: %s", sid[:20], e)

            # ── Layer 3: LLM Generated Tools (仅当有复杂问题) ──
            unresolved = self._find_unresolved(by_src, src_quality)
            if unresolved.get("needs_custom"):
                try:
                    records_sample = self._get_sample(state, sid, 5)
                    custom = self._llm_generate_tool(
                        sid, unresolved, records_sample)
                    if custom:
                        by_src["generated"] = [custom]
                        llm_count += 1
                        logger.info("[ToolPlan] %s: generated tool=%s (conf=%.2f)",
                                    sid[:20], custom["tool_name"], custom.get("confidence", 0))
                except Exception as e:
                    logger.warning("[ToolPlan] Generation failed for %s: %s", sid[:20], e)

            tool_registry["by_source"][sid] = by_src
            # 汇总到全局列表
            for t in by_src["base"]:
                if t not in tool_registry["base_tools"]:
                    tool_registry["base_tools"].append(t)
            tool_registry["adapted_tools"].extend(by_src["adapted"])
            tool_registry["generated_tools"].extend(by_src["generated"])

        norm["tool_registry"] = tool_registry
        norm["planning_method"] = "llm_enhanced" if llm_count > wf.get("llm_call_count", 0) else "rule_engine"

        logger.info("[ToolPlan] %d sources: base=%d adapted=%d generated=%d",
                    len(sources_to_process),
                    len(tool_registry["base_tools"]),
                    len(tool_registry["adapted_tools"]),
                    len(tool_registry["generated_tools"]))

        return self._build_return(norm, wf, t0, norm["planning_method"],
                                   len(sources_to_process), llm_count)

    # ── Layer 2: LLM Adaptations ──
    def _llm_plan_adaptations(self, sid, src_quality, semantic_types, base_tasks, conditions):
        """LLM 为 Base Tools 生成自定义参数。"""
        adaptations = []
        completness = src_quality.get("completeness", {})
        fmt = src_quality.get("format", {})
        consistency = src_quality.get("consistency", {})

        # schema_mapping: 注入 extra_fields 作为别名
        if "schema_mapping" in base_tasks:
            extra = set(completness.get("present_fields", [])) - set(completness.get("expected_fields", []))
            if extra:
                adaptations.append({"base_tool": "schema_mapping", "adaptation": "add_extra_aliases",
                                    "custom_params": {"extra_aliases": list(extra)},
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
        """判断是否需要 Layer 3 自定义工具。"""
        issues = []
        # 检查是否有 unit_converter 无法处理的单位
        consistency = src_quality.get("consistency", {})
        unit_status = consistency.get("unit_consistency", {})
        for fn, status in unit_status.items():
            if isinstance(status, str) and "inconsistent" in status and "GPa" in str(status) and "hardness" in fn.lower():
                issues.append(f"Hardness units may need special conversion (GPa→HV, not simple ×1000)")
                break

        # 检查是否有复杂复合问题
        issue_count = src_quality.get("issue_count", 0)
        conflict_count = src_quality.get("conflict_risk", {}).get("conflict_count", 0)
        if issue_count >= 3 and conflict_count >= 1:
            issues.append(f"Multiple overlapping issues ({issue_count} issues + {conflict_count} conflicts)")

        return {"needs_custom": len(issues) > 0, "issues": issues}

    def _get_sample(self, state, sid, n):
        """获取 source 的前 n 条 sample records。"""
        data = state.get("data_state", {}).get("current_data", {})
        records = [r for r in data.get("records", []) if r.get("source_id") == sid]
        return records[:n]

    def _llm_generate_tool(self, sid, unresolved, records_sample):
        """LLM 生成自定义 Python 工具函数。"""
        from utils.llm import get_llm, set_agent_context
        set_agent_context("normalization")

        sample_str = json.dumps([{k: str(v)[:50] for k, v in r.items()}
                                  for r in records_sample[:3]], indent=2, ensure_ascii=False)
        prompt = f"""Data issues for source {sid[:30]}:
{chr(10).join(unresolved['issues'])}

Sample records:
{sample_str}

{_BASE_TOOL_SIGNATURES}

Generate a custom Python function to fix these specific issues.
Return JSON with tool_name, tool_code, confidence (0-1), and reasoning."""

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

        # 安全检查
        if any(kw in code for kw in ("os.", "sys.", "subprocess", "socket", "requests", "import os", "import sys")):
            logger.warning("[ToolPlan] Generated code blocked: unsafe imports")
            return None

        return {"tool_name": data.get("tool_name", f"custom_{sid[:10]}"),
                "tool_code": code, "confidence": confidence,
                "source_id": sid, "reasoning": data.get("reasoning", "")}

    def _build_return(self, norm, wf, t0, method, n_sources, llm_count=None):
        history = list(wf.get("workflow_history", []))
        history.append({"agent": "ToolPlanningAgent", "stage": "ToolPlanning", "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(), "duration": round(time.time()-t0, 3),
                        "reason": f"{n_sources} sources planned (method={method})"})
        ret = {"report_state": {"normalization": norm},
               "workflow_state": {"current_node": "planning", "execution_status": "Success",
                                  "workflow_history": history}}
        if llm_count is not None:
            ret["workflow_state"]["llm_call_count"] = llm_count
        return ret
