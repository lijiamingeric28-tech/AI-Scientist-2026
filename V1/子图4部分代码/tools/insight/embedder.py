"""
embedder.py — V2 向量检索接口 (占位, 暂不启用)

V1 使用关键词匹配 (knowledge_store.search), V2 可接入 embedding 模型
实现语义检索。本模块仅定义接口契约, 不实现。
"""
from __future__ import annotations

from typing import Any


class Embedder:
    """语义检索接口 (V2 占位)。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """文本 → 向量。未实现时抛 NotImplementedError。"""
        raise NotImplementedError("V2 embedder 尚未接入 — 当前使用 V1 关键词检索")

    def semantic_search(self, query: str, corpus: list[dict], top_k: int = 5) -> list[dict]:
        """语义检索 (未实现)。"""
        raise NotImplementedError("V2 semantic_search 尚未接入")
