"""unit_converter.py — Tool 3: Unit Conversion

V2.1 修复: 转换因子以 (category, from_unit) 为键, 避免同名单位被覆盖。
例如 GPa 在 strength 中 ×1000→MPa, 在 hardness 中查表转换, 不再混淆。
"""
from typing import Any
from configs import load_yaml
from utils.logger import get_logger
logger = get_logger(__name__)

# 语义类型 → category 映射 (用于推断字段属于哪个单位类别)
# V2.2: 从配置中动态加载, 此表仅作 fallback
_SEMANTIC_TO_CATEGORY: dict[str, str] = {}

def _load_semantic_category_map():
    """从 schema_mapping.yaml 动态加载 semantic_type → unit_category 映射。"""
    global _SEMANTIC_TO_CATEGORY
    if _SEMANTIC_TO_CATEGORY:
        return
    try:
        config = load_yaml("schema_mapping.yaml")
        # 从 unit_conversions 的 key (category 名) 反向推断
        unit_conv = config.get("unit_conversions", {})
        # 从 semantic_types 推断映射
        semantic_cfg = config.get("semantic_types", {})
        for st_name, st_info in semantic_cfg.items():
            cat = st_info.get("unit_category", "")
            if cat:
                _SEMANTIC_TO_CATEGORY[st_name] = cat
        # 内置 fallback: 通用物理量 → category 映射
        _SEMANTIC_TO_CATEGORY.setdefault("mechanical_stress", "strength")
        _SEMANTIC_TO_CATEGORY.setdefault("hardness", "hardness")
        _SEMANTIC_TO_CATEGORY.setdefault("density", "density")
        _SEMANTIC_TO_CATEGORY.setdefault("temperature", "temperature")
        _SEMANTIC_TO_CATEGORY.setdefault("elongation", "percentage")
        _SEMANTIC_TO_CATEGORY.setdefault("strain", "percentage")
        _SEMANTIC_TO_CATEGORY.setdefault("strain_rate", "strain_rate")
        _SEMANTIC_TO_CATEGORY.setdefault("thermal_conductivity", "thermal_conductivity")
        _SEMANTIC_TO_CATEGORY.setdefault("fatigue_life", "fatigue_life")
        _SEMANTIC_TO_CATEGORY.setdefault("fracture_toughness", "fracture_toughness")
        _SEMANTIC_TO_CATEGORY.setdefault("elastic_modulus", "modulus")
        _SEMANTIC_TO_CATEGORY.setdefault("grain_size", "grain_size")
        # 天体物理 fallback
        _SEMANTIC_TO_CATEGORY.setdefault("redshift", "redshift")
        _SEMANTIC_TO_CATEGORY.setdefault("luminosity", "luminosity")
        _SEMANTIC_TO_CATEGORY.setdefault("parallax", "parallax")
    except Exception:
        pass


def convert_units(records: list[dict], unit_conversions: list[dict] | None = None,
                  standard_units: dict[str, str] | None = None,
                  semantic_types: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一单位转换 (V2.2: category-keyed conversions + dynamic semantic map)。"""
    _load_semantic_category_map()
    config = load_yaml("schema_mapping.yaml")
    rules = config.get("unit_conversions", {})

    # 构建 (category, from_unit) → factor 映射表
    # 同时保留 unit→category 的反向查找
    cat_map: dict[tuple, dict] = {}
    unit_categories: dict[str, list[str]] = {}  # unit → [category names]
    for cat, cv in rules.items():
        for unit, factor in cv.items():
            key = (cat, unit)
            cat_map[key] = {"category": cat, "factor": factor}
            unit_categories.setdefault(unit, []).append(cat)

    # 标准单位
    std_units = dict(standard_units or {})
    for f in config.get("target_schema", {}).get("fields", []):
        n, u = f.get("name"), f.get("standard_unit")
        if n and u:
            std_units[n] = u

    # 用户指定的目标单位
    conv_map: dict[str, str] = {}
    if unit_conversions:
        for uc in unit_conversions:
            if isinstance(uc, dict) and uc.get("field"):
                conv_map[uc["field"]] = uc.get("to", std_units.get(uc["field"], ""))

    # 构建 field_name → semantic_type → category
    field_semantic: dict[str, str] = {}
    if semantic_types:
        for fn, st_info in semantic_types.items():
            if isinstance(st_info, dict):
                st = st_info.get("semantic_type", "")
            else:
                st = str(st_info)
            field_semantic[fn] = st

    log, unconv = [], []
    for rec in records:
        fn = rec.get("field_name", "")
        val = rec.get("field_value")
        unit = rec.get("field_unit")
        target = conv_map.get(fn) or std_units.get(fn)

        if not target or not unit or unit == target or not isinstance(val, (int, float)):
            continue

        # ── V2.1: 用 (category, unit) 查找转换因子 ──
        # Step 1: 推断该字段属于哪个 category
        st = field_semantic.get(fn, "")
        inferred_cat = _SEMANTIC_TO_CATEGORY.get(st, "")

        # Step 2: 在 category 对应的规则中查找
        candidates = unit_categories.get(unit, [])
        factor = None
        matched_cat = None

        if inferred_cat and inferred_cat in candidates:
            # 优先使用推断的 category
            rule = cat_map.get((inferred_cat, unit))
            if rule:
                factor = rule["factor"]
                matched_cat = inferred_cat

        if factor is None:
            # Fallback: 遍历所有 category, 取第一个匹配的
            for cat in candidates:
                rule = cat_map.get((cat, unit))
                if rule:
                    factor = rule["factor"]
                    matched_cat = cat
                    break

        if factor is None:
            unconv.append({
                "record_id": rec.get("record_id"), "field": fn,
                "reason": f"no conversion rule for unit '{unit}' in categories {candidates}",
            })
            continue

        # ── V2.1: 量纲校验 ──
        # 不同 category 的同名单位 (如 GPa 在 strength vs hardness) 需不同处理
        if inferred_cat and matched_cat and inferred_cat != matched_cat:
            logger.warning(
                "[UnitConv] %s: unit '%s' found in category '%s' but field inferred as '%s' — using matched category",
                fn, unit, matched_cat, inferred_cat)

        try:
            new_val = _apply_factor(val, factor)
            log.append({
                "record_id": rec.get("record_id"), "field": fn,
                "original_value": val, "new_value": new_val,
                "from": unit, "to": target, "factor": str(factor),
                "category": matched_cat,
            })
            rec["field_value"] = new_val
            rec["field_unit"] = target
        except Exception as e:
            unconv.append({"record_id": rec.get("record_id"), "reason": str(e)})

    logger.info("[UnitConv] %d converted, %d unconverted", len(log), len(unconv))
    return {
        "data": records, "conversion_log": log, "unconverted": unconv,
        "summary": f"Converted {len(log)} units" + (f", {len(unconv)} failed" if unconv else ""),
    }


def _apply_factor(val: float, factor) -> float:
    if isinstance(factor, str) and factor == "offset_273.15":
        return val - 273.15  # K → °C
    elif isinstance(factor, str) and factor == "offset_-273.15":
        return val + 273.15  # °C → K
    elif isinstance(factor, str) and factor == "offset_32_5_9":
        return (val - 32.0) * 5.0 / 9.0  # °F → °C
    elif isinstance(factor, str) and factor.startswith("offset_"):
        return val + float(factor.replace("offset_", ""))
    elif isinstance(factor, str) and factor.startswith("offset_-"):
        return val - float(factor.replace("offset_-", ""))
    return val * float(factor)
