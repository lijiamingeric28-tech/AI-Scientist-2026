"""
field_insight_agent.py — Node 1: FieldInsightAgent (V3.4)

职责: 对每个字段生成领域洞察 — 观测事实 (确定性) + LLM 解读 (结合知识库)。
输入: 字段摘要 + 来源摘要 + 质量上下文 + RAG 检索
输出: field_insights[] → report_state.insights.field_insights

容错: LLM 失败 → 模板生成 (observation 填充, interpretation="LLM 不可用", confidence=0.0)
"""
from __future__ import annotations

import datetime
import json
import re
import time
from typing import Any

from ...quality_state import QualityGraphState
from ...utils.llm import get_llm, set_agent_context, track_raw_llm_call
from ...utils.logger import get_logger

logger = get_logger(__name__)

# V3.5: 领域常量从 domain_config 读取 (Astronomy Domain Adapter)
from ...configs.domain_config import (
    DEFAULT_DOMAIN, KB_CATEGORIES_FIELD_INSIGHT, KB_TOP_K,
    MAX_FIELD_SUMMARIES_CHARS, MAX_SOURCE_SUMMARIES_CHARS,
)


class FieldInsightAgent:
    """Node 1: 领域洞察 — per-field 跨来源差异分析。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ctx = state.get("context_state", {})
        domain = ctx.get("research_domain", DEFAULT_DOMAIN)

        from ...tools.insight.context_builder import (
            build_field_summaries, build_source_summaries, build_quality_context,
        )
        from ...tools.insight.knowledge_store import get_knowledge_store

        field_summaries = build_field_summaries(state)
        source_summaries = build_source_summaries(state)
        quality_ctx = build_quality_context(state)

        insights: list[dict] = []

        # ── 无字段 → 快速返回 ──
        if not field_summaries:
            return self._return(state, [], t0, "no_fields")

        # ── RAG 检索 (per-field 聚合关键词) ──
        kb = get_knowledge_store(domain)
        all_fields = list({f["field_name"] for f in field_summaries})
        all_methods = list({m for f in field_summaries for m in f.get("methods", [])})
        all_entities = list({f["entity_type"] for f in field_summaries if f["entity_type"]})
        kb_results = kb.search(
            field_names=all_fields,
            entity_types=all_entities,
            measurement_methods=all_methods,
            keywords=all_fields + all_methods,
            categories=KB_CATEGORIES_FIELD_INSIGHT,
            top_k=KB_TOP_K,
        )
        knowledge_block = _format_knowledge_block(kb_results)

        # ── LLM 调用 ──
        llm_count = state.get("workflow_state", {}).get("llm_call_count", 0)
        try:
            set_agent_context("field_insight")
            prompts = _load_prompts()
            # V3.4 fix: 用 replace 替代 format — prompt 含 JSON 示例裸花括号, format 会抛 KeyError
            system = prompts["field_insight"]["system"].replace("{domain}", domain)
            # V4 fix: 注入 Simbad 对象类型参考 (当前数据出现的实体类型 + 典型范围),
            # 使 LLM 按对象类型解读测量值 (如星系 stellar_mass 1e11 是正常的)
            try:
                from ...tools.insight.entity_types import build_entity_type_reference
                et_ref = build_entity_type_reference(field_summaries, domain)
            except Exception:
                et_ref = ""
            system = system.replace("{entity_type_reference}", et_ref)
            user = prompts["field_insight"]["user"]
            user = user.replace("{field_summaries}", json.dumps(field_summaries, ensure_ascii=False, indent=1)[:MAX_FIELD_SUMMARIES_CHARS])
            user = user.replace("{source_summaries}", json.dumps(source_summaries, ensure_ascii=False, indent=1)[:MAX_SOURCE_SUMMARIES_CHARS])
            user = user.replace("{quality_context}", json.dumps(quality_ctx, ensure_ascii=False))
            user = user.replace("{knowledge_block}", knowledge_block)
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
            text = resp.content if hasattr(resp, "content") else str(resp)
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                insights = data.get("insights", [])
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="field_insight")
        except Exception as e:
            logger.warning("[FieldInsight] LLM failed: %s — template fallback", e)
            insights = []

        # ── 模板 fallback / 补全确定性 observation ──
        insights = _merge_with_deterministic(field_summaries, insights, kb)

        elapsed = round(time.time() - t0, 3)
        logger.info("[FieldInsight] %d fields → %d insights (%.2fs)",
                    len(field_summaries), len(insights), elapsed)
        return self._return(state, insights, t0, "ok", llm_count, elapsed)

    def _return(self, state, insights, t0, reason, llm_count=None, elapsed=0.0):
        rs = state.get("report_state", {}) or {}
        existing = dict(rs.get("insights") or {})
        existing["field_insights"] = insights
        ret = {
            "report_state": {"insights": existing},
            "workflow_state": {
                "current_node": "field_insight",
                "execution_status": "Success",
                "workflow_history": [{
                    "agent": "FieldInsightAgent", "stage": "FieldInsight",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"{len(insights)} insights ({reason})",
                }],
            },
        }
        if llm_count is not None:
            ret["workflow_state"]["llm_call_count"] = llm_count
        return ret


def _typical_range_fallback(entity_type: str, field_name: str) -> str | None:
    """V4 fix: 实体典型范围确定性兜底 (LLM 未提供时, 从 entity_types 配置读取)。"""
    try:
        from ...tools.insight.entity_types import get_typical_range
        return get_typical_range(entity_type, field_name)
    except Exception:
        return None


def _merge_with_deterministic(field_summaries, llm_insights, kb) -> list[dict]:
    """LLM 洞察与确定性 observation 合并; 缺字段的补模板。"""
    by_key = {}
    for ins in llm_insights:
        key = (ins.get("entity_type", ""), ins.get("entity_name", ""), ins.get("field_name", ""))
        by_key[key] = ins

    result = []
    for f in field_summaries:
        key = (f["entity_type"], f["entity_name"], f["field_name"])
        ins = by_key.get(key, {})
        # 确定性 observation
        obs_parts = []
        if f.get("value_range"):
            obs_parts.append(f"value range: {f['value_range']}")
        obs_parts.append(f"{f.get('record_count', 0)} records from {len(f.get('source_ids', []))} sources")
        if f.get("units"):
            obs_parts.append(f"units: {f['units']}")
        if f.get("methods"):
            obs_parts.append(f"methods: {f['methods']}")
        if f.get("conditions"):
            obs_parts.append(f"conditions: {f['conditions']}")
        observation = "; ".join(obs_parts) or f"No numeric values for {f['field_name']}"

        result.append({
            "entity_type": f["entity_type"],
            "entity_name": f["entity_name"],
            "field_name": f["field_name"],
            "source_type": f["source_type"],
            "observation": ins.get("observation", observation),
            "interpretation": ins.get("interpretation", "LLM 不可用 — 仅提供确定性观测事实"),
            "cause_hypotheses": ins.get("cause_hypotheses", []),
            # V4 fix: LLM 已给 typical_range 则保留, 否则实体类型配置兜底
            "typical_range": ins.get("typical_range") or _typical_range_fallback(f["entity_type"], f["field_name"]),
            "confidence": float(ins.get("confidence", 0.0)),
            "evidence_sources": [{"type": "data", "ref": "context_snippet"}] if f.get("context_snippets") else [],
            "kb_references": ins.get("kb_references", []) or [],
        })
    return result


def _format_knowledge_block(entries: list[dict]) -> str:
    """格式化 RELEVANT DOMAIN KNOWLEDGE 注入段 (子计划 3.3)。"""
    if not entries:
        return "RELEVANT DOMAIN KNOWLEDGE: (none available)"
    lines = ["RELEVANT DOMAIN KNOWLEDGE:"]
    for e in entries:
        lines.append("---")
        lines.append(f"[kb:{e.get('id', '?')}] {e.get('title', '')}")
        lines.append(str(e.get("content", ""))[:500])
        src = e.get("source", "")
        if src:
            lines.append(f"Source: {src}")
    lines.append("---\nUse this knowledge to inform your analysis. Cite kb:IDs in evidence_sources.")
    return "\n".join(lines)


def _load_prompts() -> dict:
    from ...configs import load_yaml
    prompts = load_yaml("insight_prompts.yaml") or {}
    if not prompts:
        raise RuntimeError("insight_prompts.yaml 缺失")
    return prompts
