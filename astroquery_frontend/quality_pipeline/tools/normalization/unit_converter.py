"""unit_converter.py — Tool 3: Unit Conversion

V2.1 修复: 转换因子以 (category, from_unit) 为键, 避免同名单位被覆盖。
例如 GPa 在 strength 中 ×1000→MPa, 在 hardness 中查表转换, 不再混淆。

V2.4 (2026-08-24 重构, 回退 Aug 23 权威设计):
  - 标准单位唯一权威 = 调用方注入的 standard_units (PropertySpec/RAG 直通),
    本模块不再做任何字段名/类别的代码特判;
  - 对数单位由配置驱动: unit_conversions 条目因子形如 "10^x_yr" 表示
    10^val 后按内层单位继续换算 (任何领域可用, 无领域专用逻辑);
  - 多类同名单位 (如 yr 在 time/age) 优先选能转换到 target 的类 (通用消歧)。
"""
import re
from typing import Any
from ...configs import load_yaml, load_domain_config, load_domain_schema_config, get_research_domain
from ...utils.logger import get_logger
logger = get_logger(__name__)

# 对数单位形态: log(yr) / log10(yr) 等
_LOG_UNIT_RE = re.compile(r"^log(?:10)?\(\s*([A-Za-z0-9.*^/ -]+?)\s*\)$")


# 语义类型 → category 映射 (用于推断字段属于哪个单位类别)
# V2.2: 从配置中动态加载, 此表仅作 fallback
# V4 fix: 按领域缓存 — 不同 research_domain 的 semantic_types 段不同, 防跨域污染
_SEMANTIC_TO_CATEGORY: dict[str, str] = {}
_CACHED_DOMAIN: str | None = None

# 无量纲伪单位别名 — VLM 对无量纲量 (如 redshift) 常输出这些形态, 统一归一为 "dimensionless"
# (2026-08-11 真实运行暴露: 13 条 redshift 出现 ''/z/dimensionless/unitless 四种形态)
DIMENSIONLESS_UNIT_ALIASES = {None, "", "z", "unitless", "dimensionless"}

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

        # 无量纲归一: 字段无标准目标单位 (target 为空 → 该字段在标准单位表中无量纲,
        # 如 redshift) 且 VLM 单位是无量纲别名 → 统一归一为 "dimensionless",
        # 消除 ''/z/unitless 形态混乱; 数值不变, 留痕可追溯。
        if not target and unit in DIMENSIONLESS_UNIT_ALIASES:
            log.append({
                "record_id": rec.get("record_id"), "field": fn,
                "original_value": val, "new_value": val,
                "from": unit or "(empty)", "to": "dimensionless", "factor": "1.0",
                "category": "dimensionless",
            })
            rec["field_unit"] = "dimensionless"
            continue

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

        # V2.4: 对数单位 (log(yr) 等) — 配置驱动: 仅当配置里该单位存在
        # "10^x_<内层单位>" 因子标记时才做 10^x 还原 (任何领域可声明,
        # 无领域专用逻辑; 未标记的 log 单位走常规因子路径)
        log_unit = None
        if isinstance(unit, str):
            m = _LOG_UNIT_RE.match(unit.strip())
            if m:
                marked = any(
                    isinstance(cat_map.get((cat, unit), {}).get("factor"), str)
                    and cat_map[(cat, unit)]["factor"].startswith("10^x_")
                    for cat in unit_categories.get(unit, [])
                )
                if marked:
                    log_unit = unit
                    nv = 10.0 ** float(nv)
                    unit = m.group(1)

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
            # V2.3: 多类同名单位 — 优先取能转换到 target 的类
            # (yr 同属 time/age, target=Gyr 时应选 age 而非 time)
            if target:
                for cat in candidates:
                    if (cat, target) not in cat_map:
                        continue
                    rule = cat_map.get((cat, unit))
                    if rule:
                        factor = rule["factor"]
                        matched_cat = cat
                        break
            # Fallback: 无语义类型且无 target 兼容类时, 取第一个匹配的
            if factor is None:
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
            # M-20 fix: 两段式同时处理两侧 offset —
            # 先应用源因子到组基准, 目标侧为 offset 因子时对其做逆运算
            # (此前目标侧 offset 被丢弃: 材料段基准 °C + target_schema 标准 K
            #  时 25°C 静默转成 25 K; 现在 25°C → 298.15 K)
            tf = cat_map.get((matched_cat, target), {}).get("factor", 1.0)
            if isinstance(tf, str):
                new_val = _apply_factor(nv, factor)
                new_val = _apply_factor_inverse(new_val, tf)
            else:
                new_val = _apply_factor(nv, factor) / float(tf)
            log.append({
                "record_id": rec.get("record_id"), "field": fn,
                "original_value": val, "new_value": new_val,
                "from": log_unit or unit, "to": target,
                "factor": (f"10^x×{factor}" if log_unit else str(factor)),
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


def _apply_factor_inverse(val: float, factor) -> float:
    """M-20 fix: offset 因子的逆运算 (组基准 → 目标单位)。

    _apply_factor 把 单位→组基准, 逆运算把 组基准→目标单位:
    乘法因子取倒数, offset 因子对偏移量取反。
    """
    if isinstance(factor, str) and factor == "offset_273.15":
        return val + 273.15  # °C → K (逆: K → °C 为 -273.15)
    elif isinstance(factor, str) and factor == "offset_-273.15":
        return val - 273.15  # K → °C (逆: °C → K 为 +273.15)
    elif isinstance(factor, str) and factor == "offset_32_5_9":
        return val * 9.0 / 5.0 + 32.0  # °C → °F (逆: °F → °C)
    elif isinstance(factor, str) and factor == "offset_32_5_9_273_15":
        return (val - 273.15) * 9.0 / 5.0 + 32.0  # K → °F (逆: °F → K)
    elif isinstance(factor, str) and factor.startswith("offset_-"):
        return val + float(factor.replace("offset_-", ""))
    elif isinstance(factor, str) and factor.startswith("offset_"):
        return val - float(factor.replace("offset_", ""))
    return val / float(factor)
