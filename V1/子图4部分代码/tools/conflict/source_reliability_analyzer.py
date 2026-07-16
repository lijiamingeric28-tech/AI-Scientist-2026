"""
source_reliability_analyzer.py — Tool 4: SourceReliabilityAnalyzer

分析冲突中每个 source 的可信度，输出两两比较结果。
评分维度: 质量评分 × 0.4 + 期刊分级 × 0.35 + 时效性 × 0.25
"""
from __future__ import annotations
import datetime
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

# 期刊分级缓存 (V2.2: 从 quality_rules.yaml 动态加载)
_JOURNAL_TIERS: dict[str, list[str]] | None = None
_JOURNAL_TIER_SCORES: dict[str, float] | None = None


def _load_journal_tiers():
    """从 quality_rules.yaml 动态加载期刊分级。"""
    global _JOURNAL_TIERS, _JOURNAL_TIER_SCORES
    if _JOURNAL_TIERS is not None:
        return
    try:
        # V3.0: 领域感知 — 先加载领域专属分级, fallback 到通用
        from configs import load_domain_config
        tiers = load_domain_config("journal_tiers", "journal_tiers")
        if not tiers:
            from configs import load_yaml
            config = load_yaml("quality_rules.yaml")
            tiers = config.get("source_reliability", {}).get("journal_tiers", {})
        _JOURNAL_TIERS = {}
        for tier_name in ("tier1", "tier2", "tier3"):
            journals = tiers.get(tier_name, [])
            if journals:
                _JOURNAL_TIERS[tier_name] = [j.lower() for j in journals]
        _JOURNAL_TIER_SCORES = {
            "tier1": tiers.get("tier1_score", 1.0),
            "tier2": tiers.get("tier2_score", 0.85),
            "tier3": tiers.get("tier3_score", 0.70),
        }
    except Exception as e:
        # fallback: 空分级 (不影响核心逻辑)
        _JOURNAL_TIERS = {"tier1": [], "tier2": [], "tier3": []}
        _JOURNAL_TIER_SCORES = {"tier1": 1.0, "tier2": 0.85, "tier3": 0.70}


def analyze_source_reliability(
    conflict: dict[str, Any],
    current_data: dict[str, Any],
    quality_scoring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    分析冲突双方来源可信度。

    Args:
        conflict: 含 source_a/source_b 的冲突
        current_data: data_state.current_data
        quality_scoring: report_state.quality.quality_scoring

    Returns:
        {source_a_reliability, source_b_reliability, reliability_gap, verdict, components}
    """
    sid_a = conflict.get("source_a", "")
    sid_b = conflict.get("source_b", "")
    ctx = conflict.get("context", {})

    def _get_source_meta(source_id: str) -> dict:
        """从 current_data 提取 source 元数据。"""
        if ctx.get("source_a_meta") and source_id == sid_a:
            return ctx["source_a_meta"]
        if ctx.get("source_b_meta") and source_id == sid_b:
            return ctx["source_b_meta"]
        for s in current_data.get("sources", []):
            if s.get("source_id") == source_id:
                return {
                    "title": s.get("title", ""),
                    "year": s.get("year"),
                    "journal": s.get("journal", ""),
                    "doi": s.get("doi", ""),
                }
        return {}

    def _compute_reliability(source_id: str) -> dict:
        source_scores = {}
        if quality_scoring:
            raw = quality_scoring.get("per_source_scores", quality_scoring.get("source_scores", {}))
            # V2.1 fix: 兼容两种格式 — dict 或 float
            for k, v in raw.items():
                if isinstance(v, dict):
                    source_scores[k] = v
                elif isinstance(v, (int, float)):
                    source_scores[k] = {"overall_score": float(v), "grade": "unknown"}
        src_score = source_scores.get(source_id, {})

        # 1. Quality Score (0.4)
        quality = src_score.get("overall_score", 0.75)

        # 2. Journal Tier (0.35) — V2.2: 从 config 加载
        _load_journal_tiers()
        meta = _get_source_meta(source_id)
        journal = (meta.get("journal") or "").lower()
        tier_weight = _JOURNAL_TIER_SCORES.get("tier3", 0.70)  # default to tier3
        for tier_name in ("tier1", "tier2", "tier3"):
            keywords = (_JOURNAL_TIERS or {}).get(tier_name, [])
            if any(kw in journal for kw in keywords):
                tier_weight = (_JOURNAL_TIER_SCORES or {}).get(tier_name, 0.70)
                break

        # 3. Recency (0.25)
        year = meta.get("year")
        current_year = datetime.datetime.now().year
        recency = 0.5
        if year is not None:
            try:
                y = int(year)
                age = current_year - y
                if age <= 2:
                    recency = 1.0
                elif age <= 5:
                    recency = 0.85
                elif age <= 10:
                    recency = 0.70
                elif age <= 15:
                    recency = 0.55
                else:
                    recency = 0.40
            except (ValueError, TypeError):
                pass

        reliability = 0.4 * quality + 0.35 * tier_weight + 0.25 * recency

        # ── V2.3: extraction_method 可信度加成 ──
        records_for_source = [r for r in current_data.get("records", [])
                              if r.get("source_id") == source_id]
        table_count = sum(1 for r in records_for_source if r.get("extraction_method") == "llm_table")
        text_count = sum(1 for r in records_for_source if r.get("extraction_method") == "llm_text")
        if table_count + text_count > 0:
            extraction_bonus = 0.05 * (table_count / (table_count + text_count))
            reliability += extraction_bonus

        reliability = max(0.0, min(1.0, reliability))

        return {
            "reliability": round(reliability, 4),
            "quality_score": round(quality, 4),
            "journal_tier_weight": tier_weight,
            "recency_bonus": round(recency, 4),
        }

    rel_a = _compute_reliability(sid_a)
    rel_b = _compute_reliability(sid_b)

    gap = round(abs(rel_a["reliability"] - rel_b["reliability"]), 4)

    if gap > 0.15:
        verdict = f"source_a_more_reliable" if rel_a["reliability"] > rel_b["reliability"] else "source_b_more_reliable"
    elif gap > 0.05:
        verdict = "slight_preference_a" if rel_a["reliability"] > rel_b["reliability"] else "slight_preference_b"
    else:
        verdict = "equally_reliable"

    logger.info("[SourceReliability] %s: gap=%.3f, verdict=%s", conflict.get("conflict_id", "?"), gap, verdict)

    return {
        "source_a_id": sid_a,
        "source_b_id": sid_b,
        "source_a_reliability": rel_a["reliability"],
        "source_b_reliability": rel_b["reliability"],
        "source_a_components": rel_a,
        "source_b_components": rel_b,
        "reliability_gap": gap,
        "verdict": verdict,
        "detail": f"Source A (Q={rel_a['quality_score']:.2f}, journal_weight={rel_a['journal_tier_weight']:.1f}, recency={rel_a['recency_bonus']:.2f}) vs Source B (Q={rel_b['quality_score']:.2f}, journal_weight={rel_b['journal_tier_weight']:.1f}, recency={rel_b['recency_bonus']:.2f})",
    }
