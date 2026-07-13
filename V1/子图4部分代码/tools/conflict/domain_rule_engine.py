"""
domain_rule_engine.py — Tool 5: DomainRuleEngine

匹配领域决策规则，提供裁决指导。
规则从 quality_rules.yaml 或内置默认规则加载。
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

# 内置领域规则 (fallback, 当 quality_rules.yaml 未配置时)
_DEFAULT_RULES: dict[str, list[dict]] = {
    "materials_science": [
        {
            "name": "mechanical_stress_priority",
            "conditions": {"semantic_type": "mechanical_stress", "same_material": True},
            "guidance": "prioritize_higher_reliability",
            "note": "Mechanical properties (yield/tensile/strength) should use the most reliable source. Prefer higher-tier journal and more recent publication.",
        },
        {
            "name": "elongation_variability",
            "conditions": {"semantic_type": "elongation"},
            "guidance": "retain_range",
            "note": "Elongation inherently variable (±20% within same batch per ASTM E8). Retain value range and annotate as natural variability.",
        },
        {
            "name": "hardness_indenter_check",
            "conditions": {"semantic_type": "hardness"},
            "guidance": "check_indenter_type",
            "note": "HV ≠ HRC ≠ HB — different hardness scales may not be a real conflict. Verify indenter type before flagging.",
        },
        {
            "name": "temperature_condition",
            "conditions": {"semantic_type": "temperature"},
            "guidance": "retain_both_condition_note",
            "note": "Temperature is often an experimental condition, not a material property. Different values likely reflect different test conditions.",
        },
        {
            "name": "strain_rate_condition",
            "conditions": {"semantic_type": "strain_rate"},
            "guidance": "retain_both_condition_note",
            "note": "Strain rate is an experimental parameter. Different rates are not conflicts but different test conditions.",
        },
        {
            "name": "fatigue_life_variability",
            "conditions": {"semantic_type": "fatigue_life"},
            "guidance": "retain_range",
            "note": "Fatigue life has inherent scatter (log-normal distribution). Order-of-magnitude variation is normal.",
        },
        {
            "name": "density_consistency",
            "conditions": {"semantic_type": "density"},
            "guidance": "prioritize_higher_reliability",
            "note": "Density is a well-defined property. Significant differences (>5%) likely indicate measurement error or different materials.",
        },
    ],
    "astrophysics": [
        {
            "name": "redshift_measurement",
            "conditions": {"semantic_type": "redshift"},
            "guidance": "compute_weighted_avg",
            "note": "Redshift measurements from different instruments should be weighted-averaged if both are reliable.",
        },
        {
            "name": "luminosity_distance",
            "conditions": {"semantic_type": "luminosity"},
            "guidance": "retain_both_condition_note",
            "note": "Luminosity can vary with wavelength band. Verify both measurements use same band/filter.",
        },
        {
            "name": "parallax_precision",
            "conditions": {"semantic_type": "parallax"},
            "guidance": "prioritize_higher_reliability",
            "note": "Gaia DR3 parallax generally more precise than Hipparcos. Prefer more recent/higher-precision instrument.",
        },
    ],
    "default": [
        {
            "name": "default_statistical_priority",
            "conditions": {},
            "guidance": "default_evidence_weighting",
            "note": "No domain-specific rules matched. Use statistical evidence + source reliability to decide.",
        },
    ],
}


def match_domain_rules(
    conflict: dict[str, Any],
    semantic_types: dict[str, Any] | None,
    research_domain: str,
) -> dict[str, Any]:
    """
    匹配领域规则 (V2.2: 无匹配时自动从语义类型推断通用策略)。

    Args:
        conflict: 带上下文的冲突
        semantic_types: profile.semantic_types
        research_domain: "materials_science" | "astrophysics" | ...

    Returns:
        {matched_rules, has_domain_guidance, suggested_strategy}
    """
    fn = conflict.get("field_name", "")
    ctx = conflict.get("context", {})
    same_material = ctx.get("same_material", True)
    same_condition = ctx.get("same_condition", True)
    cohens_d = conflict.get("cohens_d", 0)

    # 获取语义类型
    semantic_info = {}
    if semantic_types:
        semantic_info = semantic_types.get(fn, {})
    inferred_st = semantic_info.get("semantic_type", "") if isinstance(semantic_info, dict) else ""

    rules = _DEFAULT_RULES.get(research_domain, _DEFAULT_RULES["default"])
    matched = []

    for rule in rules:
        conds = rule.get("conditions", {})
        all_match = True
        for ck, cv in conds.items():
            if ck == "semantic_type":
                if inferred_st != cv:
                    all_match = False
                    break
            elif ck == "same_material":
                if same_material != cv:
                    all_match = False
                    break
            elif ck == "same_condition":
                if same_condition != cv:
                    all_match = False
                    break
        if all_match:
            matched.append(rule)

    has_guidance = len(matched) > 0

    # ── V2.2: 无领域规则时的通用推断 ──
    if not has_guidance:
        generic_rule = _infer_generic_rule(inferred_st, same_material, same_condition, cohens_d)
        if generic_rule:
            matched.append(generic_rule)
            has_guidance = True

    # 规则 → 策略映射
    strategy_map = {
        "prioritize_higher_reliability": "prefer_source_a" if conflict.get("_prefer_a", True) else "prefer_source_b",
        "retain_range": "retain_range",
        "retain_both_condition_note": "retain_both",
        "check_indenter_type": "escalate_to_human",
        "compute_weighted_avg": "compute_weighted_avg",
        "default_evidence_weighting": None,
    }

    suggested = None
    if matched:
        suggested = strategy_map.get(matched[0]["guidance"])

    logger.info("[DomainRuleEngine] %s: domain=%s, matched=%d rules, suggested=%s",
                conflict.get("conflict_id", "?"), research_domain, len(matched), suggested)

    return {
        "matched_rules": [{"rule_name": r["name"], "guidance": r["guidance"], "note": r["note"]} for r in matched],
        "has_domain_guidance": has_guidance,
        "suggested_strategy": suggested,
    }


# ── V2.2: 通用规则推断 ──
# 条件类字段 → 倾向于 retain_both (不同条件自然有不同值)
_GENERIC_CONDITION_TYPES = {"temperature", "strain_rate", "pressure", "humidity",
                              "exposure_time", "wavelength", "resolution",
                              "magnetic_field", "electric_field", "ph"}
# 高变异字段 → 倾向于 retain_range
_GENERIC_VARIABLE_TYPES = {"elongation", "fatigue_life", "error", "uncertainty",
                            "flux", "count", "rate", "variability"}


def _infer_generic_rule(
    semantic_type: str,
    same_material: bool,
    same_condition: bool,
    cohens_d: float,
) -> dict | None:
    """从语义类型自动推断通用冲突处理策略。"""
    if not semantic_type:
        return None

    # 条件类 → retain_both
    if semantic_type in _GENERIC_CONDITION_TYPES:
        return {
            "name": "generic_condition_field",
            "conditions": {"semantic_type": semantic_type},
            "guidance": "retain_both_condition_note",
            "note": f"'{semantic_type}' is typically a condition/parameter, not a conflict. Retain both with annotations.",
        }

    # 高变异类 → retain_range
    if semantic_type in _GENERIC_VARIABLE_TYPES:
        return {
            "name": "generic_variable_field",
            "conditions": {"semantic_type": semantic_type},
            "guidance": "retain_range",
            "note": f"'{semantic_type}' has inherent variability. Retain value range and annotate as natural variation.",
        }

    # 小效应量 → compute_weighted_avg
    if cohens_d < 0.5:
        return {
            "name": "generic_small_effect",
            "conditions": {},
            "guidance": "compute_weighted_avg",
            "note": f"Cohen's d={cohens_d:.2f} — small effect, weighted average is appropriate.",
        }

    # 大效应量 + 不同条件/材料 → retain_both
    if cohens_d >= 0.8 and not same_condition:
        return {
            "name": "generic_different_conditions",
            "conditions": {},
            "guidance": "retain_both_condition_note",
            "note": "Large effect but different conditions — likely not a real conflict.",
        }

    # 大效应量 + 相同条件 → prefer higher reliability
    if cohens_d >= 0.8:
        return {
            "name": "generic_large_effect_same_condition",
            "conditions": {},
            "guidance": "prioritize_higher_reliability",
            "note": f"Cohen's d={cohens_d:.2f} — large effect, same conditions. Prefer more reliable source.",
        }

    # 默认: 靠统计学+可靠性判断
    return {
        "name": "generic_default",
        "conditions": {},
        "guidance": "default_evidence_weighting",
        "note": "No specific rule matched. Use statistical evidence + source reliability to decide.",
    }
