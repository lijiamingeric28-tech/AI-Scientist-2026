#!/usr/bin/env python3
"""
check_range_consistency.py — P0-1: 三套典型范围一致性校验 (防数值漂移)

背景: 同一 (entity_type, semantic_key) 的范围同时存在于三处, 无同步机制会漂移:
  1. quality_rules.yaml        → entity_types_astrophysics.typical_ranges     (实体级典型范围)
  2. reference_ranges.yaml     → entries[].ranges 结构化段                     (知识库参考范围)
  3. quality_rules.yaml        → semantic_types_astrophysics[].feasible_ranges (物理可行包络)

比对方式: 对 (entity_type, semantic_key) 两两比对 lo/hi/unit;
  同量纲单位换算用 schema_mapping.yaml unit_conversions_astrophysics 简单因子
  (乘法约定: value_std = value × factor), 无换算规则则跳过该对比。
  容忍度: 相对差 <10% 或绝对差 <1e-6 视为一致。

输出: 每对来源一行 — [OK] 一致 / [WARN] 漂移 + 建议值 / [SKIP] 无法换算跳过。
退出码: 0 = 全部一致; 1 = 有漂移 (默认 warning 模式不阻断, 加 --strict 阻断);
  配置缺失等错误 → 2。

依赖: 纯标准库 + pyyaml, 0 外部依赖。
运行: python scripts/check_range_consistency.py [--strict]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
QUALITY_RULES = ROOT / "quality_pipeline" / "configs" / "quality_rules.yaml"
SCHEMA_MAPPING = ROOT / "quality_pipeline" / "configs" / "schema_mapping.yaml"
REFERENCE_RANGES = (ROOT / "quality_pipeline" / "data" / "insight_knowledge"
                    / "astrophysics" / "reference_ranges.yaml")

TOL_REL = 0.10     # 相对差容忍度
TOL_ABS = 1e-6     # 绝对差容忍度


def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"[ERROR] 配置文件缺失: {path}", file=sys.stderr)
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def to_float(v) -> float:
    """YAML e 记法 (如 3e29) 会被 PyYAML 解析为 str — 统一强转 (与 semantic_type.py 一致)。"""
    return float(v)


def unit_factors(cfg: dict) -> dict:
    """unit_conversions_astrophysics: {category: {unit: factor}} (乘法约定)。"""
    return cfg.get("unit_conversions_astrophysics", {}) or {}


def convert(value, from_unit: str, to_unit: str, factors: dict, category: str):
    """同一 category 内简单因子换算 (value_std = value × factor); 无规则 → None。"""
    value = to_float(value)
    if from_unit == to_unit:
        return value
    table = (factors.get(category) or {}) if category else {}
    f_from, f_to = table.get(from_unit), table.get(to_unit)
    if f_from is None or f_to is None:
        return None
    return value * to_float(f_from) / to_float(f_to)


def rel_diff(a: float, b: float) -> float:
    if a == b:
        return 0.0
    denom = abs(b)
    if denom < 1e-300:
        return float("inf")
    return abs(a - b) / denom


def fmt(x: float, unit: str) -> str:
    if abs(x) >= 1e6 or (abs(x) < 1e-3 and x != 0):
        return f"{x:.2e} {unit}".strip()
    return f"{x:g} {unit}".strip()


def semantic_meta(semantic: dict, field: str) -> tuple[str, str]:
    """semantic_types 规则 → (典型单位 units[0], unit_category)。"""
    rule = semantic.get(field) or {}
    units = rule.get("units") or []
    unit = str(units[0]) if units else ""
    return unit, rule.get("unit_category") or ""


def feasible_in_unit(rule: dict, unit_t: str, factors: dict, category: str):
    """从 feasible_ranges 挑选与典型单位同量纲的单位 (优先精确匹配, 否则第一个可换算的)。"""
    fe = rule.get("feasible_ranges") or {}
    if not fe:
        return None
    if unit_t in fe:
        return unit_t, fe[unit_t]
    table = (factors.get(category) or {}) if category else {}
    if unit_t in table:
        for u, rng in fe.items():
            if u in table:
                return u, rng
    return None


def compare_pair(name1: str, lo1, hi1, u1: str,
                 name2: str, lo2, hi2, u2: str,
                 factors: dict, category: str) -> tuple[str, str]:
    """换算到同一单位后比对。返回 (status, 详情); status ∈ OK / WARN / SKIP。"""
    if u1 != u2:
        lo2c = convert(lo2, u2, u1, factors, category)
        hi2c = convert(hi2, u2, u1, factors, category)
        if lo2c is None or hi2c is None:
            return ("SKIP", f"{name1} vs {name2}: 单位 {u1!r} ↔ {u2!r} 无换算规则, 跳过")
        lo2, hi2 = lo2c, hi2c
    lo1, hi1 = to_float(lo1), to_float(hi1)

    ok = True
    detail = []
    for a, b, bound in ((lo1, lo2, "lo"), (hi1, hi2, "hi")):
        if rel_diff(a, b) >= TOL_REL and abs(a - b) >= TOL_ABS:
            ok = False
            detail.append(f"{bound}: {fmt(b, u2)} vs {fmt(a, u1)} (相对差 {rel_diff(a, b) * 100:.1f}%)")
    if ok:
        return ("OK", f"{name1} vs {name2}: {fmt(lo1, u1)}~{fmt(hi1, u1)} == {fmt(lo2, u2)}~{fmt(hi2, u2)}")
    return ("WARN", f"{name1} vs {name2}: 漂移 ({'; '.join(detail)})"
                    f" | 建议: {name2} 对齐 {name1} → {fmt(lo1, u1)}~{fmt(hi1, u1)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="三套典型范围一致性校验 (P0-1)")
    parser.add_argument("--strict", action="store_true",
                        help="有漂移时以退出码 1 阻断 (默认 warning 模式不阻断)")
    args = parser.parse_args()

    qr = load_config(QUALITY_RULES)
    sm = load_config(SCHEMA_MAPPING)
    rr = load_config(REFERENCE_RANGES)

    et_cfg = qr.get("entity_types_astrophysics") or {}
    typical = et_cfg.get("typical_ranges") or {}
    semantic = qr.get("semantic_types_astrophysics") or {}
    factors = unit_factors(sm)

    # 参考范围映射: 规范化实体 (小写) → 字段 → {lo, hi, unit}
    ref_map: dict[str, dict] = {}
    for e in rr.get("entries") or []:
        rngs = e.get("ranges") or {}
        if not isinstance(rngs, dict):
            continue
        entities = ((e.get("applies_to") or {}).get("entities")) or []
        for ent in entities:
            key = str(ent).lower()
            ref_map.setdefault(key, {})
            for field, r in rngs.items():
                if isinstance(r, dict) and all(k in r for k in ("lo", "hi", "unit")):
                    ref_map[key][field] = r

    lines_ok: list[str] = []
    lines_warn: list[str] = []
    lines_skip: list[str] = []
    compared = 0

    for entity in sorted(set(typical) | set(ref_map)):
        fields = sorted(set(typical.get(entity, {})) | set(ref_map.get(entity.lower(), {})))
        for field in fields:
            unit_t, category = semantic_meta(semantic, field)

            t_rng = typical.get(entity, {}).get(field)          # [lo, hi] (典型单位)
            r_rng = ref_map.get(entity.lower(), {}).get(field)  # {lo, hi, unit}
            fe = semantic.get(field) or {}
            f_sel = feasible_in_unit(fe, unit_t, factors, category)

            label = f"{entity} / {field}"
            present = sum(x is not None for x in (t_rng, r_rng, f_sel))

            # 1) typical vs reference (reference 换算到典型单位)
            if t_rng is not None and r_rng is not None:
                compared += 1
                status, msg = compare_pair(
                    "typical", to_float(t_rng[0]), to_float(t_rng[1]), unit_t,
                    "reference", to_float(r_rng["lo"]), to_float(r_rng["hi"]), str(r_rng["unit"]),
                    factors, category)
                (lines_ok if status == "OK" else lines_warn if status == "WARN" else lines_skip) \
                    .append(f"[{status}] {label}: {msg}")
            # 2) typical vs feasible
            if t_rng is not None and f_sel is not None:
                f_unit, f_rng = f_sel
                compared += 1
                status, msg = compare_pair(
                    "typical", to_float(t_rng[0]), to_float(t_rng[1]), unit_t,
                    "feasible", to_float(f_rng[0]), to_float(f_rng[1]), f_unit,
                    factors, category)
                (lines_ok if status == "OK" else lines_warn if status == "WARN" else lines_skip) \
                    .append(f"[{status}] {label}: {msg}")
            # 3) reference vs feasible (typical 缺失时仍有对比价值)
            elif r_rng is not None and f_sel is not None:
                f_unit, f_rng = f_sel
                compared += 1
                status, msg = compare_pair(
                    "reference", to_float(r_rng["lo"]), to_float(r_rng["hi"]), str(r_rng["unit"]),
                    "feasible", to_float(f_rng[0]), to_float(f_rng[1]), f_unit,
                    factors, category)
                (lines_ok if status == "OK" else lines_warn if status == "WARN" else lines_skip) \
                    .append(f"[{status}] {label}: {msg}")
            # 4) 单源存在 → 无法对比, 不判漂移
            elif present == 1:
                lines_skip.append(f"[SKIP] {label}: 仅单源存在, 无法对比, 跳过")

    # ── 输出 ──
    print("=" * 78)
    print("check_range_consistency.py — P0-1 三源范围一致性校验")
    print("  源1: quality_rules typical_ranges | 源2: reference_ranges ranges | 源3: semantic_types feasible_ranges")
    print("  容忍度: 相对差 <10% 或绝对差 <1e-6")
    print("=" * 78)
    for line in lines_ok:
        print(line)
    for line in lines_skip:
        print(line)
    for line in lines_warn:
        print(line)
    print("-" * 78)
    drift = len(lines_warn)
    if drift == 0:
        print(f"汇总: 对比 {compared} 项, 全部一致 → OK (退出码 0)")
        return 0
    print(f"汇总: 对比 {compared} 项 | 一致 {len(lines_ok)} | 漂移 {drift} | 跳过 {len(lines_skip)}")
    mode = "strict (漂移阻断)" if args.strict else "warning (默认不阻断)"
    print(f"模式: {mode}")
    if args.strict:
        print("→ 退出码 1 (--strict 阻断)")
        return 1
    print("→ 退出码 0 (warning 模式不阻断; 加 --strict 阻断)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
