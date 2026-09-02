"""
evidence_collection_agent.py — Node 3: EvidenceCollectionAgent (V2.3)

职责: 对每个冲突收集 4 维证据, V2.3 per-conflict 并行。
"""
from __future__ import annotations
import datetime, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.tools.conflict.source_reliability_analyzer import analyze_source_reliability
from subgraphs.quality.tools.conflict.domain_rule_engine import match_domain_rules
from subgraphs.quality.tools.conflict.statistical_evidence import analyze_statistical_evidence
from subgraphs.quality.tools.conflict.contextual_evidence import collect_contextual_evidence
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


def _collect_one_conflict(cid: str, conflict: dict, data: dict, domain: str,
                           semantic_types: dict, quality_scoring: dict) -> tuple[str, dict, int]:
    """收集单个冲突的 4 维证据 (独立线程)。"""
    evidence = {}
    errors = 0
    try:
        evidence["source_reliability"] = analyze_source_reliability(conflict, data, quality_scoring)
    except Exception:
        evidence["source_reliability"] = {"verdict": "equally_reliable", "reliability_gap": 0.0}
        errors += 1
    try:
        evidence["domain_rules"] = match_domain_rules(conflict, semantic_types, domain)
    except Exception:
        evidence["domain_rules"] = {"matched_rules": [], "has_domain_guidance": False}
        errors += 1
    try:
        evidence["statistical_evidence"] = analyze_statistical_evidence(conflict)
    except Exception:
        evidence["statistical_evidence"] = {"statistically_significant": "unknown", "recommendation": "weak_evidence"}
        errors += 1
    try:
        evidence["contextual_evidence"] = collect_contextual_evidence(conflict, data)
    except Exception:
        evidence["contextual_evidence"] = {"same_material": True, "same_condition": True}
        errors += 1
    return cid, evidence, errors


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

        # ══════════════════════════════════════════════════
        # V2.3: 并行收集所有冲突的证据
        # ══════════════════════════════════════════════════
        n_workers = min(8, max(1, len(conflicts)))
        evidence_by_id: dict[str, dict] = {}
        tool_errors = 0

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {}
            for c in conflicts:
                cid = c.get("conflict_id", "")
                f = executor.submit(_collect_one_conflict, cid, c, data, domain,
                                    semantic_types, quality_scoring)
                futures[f] = cid

            for future in as_completed(futures):
                try:
                    cid, evidence, errors = future.result()
                    evidence_by_id[cid] = evidence
                    tool_errors += errors
                except Exception as e:
                    cid = futures[future]
                    logger.warning("[Evidence] Conflict %s failed: %s", cid, e)
                    evidence_by_id[cid] = {}

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
