"""
context_builder.py — Tool 2: ConflictContextBuilder

为每个冲突构建上下文信息：来源元数据、材料一致性、
实验条件一致性、时间因素、字段关键性。
"""
from __future__ import annotations
import re
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

# ── V2.2: 通用实体提取正则 (从 config 加载, 此为基础 fallback) ──
_ENTITY_PATTERN = re.compile(r'([A-Z][a-z]?[-\d][\w-]{1,20})')

# V2.2: 测量方法关键词 (通用, 不限于材料科学)
_METHOD_PATTERNS: dict[str, re.Pattern] = {}


def _load_method_patterns():
    """从 config 加载领域特有的测量方法关键词。"""
    global _METHOD_PATTERNS
    if _METHOD_PATTERNS:
        return
    try:
        from configs import load_yaml
        config = load_yaml("quality_rules.yaml")
        methods_cfg = config.get("measurement_methods", {})
        for method_name, patterns in methods_cfg.items():
            if isinstance(patterns, list):
                combined = "|".join(patterns)
                _METHOD_PATTERNS[method_name] = re.compile(combined, re.IGNORECASE)
    except Exception:
        pass
    # 通用 fallback
    if not _METHOD_PATTERNS:
        _METHOD_PATTERNS.update({
            "test_method": re.compile(r'test|measurement|analysis|spectroscopy|diffraction|microscopy', re.IGNORECASE),
        })


def build_conflict_context(
    conflicts: list[dict],
    current_data: dict[str, Any],
    target_schema: dict[str, Any] | None,
) -> list[dict]:
    """
    为每个冲突附加上下文信息。

    Args:
        conflicts: 已提取的冲突列表 (含 conflict_id)
        current_data: data_state.current_data (sources + records)
        target_schema: context_state.target_schema

    Returns:
        附加了上下文的冲突列表
    """
    sources_list = current_data.get("sources", [])
    records_list = current_data.get("records", [])

    # 构建 source_id → source 元数据映射
    source_map: dict[str, dict] = {}
    for s in sources_list:
        source_map[s.get("source_id", "")] = s

    # 构建 source_id → records 映射
    source_records: dict[str, list[dict]] = {}
    for r in records_list:
        sid = r.get("source_id", "")
        source_records.setdefault(sid, []).append(r)

    # 字段关键性映射
    field_criticality: dict[str, str] = {}
    if target_schema:
        for f in target_schema.get("fields", []):
            field_criticality[f.get("name", "")] = f.get("criticality", "important")

    enriched = []
    for c in conflicts:
        sid_a = c.get("source_a", "")
        sid_b = c.get("source_b", "")
        fn = c.get("field_name", "")

        # 来源元数据
        src_a = source_map.get(sid_a, {})
        src_b = source_map.get(sid_b, {})

        # ── V1.1: 直接读 entity_type/entity_name (不再推断) ──
        def _extract_entities(source_id: str, source: dict) -> set[str]:
            entities: set[str] = set()
            for r in source_records.get(source_id, []):
                et = r.get("entity_type", "")
                en = r.get("entity_name", "")
                if en:
                    entities.add(f"{et}:{en}")
            # fallback: title 正则
            if not entities:
                title = source.get("title", "")
                for m in _ENTITY_PATTERN.findall(title):
                    s = (m[0] if isinstance(m, tuple) else m).strip().rstrip(".,;")
                    if len(s) >= 3:
                        entities.add(s)
            return entities

        ents_a = _extract_entities(sid_a, src_a)
        ents_b = _extract_entities(sid_b, src_b)

        same_material = True
        if ents_a and ents_b:
            same_material = bool(ents_a & ents_b)
        elif ents_a or ents_b:
            same_material = True  # 一方无法识别 → 保守

        # 实验条件提取
        def _extract_conditions(source_id: str) -> dict:
            conds: dict = {}
            for r in source_records.get(source_id, []):
                fn_lower = r.get("field_name", "").lower()
                if fn_lower in ("temperature", "temp", "t"):
                    conds["temperature"] = r.get("field_value")
                elif "strain_rate" in fn_lower or fn_lower == "strain rate":
                    conds["strain_rate"] = r.get("field_value")
            return conds

        cond_a = _extract_conditions(sid_a)
        cond_b = _extract_conditions(sid_b)

        same_condition = True
        if cond_a and cond_b:
            temp_a = cond_a.get("temperature")
            temp_b = cond_b.get("temperature")
            if temp_a is not None and temp_b is not None:
                try:
                    if abs(float(temp_a) - float(temp_b)) > 50:
                        same_condition = False
                except (ValueError, TypeError):
                    pass

        # 测量方法推断 (V2.2: 从 config 加载关键词)
        def _infer_method(source: dict) -> list[str]:
            _load_method_patterns()
            methods = []
            text = source.get("title", "") + " " + source.get("abstract", "")
            for method_name, pattern in _METHOD_PATTERNS.items():
                if pattern.search(text):
                    methods.append(method_name)
            return methods

        methods_a = _infer_method(src_a)
        methods_b = _infer_method(src_b)
        same_method = bool(set(methods_a) & set(methods_b)) if (methods_a or methods_b) else None

        # 时间因素
        year_a = src_a.get("year")
        year_b = src_b.get("year")
        temporal_gap = None
        if year_a is not None and year_b is not None:
            try:
                temporal_gap = abs(int(year_a) - int(year_b))
            except (ValueError, TypeError):
                pass

        # 值差距
        va = c.get("value_a") or c.get("mean_a")
        vb = c.get("value_b") or c.get("mean_b")
        value_gap_pct = None
        if va is not None and vb is not None:
            try:
                max_val = max(abs(float(va)), abs(float(vb)))
                if max_val > 0:
                    value_gap_pct = round(abs(float(va) - float(vb)) / max_val * 100, 1)
            except (ValueError, TypeError):
                pass

        enriched.append({
            **c,
            "context": {
                "source_a_meta": {
                    "title": src_a.get("title", ""),
                    "year": src_a.get("year"),
                    "journal": src_a.get("journal", ""),
                    "doi": src_a.get("doi", ""),
                },
                "source_b_meta": {
                    "title": src_b.get("title", ""),
                    "year": src_b.get("year"),
                    "journal": src_b.get("journal", ""),
                    "doi": src_b.get("doi", ""),
                },
                "same_material": same_material,
                "materials_a": sorted(ents_a),
                "materials_b": sorted(ents_b),
                "same_condition": same_condition,
                "conditions_a": cond_a,
                "conditions_b": cond_b,
                "same_measurement_method": same_method,
                "methods_a": methods_a,
                "methods_b": methods_b,
                "temporal_gap_years": temporal_gap,
                "value_gap_pct": value_gap_pct,
                "field_criticality": field_criticality.get(fn, "important"),
            },
        })

    logger.info("[ContextBuilder] Built context for %d conflicts", len(enriched))
    return enriched
