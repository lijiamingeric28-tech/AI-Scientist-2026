"""
gen_catalog_schema.py — VizieR 目录 schema → 配置扩展生成器 (V4.2)

数据源 (项目根):
  - vizier_catalogs_schema.json    (23 个 VizieR 目录的列定义: 列名/unit/ucd/datatype)
  - query_results_progress_final.json (25 个天体的多目录查询结果)

输出 (幂等合并到 configs/schema_mapping.yaml):
  1. 字段别名扩展:
     - 关键物理量列 (人工核对清单) → 标准字段 aliases
     - 其余全部列 → database_catalog_properties aliases (无损保留, 防 Export 白名单丢弃)
  2. 单位扩展:
     - VizieR 标准记法单位 (solMass/solRad/solLum/Sun/log(cm.s**-2) 等)
       → 现有转换组别名 + 新组 (surface_brightness/abundance/wavenumber/surface_density/percentage/area/composite)

幂等: 已存在的别名/单位跳过。用法: python scripts/gen_catalog_schema.py [--apply]
"""
from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows GBK 控制台

_PROJ_ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')   # 项目根 (含两份 json)
_SCHEMA_JSON = os.path.join(_PROJ_ROOT, 'vizier_catalogs_schema.json')
_RESULTS_JSON = os.path.join(_PROJ_ROOT, 'query_results_progress_final.json')
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '..', 'configs', 'schema_mapping.yaml')

# ── 1. 关键物理量列 → 标准字段 (人工核对, 从 query_results 864 列中筛选) ──
EXPLICIT_MAP: dict[str, list[str]] = {
    "apparent_magnitude": [
        "BPmag", "RPmag", "BTmag", "VTmag", "Bmag", "Gmag", "GRVSmag",
        "Hmag", "Hpmag", "Hpmax", "HPmin", "Jmag", "Kmag", "Kpmag", "Ksmag",
        "CombMag", "Pmag", "W1mag", "W2mag", "W3mag", "W4mag", "Vmag",
    ],
    "flux_density": ["Fnu_12", "Fnu_25", "Fnu_60", "Fnu_100", "FG", "FBP", "FRP"],
    "extinction": [
        "E(B-V)", "E(BP-RP)", "E(J-H)", "E(J-Ks)", "B_E(BP-RP)", "b_E(BP-RP)",
        "A0", "AG", "B_A0", "B_AG", "b_A0", "b_AG",
    ],
    "metallicity": ["[Fe/H]", "B_[Fe/H]", "b_[Fe/H]", "[Fe/H]temp", "[M/H]"],
    "effective_temperature": ["Teff", "B_Teff", "b_Teff", "Tefftemp"],
    "surface_gravity": ["logg", "B_logg", "b_logg", "loggtemp"],
    "stellar_mass": ["Mass", "M500", "MSZ"],
    "stellar_radius": ["Rad", "B_Rad", "b_Rad", "R500"],
    "luminosity": ["Lum", "B_Lum", "b_Lum", "L500", "L500r1", "L500r2", "L500r3", "L500r4"],
    "distance": ["Dist", "B_Dist", "b_Dist"],
    "parallax": ["Plx", "plx"],
    "proper_motion_ra": ["pmRA", "RA_pm"],
    "proper_motion_dec": ["pmDE", "pmDEC", "DE_pm"],
    "radial_velocity": ["RV", "RadVel", "Vbroad"],
    "age": ["Age", "logt"],
}

# ── 2. VizieR 单位 → 转换组补充 (乘法约定; 新组标记) ──
UNIT_PATCH: dict[str, dict[str, float]] = {
    "mass": {"solMass": 1.0, "1e+14solMass": 1e14},
    "radius": {"solRad": 1.0},
    "luminosity": {"solLum": 3.828e33, "1e+37W": 1e44},
    "surface_gravity": {"log(cm.s**-2)": 1.0, "log(cm s**-2)": 1.0},
    "surface_brightness": {"mag.arcsec**-2": 1.0, "mag/arcsec^2": 1.0, "MJy/sr": 1.0},
    "abundance": {"Sun": 1.0, "log(Sun)": 1.0},
    "wavenumber": {"um**-1": 1.0, "1/um": 1.0},
    "surface_density": {"pc**-2": 1.0, "mas**-2": 1.0},
    "percentage": {"%": 1.0, "percent": 1.0},
    "area": {"arcmin**2": 1.0, "0.001arcmin**2": 1.0},
    "composite": {"kpc/arcsec": 1.0, "1e-15W.m**-2": 1.0, "log(yr)": 1.0,
                  "log(0.1arcmin)": 1.0, "pix": 1.0, "ct": 1.0},
}

# 仅 query_results 实际使用的列 (精确性优先), catalog 兜底覆盖 schema 全量
def _load_used_columns() -> tuple[set[str], dict[str, dict]]:
    """返回 (实际使用列名集合, 全部列名→元信息)。"""
    schema = json.load(open(_SCHEMA_JSON, encoding='utf-8'))
    col_info: dict[str, dict] = {}
    for cat, c in schema.items():
        for colname, meta in (c.get('columns') or {}).items():
            if colname not in col_info:
                col_info[colname] = meta
            elif not col_info[colname].get('ucd') and meta.get('ucd'):
                col_info[colname] = meta
    results = json.load(open(_RESULTS_JSON, encoding='utf-8'))
    used: set[str] = set()
    for cat, objs in results.items():
        for name, o in objs.items():
            for key, v in (o.get('vizier_data') or {}).items():
                if isinstance(v, dict):
                    used.update(v.get('columns', []))
    return used, col_info


def _q(key: str) -> str:
    if re.fullmatch(r'[A-Za-z0-9_.+\-]+', key):
        return key
    return f'"{key}"'


def _fmt(x: float) -> str:
    d = Decimal(repr(x))
    s = format(d, 'f')
    if '.' not in s:
        s += '.0'
    return s


def _load_yaml_data() -> dict:
    import yaml
    with open(_SCHEMA_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_alias_patch(used: set[str], col_info: dict[str, dict]) -> dict[str, list[str]]:
    """计算新增别名: 标准字段 + database_catalog_properties。"""
    existing: dict[str, set] = {}
    data = _load_yaml_data()
    for f in data['target_schema_astrophysics']['fields']:
        existing[f['name']] = set(f.get('aliases', []))
    # 已覆盖别名 (大小写不敏感)
    covered = set().union(*existing.values())
    covered_lower = {c.lower() for c in covered}

    patch: dict[str, list[str]] = {}
    # 标准字段显式映射
    for field, cols in EXPLICIT_MAP.items():
        add = [c for c in cols if c.lower() not in covered_lower and c in used]
        if add:
            patch[field] = add
            covered_lower.update(c.lower() for c in add)
    # catalog 兜底: 全部 schema 列中未覆盖的
    all_cols = set(col_info.keys())
    rest = sorted(c for c in all_cols if c.lower() not in covered_lower)
    if rest:
        patch['database_catalog_properties'] = rest
    return patch


def _yaml_list_items(aliases_line: str) -> list[str]:
    """提取 aliases 单行里的现有别名 (原内容, 合并时保留)。"""
    m = re.search(r'\[(.*)\]', aliases_line)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def apply_alias_patch(patch: dict[str, list[str]]) -> None:
    """行级合并: aliases 行 = 原别名 + 新别名 (合并去重, 保留原缩进/注释)。

    安全: 写前备份 → 写后 YAML 验证 → 失败自动回滚。
    """
    import shutil
    bak = _SCHEMA_PATH + '.apply.bak'
    shutil.copy2(_SCHEMA_PATH, bak)
    lines = open(_SCHEMA_PATH, encoding='utf-8').read().split('\n')

    for field, new_aliases in patch.items():
        # 1) 找字段块: - name: "X"
        idx = None
        for i, ln in enumerate(lines):
            if re.match(rf'\s+- name:\s+"{re.escape(field)}"', ln):
                idx = i
                break
        if idx is None:
            print(f'[skip] 字段块未找到: {field}')
            continue
        # 2) 找块内 aliases 行 (块结束 = 下一个 name 行)
        j = None
        for k in range(idx + 1, len(lines)):
            if re.match(r'\s+aliases:', lines[k]):
                j = k
                break
            if re.match(r'\s+- name:\s+"', lines[k]):
                break
        if j is None:
            print(f'[skip] {field} 无 aliases 行')
            continue
        # 3) 合并原 + 新 (去重保序)
        orig = _yaml_list_items(lines[j])
        seen, merged = set(), []
        for it in orig + new_aliases:
            key = it.lower()
            if key not in seen:
                seen.add(key)
                merged.append(it)
        indent = re.match(r'\s*', lines[j]).group(0)
        lines[j] = f'{indent}aliases: [{", ".join(f"{chr(34)}{a}{chr(34)}" for a in merged)}]'
        print(f'[alias] {field}: 原 {len(orig)} + 新 {len(new_aliases)} = {len(merged)}')

    _write_and_verify(lines, bak)


def _write_and_verify(lines: list[str], bak: str) -> None:
    """写回 + YAML 验证 + 失败回滚。"""
    import yaml
    text = '\n'.join(lines)
    try:
        yaml.safe_load(text)
    except Exception as e:
        shutil.copy2(bak, _SCHEMA_PATH)
        raise RuntimeError(f'写后验证失败, 已回滚: {e}') from e
    open(_SCHEMA_PATH, 'w', encoding='utf-8').write(text)
    print('[OK] 写回并验证通过')


def build_unit_patch() -> tuple[dict[str, dict[str, str]], list[str]]:
    """计算新增单位条目 + 新组名。"""
    data = _load_yaml_data()
    conv = data.get('unit_conversions_astrophysics', {})
    existing_groups = set(conv.keys())
    patch: dict[str, dict[str, str]] = {}
    new_groups: list[str] = []
    for group, rules in UNIT_PATCH.items():
        cur = conv.get(group, {})
        add = {u: _fmt(f) for u, f in rules.items() if u not in cur}
        if add:
            patch[group] = add
        if group not in existing_groups:
            new_groups.append(group)
    return patch, new_groups


def apply_unit_patch(patch: dict[str, dict[str, str]], new_groups: list[str]) -> None:
    """行级追加: 已有组在组内末尾追加, 新组追加到段尾 (redshift 组之后)。

    安全: 备份 → 验证 → 失败回滚。
    """
    import shutil
    bak = _SCHEMA_PATH + '.apply.bak'
    shutil.copy2(_SCHEMA_PATH, bak)
    lines = open(_SCHEMA_PATH, encoding='utf-8').read().split('\n')

    # 段内组起始行定位 (组名行 = 2 空格缩进 + 名字 + :)
    def group_start(group: str) -> int | None:
        for i, ln in enumerate(lines):
            if re.match(rf'^  {re.escape(group)}:$', ln):
                return i
        return None

    # 找段尾 (unit_conversions_astrophysics 段最后一个组之后): 段尾 = 文件末尾
    # 新组统一插到 redshift 组之后 (保持现有组序稳定)
    for group, rules in patch.items():
        entry_lines = [f'    {_q(u)}: {f}' for u, f in rules.items()]
        if group in new_groups:
            anchor = group_start('redshift')
            if anchor is None:
                print(f'[skip] redshift 锚点未找到: {group}')
                continue
            insert_at = anchor + 1
            while insert_at < len(lines) and lines[insert_at].startswith('    '):
                insert_at += 1
            new_block = [f'  {group}:'] + entry_lines
            lines[insert_at:insert_at] = new_block
            print(f'[unit] 新组 {group}: +{len(rules)} (插在 redshift 后)')
        else:
            gs = group_start(group)
            if gs is None:
                print(f'[skip] 组未找到: {group}')
                continue
            # 组结束 = 下一个 2 空格组名行
            ge = gs + 1
            while ge < len(lines) and not re.match(r'^  [a-z_]+:$', lines[ge]):
                ge += 1
            lines[ge:ge] = entry_lines
            print(f'[unit] {group}: +{len(rules)} (组内追加)')

    _write_and_verify(lines, bak)


def main() -> None:
    apply = '--apply' in sys.argv
    used, col_info = _load_used_columns()
    print(f'实际使用列: {len(used)} | schema 全量列: {len(col_info)}')

    # ── 字段别名 ──
    patch = build_alias_patch(used, col_info)
    total = sum(len(v) for v in patch.values())
    print(f'[plan] 字段别名新增: {total} 条')
    for field, cols in patch.items():
        print(f'  {field}: +{len(cols)}  (示例: {cols[:5]})')

    # ── 单位 ──
    upatch, new_groups = build_unit_patch()
    print(f'[plan] 单位新增: {sum(len(v) for v in upatch.values())} 条, 新组 {new_groups}')

    if not apply:
        print('[dry-run] 未写文件 (加 --apply 合并到 schema_mapping.yaml)')
        return

    apply_alias_patch(patch)
    apply_unit_patch(upatch, new_groups)

    # 写后验证
    data = _load_yaml_data()
    conv = data.get('unit_conversions_astrophysics', {})
    n_rules = sum(len(v) for v in conv.values())
    total_aliases = sum(len(f.get('aliases', [])) for f in data['target_schema_astrophysics']['fields'])
    print(f'[OK] unit_conversions_astrophysics: {len(conv)} 组 / {n_rules} 条规则')
    print(f'[OK] target_schema_astrophysics aliases 总数: {total_aliases}')


if __name__ == '__main__':
    main()
