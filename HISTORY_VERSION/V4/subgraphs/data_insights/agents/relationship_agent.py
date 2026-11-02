"""
relationship_agent.py — Node 2: RelationshipAgent (V3.4)

职责: 识别跨字段物理关系 (物理定律/相关性/条件依赖)。
输入: Node 1 输出 + 字段对 + RAG 检索 (physical_laws, astrophysical_models)
输出: cross_field_relationships → report_state.insights.relationships

特殊处理: 样本 < 2 → 跳过 LLM, 仅输出 kb 预定义关系 (data_evidence=insufficient_data)。
V3.4: DB 字段名先映射到标准名再匹配知识 (复用 schema_mapping.yaml aliases)。
"""
from __future__ import annotations

import datetime
import json
import re
import time
from typing import Any

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.llm import get_llm, set_agent_context, track_raw_llm_call
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

# V3.5: 领域常量从 domain_config 读取
from quality_pipeline.configs.domain_config import (
    DEFAULT_DOMAIN, KB_CATEGORIES_RELATIONSHIP, KB_TOP_K,
    MAX_INSIGHTS_CHARS, MAX_PAIRS_CHARS, MAX_FIELD_PAIRS, MIN_RECORDS_FOR_RELATION,
)


class RelationshipAgent:
    """Node 2: 跨字段关系 — 物理约束/相关性检测。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ctx = state.get("context_state", {})
        domain = ctx.get("research_domain", DEFAULT_DOMAIN)
        rs = state.get("report_state", {}) or {}
        insights_state = rs.get("insights") or {}
        field_insights = insights_state.get("field_insights", []) or []

        # ── 字段对 (从数据中提取, DB 字段名映射到标准名) ──
        from quality_pipeline.tools.insight.context_builder import build_field_summaries
        summaries = build_field_summaries(state)
        # P1-2: PropertySpec 权威单轨 — target_schema (property_id) 优先, schema_mapping 回退
        std_map, std_prov = _build_standard_name_map(ctx)
        if std_prov:
            src_counts = {}
            for p in std_prov.values():
                src_counts[p["source"]] = src_counts.get(p["source"], 0) + 1
            logger.info("[Relationship] 标准名映射 %d 条 (来源: %s)",
                        len(std_prov), src_counts)
        field_pairs = _build_field_pairs(summaries, std_map)

        relationships: list[dict] = []

        # ── 样本 < 2 → 跳过 LLM, 用知识库预定义关系 ──
        distinct_fields = {f["field_name"] for f in summaries}
        if len(distinct_fields) < 2:
            kb_rels = _kb_preset_relationships(field_pairs, state, domain)
            relationships = kb_rels
            logger.info("[Relationship] <2 fields → kb preset only (%d)", len(kb_rels))
            return self._return(state, relationships, t0, "insufficient_data")

        # M-34 fix: field_pairs 空守卫 — distinct 字段 ≥2 但全部未过 MIN_RECORDS_FOR_RELATION
        # 过滤 (单条记录无统计意义) → 无有效配对, 跳过 LLM 走 kb preset 返回
        if not field_pairs:
            relationships = _kb_preset_relationships(field_pairs, state, domain)
            logger.info("[Relationship] 无有效字段对 → kb preset only (%d)", len(relationships))
            return self._return(state, relationships, t0, "insufficient_data")

        # ── RAG 检索 ──
        from quality_pipeline.tools.insight.knowledge_store import get_knowledge_store
        kb = get_knowledge_store(domain)
        pair_fields = [f for pair in field_pairs for f in pair["fields"]]
        kb_results = kb.search(
            field_names=pair_fields,
            keywords=pair_fields,
            categories=KB_CATEGORIES_RELATIONSHIP,
            top_k=KB_TOP_K,
        )
        knowledge_block = _format_knowledge_block(kb_results)

        # ── LLM 调用 ──
        llm_count = state.get("workflow_state", {}).get("llm_call_count", 0)
        try:
            set_agent_context("relationship")
            from quality_pipeline.configs import load_yaml
            prompts = load_yaml("insight_prompts.yaml")
            # V3.4 fix: replace 替代 format (JSON 示例裸花括号)
            system = prompts["relationship"]["system"].replace("{domain}", domain)
            user = prompts["relationship"]["user"]
            user = user.replace("{field_insights}", json.dumps(field_insights, ensure_ascii=False, indent=1)[:MAX_INSIGHTS_CHARS])
            user = user.replace("{field_pairs}", json.dumps(field_pairs, ensure_ascii=False, indent=1)[:MAX_PAIRS_CHARS])
            user = user.replace("{knowledge_block}", knowledge_block)
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
            text = resp.content if hasattr(resp, "content") else str(resp)
            # L-18 fix: 调用计数在 invoke 成功后、json.loads 前递增 (解析失败不吞计数)
            llm_count += 1
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                relationships = data.get("relationships", []) if isinstance(data, dict) else []
            track_raw_llm_call(time.time() - t0, agent="relationship")
        except Exception as e:
            logger.warning("[Relationship] LLM failed: %s — kb preset", e)
            relationships = _kb_preset_relationships(field_pairs, state, domain)

        # H5 fix: LLM 输出类型校验 — 非 list 置空 (防字符串逐字符迭代 AttributeError)
        if not isinstance(relationships, list):
            logger.warning("[Relationship] LLM relationships 非 list (%s), 置空",
                           type(relationships).__name__)
            relationships = []

        # 标记 data_evidence
        for r in relationships:
            r.setdefault("data_evidence", "sufficient_data")

        elapsed = round(time.time() - t0, 3)
        logger.info("[Relationship] %d field pairs → %d relationships (%.2fs)",
                    len(field_pairs), len(relationships), elapsed)
        return self._return(state, relationships, t0, "ok", llm_count, elapsed)

    def _return(self, state, relationships, t0, reason, llm_count=None, elapsed=0.0):
        rs = state.get("report_state", {}) or {}
        existing = dict(rs.get("insights") or {})
        existing["relationships"] = relationships
        # H-16 fix (R1-B8 回归): 透传上游 Failed — 前序节点失败时本节点不再覆写 Success
        upstream_status = (state.get("workflow_state") or {}).get("execution_status") or "Success"
        exec_status = "Failed" if upstream_status == "Failed" else "Success"
        ret = {
            "report_state": {"insights": existing},
            "workflow_state": {
                "current_node": "relationship",
                "execution_status": exec_status,
                "workflow_history": [{
                    "agent": "RelationshipAgent", "stage": "Relationship",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(relationships)} relationships ({reason})",
                }],
            },
        }
        if llm_count is not None:
            ret["workflow_state"]["llm_call_count"] = llm_count
        return ret


def _build_standard_name_map(ctx) -> tuple[dict, dict]:
    """构建 DB 列名 → 标准名映射 (P1-2: PropertySpec 权威单轨)。

    优先 target_schema (RAG P1 生成, quality_adapter 注入 context_state —
    字段名即 property_id 标准名); 其次回退 schema_mapping.yaml (现有逻辑)。
    回退源不覆盖 target_schema 已有项, 避免 PropertySpec 变更时映射静默失效。

    Returns:
        (mapping, provenance):
          mapping:     {lower_name → standard_name}
          provenance:  {lower_name → {"standard": name,
                                      "source": "target_schema"|"schema_mapping"}}
                       (每条映射来源记录, 供审计)
    """
    mapping: dict[str, str] = {}
    provenance: dict[str, dict] = {}

    # 1. 权威源: target_schema (PropertySpec) — 字段名 = property_id 即标准名
    for f in ((ctx.get("target_schema") or {}).get("fields") or []):
        name = str(f.get("name", "") or "").strip()
        if not name:
            continue
        nl = name.lower()
        mapping[nl] = name
        provenance[nl] = {"standard": name, "source": "target_schema"}

    # 2. 回退源: schema_mapping.yaml (不覆盖 target_schema 已有项)
    try:
        from quality_pipeline.configs import load_yaml
        cfg = load_yaml("schema_mapping.yaml")
        target = cfg.get("target_schema_astrophysics") or cfg.get("target_schema") or {}
        for f in target.get("fields", []):
            name = str(f.get("name", "") or "")
            if not name:
                continue
            nl = name.lower()
            if nl not in mapping:
                mapping[nl] = name
                provenance[nl] = {"standard": name, "source": "schema_mapping"}
            for a in f.get("aliases", []):
                al = str(a).lower()
                if al not in mapping:
                    mapping[al] = name
                    provenance[al] = {"standard": name, "source": "schema_mapping"}
    except Exception:
        pass

    return mapping, provenance


def _build_field_pairs(summaries, std_map) -> list[dict]:
    """从字段摘要构建两两字段对 (V3.5 fix: 同实体约束 — 防止跨实体错误配对)。

    只有 (entity_type, entity_name) 相同的字段才生成关系候选,
    避免 FRB.dispersion_measure 与 Gaia.parallax 这类跨对象错误配对。
    记录数 < 2 的组不参与 (统计无意义)。
    """
    seen = set()
    pairs = []
    # 按 (entity_type, entity_name) 分组
    by_entity: dict[tuple, list[dict]] = {}
    for s in summaries:
        fn = s["field_name"]
        std = std_map.get(fn.lower(), fn)
        if s.get("record_count", 0) < MIN_RECORDS_FOR_RELATION:
            continue  # V3.5: 单条记录不参与关系 (统计无意义)
        ekey = (s.get("entity_type", ""), s.get("entity_name", ""))
        by_entity.setdefault(ekey, []).append({
            "raw": fn, "standard": std,
            "entity_type": s.get("entity_type", ""),
            "entity_name": s.get("entity_name", ""),
            "record_count": s["record_count"],
        })

    for ekey, fields in by_entity.items():
        for i in range(len(fields)):
            for j in range(i + 1, len(fields)):
                a, b = fields[i], fields[j]
                key = (ekey, tuple(sorted([a["standard"].lower(), b["standard"].lower()])))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "fields": [a["standard"], b["standard"]],
                    "left_entity": {"entity_type": a["entity_type"], "entity_name": a["entity_name"]},
                    "right_entity": {"entity_type": b["entity_type"], "entity_name": b["entity_name"]},
                    "record_count": min(a["record_count"], b["record_count"]),  # P0-6: 有效配对样本 = min
                })
    return pairs[:MAX_FIELD_PAIRS]  # 限制字段对数量


def _kb_preset_relationships(field_pairs, state, domain) -> list[dict]:
    """知识库预定义关系 (LLM 跳过时使用)。"""
    from quality_pipeline.tools.insight.knowledge_store import get_knowledge_store
    kb = get_knowledge_store(domain)
    rels = []
    for pair in field_pairs:
        a, b = pair["fields"]
        # 在知识库中检索这两字段相关的条目
        hits = kb.search(field_names=[a, b], top_k=2)
        for h in hits:
            kb_id = h.get("id", "")
            applies = h.get("applies_to", {}) or {}
            fields = [f.lower() for f in applies.get("fields", [])]
            if a.lower() in fields or b.lower() in fields:
                rels.append({
                    "field_a": a, "field_b": b,
                    "relationship_type": "physical_law" if h.get("category") in
                                        ("physical_law", "empirical_relation", "cosmological_relation")
                                        else "correlation",
                    "description": f"[kb:{kb_id}] {h.get('title', '')} — {str(h.get('content', ''))[:200]}",
                    "data_evidence": "insufficient_data",
                    "confidence": 0.0,
                    "kb_references": [f"kb:{kb_id}"],
                })
    return rels


def _format_knowledge_block(entries: list[dict]) -> str:
    if not entries:
        return "RELEVANT DOMAIN KNOWLEDGE: (none available)"
    lines = ["RELEVANT DOMAIN KNOWLEDGE:"]
    for e in entries:
        lines.append("---")
        lines.append(f"[kb:{e.get('id', '?')}] {e.get('title', '')}")
        lines.append(str(e.get("content", ""))[:500])
    lines.append("---\nUse this knowledge to inform your analysis. Cite kb:IDs.")
    return "\n".join(lines)
