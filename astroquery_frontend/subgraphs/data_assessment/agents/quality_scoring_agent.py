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

from quality_pipeline.configs import load_quality_scoring_runtime
from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

# 路由严重程度 (用于聚合: 取最严重的)
_ROUTE_SEVERITY = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}

# A3: conflict severity 权重表 (Σsev/3.0 封顶扣分)
# A11 fix: 从 quality_rules.yaml quality_scoring_runtime.conflict_severity 读,
# fallback 保持旧 dict (yaml 缺失/损坏时行为不变)
_CONFLICT_SEVERITY_WEIGHT = load_quality_scoring_runtime().get(
    "conflict_severity",
    {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2},
)


def _conflict_severity_score(conflict_risk: dict) -> float:
    """A3 fix: conflict 分数按严重度加权 — 不再只数个数。

    1 个 critical unit_error 扣 1.0/3.0≈0.33 (原 0.1), 3 个 critical 扣满;
    10 个 low 才扣满 (原 0.1/个 与 critical 同等)。
    """
    conflicts = conflict_risk.get("conflicts") or []
    if not conflicts:
        return 1.0
    penalty = sum(_CONFLICT_SEVERITY_WEIGHT.get(c.get("severity", "low"), 0.2)
                  for c in conflicts)
    return round(max(0.0, 1.0 - min(1.0, penalty / 3.0)), 4)


class QualityScoringAgent:
    """Stage 3: Per-Source Scoring + Aggregate。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        rs = state.get("report_state", {})
        wf = state.get("workflow_state", {})

        quality = dict(rs.get("quality", {}) or {})
        source_reports = quality.get("sources", {})

        from quality_pipeline.configs import load_yaml
        from quality_pipeline.tools.assessment.quality_scoring import compute_quality_score

        rules = load_yaml("quality_rules.yaml")
        # ── V2.0 S1: 领域自适应权重 ──
        research_domain = state.get("context_state", {}).get("research_domain", "default")
        domain_weights_config = rules.get("domain_weights", {})
        weights = domain_weights_config.get(research_domain)
        if weights is None:
            weights = domain_weights_config.get("default")
        if weights is None:
            weights = rules.get("quality_scoring", {}).get("weights")
        # A2 fix 双保险: 权重缺 extraction_quality 时补默认值并重归一化
        # (yaml 未同步时 compute_quality_score 仍能计入提取质量维度)
        if weights is not None:
            weights = dict(weights)
            weights.setdefault("extraction_quality", 0.12)
            _wsum = sum(weights.values()) or 1.0
            if abs(_wsum - 1.0) > 1e-6:
                weights = {k: v / _wsum for k, v in weights.items()}

        source_scores: list[float] = []
        source_record_counts: list[int] = []  # A8: 记录数加权聚合
        worst_level = "excellent"
        worst_score = 1.0
        level_order = {"poor": 0, "fair": 1, "good": 2, "excellent": 3}

        # V2: per-entity score tracking
        per_entity_all: dict[str, dict] = {}

        for sid, sr in source_reports.items():
            # ── V2.1: LLM completeness 调整 ──
            raw_completeness = dict(sr.get("completeness", {}))
            llm_comp = sr.get("llm_completeness")
            if llm_comp and isinstance(llm_comp, dict):
                # A6 fix: 可加性单次计分 — 原乘法 (raw × adjusted) 双重扣分:
                # raw 已含 0.4×外键+0.3×单位+0.3×溯源惩罚, adjusted 再乘一次;
                # 改减法 field_penalty 只计一次, 且 missing_expected_fields
                # 首次进入评分链 (字段全缺不再 score=1.0)
                field_penalty = llm_comp.get("field_penalty", 0.0) or 0.0
                raw_completeness["raw_score"] = raw_completeness.get("score", 1.0)
                raw_completeness["score"] = round(
                    max(0.0, min(1.0, raw_completeness.get("raw_score", 1.0) - field_penalty)),
                    4)
                raw_completeness["llm_adjusted"] = True
                sr["completeness"] = raw_completeness

            # ── V2.3: 加入 extraction_quality ──
            extraction_q = sr.get("extraction_quality", {})
            metrics = {
                "extraction_quality": extraction_q,
                "completeness": raw_completeness,
                "consistency": sr.get("consistency", {}),
                "format": sr.get("format", {}),
                "source_reliability": sr.get("source_reliability", {}),
                "conflict_risk": {
                    # A3 fix: severity 加权 — 原公式只数个数 (1 个 critical 只扣 0.1,
                    # 10 个 low 才扣满); unit_error/cross_id 是数据语义错误应远重于
                    # 同方法同条件的统计离群。sev: critical=1.0, high=0.7, medium=0.4, low=0.2
                    "score": _conflict_severity_score(sr.get("conflict_risk", {})),
                },
            }
            scoring = compute_quality_score(metrics, weights=weights)
            sr["quality_scoring"] = scoring
            source_scores.append(scoring["overall_score"])
            source_record_counts.append(sr.get("record_count", 0))  # A8

            # ── V2: per-entity scoring from tool outputs ──
            src_per_entity: dict[str, dict] = {}
            # 从 extraction_quality 获取 per-entity 数据
            extr_per_entity = extraction_q.get("per_entity_scores", {})
            for elabel, escore in extr_per_entity.items():
                src_per_entity.setdefault(elabel, {})["extraction_quality"] = escore
            # 从 completeness 获取 per-entity 数据
            comp_per_entity_present = raw_completeness.get("per_entity_present", {})
            comp_per_entity_missing = raw_completeness.get("per_entity_missing", {})
            all_entities_in_src = set(comp_per_entity_present.keys()) | set(comp_per_entity_missing.keys())
            for elabel in all_entities_in_src:
                entity_completeness = 1.0
                present = comp_per_entity_present.get(elabel, [])
                missing = comp_per_entity_missing.get(elabel, [])
                if present or missing:
                    entity_completeness = round(len(present) / max(len(present) + len(missing), 1), 4)
                src_per_entity.setdefault(elabel, {})["completeness"] = entity_completeness
            # 从 consistency 获取 per-entity 数据
            per_entity_type = sr.get("consistency", {}).get("per_entity_type_consistency", {})
            per_entity_unit = sr.get("consistency", {}).get("per_entity_unit_consistency", {})
            for elabel in set(per_entity_type.keys()) | set(per_entity_unit.keys()):
                tc = per_entity_type.get(elabel, 1.0)
                uc = per_entity_unit.get(elabel, 1.0)
                src_per_entity.setdefault(elabel, {})["type_consistency"] = tc
                src_per_entity.setdefault(elabel, {})["unit_consistency"] = uc
            # 从 format 获取 per-entity issues
            per_entity_fmt = sr.get("format", {}).get("per_entity_issues", {})
            for elabel, ecount in per_entity_fmt.items():
                src_per_entity.setdefault(elabel, {})["format_issues"] = ecount
            per_entity_all[sid] = src_per_entity

            # 追踪最差等级
            lvl = scoring.get("quality_level", "excellent")
            if level_order.get(lvl, 3) < level_order.get(worst_level, 3):
                worst_level = lvl
                worst_score = scoring["overall_score"]

        # ── 聚合 (A8 fix: 记录数加权 — 1 条记录的小 source 不再与 1000 条同权) ──
        total_n = sum(source_record_counts)
        if total_n > 0 and source_scores:
            overall_score = round(
                sum(s * n for s, n in zip(source_scores, source_record_counts)) / total_n, 4)
        else:
            overall_score = round(sum(source_scores) / len(source_scores), 4) if source_scores else 0.0

        # A8: Bootstrap CI (B=1000, 按 source 重抽样, 纯 numpy) — 评分不确定性输出
        overall_score_ci = None
        if len(source_scores) >= 2 and total_n > 0:
            import numpy as np
            arr_s = np.array(source_scores, dtype=float)
            arr_n = np.array(source_record_counts, dtype=float)
            rng = np.random.default_rng(42)  # 固定种子, 可复现
            _B = 1000
            boot = np.empty(_B)
            for _b in range(_B):
                _idx = rng.integers(0, len(arr_s), size=len(arr_s))
                _ns = arr_n[_idx]
                _ss = arr_s[_idx]
                _denom = _ns.sum()
                boot[_b] = (_ss * _ns).sum() / _denom if _denom > 0 else _ss.mean()
            _ci_lo, _ci_hi = np.percentile(boot, [2.5, 97.5])
            overall_score_ci = [round(float(_ci_lo), 4), round(float(_ci_hi), 4)]

        # ── V2.0 S2: 非线性惩罚 ──
        # 2026-08-14 fix: ①惩罚只对"有数值记录"的源生效——聚合侧（aggregator）
        # 保留条件是 records 或 figure_evidence，"仅图证/无数据"的源是正常产物
        # 形态而非系统性失败（此前 10 个仅图证论文源 completeness=0 触发 ×0.7，
        # 任务 5a22f9d3 实证 89.9→62.9 分）。②惩罚后 CI 同步乘惩罚系数（此前
        # CI 是惩罚前 bootstrap，显示与分数矛盾）。③惩罚后 overall_score 重新
        # round（此前 0.8988×0.7 产出 0.6291599999999999 浮点脏值）。
        penalty_applied = False
        penalty_reason = ""
        for sid, sr in source_reports.items():
            if sr.get("record_count", 0) <= 0:
                continue
            for dim in ("completeness", "consistency", "format"):
                if sr.get(dim, {}).get("score", 1.0) == 0.0:
                    overall_score *= 0.7
                    penalty_applied = True
                    penalty_reason = f"Systematic failure in {sid[:20]}"
                    break
            if penalty_applied:
                break
        if penalty_applied:
            overall_score = round(overall_score, 4)
            if overall_score_ci is not None:
                overall_score_ci = [round(overall_score_ci[0] * 0.7, 4),
                                    round(overall_score_ci[1] * 0.7, 4)]

        # Sparsity penalty: 总记录数 < 10 → 降低置信度
        total_records = sum(sr.get("record_count", 0) for sr in source_reports.values())
        import math
        if total_records < 10 and total_records > 0:
            sparsity_factor = math.log(total_records) / math.log(10)
            confidence_mult = max(0.3, sparsity_factor)
        else:
            confidence_mult = 1.0

        # ── V2.0 S3: 置信度校准 ──
        # A11 fix: volume/agreement 阈值从 quality_scoring_runtime 读 (fallback 旧值)
        _runtime_cfg = load_quality_scoring_runtime()
        _vol_th = _runtime_cfg.get("volume_thresholds", {10: 0.3, 100: 0.7, "else": 0.9})
        _std_coef = float(_runtime_cfg.get("agreement_std_coef", 2.0))
        # data volume factor
        if total_records < 10:
            volume_factor = float(_vol_th.get(10, 0.3))
        elif total_records < 100:
            volume_factor = float(_vol_th.get(100, 0.7))
        else:
            volume_factor = float(_vol_th.get("else", 0.9))
        # agreement factor: per-source评分一致性
        if overall_score_ci is not None:
            # A8: 改用 Bootstrap CI 宽度 — 评分离散度直接反映不确定性
            agreement_factor = max(0.3, 1.0 - (overall_score_ci[1] - overall_score_ci[0]))
        elif len(source_scores) >= 2:
            import statistics
            try:
                score_std = statistics.stdev(source_scores)
                agreement_factor = max(0.3, 1.0 - score_std * _std_coef)
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
            "overall_score_ci": overall_score_ci,  # A8: Bootstrap 95% CI (可为 None)
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
            # V2: per-entity score breakdown
            "per_entity_scores": per_entity_all,
        }

        # H-11 fix (A7 回归): 透传上游 execution_status — 硬编码 Success 会经
        # _merge_dict 标量覆盖抹掉 profiling/assessment 的 Failed/Retry, 子图级
        # 重试机制形同虚设 (与 assessment/decision 同款透传)
        prev_status = wf.get("execution_status", "Success")
        exec_status = prev_status if prev_status in ("Failed", "Retry") else "Success"

        elapsed = round(time.time() - t0, 3)
        logger.info("[QualityScoringAgent] %d sources, overall=%.4f (%s), worst=%s, %.2fs",
                    len(source_reports), overall_score, worst_level,
                    min(source_scores) if source_scores else "N/A", elapsed)

        return {
            "report_state": {"quality": quality},
            "workflow_state": {
                "current_node": "scoring",
                "execution_status": exec_status,
                "workflow_history": [{
                    "agent": "QualityScoringAgent", "stage": "QualityScoring",
                    "status": exec_status,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(source_reports)} sources, overall={overall_score:.2f} ({worst_level})",
                }],
            },
        }
