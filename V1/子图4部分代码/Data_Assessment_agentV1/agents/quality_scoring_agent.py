"""
quality_scoring_agent.py — Stage 3: QualityScoringAgent

职责: 对每篇论文独立评分, 然后聚合为整体质量等级。
- 每个 source 独立计算 quality_scoring
- 聚合: overall_score = weighted average, overall_level = worst among sources
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from quality_state import QualityGraphState
from utils.logger import get_logger

logger = get_logger(__name__)

# 路由严重程度 (用于聚合: 取最严重的)
_ROUTE_SEVERITY = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}


class QualityScoringAgent:
    """Stage 3: Per-Source Scoring + Aggregate。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        quality = dict(rs.get("quality", {}) or {})
        source_reports = quality.get("sources", {})

        from configs import load_yaml
        from tools.assessment.quality_scoring import compute_quality_score

        rules = load_yaml("quality_rules.yaml")
        # ── V2.0 S1: 领域自适应权重 ──
        research_domain = state.get("context_state", {}).get("research_domain", "default")
        domain_weights_config = rules.get("domain_weights", {})
        weights = domain_weights_config.get(research_domain)
        if weights is None:
            weights = domain_weights_config.get("default")
        if weights is None:
            weights = rules.get("quality_scoring", {}).get("weights")

        source_scores: list[float] = []
        worst_level = "excellent"
        worst_score = 1.0
        level_order = {"poor": 0, "fair": 1, "good": 2, "excellent": 3}

        for sid, sr in source_reports.items():
            # ── V2.1: LLM completeness 调整 ──
            raw_completeness = dict(sr.get("completeness", {}))
            llm_comp = sr.get("llm_completeness")
            if llm_comp and isinstance(llm_comp, dict):
                adjusted = llm_comp.get("adjusted_completeness")
                if adjusted is not None:
                    # 保留原始分, 显式计算 effective score
                    raw_completeness["raw_score"] = raw_completeness.get("score", 1.0)
                    raw_completeness["score"] = round(
                        raw_completeness.get("raw_score", 1.0) * adjusted, 4)
                    raw_completeness["llm_adjusted"] = True
                    sr["completeness"] = raw_completeness

            metrics = {
                "completeness": raw_completeness,
                "consistency": sr.get("consistency", {}),
                "format": sr.get("format", {}),
                "source_reliability": sr.get("source_reliability", {}),
                "conflict_risk": {
                    "score": 1.0 - min(1.0, sr.get("conflict_risk", {}).get("conflict_count", 0) * 0.1),
                },
            }
            scoring = compute_quality_score(metrics, weights=weights)
            sr["quality_scoring"] = scoring
            source_scores.append(scoring["overall_score"])

            # 追踪最差等级
            lvl = scoring.get("quality_level", "excellent")
            if level_order.get(lvl, 3) < level_order.get(worst_level, 3):
                worst_level = lvl
                worst_score = scoring["overall_score"]

        # ── 聚合 ──
        overall_score = round(sum(source_scores) / len(source_scores), 4) if source_scores else 0.0

        # ── V2.0 S2: 非线性惩罚 ──
        penalty_applied = False
        penalty_reason = ""
        # Systematic failure: 任何 source 的维度得分=0 → 乘性惩罚
        for sid, sr in source_reports.items():
            for dim in ("completeness", "consistency", "format"):
                if sr.get(dim, {}).get("score", 1.0) == 0.0:
                    overall_score *= 0.7
                    penalty_applied = True
                    penalty_reason = f"Systematic failure in {sid[:20]}"
                    break
            if penalty_applied:
                break

        # Sparsity penalty: 总记录数 < 10 → 降低置信度
        total_records = sum(sr.get("record_count", 0) for sr in source_reports.values())
        import math
        if total_records < 10 and total_records > 0:
            sparsity_factor = math.log(total_records) / math.log(10)
            confidence_mult = max(0.3, sparsity_factor)
        else:
            confidence_mult = 1.0

        # ── V2.0 S3: 置信度校准 ──
        # data volume factor
        if total_records < 10:
            volume_factor = 0.3
        elif total_records < 100:
            volume_factor = 0.7
        else:
            volume_factor = 0.9
        # agreement factor: per-source评分一致性
        if len(source_scores) >= 2:
            import statistics
            try:
                score_std = statistics.stdev(source_scores)
                agreement_factor = max(0.3, 1.0 - score_std * 2)
            except statistics.StatisticsError:
                agreement_factor = 0.5
        else:
            agreement_factor = 0.5
        # combined
        calibrated_confidence = round(
            volume_factor * 0.4 + agreement_factor * 0.4 + confidence_mult * 0.2, 4
        )

        quality["quality_scoring"] = {
            "overall_score": overall_score,
            "quality_level": worst_level,
            "per_source_scores": {sid: sr.get("quality_scoring", {}).get("overall_score", 0)
                                  for sid, sr in source_reports.items()},
            "source_count": len(source_reports),
            "dimension_weights": weights or {},
            "penalty_applied": penalty_applied,
            "penalty_reason": penalty_reason,
            "calibrated_confidence": calibrated_confidence,
            "confidence_factors": {
                "data_volume": volume_factor,
                "agreement": agreement_factor,
                "sparsity": confidence_mult,
            },
        }

        elapsed = round(time.time() - t0, 3)
        logger.info("[QualityScoringAgent] %d sources, overall=%.4f (%s), worst=%s, %.2fs",
                    len(source_reports), overall_score, worst_level,
                    min(source_scores) if source_scores else "N/A", elapsed)

        return {
            "report_state": {"quality": quality},
            "workflow_state": {
                "current_node": "scoring",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "QualityScoringAgent", "stage": "QualityScoring",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(source_reports)} sources, overall={overall_score:.2f} ({worst_level})",
                }],
            },
        }
