"""
domain_rule_engine.py — Tool 5: DomainRuleEngine (V3.0)

V3.0 修改: 领域规则从"冲突裁决策略"改为"差异原因推断辅助"。
  规则来源: quality_rules.yaml (优先) → 内置 domain-level 规则 (fallback)。

天文领域规则 (domain-level, 不绑定具体实体类型):
  - 不同观测频段/波段 → 预期 condition_variance (不是冲突)
  - 不同测量方法 (spectroscopy vs photometry) → 预期 methodological_variance
  - 时间跨度 > 5 年 → 预期 temporal_variation
  - 已知仪器间系统偏差 (Gaia vs Hipparcos 等)
"""
from __future__ import annotations
from typing import Any
from ...utils.logger import get_logger
logger = get_logger(__name__)


# ── V3.0: 领域级差异规则 (不绑定实体类型, 从 semantic_type + field 特征推断) ──
_DEFAULT_RULES: dict[str, list[dict]] = {
    "astrophysics": [
        {
            "name": "band_dependent_flux",
            "conditions": {"field_category": "flux_measurement"},
            "expected_cause": "condition_variance",
            "note": "Flux/ luminosity measurements are wavelength-dependent. Different bands → expected difference.",
        },
        {
            "name": "method_dependent_redshift",
            "conditions": {"field_category": "distance_measurement"},
            "expected_cause": "methodological_variance",
            "note": "Distance/redshift measurements depend on method (spectroscopic vs photometric, parallax vs Cepheid).",
        },
        {
            "name": "time_domain_variability",
            "conditions": {"field_category": "time_domain_property"},
            "expected_cause": "temporal_variation",
            "note": "Time-domain properties (DM, period, flux) naturally vary between epochs. Not a conflict.",
        },
        {
            "name": "instrument_systematic_offset",
            "conditions": {"field_category": "astrometric_measurement"},
            "expected_cause": "methodological_variance",
            "note": "Astrometric measurements from different instruments have known systematic offsets (Gaia/Hipparcos/VLBI).",
        },
        {
            "name": "temperature_method_gap",
            "conditions": {"field_category": "stellar_parameter"},
            "expected_cause": "methodological_variance",
            "note": "Stellar parameters (Teff, log g, [Fe/H]) vary by method: spectroscopy vs photometry vs SED fitting.",
        },
    ],
    "materials_science": [
        {
            "name": "test_condition_variance",
            "conditions": {"field_category": "experimental_condition"},
            "expected_cause": "condition_variance",
            "note": "Temperature, strain rate, pressure are experimental conditions — different values are expected.",
        },
        {
            "name": "mechanical_property_variability",
            "conditions": {"field_category": "mechanical_property"},
            "expected_cause": "measurement_uncertainty",
            "note": "Mechanical properties have inherent variability (±5-15%) across samples and labs.",
        },
    ],
    "default": [
        {
            "name": "default_multi_source_preserve",
            "conditions": {},
            "expected_cause": None,
            "note": "No domain-specific rules matched. All multi-source values preserved with annotations.",
        },
    ],
}


# ── V3.0: field_category 推断 (从 field_name + semantic_type, 不绑定实体类型) ──
_FIELD_CATEGORY_PATTERNS: dict[str, list[str]] = {
    # 注: dict 按插入顺序匹配, 更具体的 pattern 放在前面
    "stellar_parameter": [
        "effective_temperature", "surface_gravity", "metallicity",
        "stellar_mass", "stellar_radius", "spectral_type", "teff", "log_g",
    ],
    "distance_measurement": [
        "redshift", "distance", "parallax", "distance_modulus",
        "luminosity_distance", "angular_diameter_distance",
    ],
    "time_domain_property": [
        "dispersion_measure", "period", "period_derivative", "pulse_width",
        "burst_rate", "scattering_time", "rotation_measure", "dm",
    ],
    "astrometric_measurement": [
        "right_ascension", "declination", "proper_motion",
        "pm_ra", "pm_dec",
    ],
    "flux_measurement": [
        "flux", "flux_density", "luminosity", "magnitude", "brightness",
        "radio_flux", "xray_flux", "apparent_magnitude", "absolute_magnitude",
    ],
    "experimental_condition": [
        "temperature", "strain_rate", "pressure", "humidity",
        "exposure_time", "frequency", "wavelength",
    ],
    "mechanical_property": [
        "yield_strength", "tensile_strength", "elongation", "hardness",
        "fatigue_life", "fracture_toughness", "elastic_modulus",
    ],
}


def _infer_field_category(field_name: str, semantic_type: str) -> str | None:
    """从 field_name 和 semantic_type 推断字段类别 (泛化, 不绑定实体类型)。"""
    fn_lower = field_name.lower().replace(" ", "_").replace("-", "_")
    for category, patterns in _FIELD_CATEGORY_PATTERNS.items():
        for pat in patterns:
            if pat in fn_lower:
                return category
    # semantic_type 回退
    st_lower = (semantic_type or "").lower()
    if st_lower:  # 只对非空语义类型做回退推断
        for category in _FIELD_CATEGORY_PATTERNS:
            if category.replace("_", " ") in st_lower or st_lower in category.replace("_", " "):
                return category
    return None


def match_domain_rules(
    variance: dict[str, Any],
    semantic_types: dict[str, Any] | None,
    research_domain: str,
) -> dict[str, Any]:
    """
    V3.0: 匹配领域差异规则 — 辅助推断差异原因。

    从 field_name + semantic_type 推断 field_category,
    然后匹配 domain-level 规则 (不绑定实体类型)。

    Args:
        variance: 方差条目
        semantic_types: profile.semantic_types (可选)
        research_domain: "astrophysics" | "materials_science" | ...

    Returns:
        {matched_rules, has_domain_guidance, suggested_cause, confidence_boost}
    """
    field_name = variance.get("field_name", "")
    semantic_info = {}
    if semantic_types:
        semantic_info = semantic_types.get(field_name, {})
    semantic_type = semantic_info.get("semantic_type", "") if isinstance(semantic_info, dict) else ""

    # 推断 field_category
    field_category = _infer_field_category(field_name, semantic_type)

    rules = _DEFAULT_RULES.get(research_domain, _DEFAULT_RULES["default"])
    matched = []

    for rule in rules:
        conds = rule.get("conditions", {})
        required_category = conds.get("field_category")
        if required_category and field_category == required_category:
            matched.append(rule)
        elif not required_category:
            matched.append(rule)

    has_guidance = len(matched) > 0
    suggested_cause = matched[0].get("expected_cause") if matched else None
    confidence_boost = 0.05 if has_guidance else 0.0

    logger.info("[DomainRuleEngine V3.0] %s: domain=%s, category=%s, matched=%d, cause=%s",
                field_name, research_domain, field_category, len(matched), suggested_cause)

    return {
        "matched_rules": [
            {"rule_name": r["name"], "expected_cause": r.get("expected_cause"),
             "note": r["note"]}
            for r in matched
        ],
        "has_domain_guidance": has_guidance,
        "suggested_cause": suggested_cause,
        "confidence_boost": round(min(confidence_boost, 0.15), 3),
    }
