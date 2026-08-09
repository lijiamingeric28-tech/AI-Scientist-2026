"""unit_converter.py — Tool 3: Unit Conversion

V2.1 修复: 转换因子以 (category, from_unit) 为键, 避免同名单位被覆盖。
例如 GPa 在 strength 中 ×1000→MPa, 在 hardness 中查表转换, 不再混淆。
"""
from typing import Any
from ...configs import load_yaml, load_domain_config, load_domain_schema_config, get_research_domain
from ...utils.logger import get_logger
logger = get_logger(__name__)

# 语义类型 → category 映射 (用于推断字段属于哪个单位类别)
# V2.2: 从配置中动态加载, 此表仅作 fallback
# V4 fix: 按领域缓存 — 不同 research_domain 的 semantic_types 段不同, 防跨域污染
_SEMANTIC_TO_CATEGORY: dict[str, str] = {}
_CACHED_DOMAIN: str | None = None

def _load_semantic_category_map(research_domain: str | None = None):
    """从 quality_rules.yaml 动态加载 semantic_type → unit_category 映射 (领域感知)。

    Phase 3 显式化: 优先显式 research_domain, None 时回退全局。
    """
    global _SEMANTIC_TO_CATEGORY, _CACHED_DOMAIN
    domain = research_domain or get_research_domain()
    if _CACHED_DOMAIN == domain and _SEMANTIC_TO_CATEGORY:
        return
    _SEMANTIC_TO_CATEGORY.clear()
    try:
        # V4 fix: 领域专属段优先 (semantic_types_astrophysics), 通用段兜底
        semantic_cfg = load_domain_config("semantic_types", "semantic_types",
                                          research_domain=research_domain)
        for st_name, st_info in semantic_cfg.items():
            if isinstance(st_info, dict):
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
    _CACHED_DOMAIN = domain


def convert_units(records: list[dict], unit_conversions: list[dict] | None = None,
                  standard_units: dict[str, str] | None = None,
                  semantic_types: dict[str, Any] | None = None,
                  target_schema: dict[str, Any] | None = None,
                  research_domain: str | None = None) -> dict[str, Any]:
    """统一单位转换 (V2.2: category-keyed conversions + dynamic semantic map)。

    V4 fix: 领域感知加载 — 按 research_domain 读取 unit_conversions_{domain} /
    target_schema_{domain} 段 (如天体物理的 pc/kpc/Mpc/mag/dex/Msun 规则),
    空 domain 回退通用段, 材料域行为不变。

    Phase 3 显式化: 增加 research_domain 参数 (None 时回退全局 get_research_domain,
    兼容 LLM 工具路径——工具签名不要求 LLM 传 domain)。
    """
    _load_semantic_category_map(research_domain)
    # V4 fix: 领域专属转换规则优先 (unit_conversions_astrophysics), 通用段兜底
    rules = load_domain_schema_config("unit_conversions", research_domain=research_domain)

    # 构建 (category, from_unit) → factor 映射表
    # 同时保留 unit→category 的反向查找
    cat_map: dict[tuple, dict] = {}
    unit_categories: dict[str, list[str]] = {}  # unit → [category names]
    for cat, cv in rules.items():
        for unit, factor in cv.items():
            key = (cat, unit)
            cat_map[key] = {"category": cat, "factor": factor}
            unit_categories.setdefault(unit, []).append(cat)

    # 标准单位: 调用方显式 target_schema 优先, 其次领域配置, 最后参数
    std_units = dict(standard_units or {})
    schema_cfg = target_schema or load_domain_schema_config("target_schema",
                                                            research_domain=research_domain)
    for f in (schema_cfg or {}).get("fields", []):
        n, u = f.get("name"), f.get("standard_unit")
        if n and u:
            std_units[n] = u

    # 用户指定的目标单位 (V2: 支持 entity-aware key)
    conv_map: dict[str, str] = {}
    # V2: entity-aware map: (entity_type, entity_name, field_name) → target_unit
    entity_conv_map: dict[tuple, str] = {}
    if unit_conversions:
        for uc in unit_conversions:
            if isinstance(uc, dict) and uc.get("field"):
                fn = uc["field"]
                conv_map[fn] = uc.get("to", std_units.get(fn, ""))
                # V2: if entity_key is present, register entity-aware mapping
                ekey = uc.get("entity_key", "")
                if ekey:
                    # entity_key may be "FRB:FRB_A/dispersion_measure" or "FRB_A/dispersion_measure"
                    parts = ekey.split("/", 1)
                    entity_label = parts[0] if parts else ekey
                    entity_conv_map[(entity_label, fn)] = uc.get("to", std_units.get(fn, ""))

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

        # V3.1 fix: 每条记录开始时初始化 target, 防止 UnboundLocalError
        target = None
        # V2: entity-aware target lookup — try entity-specific first, then global fallback
        et = rec.get("entity_type", "") or ""
        en = rec.get("entity_name", "") or ""
        if et and en:
            target = entity_conv_map.get((f"{et}:{en}", fn))
            if target is None:
                target = entity_conv_map.get((en, fn))
        if target is None:
            target = conv_map.get(fn) or std_units.get(fn)

        from ...tools._parse_utils import parse_numeric
        nv = parse_numeric(val)
        # V4 fix: 拆分静默跳过 — 各类失败显式记录 unconverted (kind 区分),
        # 供 normalization_agent 汇入 errors, 使 has_unconverted_units 真实化
        if nv is None:
            continue  # 非数值, 无法转换
        if unit == target:
            continue  # 已是目标单位
        if not unit:
            unconv.append({"record_id": rec.get("record_id"), "field": fn,
                           "reason": f"missing unit (empty), target={target}",
                           "kind": "missing_unit"})
            continue
        if not target:
            unconv.append({"record_id": rec.get("record_id"), "field": fn,
                           "reason": "no target unit for field",
                           "kind": "no_target_unit"})
            continue

        # ── V2.1: 用 (category, unit) 查找转换因子 ──
        # Step 1: 推断该字段属于哪个 category
        st = field_semantic.get(fn, "")
        if not st:
            # V4 fix: semantic_types 键可能是 entity-aware "{et}:{en}/{field}",
            # 按后缀匹配纯字段名
            for k in field_semantic:
                if str(k).endswith("/" + fn):
                    st = field_semantic[k]
                    break
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

        if factor is None and not inferred_cat:
            # Fallback: 无语义类型时遍历所有 category, 取第一个匹配的
            for cat in candidates:
                rule = cat_map.get((cat, unit))
                if rule:
                    factor = rule["factor"]
                    matched_cat = cat
                    break

        # V4 fix: 量纲一致性 — target 单位必须属于 matched_cat 的规则集。
        # 防止跨类误转 (如 distance 字段的 'mag' 经 magnitude 类规则转成 pc,
        # 或无语义类型时 mag→pc 的 fallback 误转)。
        if factor is not None and matched_cat:
            if (matched_cat, target) not in cat_map:
                unconv.append({
                    "record_id": rec.get("record_id"), "field": fn,
                    "reason": f"unit '{unit}' (category '{matched_cat}') incompatible with target '{target}'",
                    "kind": "no_conversion_rule",
                })
                continue

        if factor is None:
            unconv.append({
                "record_id": rec.get("record_id"), "field": fn,
                "reason": f"no conversion rule for unit '{unit}' in categories {candidates}",
                "kind": "no_conversion_rule",
            })
            continue

        # ── V2.1: 量纲校验 ──
        # 不同 category 的同名单位 (如 GPa 在 strength vs hardness) 需不同处理
        if inferred_cat and matched_cat and inferred_cat != matched_cat:
            logger.warning(
                "[UnitConv] %s: unit '%s' found in category '%s' but field inferred as '%s' — using matched category",
                fn, unit, matched_cat, inferred_cat)

        try:
            # V4.2 fix: target 非组基准单位时换算修正 —
            # val × factor(unit) 先到组基准, 再 ÷ factor(target) 到目标单位。
            # (此前只做 "→组基准" 单向换算却把 field_unit 替换为任意 target,
            #  如 5 G→"5.0 T" 静默错误; offset 因子走 _apply_factor 原路径)
            tf = cat_map.get((matched_cat, target), {}).get("factor", 1.0)
            if isinstance(factor, str) or isinstance(tf, str) or float(tf) == 1.0:
                new_val = _apply_factor(nv, factor)
            else:
                new_val = _apply_factor(nv, factor) / float(tf)
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
    elif isinstance(factor, str) and factor == "offset_32_5_9_273_15":
        return (val - 32.0) * 5.0 / 9.0 + 273.15  # °F → K
    elif isinstance(factor, str) and factor.startswith("offset_"):
        return val + float(factor.replace("offset_", ""))
    elif isinstance(factor, str) and factor.startswith("offset_-"):
        return val - float(factor.replace("offset_-", ""))
    return val * float(factor)
