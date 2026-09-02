"""
field_insight_agent.py — Node 1: FieldInsightAgent (V3.4)

职责: 对每个字段生成领域洞察 — 观测事实 (确定性) + LLM 解读 (结合知识库)。
输入: 字段摘要 + 来源摘要 + 质量上下文 + RAG 检索
输出: field_insights[] → report_state.insights.field_insights

容错: LLM 失败 → 模板生成 (observation 填充, interpretation="LLM 不可用", confidence=0.0)
P0-4: 字段分批 (INSIGHT_BATCH_SIZE=6) 调 LLM, 批次上限 MAX_INSIGHT_BATCHES=3 —
      超出上限的字段不再调 LLM, 合并时以诚实文案标记 (LLM 未覆盖), confidence=0。
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

# V3.5: 领域常量从 domain_config 读取 (Astronomy Domain Adapter)
from quality_pipeline.configs.domain_config import (
    DEFAULT_DOMAIN, INSIGHT_BATCH_SIZE, KB_CATEGORIES_FIELD_INSIGHT, KB_TOP_K,
    MAX_FIELD_SUMMARIES_CHARS, MAX_INSIGHT_BATCHES, MAX_SOURCE_SUMMARIES_CHARS,
)

# P0-4: 未被任何 batch 覆盖的字段 → 诚实文案 (LLM 确实没看过这些字段, 不冒充)
HONEST_UNCOVERED_TEXT = "LLM 未覆盖该字段 (超出分批上限), 仅确定性观测"
LLM_UNAVAILABLE_TEXT = "LLM 不可用 — 仅提供确定性观测事实"


class FieldInsightAgent:
    """Node 1: 领域洞察 — per-field 跨来源差异分析。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ctx = state.get("context_state", {})
        domain = ctx.get("research_domain", DEFAULT_DOMAIN)

        from quality_pipeline.tools.insight.context_builder import (
            build_field_summaries, build_source_summaries, build_quality_context,
        )
        from quality_pipeline.tools.insight.knowledge_store import get_knowledge_store

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
        # P1-1: RAG 目录性质注记 (DB 字段口径解读) — 追加段, 无匹配整段省略;
        # 追加在 knowledge_block 内 → 所有 P0-4 批次共享同一注记
        catalog_block = _format_catalog_property_notes(field_summaries)
        if catalog_block:
            knowledge_block = f"{knowledge_block}\n\n{catalog_block}"

        # ── LLM 调用 (P0-4: 按 INSIGHT_BATCH_SIZE 分批, 上限 MAX_INSIGHT_BATCHES) ──
        # 每块独立构造一次 LLM 调用 (temperature=0, 同一 prompt 模板, 仅替换 {field_summaries});
        # 单批失败 → 该批回退模板, 不影响其他批; llm_call_count 按实际批次数累加。
        llm_count = state.get("workflow_state", {}).get("llm_call_count", 0)
        llm_insights: list[dict] = []
        batches = [field_summaries[i:i + INSIGHT_BATCH_SIZE]
                   for i in range(0, len(field_summaries), INSIGHT_BATCH_SIZE)]
        active_batches = batches[:MAX_INSIGHT_BATCHES]
        prompts = None
        for b_idx, batch in enumerate(active_batches, start=1):
            b_t0 = time.time()
            try:
                set_agent_context("field_insight")
                if prompts is None:
                    prompts = _load_prompts()
                # V3.4 fix: 用 replace 替代 format — prompt 含 JSON 示例裸花括号, format 会抛 KeyError
                system = prompts["field_insight"]["system"].replace("{domain}", domain)
                # V4 fix: 注入 Simbad 对象类型参考 (本批出现的实体类型 + 典型范围),
                # 使 LLM 按对象类型解读测量值 (如星系 stellar_mass 1e11 是正常的)
                try:
                    from quality_pipeline.tools.insight.entity_types import build_entity_type_reference
                    et_ref = build_entity_type_reference(batch, domain)
                except Exception:
                    et_ref = ""
                system = system.replace("{entity_type_reference}", et_ref)
                user = prompts["field_insight"]["user"]
                user = user.replace("{field_summaries}", json.dumps(batch, ensure_ascii=False, indent=1)[:MAX_FIELD_SUMMARIES_CHARS])
                user = user.replace("{source_summaries}", json.dumps(source_summaries, ensure_ascii=False, indent=1)[:MAX_SOURCE_SUMMARIES_CHARS])
                user = user.replace("{quality_context}", json.dumps(quality_ctx, ensure_ascii=False))
                # P1-6/P1-2: 注入权威标准单位 (来自 PropertySpec target_schema)
                try:
                    _ts = (state.get("context_state", {}) or {}).get("target_schema", {}) or {}
                    _std_units = {
                        f.get("name", ""): f.get("standard_unit", "")
                        for f in (_ts.get("fields", []) or []) if f.get("name")
                    }
                    user = user.replace("{standard_units}",
                                        json.dumps(_std_units, ensure_ascii=False) if _std_units
                                        else "(none provided)")
                except Exception:
                    user = user.replace("{standard_units}", "(none provided)")
                user = user.replace("{knowledge_block}", knowledge_block)
                llm = get_llm(temperature=0.0)
                resp = llm.invoke([{"role": "system", "content": system},
                                   {"role": "user", "content": user}])
                text = resp.content if hasattr(resp, "content") else str(resp)
                # L-18 fix: 调用计数在 invoke 成功后、json.loads 前递增 (解析失败不吞计数)
                llm_count += 1
                m = re.search(r'\{.*\}', text, re.DOTALL)
                batch_insights = []
                if m:
                    data = json.loads(m.group(0))
                    batch_insights = data.get("insights", []) if isinstance(data, dict) else []

                # H5 fix: LLM 输出类型校验 — 非 list 一律置空走确定性兜底
                # (此前字符串会被 _merge_with_deterministic 逐字符迭代 → AttributeError 拖垮整条管线)
                if not isinstance(batch_insights, list):
                    logger.warning("[FieldInsight] batch %d/%d LLM insights 非 list (%s), 置空走确定性",
                                   b_idx, len(active_batches), type(batch_insights).__name__)
                    batch_insights = []

                llm_insights.extend(batch_insights)
                track_raw_llm_call(time.time() - b_t0, agent="field_insight")
                logger.info("[FieldInsight] batch %d/%d: %d fields → %d insights",
                            b_idx, len(active_batches), len(batch), len(batch_insights))
            except Exception as e:
                logger.warning("[FieldInsight] batch %d/%d LLM failed: %s — template fallback",
                               b_idx, len(active_batches), e)
                continue

        covered_fields = len(field_summaries) if not active_batches else sum(len(b) for b in active_batches)
        if covered_fields < len(field_summaries):
            logger.info("[FieldInsight] %d 字段超出分批上限 (%d batches × %d), 不再调 LLM, 走确定性兜底",
                        len(field_summaries) - covered_fields, MAX_INSIGHT_BATCHES, INSIGHT_BATCH_SIZE)

        # ── 模板 fallback / 补全确定性 observation (未覆盖字段 → 诚实文案) ──
        insights = _merge_with_deterministic(field_summaries, llm_insights, kb)

        elapsed = round(time.time() - t0, 3)
        logger.info("[FieldInsight] %d fields → %d insights (%.2fs)",
                    len(field_summaries), len(insights), elapsed)
        return self._return(state, insights, t0, "ok", llm_count, elapsed)

    def _return(self, state, insights, t0, reason, llm_count=None, elapsed=0.0):
        rs = state.get("report_state", {}) or {}
        existing = dict(rs.get("insights") or {})
        existing["field_insights"] = insights
        # H-16 fix (R1-B8 回归): 透传上游 Failed — 前序节点失败时本节点不再覆写 Success
        upstream_status = (state.get("workflow_state") or {}).get("execution_status") or "Success"
        exec_status = "Failed" if upstream_status == "Failed" else "Success"
        ret = {
            "report_state": {"insights": existing},
            "workflow_state": {
                "current_node": "field_insight",
                "execution_status": exec_status,
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
        from quality_pipeline.tools.insight.entity_types import get_typical_range
        return get_typical_range(entity_type, field_name)
    except Exception:
        return None


def _validate_kb_refs(refs, kb) -> tuple[list, list]:
    """P0-5 fix: kb:ID 引用闭环校验 — 幻觉 ID 剔除, 有效引用回填 title/source。

    knowledge_store.get_entry 已实现但此前从不调用, LLM 幻觉的 kb:ID 原样
    进 evidence_sources/kb_references 污染证据可信度。
    """
    valid, invalid = [], []
    for ref in refs or []:
        if isinstance(ref, dict):
            ref_id = ref.get("id", "") or ref.get("kb_id", "")
        else:
            ref_id = str(ref)
        ref_id = ref_id.replace("kb:", "")
        entry = kb.get_entry(ref_id) if kb else None
        if entry:
            valid.append({"id": ref_id,
                          "title": entry.get("title", ref_id),
                          "source": entry.get("source", "")})
        else:
            invalid.append(ref_id)
    return valid, invalid


def _clamp_confidence(value) -> float:
    """H-17 fix: 置信度规范化 — try/float 夹 [0,1], 转换失败 → 0.0。"""
    try:
        conf = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    return min(1.0, max(0.0, conf))


def _merge_with_deterministic(field_summaries, llm_insights, kb) -> list[dict]:
    """LLM 洞察与确定性 observation 合并; 缺字段的补模板。

    P0-4 诚实覆盖: 未被任何 batch 覆盖的字段 (key 不在 LLM 结果中) 不再伪装成
    LLM 解读 — interpretation 标记 'LLM 未覆盖该字段', confidence=0。
    仅当整批 LLM 调用全部失败 (llm_insights 为空) 时保留原 'LLM 不可用' 文案。
    """
    by_key = {}
    for ins in llm_insights:
        # H-17 fix: 逐条防御 — 非 dict 条目跳过记 warning (防 .get 抛 AttributeError)
        if not isinstance(ins, dict):
            logger.warning("[FieldInsight] LLM insight 条目非 dict (%s), 跳过", type(ins).__name__)
            continue
        # H-17 fix: 字段级类型校验 — 非 str 典型范围 → None (走实体配置兜底);
        # 非 list 假设原因/kb_references → [] (防字符串逐字符迭代污染)
        if not isinstance(ins.get("typical_range"), str):
            ins["typical_range"] = None
        if not isinstance(ins.get("cause_hypotheses"), list):
            ins["cause_hypotheses"] = []
        if not isinstance(ins.get("kb_references"), list):
            ins["kb_references"] = []
        key = (ins.get("entity_type", ""), ins.get("entity_name", ""), ins.get("field_name", ""))
        # P0-5: 引用闭环校验 (幻觉 kb:ID 剔除, 有效引用带 title/source)
        valid_refs, invalid_refs = _validate_kb_refs(ins.get("kb_references", []), kb)
        if invalid_refs:
            ins["invalid_kb_references"] = invalid_refs
        ins["kb_references"] = valid_refs
        by_key[key] = ins

    result = []
    # P0-4: llm_insights 全空 = LLM 整批失败 (模板兜底); 非空 = 部分字段未被覆盖
    uncovered_text = LLM_UNAVAILABLE_TEXT if not llm_insights else HONEST_UNCOVERED_TEXT
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
            "interpretation": ins.get("interpretation", uncovered_text),
            "cause_hypotheses": ins.get("cause_hypotheses", []),
            # V4 fix: LLM 已给 typical_range 则保留, 否则实体类型配置兜底
            "typical_range": ins.get("typical_range") or _typical_range_fallback(f["entity_type"], f["field_name"]),
            # H-17 fix: confidence try/float 夹 [0,1], 转换失败 → 0.0
            "confidence": _clamp_confidence(ins.get("confidence")),
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


def _format_catalog_property_notes(field_summaries) -> str:
    """P1-1: RAG 目录性质注记 — 每字段一行 [prop:{property_id}] {name_cn}: {description 摘要}。

    只注入当前数据出现的字段; 全部无匹配 → 返回空串 (整段省略)。
    0 LLM 纯查找; rag_properties 缺失/异常 → 空串 (绝不崩溃)。
    """
    if not field_summaries:
        return ""
    try:
        from quality_pipeline.tools.insight.rag_property_matcher import RagPropertyMatcher
        matcher = RagPropertyMatcher()
    except Exception:
        return ""
    lines = []
    seen: set[str] = set()
    try:
        for f in field_summaries:
            fn = str(f.get("field_name", "") or "")
            if not fn or fn in seen:
                continue
            seen.add(fn)
            try:
                entry = matcher.lookup(f.get("entity_type", ""), fn)
            except Exception:
                entry = None
            if not entry or not entry.get("name_cn"):
                continue
            desc = str(entry.get("description", "") or "")[:120]
            lines.append(f"[prop:{fn}] {entry.get('name_cn')}: {desc}".rstrip())
    except Exception:
        return ""
    if not lines:
        return ""
    return "CATALOG PROPERTY NOTES:\n" + "\n".join(lines)


def _load_prompts() -> dict:
    from quality_pipeline.configs import load_yaml
    prompts = load_yaml("insight_prompts.yaml") or {}
    if not prompts:
        raise RuntimeError("insight_prompts.yaml 缺失")
    return prompts
