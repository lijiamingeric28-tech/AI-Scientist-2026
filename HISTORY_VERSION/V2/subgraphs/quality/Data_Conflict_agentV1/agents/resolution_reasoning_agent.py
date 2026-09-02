"""
resolution_reasoning_agent.py — Node 4: ResolutionReasoningAgent

职责: 加权证据融合 → 策略选择 → LLM 推理裁决。
LLM: 是 (per-conflict + 聚合) | Tools: 0
"""
from __future__ import annotations
import datetime, json, re, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.utils.llm import get_llm, set_agent_context, track_raw_llm_call
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)

# ── V2.2: 证据融合权重从 config 加载, 代码只有 fallback ──
_DEFAULT_WEIGHTS = {"source_reliability": 0.30, "domain_rules": 0.25,
                     "statistical": 0.25, "contextual": 0.20}

# V2.2: 高变异语义类型 (从 config semantic_types.expected_in_study 也可推断,
# 此处仅作 fallback)
_VARIABLE_SEMANTIC_TYPES: set[str] = set()


def _load_domain_weights(research_domain: str) -> dict:
    """从 quality_rules.yaml 加载领域证据权重。"""
    try:
        from subgraphs.quality.configs import load_yaml
        config = load_yaml("quality_rules.yaml")
        # 尝试 resolution_weights, fallback 到 domain_weights
        rw = config.get("resolution_weights", config.get("domain_weights", {}))
        domain_weights = rw.get(research_domain, rw.get("default", _DEFAULT_WEIGHTS))
        return {
            "source_reliability": domain_weights.get("source_reliability", 0.30),
            "domain_rules": domain_weights.get("domain_rules", 0.25),
            "statistical": domain_weights.get("statistical", 0.25),
            "contextual": domain_weights.get("contextual", 0.20),
        }
    except Exception:
        return dict(_DEFAULT_WEIGHTS)


def _load_variable_types():
    """从 config 加载高变异语义类型列表。"""
    global _VARIABLE_SEMANTIC_TYPES
    if _VARIABLE_SEMANTIC_TYPES:
        return
    try:
        from subgraphs.quality.configs import load_yaml
        config = load_yaml("quality_rules.yaml")
        semantic_cfg = config.get("semantic_types", {})
        for st_name, st_info in semantic_cfg.items():
            expected = st_info.get("expected_in_study", "")
            if expected in ("conditional", "optional"):
                _VARIABLE_SEMANTIC_TYPES.add(st_name)
        # 通用高变异类型 (跨领域)
        _VARIABLE_SEMANTIC_TYPES.update({
            "elongation", "strain", "fatigue_life", "error", "uncertainty",
            "flux", "count", "variability", "scatter",
        })
    except Exception:
        pass

_REASONING_SYSTEM = """You are a scientific data conflict resolution expert.

Your task: Decide how to resolve each data conflict using available evidence.

Available strategies:
- prefer_source_a: Adopt Source A's value (Source A is more reliable)
- prefer_source_b: Adopt Source B's value (Source B is more reliable)
- compute_weighted_avg: Weighted average by reliability
- retain_range: Keep [min, max] range, annotate as natural variability
- retain_both: Keep both values, annotate condition differences
- flag_outlier: Flag one source as outlier, recommend exclusion
- escalate_to_human: Cannot auto-resolve, escalate

RULES:
1. NEVER fabricate or interpolate values. Only choose from existing data.
2. When NOT confident, escalate to human — do NOT guess.
3. Cite specific evidence for every decision.
4. Prefer the more reliable source when there's a clear reliability gap.
5. Elongation/fatigue-life fields with moderate differences → retain_range
6. Condition fields with different experimental parameters → retain_both

Output JSON:
{
  "resolutions": [
    {
      "conflict_id": "CF-001",
      "strategy": "prefer_source_a",
      "resolved_value": 450.0,
      "resolution": "auto_resolved",
      "reasoning_chain": ["Step 1...", "Step 2..."],
      "risk_assessment": "...",
      "confidence": 0.88
    }
  ]
}"""


class ResolutionReasoningAgent:
    """Node 4: 冲突推理 — 证据融合 + LLM 裁决"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        classification = conflict_state.get("classification", {})
        evidence = conflict_state.get("evidence", {})
        conflicts = classification.get("classified_conflicts", [])
        domain = state.get("context_state", {}).get("research_domain", "default")
        iteration = wf.get("iteration_counter", 0)

        weights = _load_domain_weights(domain)
        llm_count = wf.get("llm_call_count", 0)

        # ── Step 1: 加权证据融合 (per-conflict) ──
        fused_scores = {}
        for c in conflicts:
            cid = c.get("conflict_id", "")
            ev = evidence.get(cid, {})
            fused_scores[cid] = self._fuse_evidence(ev, weights)

        # ── Step 2: LLM 推理 ──
        resolutions = []
        llm_input_data = []
        for c in conflicts:
            cid = c.get("conflict_id", "")
            ev = evidence.get(cid, {})
            fs = fused_scores.get(cid, {})

            src_rel = ev.get("source_reliability", {})
            ctx = c.get("context", {})

            llm_input_data.append({
                "conflict_id": cid,
                "field_name": c.get("field_name", ""),
                "entity_type": c.get("entity_type", ""),
                "entity_name": c.get("entity_name", ""),
                "semantic_type": c.get("semantic_type", ""),
                "criticality": ctx.get("field_criticality", "important"),
                "source_a": {
                    "title": str(ctx.get("source_a_meta", {}).get("title", ""))[:80],
                    "year": ctx.get("source_a_meta", {}).get("year"),
                    "reliability": src_rel.get("source_a_reliability", 0.5),
                    "value": c.get("value_a") or c.get("mean_a"),
                },
                "source_b": {
                    "title": str(ctx.get("source_b_meta", {}).get("title", ""))[:80],
                    "year": ctx.get("source_b_meta", {}).get("year"),
                    "reliability": src_rel.get("source_b_reliability", 0.5),
                    "value": c.get("value_b") or c.get("mean_b"),
                },
                "cohens_d": c.get("cohens_d", 0),
                "effect_size": c.get("effect_size", ""),
                "ci_95": c.get("ci_95", []),
                "context": {
                    "same_material": ctx.get("same_material", True),
                    "same_condition": ctx.get("same_condition", True),
                    "temporal_gap_years": ctx.get("temporal_gap_years"),
                    "value_gap_pct": ctx.get("value_gap_pct"),
                },
                "evidence_summary": {
                    "source_verdict": src_rel.get("verdict", "equally_reliable"),
                    "reliability_gap": src_rel.get("reliability_gap", 0),
                    "statistical": ev.get("statistical_evidence", {}).get("effect_size_interpretation", ""),
                    "domain_guidance": [r["guidance"] for r in ev.get("domain_rules", {}).get("matched_rules", [])],
                },
                "fused_scores": fs,
            })

        try:
            set_agent_context("conflict_reasoning")
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([
                {"role": "system", "content": _REASONING_SYSTEM},
                {"role": "user", "content": f"Resolve these {len(llm_input_data)} conflicts:\n{json.dumps(llm_input_data, indent=2)}"},
            ])
            llm_text = resp.content if hasattr(resp, "content") else str(resp)
            json_match = re.search(r'\{.*\}', llm_text, re.DOTALL)
            if json_match:
                llm_result = json.loads(json_match.group(0))
                llm_resolutions = llm_result.get("resolutions", [])
            else:
                llm_resolutions = []
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="conflict_reasoning")
        except Exception as e:
            logger.warning("[ResolutionReasoning] LLM failed: %s — using rule-based fallback", e)
            llm_resolutions = []

        # ── Step 3: 合并 LLM + Fallback ──
        llm_map = {r["conflict_id"]: r for r in llm_resolutions}
        for c in conflicts:
            cid = c.get("conflict_id", "")
            ev = evidence.get(cid, {})
            fs = fused_scores.get(cid, {})

            if cid in llm_map:
                llm_r = llm_map[cid]
                resolutions.append({
                    "conflict_id": cid,
                    "strategy": llm_r.get("strategy", "escalate_to_human"),
                    "resolved_value": llm_r.get("resolved_value"),
                    "resolution": llm_r.get("resolution", "escalated_to_human"),
                    "reasoning_chain": llm_r.get("reasoning_chain", []),
                    "risk_assessment": llm_r.get("risk_assessment", ""),
                    "llm_confidence": llm_r.get("confidence", 0.5),
                    "fused_evidence_scores": fs,
                })
            else:
                # 规则引擎 fallback
                fallback = self._rule_fallback(c, ev)
                resolutions.append({**fallback, "fused_evidence_scores": fs, "llm_fallback": True})

        # ── Step 4: 聚合 + 构建 resolution_plan ──
        plan = self._build_resolution_plan(resolutions, evidence)
        auto_count = sum(1 for r in resolutions if r["resolution"] == "auto_resolved")
        human_count = len(resolutions) - auto_count

        elapsed = round(time.time() - t0, 3)
        logger.info("[ResolutionReasoning] %d conflicts: %d auto / %d human, %.2fs",
                    len(resolutions), auto_count, human_count, elapsed)

        return {
            "report_state": {"conflict": {
                "reasoning": {
                    "per_conflict": resolutions,
                    "aggregated": {
                        "auto_resolved": auto_count,
                        "human_required": human_count,
                        "resolution_plan": plan,
                    },
                }
            }},
            "workflow_state": {
                "current_node": "resolution_reasoning",
                "execution_status": "Success",
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "ResolutionReasoningAgent", "stage": "Reasoning",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{auto_count} auto-resolved, {human_count} escalated",
                }],
            },
        }

    def _fuse_evidence(self, evidence: dict, weights: dict) -> dict:
        """加权证据融合 → 每个策略得分"""
        src_rel = evidence.get("source_reliability", {})
        domain = evidence.get("domain_rules", {})
        stat = evidence.get("statistical_evidence", {})

        gap = src_rel.get("reliability_gap", 0)
        cohens_d = stat.get("cohens_d", 0)
        stat_sig = stat.get("statistically_significant", False)
        suggested = domain.get("suggested_strategy")

        strategies = {}
        # prefer_source_a
        pref_a_score = (
            weights["source_reliability"] * min(1.0, gap / 0.20) +
            weights["statistical"] * min(1.0, cohens_d / 1.0) +
            weights["domain_rules"] * (0.8 if suggested == "prefer_source_a" else 0.3) +
            weights["contextual"] * 0.5
        )
        strategies["prefer_source_a"] = round(pref_a_score, 4)

        # prefer_source_b
        strategies["prefer_source_b"] = round(pref_a_score * 0.95, 4)  # slight bias toward A

        # compute_weighted_avg
        avg_score = (
            weights["source_reliability"] * (1.0 - min(1.0, gap / 0.20)) +
            weights["statistical"] * (1.0 - min(1.0, cohens_d / 1.0)) +
            weights["domain_rules"] * (0.8 if suggested == "compute_weighted_avg" else 0.3) +
            weights["contextual"] * 0.5
        )
        strategies["compute_weighted_avg"] = round(avg_score, 4)

        # retain_range
        range_score = (
            weights["domain_rules"] * (0.8 if suggested == "retain_range" else 0.4) +
            weights["statistical"] * 0.5 +
            weights["contextual"] * 0.6 +
            weights["source_reliability"] * 0.3
        )
        strategies["retain_range"] = round(range_score, 4)

        # retain_both
        both_score = (
            weights["contextual"] * 0.7 +
            weights["domain_rules"] * 0.5 +
            weights["source_reliability"] * 0.3 +
            weights["statistical"] * 0.3
        )
        strategies["retain_both"] = round(both_score, 4)

        # escalate_to_human (inverse of best auto strategy)
        best_auto = max(
            strategies.get("prefer_source_a", 0),
            strategies.get("retain_range", 0),
            strategies.get("compute_weighted_avg", 0),
            strategies.get("retain_both", 0),
        )
        strategies["escalate_to_human"] = round(1.0 - best_auto, 4)

        # 最佳策略
        best_strategy = max(strategies, key=strategies.get)  # type: ignore[arg-type]
        strategies["best_strategy"] = best_strategy
        strategies["best_score"] = strategies[best_strategy]

        return strategies

    def _rule_fallback(self, conflict: dict, evidence: dict) -> dict:
        """LLM 失败时的规则引擎裁决"""
        src_rel = evidence.get("source_reliability", {})
        gap = src_rel.get("reliability_gap", 0)
        verdict = src_rel.get("verdict", "equally_reliable")
        cohens_d = conflict.get("cohens_d", 0)
        stat_ev = evidence.get("statistical_evidence", {})

        if gap > 0.15 and cohens_d > 0.3:
            if "a_more" in verdict:
                strategy = "prefer_source_a"
            elif "b_more" in verdict:
                strategy = "prefer_source_b"
            else:
                strategy = "prefer_source_a"
            resolution = "auto_resolved"
            resolved_value = conflict.get("value_a") or conflict.get("mean_a") if strategy == "prefer_source_a" else conflict.get("value_b") or conflict.get("mean_b")
        elif cohens_d < 0.5:
            strategy = "retain_range"
            resolution = "auto_resolved"
            resolved_value = None
        else:
            strategy = "escalate_to_human"
            resolution = "escalated_to_human"
            resolved_value = None

        return {
            "conflict_id": conflict.get("conflict_id"),
            "strategy": strategy,
            "resolved_value": resolved_value,
            "resolution": resolution,
            "reasoning_chain": [
                f"Rule-based fallback: reliability_gap={gap:.3f}, cohens_d={cohens_d:.3f}, verdict={verdict}",
            ],
            "risk_assessment": "Rule-based fallback — lower confidence than LLM reasoning",
            "llm_confidence": 0.5,
        }

    def _build_resolution_plan(self, resolutions: list[dict], evidence: dict) -> dict:
        """构建 resolution_plan"""
        actions_to_normalize = []
        annotations_to_add = []
        human_review_items = []

        for r in resolutions:
            if r["resolution"] == "auto_resolved":
                strategy = r["strategy"]
                if strategy in ("prefer_source_a", "prefer_source_b", "flag_outlier", "compute_weighted_avg"):
                    actions_to_normalize.append({
                        "conflict_id": r["conflict_id"],
                        "action": "normalize",
                        "target_source": r.get("target_source", "*"),
                        "entity_type": r.get("entity_type", ""),
                        "entity_name": r.get("entity_name", ""),
                        "field": r.get("field_name", r.get("conflict_id", "")),
                        "new_value": r.get("resolved_value"),
                        "reason": "; ".join(r.get("reasoning_chain", [])),
                    })
                elif strategy in ("retain_range", "retain_both"):
                    annotations_to_add.append({
                        "conflict_id": r["conflict_id"],
                        "action": "annotate",
                        "annotation": f"Strategy: {strategy}. " + "; ".join(r.get("reasoning_chain", [])),
                    })
            else:
                ev = evidence.get(r["conflict_id"], {})
                human_review_items.append({
                    "conflict_id": r["conflict_id"],
                    "reason": f"Cannot auto-resolve (strategy={r['strategy']})",
                    "evidence_summary": {
                        "source_verdict": ev.get("source_reliability", {}).get("verdict", "unknown"),
                        "domain_rules": [m["rule_name"] for m in ev.get("domain_rules", {}).get("matched_rules", [])],
                        "statistical": ev.get("statistical_evidence", {}).get("effect_size_interpretation", ""),
                    },
                })

        return {
            "actions_to_normalize": actions_to_normalize,
            "annotations_to_add": annotations_to_add,
            "human_review_items": human_review_items,
        }
