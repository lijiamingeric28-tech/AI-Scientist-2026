"""
adaptive_threshold.py

AdaptiveThresholdEngine — 自适应阈值引擎 (V2.0 A1)

根据三个维度动态调整质量阈值:
  1. Field Criticality: 关键字段 vs 辅助字段
  2. Sample Size: 小样本更宽松, 大样本更严格
  3. Domain Tightness: 精确定量科学 vs 探索性科学
"""

from __future__ import annotations

from typing import Any

from subgraphs.quality.configs import load_yaml
from subgraphs.quality.utils.logger import get_logger

logger = get_logger(__name__)


class AdaptiveThresholdEngine:
    """自适应阈值引擎。"""

    def __init__(self, config: dict[str, Any] | None = None):
        rules = config or load_yaml("quality_rules.yaml")
        self._cfg = rules.get("adaptive_thresholds", {})
        self._enabled = self._cfg.get("enabled", True)
        self._domain = "default"

    def set_domain(self, research_domain: str):
        """设置当前研究领域 (如 'materials_science', 'astrophysics')。"""
        self._domain = research_domain

    def get_completeness_threshold(
        self,
        field_name: str,
        sample_size: int,
        field_criticality: str = "",
    ) -> float:
        """
        计算自适应 completeness 阈值 (V2.2: 支持 target_schema criticality fallback)。

        公式: threshold = base × criticality_factor × sample_factor × domain_factor

        Returns:
            调整后的阈值 (0-1)
        """
        if not self._enabled:
            return 0.90

        # ── base: 根据字段关键性 (V2.2: 三重 fallback) ──
        critical_fields = self._cfg.get("field_criticality", {}).get("critical_fields", [])
        auxiliary_fields = self._cfg.get("field_criticality", {}).get("auxiliary_fields", [])

        if field_name and field_name in critical_fields:
            base = self._cfg.get("field_criticality", {}).get("critical_completeness", 0.95)
        elif field_name and field_name in auxiliary_fields:
            base = self._cfg.get("field_criticality", {}).get("auxiliary_completeness", 0.70)
        elif field_criticality == "critical":
            base = self._cfg.get("field_criticality", {}).get("critical_completeness", 0.95)
        elif field_criticality == "auxiliary":
            base = self._cfg.get("field_criticality", {}).get("auxiliary_completeness", 0.70)
        elif field_criticality == "important":
            base = 0.85
        else:
            base = 0.90

        # ── sample_factor: 样本量调节 ──
        small_n = self._cfg.get("sample_size", {}).get("small_n", 10)
        large_n = self._cfg.get("sample_size", {}).get("large_n", 100)
        small_mult = self._cfg.get("sample_size", {}).get("small_n_multiplier", 1.3)
        large_mult = self._cfg.get("sample_size", {}).get("large_n_multiplier", 0.8)

        # 小样本 → 更宽松 (阈值更低), 大样本 → 标准
        if sample_size < small_n:
            sample_factor = small_mult
        elif sample_size > large_n:
            sample_factor = large_mult
        else:
            sample_factor = small_mult + (large_mult - small_mult) * (sample_size - small_n) / (large_n - small_n)

        # ── domain_factor: 领域调节 ──
        tightness = self._cfg.get("domain_tightness", {}).get(self._domain, "normal")
        multipliers = self._cfg.get("domain_tightness", {})
        domain_factor = multipliers.get(f"{tightness}_multiplier", 1.0)

        threshold = base * sample_factor * domain_factor
        threshold = max(0.30, min(0.99, threshold))
        return round(threshold, 4)

    def get_conflict_threshold(
        self,
        field_name: str,
        sample_size: int,
    ) -> float:
        if not self._enabled:
            return 0.20

        critical_fields = self._cfg.get("field_criticality", {}).get("critical_fields", [])
        if field_name in critical_fields:
            base = self._cfg.get("field_criticality", {}).get("critical_conflict", 0.10)
        else:
            base = 0.20

        small_n = self._cfg.get("sample_size", {}).get("small_n", 10)
        large_n = self._cfg.get("sample_size", {}).get("large_n", 100)
        small_mult = self._cfg.get("sample_size", {}).get("small_n_multiplier", 0.85)
        large_mult = self._cfg.get("sample_size", {}).get("large_n_multiplier", 1.0)

        if sample_size < small_n:
            sample_factor = small_mult
        elif sample_size > large_n:
            sample_factor = large_mult
        else:
            sample_factor = small_mult + (large_mult - small_mult) * (sample_size - small_n) / (large_n - small_n)

        threshold = base * sample_factor
        threshold = max(0.05, min(0.50, threshold))
        return round(threshold, 4)


# 全局单例
_engine: AdaptiveThresholdEngine | None = None


def get_adaptive_engine(config: dict[str, Any] | None = None) -> AdaptiveThresholdEngine:
    global _engine
    if _engine is None:
        _engine = AdaptiveThresholdEngine(config)
    return _engine
