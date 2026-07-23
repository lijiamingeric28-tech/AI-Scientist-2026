"""
conflict_identification_agent.py — Node 1: ConflictIdentificationAgent

职责: 汇总冲突列表, 确定触发路径 (A→C / B→C),
      提取所有冲突字段及冲突对象, 构建冲突上下文。
LLM: 无 | Tools: 2 (ConflictExtractor + ContextBuilder)
"""
from __future__ import annotations
import datetime, time
from typing import Any
from subgraphs.quality.state import QualityGraphState
from subgraphs.quality.tools.conflict.conflict_extractor import extract_conflicts
from subgraphs.quality.tools.conflict.context_builder import build_conflict_context
from subgraphs.quality.utils.logger import get_logger
logger = get_logger(__name__)


class ConflictIdentificationAgent:
    """Node 1: 冲突识别 — 汇总 + 去重 + 上下文构建"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})
        ctx_state = state.get("context_state", {})

        quality = rs.get("quality") or {}
        normalization = rs.get("normalization") or {}
        data = state.get("data_state", {}).get("current_data", {})

        # ── 1. 确定触发路径 ──
        trigger_path = self._determine_trigger(quality, normalization)
        if trigger_path == "unknown":
            logger.warning("[ConflictIdentification] No conflict source found")
            return self._no_conflicts_result(t0, wf)

        # ── 2. 提取冲突 (Tool 1) ──
        extracted = extract_conflicts(quality, normalization, trigger_path)
        if extracted["total_conflicts"] == 0:
            logger.info("[ConflictIdentification] No conflicts to resolve → Export")
            return self._no_conflicts_result(t0, wf)

        # ── 3. 构建上下文 (Tool 2) ──
        conflicts_with_context = build_conflict_context(
            extracted["conflicts"],
            data,
            ctx_state.get("target_schema"),
        )

        elapsed = round(time.time() - t0, 3)
        logger.info("[ConflictIdentification] %d conflicts via %s, %.2fs",
                    extracted["total_conflicts"], trigger_path, elapsed)

        return {
            "report_state": {"conflict": {
                "identification": {
                    "trigger_path": trigger_path,
                    "total_conflicts": extracted["total_conflicts"],
                    "conflicts": conflicts_with_context,
                    "involved_sources": extracted["involved_sources"],
                    "involved_fields": extracted["involved_fields"],
                    "summary": extracted["summary"],
                }
            }},
            "workflow_state": {
                "current_node": "conflict_identification",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "ConflictIdentificationAgent", "stage": "Identification",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"Identified {extracted['total_conflicts']} conflict(s) via {trigger_path}",
                }],
            },
        }

    def _determine_trigger(self, quality: dict, normalization: dict) -> str:
        """确定触发路径"""
        # A→C: 从 Assessment 直接检测
        if quality:
            sources = quality.get("sources", {})
            for sid, src in sources.items():
                cr = src.get("conflict_risk", {})
                if cr.get("has_conflicts") and cr.get("conflict_count", 0) > 0:
                    return "A→C"
        # B→C: 从 Normalization 后检测
        if normalization:
            val = normalization.get("validation", {})
            if val.get("needs_conflict_analysis") and val.get("conflict_check", {}).get("conflict_count", 0) > 0:
                return "B→C"
        return "unknown"

    def _no_conflicts_result(self, t0: float, wf: dict) -> dict:
        """无冲突时的直接跳过结果"""
        return {
            "report_state": {"conflict": {
                "identification": {
                    "trigger_path": "none",
                    "total_conflicts": 0,
                    "conflicts": [],
                    "involved_sources": [],
                    "involved_fields": [],
                    "summary": "No conflicts detected.",
                }
            }},
            "workflow_state": {
                "route_decision": "Export",
                "execution_status": "Success",
                "current_node": "conflict_identification",
                "workflow_history": [{
                    "agent": "ConflictIdentificationAgent", "stage": "Identification",
                    "status": "Success", "timestamp": datetime.datetime.now().isoformat(),
                    "duration": round(time.time() - t0, 3),
                    "reason": "No conflicts found → Export",
                }],
            },
        }
