"""
knowledge_store.py — 天体物理理论知识库 (V3.4)

存储理论性知识 (物理定律/测量理论/标准模型/参考范围/方法论)，
供洞察节点检索引用。

检索策略 (V1): 关键词 + 标签 + 适用条件匹配评分。
可降级: 知识库文件缺失/为空/解析失败 → search() 返回 [] → 纯 LLM 模式。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ...utils.logger import get_logger

logger = get_logger(__name__)

# 知识库根目录: V1\子图4部分代码\data\insight_knowledge\{domain}\
_KB_ROOT = Path(__file__).parent.parent.parent / "data" / "insight_knowledge"

# 检索评分权重 (子计划 3.1)
_TAG_SCORE = 3          # tags 匹配关键词
_FIELD_SCORE = 5        # applies_to.fields 匹配 field_names
_ENTITY_SCORE = 3       # applies_to.entities 匹配 entity_types
_METHOD_SCORE = 3       # applies_to.methods 匹配 measurement_methods
_CATEGORY_SCORE = 2     # category 匹配
# V4 fix: Simbad 父类匹配加分 (低于直接命中, 不压过精确匹配)
try:
    from ...configs.domain_config import ENTITY_TYPE_PARENT_SCORE
    _PARENT_SCORE = ENTITY_TYPE_PARENT_SCORE
except Exception:
    _PARENT_SCORE = 2


class KnowledgeStore:
    """天体物理理论知识库 — 加载 + 关键词检索。"""

    def __init__(self, domain: str = "astrophysics"):
        self._domain = domain
        self._entries: list[dict] = []
        # V4 fix: 实体祖先链缓存 (Simbad 父类匹配, 一次配置加载 N 次查询复用)
        self._family_cache: dict[str, list[str]] = {}
        self._load_all(domain)

    def _entity_families(self, entity_type: str) -> list[str]:
        """查询实体的祖先规范名 (不含自身, 如 quasar → [agn, galaxy])。"""
        if entity_type in self._family_cache:
            return self._family_cache[entity_type]
        try:
            from ...tools.insight.entity_types import entity_ancestors
            fam = entity_ancestors(entity_type, self._domain)[1:]
        except Exception:
            fam = []
        self._family_cache[entity_type] = fam
        return fam

    def _load_all(self, domain: str) -> None:
        """加载 domain 目录下所有 YAML 文件 (可降级: 缺文件/解析失败不崩溃)。"""
        base = _KB_ROOT / domain
        if not base.exists():
            logger.warning("[KnowledgeStore] 知识库目录不存在: %s — 纯 LLM 模式", base)
            return
        try:
            from ...configs import load_yaml
        except ImportError:
            return
        for yf in sorted(base.glob("*.yaml")):
            try:
                data = load_yaml(str(yf))
                entries = (data or {}).get("entries", [])
                if entries:
                    self._entries.extend(entries)
                    logger.info("[KnowledgeStore] 加载 %s: %d 条", yf.name, len(entries))
            except Exception as e:
                logger.warning("[KnowledgeStore] 跳过 %s (解析失败: %s)", yf.name, e)
        logger.info("[KnowledgeStore] 共加载 %d 条知识 (domain=%s)", len(self._entries), domain)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def search(
        self,
        field_names: list[str] | None = None,
        entity_types: list[str] | None = None,
        measurement_methods: list[str] | None = None,
        keywords: list[str] | None = None,
        categories: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """关键词 + 标签 + 适用条件匹配检索 (子计划 3.1 评分规则)。

        Returns:
            top_k 得分最高的条目 (含 score 字段)。
            知识库为空 → []。
        """
        if not self._entries:
            return []

        field_names = [f.lower() for f in (field_names or [])]
        entity_types = [e.lower() for e in (entity_types or [])]
        methods = [m.lower() for m in (measurement_methods or [])]
        keywords = [k.lower() for k in (keywords or [])]
        categories = [c.lower() for c in (categories or [])]

        scored = []
        for entry in self._entries:
            score = 0.0

            # tags 匹配关键词
            tags = [t.lower() for t in entry.get("tags", [])]
            for kw in keywords:
                if any(kw in t or t in kw for t in tags):
                    score += _TAG_SCORE

            # applies_to.fields 匹配 field_names
            applies = entry.get("applies_to", {}) or {}
            entry_fields = [f.lower() for f in applies.get("fields", [])]
            for fn in field_names:
                if any(fn == ef or fn in ef or ef in fn for ef in entry_fields):
                    score += _FIELD_SCORE

            # applies_to.entities
            entry_entities = [e.lower() for e in applies.get("entities", [])]
            for et in entity_types:
                if any(et == ee or et in ee or ee in et for ee in entry_entities):
                    score += _ENTITY_SCORE
                # V4 fix: 父类匹配 — 查询实体的 Simbad 祖先 (如 quasar→[agn,galaxy])
                # 命中条目加低一档分 (直接命中 +3, 父类 +2)
                for fam in self._entity_families(et):
                    if any(fam == ee or fam in ee or ee in fam for ee in entry_entities):
                        score += _PARENT_SCORE
                        break

            # applies_to.methods
            entry_methods = [m.lower() for m in applies.get("methods", [])]
            for mm in methods:
                if any(mm == em or mm in em or em in mm for em in entry_methods):
                    score += _METHOD_SCORE

            # category
            cat = (entry.get("category", "") or "").lower()
            if cat and cat in categories:
                score += _CATEGORY_SCORE

            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return [dict(e, score=round(s, 2)) for s, e in scored[:top_k]]

    def get_entry(self, kb_id: str) -> dict | None:
        """按 id 取条目 (用于 evidence_sources 引用解析)。"""
        for e in self._entries:
            if e.get("id") == kb_id:
                return e
        return None


# V3.5 fix: 按领域隔离的缓存 (防止跨领域复用污染)
_stores: dict[str, KnowledgeStore] = {}


def get_knowledge_store(domain: str = "astrophysics") -> KnowledgeStore:
    """获取指定领域的知识库 (每领域独立实例, 跨领域不污染)。"""
    global _stores
    if domain not in _stores:
        _stores[domain] = KnowledgeStore(domain)
    return _stores[domain]
