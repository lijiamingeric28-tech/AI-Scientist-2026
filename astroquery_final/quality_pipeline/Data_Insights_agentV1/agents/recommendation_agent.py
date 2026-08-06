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

from ...quality_state import QualityGraphState
from ...utils.llm import get_llm, set_agent_context, track_raw_llm_call
from ...utils.logger import get_logger

logger = get_logger(__name__)

# V3.5: 领域常量从 domain_config 读取
from ...configs.domain_config import (
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
        from ...tools.insight.context_builder import (
            build_quality_context, build_low_confidence_records, build_coverage_gaps,
        )
        quality_ctx = build_quality_context(state)
        low_conf = build_low_confidence_records(state)   # V3.4: DB records 跳过
        coverage = build_coverage_gaps(state)

        # ── RAG 检索 (methodology) ──
        from ...tools.insight.knowledge_store import get_knowledge_store
        kb = get_knowledge_store(domain)
        entities = list({f.get("entity_type", "") for f in field_insights if f.get("entity_type")})
        kb_results = kb.search(
            entity_types=entities,
            keywords=[domain],
            categories=KB_CATEGORIES_RECOMMENDATION,
            top_k=KB_TOP_K,
        )
        knowledge_block = _format_knowledge_block(kb_results)

        rec: dict = {}
        llm_count = state.get("workflow_state", {}).get("llm_call_count", 0)
        try:
            set_agent_context("recommendation")
            from ...configs import load_yaml
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
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                rec = json.loads(m.group(0))
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="recommendation")
        except Exception as e:
            logger.warning("[Recommendation] LLM failed: %s — template fallback", e)
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

        rs_out = dict(rs.get("insights") or {})
        rs_out["recommendations"] = rec
        ret = {
            "report_state": {"insights": rs_out},
            "workflow_state": {
                "current_node": "recommendation",
                "execution_status": "Success",
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
