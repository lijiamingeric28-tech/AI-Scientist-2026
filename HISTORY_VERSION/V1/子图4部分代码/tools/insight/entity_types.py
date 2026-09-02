"""
entity_types.py — Simbad 对象类型配置消费层 (V4)

从 quality_rules.yaml 的 entity_types_{domain} 段加载 (load_domain_config),
提供:
  - normalize_entity_type: "Unknown"/空 → 推断 (catalog > field > field_class > default);
    已知值 → kws 别名查规范名; 未识别 → 小写原样返回 (兼容 FRB 等非 Simbad 类型)
  - infer_entity_type: 三级推断链
  - entity_ancestors: 父类链展开 (如 quasar → [quasar, agn, galaxy])
  - get_typical_range: 实体典型范围兜底 (字段 → 语义类型 → typical_ranges)

配置缺失 → 全部安全降级 (不抛异常)。
"""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger(__name__)

# 按 domain 缓存 (镜像 semantic_type.py 模式, 防跨领域污染)
_CFG: dict[str, dict] = {}


def _load(domain: str) -> dict:
    """加载 entity_types_{domain} 配置段 (缺失 → {})。"""
    domain = domain or "astrophysics"
    if domain not in _CFG:
        raw: dict = {}
        try:
            from configs import load_domain_config
            raw = load_domain_config("entity_types", "entity_types") or {}
        except Exception as e:
            logger.warning("[EntityTypes] 配置加载失败 (domain=%s): %s", domain, e)
        _CFG[domain] = raw
    return _CFG[domain]


def _types_map(domain: str) -> dict:
    """{规范名: 类型条目} + {code: 条目} 索引。"""
    cfg = _load(domain)
    types = cfg.get("types", {}) or {}
    return types


def _name_to_entry(types: dict, name: str) -> dict | None:
    """按规范名或 code 查类型条目。"""
    name_l = str(name).lower()
    for code, entry in types.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name", "")).lower() == name_l or str(code).lower() == name_l:
            return entry
    return None


def _kws_lookup(types: dict, raw: str) -> str | None:
    """按 kws 别名查规范名 (大小写不敏感)。"""
    raw_l = str(raw).lower()
    for entry in types.values():
        if not isinstance(entry, dict):
            continue
        for kw in entry.get("kws", []) or []:
            if str(kw).lower() == raw_l:
                return str(entry.get("name", ""))
    return None


def infer_entity_type(field_name: str, source: dict | None = None,
                      domain: str = "astrophysics") -> str:
    """三级推断链: catalog_inference (DB 目录) > field_inference (字段名) >
    field_class_inference (语义类型) > default_entity_type。

    Args:
        field_name: 记录的字段名
        source: 所属 source (读 vizier_table_id 匹配 catalog_inference)
        domain: 研究领域

    Returns:
        推断的规范实体类型 (如 galaxy / star); 配置缺失 → "galaxy" (default)。
    """
    cfg = _load(domain)
    if not cfg:
        return str(cfg.get("default_entity_type", "galaxy"))

    # 1. catalog_inference: DB 目录前缀匹配 (优先级最高, 目录本身定义对象性质)
    if source:
        vid = str(source.get("vizier_table_id", "") or "")
        if vid:
            for prefix, et in (cfg.get("catalog_inference", {}) or {}).items():
                if vid.startswith(str(prefix)):
                    return str(et)

    # 2. field_inference: 字段名精确匹配
    fn = str(field_name or "").lower()
    fi = cfg.get("field_inference", {}) or {}
    if fn in fi:
        return str(fi[fn])

    # 3. field_class_inference: 字段的语义类型 → 实体类型
    fci = cfg.get("field_class_inference", {}) or {}
    if fci and fn:
        try:
            from tools.assessment.semantic_type import infer_semantic_type
            st = infer_semantic_type(field_name, "", None).get("semantic_type", "")
            if st in fci:
                return str(fci[st])
        except Exception:
            pass

    # 4. 默认
    return str(cfg.get("default_entity_type", "galaxy"))


def normalize_entity_type(entity_type: str, field_name: str = "",
                          source: dict | None = None,
                          domain: str = "astrophysics") -> str:
    """实体类型规范化。

    - "Unknown"/空 → infer_entity_type 推断
    - 已知值 → kws 别名查规范名 (Quasar → quasar)
    - 未识别值 → 小写原样返回 (兼容 FRB 等非 Simbad 类型, KB 双向子串匹配不受影响)
    """
    raw = str(entity_type or "").strip()
    cfg = _load(domain)

    if not raw or raw.lower() in ("unknown", "none", "n/a"):
        return infer_entity_type(field_name, source, domain)

    types = _types_map(domain)
    # 已是指定规范名 → 原样 (小写)
    if _name_to_entry(types, raw):
        return raw.lower()
    # kws 别名匹配
    canonical = _kws_lookup(types, raw)
    if canonical:
        return canonical
    return raw.lower()


def entity_ancestors(entity_type: str, domain: str = "astrophysics") -> list[str]:
    """返回 [自身] + 所有祖先的规范名 (父链按 code 上溯)。

    如 quasar → [quasar, agn, galaxy]; 未知类型 → [自身小写]。
    """
    types = _types_map(domain)
    entry = _name_to_entry(types, entity_type)
    if not entry:
        return [str(entity_type).lower()]

    result = [str(entry.get("name", entity_type)).lower()]
    parent_code = entry.get("parent")
    seen = set(result)
    guard = 0
    while parent_code and guard < 8:  # 层级 ≤4, 8 为安全上限
        guard += 1
        p_entry = types.get(str(parent_code))
        if not isinstance(p_entry, dict):
            break
        p_name = str(p_entry.get("name", "")).lower()
        if not p_name or p_name in seen:
            break
        result.append(p_name)
        seen.add(p_name)
        parent_code = p_entry.get("parent")
    return result


def get_typical_range(entity_type: str, field_name: str,
                      domain: str = "astrophysics") -> str | None:
    """典型范围兜底: 字段 → 语义类型 → typical_ranges[实体][语义键] → "lo~hi unit"。

    unit 取 semantic_types_astrophysics 该键 units[0]; 无匹配 → None。
    """
    cfg = _load(domain)
    if not cfg:
        return None
    tr = cfg.get("typical_ranges", {}) or {}
    et_entry = tr.get(str(entity_type).lower())
    if not et_entry:
        return None

    # 字段 → 语义类型
    try:
        from tools.assessment.semantic_type import infer_semantic_type
        sem_key = infer_semantic_type(field_name, "", None).get("semantic_type", "")
    except Exception:
        sem_key = ""
    if not sem_key or sem_key not in et_entry:
        return None

    try:
        lo, hi = float(et_entry[sem_key][0]), float(et_entry[sem_key][1])
    except (TypeError, ValueError, IndexError):
        return None

    # 单位: semantic_types 该键 units[0]
    unit = ""
    try:
        from configs import load_domain_config
        st_cfg = load_domain_config("semantic_types", "semantic_types") or {}
        rule = st_cfg.get(sem_key, {})
        units = rule.get("units", []) or []
        unit = str(units[0]) if units else ""
    except Exception:
        pass

    def _fmt(x: float) -> str:
        if abs(x) >= 1e6 or (abs(x) < 1e-3 and x != 0):
            return f"{x:.2e}"
        return f"{x:g}"

    return f"{_fmt(lo)}~{_fmt(hi)} {unit}".strip()


def build_entity_type_reference(field_summaries: list[dict],
                                domain: str = "astrophysics") -> str:
    """构建 field_insight prompt 的 {entity_type_reference} 内容。

    对出现的实体类型去重, 每类一行: "name (code): parent — typical 前 3 键"。
    配置缺失 → 返回空串 (绝不残留占位符)。
    """
    cfg = _load(domain)
    types = _types_map(domain)
    tr = cfg.get("typical_ranges", {}) or {}
    if not types:
        return ""

    entities = sorted({str(f.get("entity_type", "") or "") for f in field_summaries if f.get("entity_type")})
    if not entities:
        return ""

    lines = []
    for et in entities:
        entry = _name_to_entry(types, et)
        if not entry:
            continue
        name = str(entry.get("name", et))
        code = next((c for c, e in types.items() if isinstance(e, dict) and str(e.get("name", "")).lower() == name.lower()), "")
        parent = ""
        p_code = entry.get("parent")
        if p_code:
            p_entry = types.get(str(p_code))
            if isinstance(p_entry, dict):
                parent = f", parent: {p_entry.get('name', p_code)}"
        # typical 前 3 键
        typical_parts = []
        for k, v in (tr.get(name, {}) or {}).items():
            try:
                typical_parts.append(f"{k} {float(v[0]):.1e}~{float(v[1]):.1e}")
            except Exception:
                continue
            if len(typical_parts) >= 3:
                break
        typical_str = f"; typical {', '.join(typical_parts)}" if typical_parts else ""
        lines.append(f"  {name} ({code}){parent}{typical_str}")
    return "\n".join(lines)
