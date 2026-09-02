"""
rag_property_matcher.py — RAG 性质库匹配器 (P1-1)

rag_properties/ (100 文件 / 3293 条性质, 含逐星表口径细节) 与 insight KB
同命名空间但运行时零关联。本模块按 otype 文件名懒加载 JSON (进程级缓存),
对 DB 原始列提供目录口径解读 (name_cn / description / unit / category)。

0 LLM 纯查找; rag_properties 缺失/解析失败 → lookup 返回 None (绝不崩溃)。

文件名映射 (与 astroquery_ai/property_standardization.py 同源约定):
  galaxy → G.json, star → _star.json (Simbad 紧凑码 `*` 在文件系统转义为 _star),
  其他实体类型规范名 → 按 entity_types 配置反向索引 (name → code → 文件名)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ...utils.logger import get_logger

logger = get_logger(__name__)

# rag_properties 根目录: 项目根 /rag_properties
# (本文件: quality_pipeline/tools/insight/rag_property_matcher.py → 上溯 4 级)
_RAG_ROOT = Path(__file__).parent.parent.parent.parent / "rag_properties"


def _escape_filename(code: str) -> str:
    """Simbad 紧凑码 → 文件名片段 (* → _star, / → _, 空格 → _)。"""
    return code.strip().replace("*", "_star").replace("/", "_").replace(" ", "_")


# 实体规范名 → 文件名 特例 (Simbad 紧凑码为 YAML/文件系统保留字符)
_SPECIAL_NAME_TO_FILE = {
    "galaxy": "G.json",
    "star": "_star.json",
}


class RagPropertyMatcher:
    """按 otype 文件名懒加载 RAG 性质库 — 进程级缓存 {otype: {property_id: entry}}。

    lookup(entity_type, field_name) → {name_cn, description, unit, category} | None。
    """

    # 进程级缓存 (多实例共享, 懒加载; 类属性规避实例重复建索引)
    _cache: dict[str, dict[str, dict]] = {}       # 文件名 → {property_id: entry}
    _name_to_file: dict[str, str] = {}            # 实体规范名 → 文件名
    _available: Optional[frozenset[str]] = None   # rag_properties 目录内 *.json
    _resolved: dict[str, Optional[str]] = {}      # entity_type → 文件名 (含负缓存)

    def __init__(self, domain: str = "astrophysics"):
        self._domain = domain or "astrophysics"

    # ── 懒加载辅助 ──

    def _available_files(self) -> frozenset[str]:
        if RagPropertyMatcher._available is None:
            try:
                avail = (frozenset(p.name for p in _RAG_ROOT.glob("*.json"))
                         if _RAG_ROOT.exists() else frozenset())
            except Exception as e:
                logger.warning("[RagPropertyMatcher] rag_properties 扫描失败: %s", e)
                avail = frozenset()
            RagPropertyMatcher._available = avail
            if not avail:
                logger.warning("[RagPropertyMatcher] rag_properties 缺失/为空: %s — 纯 LLM 模式", _RAG_ROOT)
        return RagPropertyMatcher._available

    def _build_name_to_file(self) -> dict[str, str]:
        """实体规范名 → 文件名: 特例 + entity_types 配置反向索引 (name → code)。"""
        if RagPropertyMatcher._name_to_file:
            return RagPropertyMatcher._name_to_file
        mapping = dict(_SPECIAL_NAME_TO_FILE)
        try:
            from ...configs import load_domain_config
            cfg = load_domain_config("entity_types", "entity_types",
                                     research_domain=self._domain) or {}
            avail = self._available_files()
            for code, entry in (cfg.get("types") or {}).items():
                if not isinstance(entry, dict):
                    continue
                fname = _escape_filename(str(code)) + ".json"
                name = str(entry.get("name", "")).lower().strip()
                if name and fname in avail:
                    mapping[name] = fname
        except Exception as e:
            logger.warning("[RagPropertyMatcher] 名称→文件索引构建失败: %s", e)
        RagPropertyMatcher._name_to_file = mapping
        return mapping

    def _resolve_file(self, entity_type: str) -> Optional[str]:
        """实体类型 → rag_properties 文件名 (失败/未知 → None)。"""
        et = str(entity_type or "").strip().lower()
        if not et:
            return None
        if et in RagPropertyMatcher._resolved:
            return RagPropertyMatcher._resolved[et]
        fname = self._resolve_file_uncached(et)
        RagPropertyMatcher._resolved[et] = fname  # 含 None 负缓存, 避免重复失败
        return fname

    def _resolve_file_uncached(self, et: str) -> Optional[str]:
        avail = self._available_files()
        if not avail:
            return None
        # 1. 规范名直接命中 (galaxy→G.json, star→_star.json, quasar→QSO.json...)
        fname = self._build_name_to_file().get(et)
        if fname and fname in avail:
            return fname
        # 2. 实体类型本身即文件名 (Simbad code; 大小写不敏感: G→G.json, sbg→SBG.json)
        direct = _escape_filename(et) + ".json"
        if direct in avail:
            return direct
        direct_l = direct.lower()
        for f in avail:
            if f.lower() == direct_l:
                return f
        return None

    def _load(self, entity_type: str) -> Optional[dict]:
        """按 otype 文件名懒加载 JSON → {property_id: entry} (进程级缓存)。"""
        fname = self._resolve_file(entity_type)
        if not fname:
            return None
        cache = RagPropertyMatcher._cache
        if fname not in cache:
            fp = _RAG_ROOT / fname
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                props = data.get("properties", []) or []
                cache[fname] = {
                    str(p.get("property_id", "")): p
                    for p in props if p.get("property_id")
                }
            except Exception as e:
                logger.warning("[RagPropertyMatcher] 加载 %s 失败: %s — 降级 None", fname, e)
                cache[fname] = {}  # 负缓存
        return cache[fname]

    # ── 对外接口 ──

    def lookup(self, entity_type: str, field_name: str) -> Optional[dict]:
        """实体类型 + 字段名 → {name_cn, description, unit, category} | None。

        0 LLM 纯查找; rag_properties 缺失/字段未收录/任何异常 → None (绝不崩溃)。
        """
        try:
            props = self._load(entity_type)
            if not props:
                return None
            key = str(field_name or "").strip()
            entry = props.get(key) or props.get(key.lower())
            if not entry or not isinstance(entry, dict):
                return None
            return {
                "name_cn": str(entry.get("name_cn", "") or ""),
                "description": str(entry.get("description", "") or ""),
                "unit": str(entry.get("unit", "") or ""),
                "category": str(entry.get("category", "") or ""),
            }
        except Exception:
            return None
