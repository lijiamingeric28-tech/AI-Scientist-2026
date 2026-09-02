"""
gen_astro_units.py — 生成天体物理单位转换扩展组 (V4.2)

向 configs/schema_mapping.yaml 的 unit_conversions_astrophysics 段末尾追加 10 个新维度组:
  flux_density / dispersion_measure / rotation_measure / frequency /
  energy / magnetic_field / pressure / density / angle / wavelength

数值锚点来源 (websearch 调研):
  - IAU 2015 B3 名义常数 (R_sun/L_sun/au 精确), CDS/VizieR catstd 标准单位字典
  - CODATA 2018 精确值 (eV = 1.602176634e-19 J, k_B = 1.380649e-23)
  - STScI UNITS.txt: 1 Jy = 1e-26 W/m^2/Hz = 1e-23 erg/s/cm^2/Hz
  - 1 T = 1e4 G, 1 bar = 1e5 Pa, 1 dyn/cm^2 = 0.1 Pa, 1 g/cm^3 = 1000 kg/m^3
  - 1 amu = 1.66053906660e-24 g, 1 rad = 180/pi deg

PyYAML 6.x 把 1e+38/1e-05 解析为字符串 — 因子用 Decimal 展开为完整十进制。
幂等: 已存在的组名跳过。用法: python scripts/gen_astro_units.py [--apply]
"""
from __future__ import annotations

import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows GBK 控制台

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '..', 'configs', 'schema_mapping.yaml')


def _fmt(x) -> str:
    """数值 → 完整十进制 YAML 字面量 (PyYAML 6.x 科学计数法防护, 保留全部精度)。"""
    if isinstance(x, str):
        return x  # offset_* 等特殊因子原样
    d = Decimal(repr(x))  # repr(float) 是最短往返表示, Decimal 精确展开
    s = format(d, 'f')
    if '.' not in s:
        s += '.0'
    return s


def _q(key: str) -> str:
    """YAML 键: 纯 [A-Za-z0-9_.+-] 不加引号 (与现有文件风格一致), 否则双引号。"""
    if re.fullmatch(r'[A-Za-z0-9_.+\-]+', key):
        return key
    return f'"{key}"'


# ── 新增 10 组: 组名 → {单位: 因子 (乘法约定, value_std = value × factor)} ──
NEW_GROUPS: dict[str, dict[str, object]] = {
    # 闭环缺口: flux_density (Jy) — 1 Jy = 1e-26 W/m^2/Hz = 1e-23 erg/s/cm^2/Hz
    "flux_density": {
        "Jy": 1.0, "jy": 1.0, "Jansky": 1.0, "jansky": 1.0,
        "mJy": 0.001, "uJy": 1e-6, "μJy": 1e-6, "nJy": 1e-9, "pJy": 1e-12,
        "erg/s/cm^2/Hz": 1e23, "erg s^-1 cm^-2 Hz^-1": 1e23, "erg cm^-2 s^-1 Hz^-1": 1e23,
        "W/m^2/Hz": 1e26, "W m^-2 Hz^-1": 1e26,
    },
    # 闭环缺口: dispersion_measure (FRB/脉冲星) — 复合单位, 组内自转换
    "dispersion_measure": {
        "cm^-3 pc": 1.0, "pc cm^-3": 1.0, "pc/cm^3": 1.0, "cm⁻³ pc": 1.0,
    },
    # 闭环缺口: rotation_measure (法拉第旋转) — 复合单位, 组内自转换
    "rotation_measure": {
        "rad/m^2": 1.0, "rad m^-2": 1.0, "rad/m²": 1.0, "rad m-2": 1.0,
    },
    # 扩展: frequency
    "frequency": {
        "Hz": 1.0, "hz": 1.0, "hertz": 1.0,
        "kHz": 1000.0, "MHz": 1000000.0, "GHz": 1000000000.0, "THz": 1000000000000.0,
        "s^-1": 1.0, "1/s": 1.0, "s⁻¹": 1.0,
    },
    # 扩展: energy — 基准 erg (cgs 天文惯例); eV 系 CODATA 2018 精确
    "energy": {
        "erg": 1.0, "J": 10000000.0, "joule": 10000000.0,
        "eV": 1.602176634e-12, "electronvolt": 1.602176634e-12,
        "keV": 1.602176634e-9, "MeV": 1.602176634e-6,
        "GeV": 1.602176634e-3, "TeV": 1.602176634,
        "PeV": 1602.176634, "EeV": 1602176.634,
    },
    # 扩展: magnetic_field — 基准 G (天文惯例); 1 T = 1e4 G
    "magnetic_field": {
        "G": 1.0, "gauss": 1.0,
        "mG": 0.001, "milligauss": 0.001,
        "uG": 1e-6, "μG": 1e-6, "microgauss": 1e-6,
        "nG": 1e-9, "nanogauss": 1e-9, "kG": 1000.0,
        "T": 10000.0, "tesla": 10000.0, "mT": 10.0, "uT": 0.01, "μT": 0.01,
        "nT": 1e-5,
    },
    # 扩展: pressure — 基准 Pa; 1 bar = 1e5 Pa, 1 atm = 101325 Pa, 1 dyn/cm^2 = 0.1 Pa
    "pressure": {
        "Pa": 1.0, "pascal": 1.0,
        "hPa": 100.0, "kPa": 1000.0, "MPa": 1000000.0, "GPa": 1000000000.0,
        "bar": 100000.0, "mbar": 100.0, "millibar": 100.0,
        "atm": 101325.0, "atmosphere": 101325.0,
        "dyn/cm^2": 0.1, "dyn cm^-2": 0.1, "dyn/cm²": 0.1,
        "dyne/cm^2": 0.1, "dyne cm^-2": 0.1,
        "mmHg": 133.322, "torr": 133.322,
    },
    # 扩展: density (质量密度) — 基准 g/cm^3; 1 amu = 1.66053906660e-24 g
    "density": {
        "g/cm^3": 1.0, "g/cm³": 1.0, "g cm^-3": 1.0, "g cm-3": 1.0, "g/cc": 1.0,
        "kg/m^3": 0.001, "kg/m³": 0.001, "kg m^-3": 0.001,
        "amu/cm^3": 1.66053906660e-24, "amu cm^-3": 1.66053906660e-24,
        "u/cm^3": 1.66053906660e-24,
    },
    # 扩展: angle — 基准 deg; 1 rad = 180/pi deg
    "angle": {
        "deg": 1.0, "degree": 1.0, "degrees": 1.0, "°": 1.0, "deg.": 1.0,
        "arcmin": 0.016666666666666666, "arcminute": 0.016666666666666666,
        "arcminutes": 0.016666666666666666,
        "arcsec": 0.0002777777777777778, "arcsecond": 0.0002777777777777778,
        "arcseconds": 0.0002777777777777778,
        "mas": 2.7777777777777778e-7, "milliarcsec": 2.7777777777777778e-7,
        "milliarcsecond": 2.7777777777777778e-7,
        "rad": 57.29577951308232, "radian": 57.29577951308232, "radians": 57.29577951308232,
    },
    # 扩展: wavelength — 基准 nm; 1 Å = 0.1 nm (不含 cm/m, 防与 distance/radius 组撞车)
    "wavelength": {
        "nm": 1.0, "nanometer": 1.0, "nanometers": 1.0,
        "Å": 0.1, "angstrom": 0.1, "Angstrom": 0.1, "angstroms": 0.1,
        "um": 1000.0, "μm": 1000.0, "µm": 1000.0, "micron": 1000.0, "micrometer": 1000.0,
        "mm": 1000000.0, "millimeter": 1000000.0,
    },
}

_GROUP_NOTE = """  # ── V4.2 扩展组 (IAU 2015 B3 / CDS catstd / CODATA 2018 锚点, 乘法约定) ──"""


def build_block() -> str:
    """生成追加段文本 (组序 = 字典序保持定义顺序)。"""
    lines = [_GROUP_NOTE]
    for gname, rules in NEW_GROUPS.items():
        lines.append(f"  {gname}:")
        for unit, factor in rules.items():
            lines.append(f"    {_q(unit)}: {_fmt(factor)}")
    return "\n".join(lines)


def _existing_groups() -> set[str]:
    try:
        import yaml
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return set((data.get("unit_conversions_astrophysics") or {}).keys())
    except Exception:
        return set()


def main() -> None:
    apply = "--apply" in sys.argv
    existing = _existing_groups()
    to_add = {g for g in NEW_GROUPS if g not in existing}
    skipped = {g for g in NEW_GROUPS if g in existing}
    if skipped:
        print(f"[skip] 已存在: {sorted(skipped)}")
    if not to_add:
        print("[idle] 全部组已存在, 无需追加")
        return
    block = build_block()
    print(f"[plan] 新增 {len(to_add)} 组: {sorted(to_add)}")
    print("---- 生成段 ----")
    print(block)
    print("----------------")
    if not apply:
        print("[dry-run] 未写文件 (加 --apply 追加到 schema_mapping.yaml)")
        return
    with open(_SCHEMA_PATH, "a", encoding="utf-8") as f:
        f.write("\n" + block + "\n")
    # 写后验证: 重新加载确认组数与可解析性
    import yaml
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    conv = data["unit_conversions_astrophysics"]
    n_rules = sum(len(v) for v in conv.values())
    print(f"[OK] 已追加。unit_conversions_astrophysics: {len(conv)} 组 / {n_rules} 条规则")


if __name__ == "__main__":
    main()
