"""
test_kb_retrieval.py — P1-5 检索评测基准 (golden queries + recall@5/precision@5)

离线评测 (零 LLM 零网络), 直接对 knowledge_store.search 做 golden query 验证:

  Q1 ('dispersion_measure','redshift')   → 期望命中 DM_redshift_relation (Macquart relation)
  Q2 ('effective_temperature','O-type')  → star_teff_luminosity_span 类条目 (恒星 Teff 全域类)
  Q3 ('Chandrasekhar','limit')           → 白矮星相关条目 (content 匹配验证)

指标 (top_k=5, 相关条目集由 KB 内容确定性计算, 不依赖检索结果):
  - recall@5 ≥ 0.8  — 相关条目被召回的占比
  - precision@5 ≥ 0.6 — 相关条目占 top-5 的比例
    结构限制: 相关集 |rel| 与 KB 规模正相关 — KB 78 条时 Q1/Q3 相关集各 2 条,
    recall@5 上界 = |rel|/5; 第三轮扩展至 286 条后 Q3 (content 含 chandrasekhar) 相关集
    扩至 8 条, recall@5 结构上界 = 5/8 = 0.625 (顶配检索也不可能 ≥0.8), 故 Q3 的 top_k
    随相关集放宽到 8 (recall@8 保持 ≥0.8 门槛语义); Q1/Q2 相关集仍 ≤5, top_k=5 不变。
    |相关集| < 3 的查询断言: 全部相关条目已召回 (precision 达结构上界) + precision@3 ≥ 0.6;
    |相关集| ≥ 3 的查询断言 precision@5 ≥ 0.6。

运行: python -m pytest tests/test_kb_retrieval.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from quality_pipeline.tools.insight.knowledge_store import get_knowledge_store

# 知识库目录: astroquery_final/quality_pipeline/data/insight_knowledge/astrophysics
KB_DIR = (Path(__file__).resolve().parent.parent
          / "quality_pipeline" / "data" / "insight_knowledge" / "astrophysics")


# ══════════════════════════════════════════════════════════════
# 相关条目集: 确定性从 KB 内容计算 (独立于检索结果, 防止自证)
# ══════════════════════════════════════════════════════════════

def _load_entries() -> list[dict]:
    from quality_pipeline.configs import load_yaml
    entries: list[dict] = []
    for yf in sorted(KB_DIR.glob("*.yaml")):
        data = load_yaml(str(yf)) or {}
        entries.extend(data.get("entries", []))
    return entries


def _text(e: dict) -> str:
    """聚合条目全部可检索文本 (title/content/tags/hypothetical_queries/applies_to/category)。"""
    applies = e.get("applies_to") or {}
    parts = [
        e.get("title", ""), e.get("content", ""),
        " ".join(e.get("tags", []) or []),
        " ".join(e.get("hypothetical_queries", []) or []),
        " ".join(applies.get("fields", []) or []),
        " ".join(applies.get("entities", []) or []),
        " ".join(applies.get("methods", []) or []),
        e.get("category", ""),
    ]
    return " ".join(str(p) for p in parts).lower()


def _relevant_q1(entries: list[dict]) -> list[str]:
    """Q1 相关: 文本同时含 dispersion_measure 与 redshift (物理定律/测量理论类双词命中)。"""
    return [e["id"] for e in entries
            if "dispersion_measure" in _text(e) and "redshift" in _text(e)]


def _relevant_q2(entries: list[dict]) -> list[str]:
    """Q2 相关: star_teff_luminosity_span 类 — reference_range 类目 ∩ effective_temperature
    字段 ∩ teff/temperature 标签 (恒星 Teff 全域参考类)。"""
    out = []
    for e in entries:
        fields = (e.get("applies_to") or {}).get("fields", []) or []
        tags = [str(t).lower() for t in (e.get("tags") or [])]
        if (e.get("category") == "reference_range"
                and "effective_temperature" in fields
                and any("teff" in t or "temperature" in t for t in tags)):
            out.append(e["id"])
    return out


def _relevant_q3(entries: list[dict]) -> list[str]:
    """Q3 相关: content 含 chandrasekhar (白矮星相关, content 匹配验证)。"""
    return [e["id"] for e in entries
            if "chandrasekhar" in str(e.get("content", "")).lower()]


# ══════════════════════════════════════════════════════════════
# 指标断言
# ══════════════════════════════════════════════════════════════

def _assert_metrics(name: str, ids: list[str], relevant: list[str]) -> None:
    hits = len(set(ids) & set(relevant))
    recall = hits / len(relevant)
    assert recall >= 0.8, f"{name}: recall@k={recall:.2f} < 0.8 (hits={hits}/{len(relevant)})"
    # precision@5 恒取 top-5 窗口 (与指标名一致, 与 top_k 松耦合)
    precision = len(set(ids[:5]) & set(relevant)) / 5
    if len(relevant) >= 3:
        assert precision >= 0.6, f"{name}: precision@5={precision:.2f} < 0.6"
    else:
        # 结构限制: 相关集 <3 → precision@5 上界 = len(rel)/5,
        # 断言已达上界 (全部相关条目召回) + precision@3 ≥ 0.6
        assert hits == len(relevant), f"{name}: 相关条目未全部召回 {hits}/{len(relevant)}"
        p3 = len(set(ids[:3]) & set(relevant)) / 3
        assert p3 >= 0.6, f"{name}: precision@3={p3:.2f} < 0.6"


# ══════════════════════════════════════════════════════════════
# golden query 集
# ══════════════════════════════════════════════════════════════

GOLDEN = [
    pytest.param(
        "Q1_DM_redshift", ["dispersion_measure"], ["redshift"],
        _relevant_q1, {"DM_redshift_relation"}, None, 5,
        id="Q1_dispersion_measure_redshift",
    ),
    pytest.param(
        "Q2_star_teff", ["effective_temperature"], ["O-type"],
        _relevant_q2, {"star_teff_luminosity_span"}, None, 5,
        id="Q2_effective_temperature_Otype",
    ),
    # Q3: KB 286 条后相关集 8 条, top_k=5 时 recall 结构上界 0.625, 放宽到 top_k=8
    pytest.param(
        "Q3_chandrasekhar", [], ["Chandrasekhar"],
        _relevant_q3, {"chandrasekhar_limit"}, "白矮星", 8,
        id="Q3_Chandrasekhar_limit",
    ),
]


@pytest.mark.parametrize(
    "name,field_names,keywords,rel_fn,expected_ids,content_marker,top_k", GOLDEN,
)
def test_golden_query_retrieval(name, field_names, keywords, rel_fn, expected_ids, content_marker, top_k):
    """每条 golden query: 期望命中 top-k + recall@k ≥ 0.8 + precision ≥ 0.6 (结构可达时)。"""
    kb = get_knowledge_store("astrophysics")
    entries = _load_entries()
    top = kb.search(field_names=field_names, keywords=keywords, top_k=top_k)
    ids = [e["id"] for e in top]
    assert top, f"{name}: 检索结果为空"
    missing = expected_ids - set(ids)
    assert not missing, f"{name}: 期望命中 {missing} 不在 top5 {ids}"
    if content_marker:
        for e in top:
            if e["id"] in expected_ids:
                assert content_marker in str(e.get("content", "")), \
                    f"{name}: 命中条目 content 匹配失败 ({e['id']})"
    relevant = rel_fn(entries)
    assert relevant, f"{name}: 相关条目集为空 — 检查 golden 定义"
    _assert_metrics(name, ids, relevant)


def test_semantic_recall_path():
    """P1-4: 规则 0 分但 TF-IDF>0 的条目进入候选 (提 recall)。

    "radius" 高频词的 top 全为规则命中条目, 语义兜底条目位于候选尾部
    (rank 10-12), 故窗口放宽到 top_k=12 验证语义路径仍生效。
    KB 286 条 (第三轮) 后 tfidf 排名随库扩容漂移, 代表条目由 white_dwarf_parameters
    更新为 globular_cluster_range (rule_score=0 且 tfidf>0, rank 10)。"""
    kb = get_knowledge_store("astrophysics")
    top = kb.search(keywords=["radius"], top_k=12)
    rule0 = [e for e in top if e.get("rule_score", 0) == 0 and e["score"] > 0]
    assert rule0, f"规则 0 分但 tfidf>0 的条目未进入候选: {[(e['id'], e['score']) for e in top]}"
    assert any(e["id"] == "globular_cluster_range" for e in rule0), \
        f"期望 globular_cluster_range 经 tfidf 进入候选: {[e['id'] for e in rule0]}"


def test_lexical_embedder_cosine():
    """LexicalEmbedder 单元: 余弦相似度 + 单位符号保留 tokenize。"""
    from quality_pipeline.tools.insight.embedder import LexicalEmbedder, tokenize

    assert tokenize("pc cm⁻³ at z~1, M☉, μm") == ["pc", "cm3", "at", "z", "1", "msun", "um"]

    entries = _load_entries()
    emb = LexicalEmbedder(entries)
    chand = next(e for e in entries if e["id"] == "chandrasekhar_limit")
    sim = emb.cosine(["chandrasekhar", "limit"], chand)
    assert sim > 0.0, f"chandrasekhar_limit 余弦应为正, got {sim}"
    assert emb.cosine(["zzz_unrelated_token"], chand) == 0.0


def test_kb_loaded():
    """知识库非空 (纯 LLM 降级模式会静默返回 [] — 评测前提)。"""
    kb = get_knowledge_store("astrophysics")
    assert kb.entry_count >= 78, f"知识库条目过少: {kb.entry_count}"
