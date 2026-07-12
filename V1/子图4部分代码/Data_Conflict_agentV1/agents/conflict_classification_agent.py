"""
conflict_classification_agent.py — Node 2: ConflictClassificationAgent

职责: 对冲突进行分类 (Type/Subtype/Severity)。
      规则分类器处理确定项, LLM 补充不确定项。
LLM: 是 | Tools: 1 (RuleBasedClassifier)
"""
from __future__ import annotations
import datetime, json, time
from typing import Any
from quality_state import QualityGraphState
from tools.conflict.rule_classifier import classify_conflict_rule
from utils.llm import get_llm, set_agent_context, track_raw_llm_call
from utils.logger import get_logger
logger = get_logger(__name__)

_CLASSIFICATION_SYSTEM = """You are a scientific data conflict classification expert in materials science and astrophysics.

Classify each data conflict by determining its subtype and severity.

Conflict Types:
- cross_source_value_conflict: numerical value mismatch between sources
  Subtypes:
  * systematic_bias: genuine difference, same material/condition (Cohen's d > 0.8)
  * measurement_discrepancy: likely measurement error (moderate d, high variance)
  * condition_difference: actually different experimental conditions
  * material_difference: actually different materials/samples
  * temporal_drift: different eras/techniques (10+ year gap)
- type_inconsistency: same field has different data types across sources
- unit_inconsistency: same field uses different units
- semantic_conflict: semantic type inference contradicts
- completeness_conflict: critical field missing in one source

Severity: critical | high | medium | low

Output JSON: {"classifications": [{"conflict_id": "...", "subtype": "...", "severity": "...", "classification_reason": "..."}]}"""


class ConflictClassificationAgent:
    """Node 2: 冲突分类 — 规则 + LLM 补充"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        identification = conflict_state.get("identification", {})
        conflicts = identification.get("conflicts", [])

        quality = state.get("report_state", {}).get("quality", {}) or {}
        profile = quality.get("profile", {})
        semantic_types = profile.get("semantic_types", {})
        target_schema = state.get("context_state", {}).get("target_schema", {})

        llm_count = wf.get("llm_call_count", 0)

        classified = []
        needs_llm = []

        for c in conflicts:
            ctx = c.get("context", {})
            fn = c.get("field_name", "")
            field_crit = ctx.get("field_criticality", "important")

            # 规则分类
            rule_result = classify_conflict_rule(c, semantic_types, field_crit)

            merged = {**c, **rule_result}

            if rule_result["subtype"] == "undetermined":
                needs_llm.append(merged)
            classified.append(merged)

        # LLM 补充不确定项
        if needs_llm:
            try:
                set_agent_context("conflict_classification")
                llm = get_llm(temperature=0.0)
                undetermined_data = [
                    {
                        "conflict_id": c["conflict_id"],
                        "field_name": c.get("field_name", ""),
                        "value_a": c.get("value_a") or c.get("mean_a", "?"),
                        "value_b": c.get("value_b") or c.get("mean_b", "?"),
                        "cohens_d": c.get("cohens_d", 0),
                        "same_material": c.get("context", {}).get("same_material", True),
                        "same_condition": c.get("context", {}).get("same_condition", True),
                        "temporal_gap_years": c.get("context", {}).get("temporal_gap_years"),
                        "type": c.get("type", ""),
                    }
                    for c in needs_llm
                ]
                prompt = f"Classify these {len(undetermined_data)} conflicts:\n{json.dumps(undetermined_data, indent=2)}"
                resp = llm.invoke([
                    {"role": "system", "content": _CLASSIFICATION_SYSTEM},
                    {"role": "user", "content": prompt},
                ])
                llm_text = resp.content if hasattr(resp, "content") else str(resp)
                # 简单提取 JSON
                import re
                json_match = re.search(r'\{.*\}', llm_text, re.DOTALL)
                if json_match:
                    llm_result = json.loads(json_match.group(0))
                    llm_classifications = llm_result.get("classifications", [])
                else:
                    llm_classifications = []

                llm_count += 1
                track_raw_llm_call(time.time() - t0, agent="conflict_classification")

                # 合并 LLM 结果
                llm_map = {c["conflict_id"]: c for c in llm_classifications}
                for c in classified:
                    if c["conflict_id"] in llm_map:
                        llm_c = llm_map[c["conflict_id"]]
                        c["subtype"] = llm_c.get("subtype", c["subtype"])
                        c["severity"] = llm_c.get("severity", c["severity"])
                        c["classification_reason"] = llm_c.get("classification_reason", "")
                        c["llm_classified"] = True

            except Exception as e:
                logger.warning("[ConflictClassification] LLM classification failed: %s", e)

        # 分组统计
        by_type: dict[str, list] = {}
        by_severity: dict[str, list] = {}
        for c in classified:
            t = c.get("type", "unknown")
            s = c.get("severity", "medium")
            by_type.setdefault(t, []).append(c["conflict_id"])
            by_severity.setdefault(s, []).append(c["conflict_id"])

        elapsed = round(time.time() - t0, 3)
        logger.info("[ConflictClassification] %d conflicts: %s", len(classified),
                    ", ".join(f"{t}={len(v)}" for t, v in by_type.items()))

        return {
            "report_state": {"conflict": {
                "classification": {
                    "classified_conflicts": classified,
                    "by_type": by_type,
                    "by_severity": by_severity,
                }
            }},
            "workflow_state": {
                "current_node": "conflict_classification",
                "execution_status": "Success",
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "ConflictClassificationAgent", "stage": "Classification",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Classified {len(classified)} conflicts ({len(needs_llm)} via LLM)",
                }],
            },
        }
