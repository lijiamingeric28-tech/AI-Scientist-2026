"""
conflict_detector.py

Stage 2e：Conflict Risk Assessment — 识别潜在的数据冲突风险，
判断是否需要进入 Conflict Resolution Agent 进行进一步分析。

V1.1: 加入同一实体/材料/条件约束，避免误判不同实验条件的数据为冲突。
  - 只有同一材料的同一字段才做跨来源比较
  - temperature/strain_rate 等条件字段用绝对阈值而非相对阈值
"""

from __future__ import annotations

import re
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)

# 默认数值差异阈值（相对差异）
_DEFAULT_THRESHOLD = 0.20

# 条件类字段（不同实验可能有不同值，不是冲突而是不同条件）
_CONDITION_FIELDS = {"temperature", "strain_rate", "temp", "T", "strain rate"}
# 条件字段的绝对差异阈值
_CONDITION_ABS_THRESHOLD = 50.0   # temperature 差 50°C 以上=不同条件,不是冲突

# 材料/实体提取正则
_MATERIAL_PATTERNS = [
    re.compile(r"(Al-\d+|Ti-\d+|Mg-\w+|Cu-\w+|NiTi|Inconel\s*\w*|Stainless\s*\w*|Hastelloy\s*\w*|CoCrMo|Zr-\w+|Fe-\w+|Invar\s*\w*|Monel\s*\w*|Haynes\s*\w*|AlBeMet\s*\w*|WC-Co)", re.IGNORECASE),
    re.compile(r"(\d+\w+\s+(Aluminum|Stainless|Steel|Alloy|Magnesium|Titanium|Copper|Superalloy|Composite))", re.IGNORECASE),
]


def _extract_entities_from_text(text: str) -> set[str]:
    """从文本中提取实体名称（材料/天体/化合物等）。优先用标题正则，已泛化。"""
    entities: set[str] = set()
    # 通用模式：大写字母+数字组合 (Al-7075, SN1987A, Fe2O3)
    import re as _re
    generic_pat = _re.compile(r'([A-Z][a-z]?[-\d][\w-]{1,20})')
    for m in generic_pat.findall(text or ""):
        s = m.strip().rstrip(".,;")
        if len(s) >= 3:
            entities.add(s)
    # 材料专用正则 (fallback)
    for pat in _MATERIAL_PATTERNS:
        for m in pat.findall(text or ""):
            entities.add(m[0] if isinstance(m, tuple) else m)
    return entities


def _get_source_entities(
    data: dict[str, Any],
    clarified_intent: dict[str, Any] | None = None,
) -> dict[str, set[str]]:
    """
    构建 source_id → 实体名称集合 的映射。

    优先级:
      1. clarified_intent.entities (用户指定目标实体)
      2. records 中的 material/sample/entity 字段值
      3. 来源标题文本提取 (fallback)
    """
    source_entities: dict[str, set[str]] = {}

    # 预先从 clarified_intent 获取全局实体列表
    global_entities: set[str] = set()
    if clarified_intent:
        global_entities.update(clarified_intent.get("entities", []))

    # 从 records 中提取实体字段值（按 source_id 分组）
    for rec in data.get("records", []):
        sid = rec.get("source_id", "")
        if sid not in source_entities:
            source_entities[sid] = set()
        fn = rec.get("field_name", "").lower()
        fv = str(rec.get("field_value", ""))
        # 识别实体类字段
        if fn in ("material", "sample", "entity", "specimen", "alloy", "compound",
                  "composition", "target", "object"):
            source_entities[sid].add(fv)

    # 从标题提取 (fallback)
    for src in data.get("sources", []):
        sid = src.get("source_id", "")
        if sid not in source_entities:
            source_entities[sid] = set()
        title = src.get("title", "")
        title_entities = _extract_entities_from_text(title)
        source_entities[sid].update(title_entities)

    # 合并全局实体到所有来源
    if global_entities:
        for sid in source_entities:
            source_entities[sid].update(global_entities)

    return source_entities


def _share_material(mat_a: set[str], mat_b: set[str]) -> bool:
    """判断两个来源是否研究同一类材料。都为空则视为可能相同（不确定时保守处理）。"""
    if not mat_a and not mat_b:
        return True   # 无法判断 → 保守: 仍检测冲突
    if not mat_a or not mat_b:
        return True   # 一方无法识别 → 保守: 仍检测
    return bool(mat_a & mat_b)


def detect_conflicts(
    data: dict[str, Any],
    threshold: float = _DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """
    检测数据中的潜在冲突。

    冲突检测维度（V1.1 优化）:
    1. 同一 field_name + 同一材料/实体 + 不同 source 的数值差异
    2. 条件类字段 (temperature/strain_rate) 用绝对阈值
    3. 同一 field_name 下的类型不一致

    Args:
        data: grounded_data JSON。
        threshold: 数值差异阈值（相对差异）。

    Returns:
        冲突检测结果字典。
    """
    logger.info("开始冲突检测 (带材料/条件约束)...")

    records = data.get("records", [])
    if not records:
        return {
            "has_conflicts": False, "conflict_count": 0,
            "conflicts": [], "risk_level": "none",
            "summary": "无数据记录，无冲突风险。",
        }

    # 构建来源→实体映射 (优先 clarified_intent.entities + record字段, 标题正则 fallback)
    clarified_intent = data.get("_clarified_intent")  # 可选：由调用方注入
    source_entities = _get_source_entities(data, clarified_intent)

    conflicts: list[dict] = []
    skipped_different_material = 0
    skipped_condition_field = 0

    # ── 1. 跨来源数值冲突（带实体约束） ──
    field_groups: dict[str, list[dict]] = {}
    for rec in records:
        field_name = rec.get("field_name", "unknown")
        value = rec.get("field_value")
        if not isinstance(value, (int, float)):
            continue
        field_groups.setdefault(field_name, []).append(rec)

    for field_name, group in field_groups.items():
        if len(group) < 2:
            continue

        is_condition = field_name.lower() in _CONDITION_FIELDS or any(
            k in field_name.lower() for k in ("temperature", "strain_rate", "temp", "strain rate"))

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                ri, rj = group[i], group[j]

                # 同一来源内部不视为冲突
                if ri.get("source_id") == rj.get("source_id"):
                    continue

                # ── 材料/实体约束 ──
                mat_a = source_entities.get(ri.get("source_id", ""), set())
                mat_b = source_entities.get(rj.get("source_id", ""), set())
                if not _share_material(mat_a, mat_b):
                    skipped_different_material += 1
                    logger.debug("跳过: %s 字段, 不同材料 %s vs %s",
                                field_name, mat_a, mat_b)
                    continue

                vi, vj = ri["field_value"], rj["field_value"]
                try:
                    vi_f, vj_f = float(vi), float(vj)
                except (ValueError, TypeError):
                    continue

                if vi_f == 0 and vj_f == 0:
                    continue

                max_val = max(abs(vi_f), abs(vj_f))
                if max_val == 0:
                    continue

                rel_diff = abs(vi_f - vj_f) / max_val
                abs_diff = abs(vi_f - vj_f)

                # ── 条件字段: 绝对阈值 >50才视为冲突 ──
                if is_condition and abs_diff <= _CONDITION_ABS_THRESHOLD:
                    skipped_condition_field += 1
                    logger.debug("跳过: %s 字段, 绝对差异 %.1f <= %.1f (可能是不同实验条件)",
                                field_name, abs_diff, _CONDITION_ABS_THRESHOLD)
                    continue

                if rel_diff > threshold:
                    conflicts.append({
                        "type": "cross_source_value_conflict",
                        "field_name": field_name,
                        "record_a": ri.get("record_id"),
                        "record_b": rj.get("record_id"),
                        "source_a": ri.get("source_id"),
                        "source_b": rj.get("source_id"),
                        "value_a": vi_f,
                        "value_b": vj_f,
                        "relative_difference": round(rel_diff, 4),
                        "absolute_difference": round(abs_diff, 2),
                        "threshold": threshold,
                        "materials_a": sorted(mat_a),
                        "materials_b": sorted(mat_b),
                        "is_condition_field": is_condition,
                    })

    # ── 2. 类型冲突 ──
    field_types: dict[str, set[type]] = {}
    for rec in records:
        fn = rec.get("field_name", "unknown")
        field_types.setdefault(fn, set()).add(type(rec.get("field_value")))

    for fn, types in field_types.items():
        if len(types) > 1:
            conflicts.append({
                "type": "type_conflict",
                "field_name": fn,
                "types": [t.__name__ for t in types],
            })

    # ── 3. 判定风险等级 ──
    conflict_count = len(conflicts)
    if conflict_count == 0:
        risk_level = "none"
    elif conflict_count <= 2:
        risk_level = "low"
    elif conflict_count <= 5:
        risk_level = "medium"
    else:
        risk_level = "high"

    summary_parts = []
    if conflicts:
        summary_parts.append(f"检测到 {conflict_count} 个潜在冲突，风险等级: {risk_level}")
    else:
        summary_parts.append("未检测到冲突风险")
    if skipped_different_material:
        summary_parts.append(f"跳过 {skipped_different_material} 对不同材料比较")
    if skipped_condition_field:
        summary_parts.append(f"跳过 {skipped_condition_field} 对条件字段比较")

    result = {
        "has_conflicts": conflict_count > 0,
        "conflict_count": conflict_count,
        "conflicts": conflicts,
        "risk_level": risk_level,
        "skipped_different_material": skipped_different_material,
        "skipped_condition_field": skipped_condition_field,
        "summary": "。".join(summary_parts) + "。",
    }

    logger.info("冲突检测完成: %d 个冲突, 风险=%s, 跳过材料=%d, 跳过条件=%d",
                conflict_count, risk_level, skipped_different_material, skipped_condition_field)
    return result
