"""
embedder.py — 词法语义检索 (TF-IDF, 纯标准库) (P1-4)

当前启用 lexic TF-IDF 混合检索 (knowledge_store.search):
    final_score = rule_score + KB_SEMANTIC_WEIGHT * tfidf_cosine(查询词, entry)

V2 可接入 embedding 模型实现真语义检索 — 本模块保留 Embedder 接口契约
(embed / semantic_search 未实现, 仅作未来扩展占位)。

LexicalEmbedder:
  - 构造时对条目列表构建 TF-IDF 向量 (token = 小写 + 正则 [a-z0-9]+ 拆分
    + 单位符号保留: 上下标/μ/☉ 折叠为 ASCII, 如 cm⁻³→cm3, M☉→msun)
  - 纯标准库: collections.Counter + math
  - cosine(query_tokens, entry) → float (条目级向量缓存, 已预计算)
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

# ── 单位符号折叠表: 上标/下标/希腊/太阳符号 → ASCII (保留单位 token) ──
_UNIT_FOLDS = str.maketrans({
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
    "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁻": "", "₋": "",        # 负号折叠, cm⁻³ → cm3 保持单 token
    "µ": "u", "μ": "u",      # 微米 μm → um
    "☉": "sun", "☾": "moon",
})
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """小写 + [a-z0-9]+ 拆分 + 单位符号保留 (上下标/μ/☉ 折叠为 ASCII)。"""
    if not text:
        return []
    t = str(text).lower().translate(_UNIT_FOLDS)
    return _TOKEN_RE.findall(t)


class LexicalEmbedder:
    """TF-IDF 词法向量检索 (纯标准库, 条目级向量缓存)。

    条目文本 = title + content + tags + hypothetical_queries + applies_to + category。
    权重: tf = 1 + log(频次) (次线性), idf = log((N+1)/(df+1)) + 1 (平滑)。
    """

    def __init__(self, entries: list[dict]):
        self._entries = list(entries or [])
        self._vectors: dict[str, dict[str, float]] = {}   # 条目 id → {token: tfidf}
        self._norms: dict[str, float] = {}                # 条目 id → 向量模长
        self._idf: dict[str, float] = {}                  # token → idf
        self._n = len(self._entries)
        if self._n:
            self._build()

    # ── 构造 ──
    @staticmethod
    def _entry_id(entry: dict) -> str:
        eid = entry.get("id")
        return eid if isinstance(eid, str) and eid else f"__idx{id(entry)}"

    @staticmethod
    def _entry_text(entry: dict) -> str:
        """聚合条目全部可检索文本 (title/content/tags/hypothetical_queries/applies_to/category)。"""
        applies = entry.get("applies_to") or {}
        parts = [
            entry.get("title", ""),
            entry.get("content", ""),
            " ".join(entry.get("tags", []) or []),
            " ".join(entry.get("hypothetical_queries", []) or []),
            " ".join(applies.get("fields", []) or []),
            " ".join(applies.get("entities", []) or []),
            " ".join(applies.get("methods", []) or []),
            entry.get("category", ""),
        ]
        return " ".join(str(p) for p in parts if p)

    def _build(self) -> None:
        docs: dict[str, Counter] = {}
        for e in self._entries:
            eid = self._entry_id(e)
            docs[eid] = Counter(tokenize(self._entry_text(e)))

        # df + 平滑 idf
        df: Counter = Counter()
        for toks in docs.values():
            df.update(set(toks))
        n = self._n
        idf = {tok: math.log((n + 1) / (d + 1)) + 1.0 for tok, d in df.items()}
        self._idf = idf

        # 条目向量 (tf = 1 + log count, 次线性) + 模长
        for eid, toks in docs.items():
            vec: dict[str, float] = {}
            norm2 = 0.0
            for tok, c in toks.items():
                w = (1.0 + math.log(c)) * idf[tok]
                vec[tok] = w
                norm2 += w * w
            self._vectors[eid] = vec
            self._norms[eid] = math.sqrt(norm2)

    # ── 查询 ──
    def cosine(self, query_tokens: Any, entry: dict) -> float:
        """查询词与条目的 TF-IDF 余弦相似度。

        Args:
            query_tokens: Counter | list[str] | str — 查询词 (未分词 str 自动 tokenize)
            entry: 知识库条目 dict (按 id 查向量, 浅拷贝 dict 亦可)

        Returns:
            0.0 ~ 1.0 余弦相似度; 空查询/未知条目 → 0.0
        """
        if not self._vectors or not query_tokens:
            return 0.0
        if isinstance(query_tokens, str):
            q = Counter(tokenize(query_tokens))
        elif isinstance(query_tokens, Counter):
            q = query_tokens
        else:
            q = Counter(tokenize(" ".join(str(t) for t in query_tokens)))

        eid = self._entry_id(entry)
        vec = self._vectors.get(eid)
        e_norm = self._norms.get(eid, 0.0)
        if not vec or e_norm <= 0.0 or not q:
            return 0.0

        dot = 0.0
        q_norm2 = 0.0
        for tok, c in q.items():
            w = self._idf.get(tok, 0.0) * c   # 查询 tf = 原始频次
            q_norm2 += w * w
            if tok in vec:
                dot += w * vec[tok]
        if q_norm2 <= 0.0:
            return 0.0
        return dot / (math.sqrt(q_norm2) * e_norm)


# ══════════════════════════════════════════════════════════════
# V2 语义检索接口 (未启用 — 当前启用 lexic TF-IDF, 见模块 docstring)
# ══════════════════════════════════════════════════════════════

class Embedder:
    """语义检索接口 (V2 占位 — 当前启用 lexic TF-IDF 混合检索)。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本 → 向量。未实现时抛 NotImplementedError。"""
        raise NotImplementedError("V2 embedder 尚未接入 — 当前启用 lexic TF-IDF (LexicalEmbedder)")

    def semantic_search(self, query: str, corpus: list[dict], top_k: int = 5) -> list[dict]:
        """语义检索 (未实现)。"""
        raise NotImplementedError("V2 semantic_search 尚未接入")
