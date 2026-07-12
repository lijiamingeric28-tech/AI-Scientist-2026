"""
evidence_collection_agent.py — Node 3: EvidenceCollectionAgent

职责: 对每个冲突收集 4 维证据:
  - Source Reliability (来源可信度分析)
  - Domain Rules (领域规则匹配)
  - Statistical Evidence (统计效果量分析)
  - Contextual Evidence (上下文一致性)
LLM: 无 | Tools: 4
"""
from __future__ import annotations
import datetime, time
from typing import Any
from quality_state import QualityGraphState
from tools.conflict.source_reliability_analyzer import analyze_source_reliability
from tools.conflict.domain_rule_engine import match_domain_rules
from tools.conflict.statistical_evidence import analyze_statistical_evidence
from tools.conflict.contextual_evidence import collect_contextual_evidence
from utils.logger import get_logger
logger = get_logger(__name__)


class EvidenceCollectionAgent:
    """Node 3: 证据收集 — 4 维 × N conflicts"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        conflict_state = state.get("report_state", {}).get("conflict", {})
        wf = state.get("workflow_state", {})
        classification = conflict_state.get("classification", {})
        conflicts = classification.get("classified_conflicts", [])

        rs = state.get("report_state", {}) or {}
        quality = rs.get("quality", {}) or {}
        data = state.get("data_state", {}).get("current_data", {})
        domain = state.get("context_state", {}).get("research_domain", "default")
        profile = quality.get("profile", {})
        semantic_types = profile.get("semantic_types", {})
        quality_scoring = quality.get("quality_scoring", {})

        tool_errors = 0
        evidence_by_id: dict[str, dict] = {}

        for c in conflicts:
            cid = c.get("conflict_id", "")
            evidence = {}

            # Tool 4: Source Reliability
            try:
                evidence["source_reliability"] = analyze_source_reliability(
                    c, data, quality_scoring
                )
            except Exception as e:
                logger.warning("[Evidence] SourceReliability failed for %s: %s", cid, e)
                evidence["source_reliability"] = {
                    "verdict": "equally_reliable", "reliability_gap": 0.0,
                    "error": str(e),
                }
                tool_errors += 1

            # Tool 5: Domain Rules
            try:
                evidence["domain_rules"] = match_domain_rules(
                    c, semantic_types, domain
                )
            except Exception as e:
                logger.warning("[Evidence] DomainRules failed for %s: %s", cid, e)
                evidence["domain_rules"] = {
                    "matched_rules": [], "has_domain_guidance": False,
                    "suggested_strategy": None, "error": str(e),
                }
                tool_errors += 1

            # Tool 6: Statistical Evidence
            try:
                evidence["statistical_evidence"] = analyze_statistical_evidence(c)
            except Exception as e:
                logger.warning("[Evidence] StatisticalEvidence failed for %s: %s", cid, e)
                evidence["statistical_evidence"] = {
                    "statistically_significant": "unknown", "recommendation": "weak_evidence",
                    "error": str(e),
                }
                tool_errors += 1

            # Tool 7: Contextual Evidence
            try:
                evidence["contextual_evidence"] = collect_contextual_evidence(c, data)
            except Exception as e:
                logger.warning("[Evidence] ContextualEvidence failed for %s: %s", cid, e)
                evidence["contextual_evidence"] = {
                    "same_material": True, "same_condition": True, "error": str(e),
                }
                tool_errors += 1

            evidence_by_id[cid] = evidence

        elapsed = round(time.time() - t0, 3)
        if tool_errors >= 3:
            logger.warning("[Evidence] %d tool errors — may need retry", tool_errors)

        logger.info("[EvidenceCollection] %d conflicts × 4 tools, %d errors, %.2fs",
                    len(conflicts), tool_errors, elapsed)

        tool_count = wf.get("tool_call_count", 0) + len(conflicts) * 4

        return {
            "report_state": {"conflict": {
                "evidence": evidence_by_id,
            }},
            "workflow_state": {
                "current_node": "evidence_collection",
                "execution_status": "Retry" if tool_errors >= 3 else "Success",
                "tool_call_count": tool_count,
                "workflow_history": [{
                    "agent": "EvidenceCollectionAgent", "stage": "EvidenceCollection",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Collected 4-dim evidence for {len(conflicts)} conflict(s), {tool_errors} tool error(s)",
                }],
            },
        }
