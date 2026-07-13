"""
contextual_evidence.py — Tool 7: ContextualEvidenceCollector

收集上下文证据：材料一致性、实验条件一致性、测量方法推断、时间因素。
(大部分工作在 ContextBuilder 已完成，此工具做专项汇总)
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)


def collect_contextual_evidence(
    conflict: dict[str, Any],
    current_data: dict[str, Any],
) -> dict[str, Any]:
    """
    收集和汇总上下文证据。

    Args:
        conflict: 带上下文的冲突
        current_data: data_state.current_data

    Returns:
        汇总的上下文证据
    """
    ctx = conflict.get("context", {})

    same_material = ctx.get("same_material", True)
    materials_a = ctx.get("materials_a", [])
    materials_b = ctx.get("materials_b", [])
    same_condition = ctx.get("same_condition", True)
    conds_a = ctx.get("conditions_a", {})
    conds_b = ctx.get("conditions_b", {})
    same_method = ctx.get("same_measurement_method")
    methods_a = ctx.get("methods_a", [])
    methods_b = ctx.get("methods_b", [])
    temporal_gap = ctx.get("temporal_gap_years")

    # 材料详情
    materials_note = ""
    if materials_a and materials_b:
        common = set(materials_a) & set(materials_b)
        if common:
            materials_note = f"Same material(s): {sorted(common)}"
        else:
            materials_note = f"Different materials: A={sorted(materials_a)}, B={sorted(materials_b)}"
    elif materials_a or materials_b:
        materials_note = "Insufficient material identification for comparison"

    # 条件详情
    conditions_note = ""
    if conds_a and conds_b:
        diffs = []
        for key in set(list(conds_a.keys()) + list(conds_b.keys())):
            va = conds_a.get(key)
            vb = conds_b.get(key)
            if va is not None and vb is not None and va != vb:
                diffs.append(f"{key}: {va} vs {vb}")
        if diffs:
            conditions_note = f"Different conditions: {', '.join(diffs)}"
        else:
            conditions_note = "Same experimental conditions"
    elif conds_a or conds_b:
        conditions_note = "Condition data only available for one source"

    # 方法详情
    methods_note = ""
    if same_method is True:
        common_m = set(methods_a) & set(methods_b)
        methods_note = f"Same measurement method: {sorted(common_m)}"
    elif same_method is False:
        methods_note = f"Different methods: A={methods_a}, B={methods_b}"
    elif same_method is None:
        methods_note = "Unable to determine measurement methods from metadata"

    # 时间因素
    temporal_note = ""
    if temporal_gap is not None:
        if temporal_gap <= 2:
            temporal_note = f"Contemporary ({temporal_gap}yr gap — no significant temporal factor)"
        elif temporal_gap <= 10:
            temporal_note = f"Some temporal gap ({temporal_gap}yr — minor technique evolution possible)"
        else:
            temporal_note = f"Large temporal gap ({temporal_gap}yr — measurement techniques may have evolved significantly)"

    # 额外备注
    additional_notes = []
    if ctx.get("value_gap_pct") is not None:
        additional_notes.append(f"Value gap: {ctx['value_gap_pct']}%")
    fn = conflict.get("field_name", "")
    if ctx.get("field_criticality") == "critical":
        additional_notes.append(f"Field '{fn}' is critical — higher scrutiny required")

    logger.info("[ContextualEvidence] %s: same_material=%s, same_condition=%s, same_method=%s",
                conflict.get("conflict_id", "?"), same_material, same_condition, same_method)

    return {
        "same_material": same_material,
        "materials_detail": materials_note,
        "same_condition": same_condition,
        "conditions_detail": conditions_note,
        "same_measurement_method": same_method,
        "method_detail": methods_note,
        "temporal_gap_years": temporal_gap,
        "temporal_note": temporal_note,
        "additional_notes": additional_notes,
    }
