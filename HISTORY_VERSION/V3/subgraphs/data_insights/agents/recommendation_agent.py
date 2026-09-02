"""
recommendation_agent.py — Node 3: RecommendationAgent (V3.4)

职责: 数据使用建议 — 适用场景/局限性/caveats。
确定性组件: low_confidence_records (paper extraction_confidence<0.7; DB 跳过) + coverage_gaps。
输入: Node 1+2 + quality_scoring + metadata + workflow 统计 + RAG 检索 (methodology)
输出: recommendations → report_state.insights.recommendations
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
    DEFAULT_DOMAIN, KB_CATEGORIES_RECOMMENDATION, KB_TOP_K,
    MAX_INSIGHTS_CHARS, MAX_PAIRS_CHARS, LOW_CONFIDENCE_THRESHOLD,
    MAX_LOW_CONF_RECORDS, MAX_COVERAGE_GAPS,
)


class RecommendationAgent:
    """Node 3: 数据使用建议。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ctx = state.get("context_state", {})
        domain = ctx.get("research_domain", DEFAULT_DOMAIN)
        rs = state.get("report_state", {}) or {}
        insights_state = rs.get("insights") or {}
        field_insights = insights_state.get("field_insights", []) or []
        relationships = insights_state.get("relationships", []) or []

        # ── 确定性组件 ──
        from quality_pipeline.tools.insight.context_builder import (
            build_quality_context, build_low_confidence_records, build_coverage_gaps,
        )
        quality_ctx = build_quality_context(state)
        low_conf = build_low_confidence_records(state)   # V3.4: DB records 跳过
        coverage = build_coverage_gaps(state)

        # ── RAG 检索 (methodology) ──
        # P1-3 fix: keywords=[domain] 在全部 78 条 tag 中无命中 → 检索只靠
        # entity_types+category 硬分类, methodology/best_practice 条目进不了 prompt。
        # 改为确定性派生检索词: 实体名 + 字段名 + 按质量状态映射的主题词表 + 兜底。
        from quality_pipeline.tools.insight.knowledge_store import get_knowledge_store
        kb = get_knowledge_store(domain)
        entities = list({f.get("entity_type", "") for f in field_insights if f.get("entity_type")})
        search_kws = _derive_search_keywords(quality_ctx, low_conf, coverage, field_insights)
        kb_results = kb.search(
            entity_types=entities,
            keywords=search_kws,
            categories=KB_CATEGORIES_RECOMMENDATION,
            top_k=KB_TOP_K,
        )
        knowledge_block = _format_knowledge_block(kb_results)

        rec: dict = {}
        llm_count = state.get("workflow_state", {}).get("llm_call_count", 0)
        try:
            set_agent_context("recommendation")
            from quality_pipeline.configs import load_yaml
            prompts = load_yaml("insight_prompts.yaml")
            # V3.4 fix: replace 替代 format (JSON 示例裸花括号)
            system = prompts["recommendation"]["system"].replace("{domain}", domain)
            user = prompts["recommendation"]["user"]
            user = user.replace("{field_insights}", json.dumps(field_insights, ensure_ascii=False, indent=1)[:MAX_INSIGHTS_CHARS])
            user = user.replace("{relationships}", json.dumps(relationships, ensure_ascii=False, indent=1)[:MAX_PAIRS_CHARS])
            user = user.replace("{quality_context}", json.dumps(quality_ctx, ensure_ascii=False))
            user = user.replace("{low_confidence_records}", json.dumps(low_conf[:MAX_LOW_CONF_RECORDS], ensure_ascii=False))
            user = user.replace("{coverage_gaps}", json.dumps(coverage[:MAX_COVERAGE_GAPS], ensure_ascii=False))
            user = user.replace("{knowledge_block}", knowledge_block)
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
            text = resp.content if hasattr(resp, "content") else str(resp)
            # L-18 fix: 调用计数在 invoke 成功后、json.loads 前递增 (解析失败不吞计数)
            llm_count += 1
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                rec = json.loads(m.group(0))
            track_raw_llm_call(time.time() - t0, agent="recommendation")
        except Exception as e:
            logger.warning("[Recommendation] LLM failed: %s — template fallback", e)
            rec = {}

        # H5 fix: LLM 输出类型校验 — 非 dict 置空 (防 .setdefault 抛 AttributeError)
        if not isinstance(rec, dict):
            logger.warning("[Recommendation] LLM 输出非 dict (%s), 置空走确定性",
                           type(rec).__name__)
            rec = {}

        # ── 确定性组件合并 ──
        rec.setdefault("overall_grade", quality_ctx.get("quality_level", "unknown"))
        rec.setdefault("suitable_use_cases", [])
        rec.setdefault("limitations", [])
        rec.setdefault("recommended_caveats", [])
        rec["low_confidence_records"] = low_conf[:MAX_LOW_CONF_RECORDS]
        rec["coverage_gaps"] = coverage[:MAX_COVERAGE_GAPS]

        elapsed = round(time.time() - t0, 3)
        logger.info("[Recommendation] grade=%s, %d low-conf, %d gaps (%.2fs)",
                    rec.get("overall_grade"), len(low_conf), len(coverage), elapsed)

        # H-16 fix (R1-B8 回归): 透传上游 Failed — 前序节点失败时本节点不再覆写 Success
        upstream_status = (state.get("workflow_state") or {}).get("execution_status") or "Success"
        exec_status = "Failed" if upstream_status == "Failed" else "Success"
        rs_out = dict(rs.get("insights") or {})
        rs_out["recommendations"] = rec
        ret = {
            "report_state": {"insights": rs_out},
            "workflow_state": {
                "current_node": "recommendation",
                "execution_status": exec_status,
                "llm_call_count": llm_count,
                "workflow_history": [{
                    "agent": "RecommendationAgent", "stage": "Recommendation",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"grade={rec.get('overall_grade')}",
                }],
            },
        }
        return ret


def _derive_search_keywords(quality_ctx: dict, low_conf: list, coverage: list,
                            field_insights: list) -> list[str]:
    """P1-3: 确定性派生检索词 (全部来自 build_quality_context 输出 + 确定性组件)。

    组成:
      1. 实体名 + 字段名 (当前数据实际出现的概念)
      2. 按质量状态映射的主题词表:
           anomalies>0          → anomaly/outlier
           variance_groups>0    → cross-source/comparison
           conflict_status 非空 → conflict
           coverage_gaps 非空   → missing/coverage
           low_conf 非空        → confidence/uncertainty
      3. 兜底: methodology/best_practice (保证推荐类目可命中)

    Returns:
        去重保序的小写关键词列表 (空关键词已过滤)。
    """
    kws: list[str] = []
    # 1. 实体名 + 字段名
    for f in field_insights or []:
        if not isinstance(f, dict):
            continue
        if f.get("entity_name"):
            kws.append(str(f["entity_name"]))
        if f.get("field_name"):
            kws.append(str(f["field_name"]))
    # 2. 质量状态 → 主题词表
    try:
        if (quality_ctx.get("anomalies") or 0) > 0:
            kws += ["anomaly", "outlier"]
        if (quality_ctx.get("variance_groups") or 0) > 0:
            kws += ["cross-source", "comparison"]
        if quality_ctx.get("conflict_status"):
            kws += ["conflict"]
        if coverage:
            kws += ["missing", "coverage"]
        if low_conf:
            kws += ["confidence", "uncertainty"]
    except Exception:
        pass
    # 3. 兜底
    kws += ["methodology", "best_practice"]
    # 去重保序 + 过滤空
    seen: set[str] = set()
    out: list[str] = []
    for k in kws:
        k = str(k).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _format_knowledge_block(entries: list[dict]) -> str:
    if not entries:
        return "RELEVANT DOMAIN KNOWLEDGE: (none available)"
    lines = ["RELEVANT DOMAIN KNOWLEDGE:"]
    for e in entries:
        lines.append("---")
        lines.append(f"[kb:{e.get('id', '?')}] {e.get('title', '')}")
        lines.append(str(e.get("content", ""))[:500])
    lines.append("---\nUse this knowledge to inform your recommendations.")
    return "\n".join(lines)
