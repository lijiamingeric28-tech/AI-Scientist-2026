"""
synthesis_agent.py — Node 4: SynthesisAgent (V3.4)

职责: 综合 Node 1+2+3 输出, 生成 overall_narrative, 组装 DataInsightsReport,
     写入 insights_{timestamp}.json, 更新 manifest, 写 output_state.insights。
LLM: 1 次 (overall_narrative)。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
from typing import Any

from quality_state import QualityGraphState
from utils.llm import get_llm, set_agent_context, track_raw_llm_call
from utils.logger import get_logger

logger = get_logger(__name__)

# V3.5: 领域常量从 domain_config 读取
from configs.domain_config import DEFAULT_DOMAIN, MAX_NARRATIVE_CHARS, MAX_KEY_OBSERVATIONS

_DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")


class SynthesisAgent:
    """Node 4: 综合 + 文件写入。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        t0 = time.time()
        ctx = state.get("context_state", {})
        domain = ctx.get("research_domain", DEFAULT_DOMAIN)
        rs = state.get("report_state", {}) or {}
        insights_state = rs.get("insights") or {}
        wf = state.get("workflow_state", {}) or {}

        field_insights = insights_state.get("field_insights", []) or []
        relationships = insights_state.get("relationships", []) or []
        rec = insights_state.get("recommendations", {}) or {}

        # ── insufficient_context_fields 检查 ──
        missing = []
        if not field_insights:
            missing.append("field_insights")
        if not rec:
            missing.append("recommendations")

        # ── LLM: overall_narrative ──
        narrative = ""
        llm_count = wf.get("llm_call_count", 0)
        try:
            set_agent_context("synthesis")
            from configs import load_yaml
            prompts = load_yaml("insight_prompts.yaml")
            # V3.4 fix: replace 替代 format (JSON 示例裸花括号)
            system = prompts["synthesis"]["system"].replace("{domain}", domain)
            user = prompts["synthesis"]["user"]
            user = user.replace("{domain}", domain)
            user = user.replace("{n_insights}", str(len(field_insights)))
            user = user.replace("{n_relationships}", str(len(relationships)))
            user = user.replace("{overall_grade}", str(rec.get("overall_grade", "unknown")))
            user = user.replace("{key_observations}", json.dumps(
                [f.get("interpretation", "")[:200] for f in field_insights[:MAX_KEY_OBSERVATIONS]],
                ensure_ascii=False,
            ))
            llm = get_llm(temperature=0.0)
            resp = llm.invoke([{"role": "system", "content": system},
                               {"role": "user", "content": user}])
            # V3.5 fix: MagicMock/非字符串响应防护 — 只接受 str 类型
            raw = getattr(resp, "content", None)
            if isinstance(raw, str):
                narrative = raw[:MAX_NARRATIVE_CHARS]
            else:
                narrative = ""
                logger.warning("[Synthesis] LLM 返回非字符串内容 (%s) — 使用模板", type(raw).__name__)
            llm_count += 1
            track_raw_llm_call(time.time() - t0, agent="synthesis")
        except Exception as e:
            logger.warning("[Synthesis] LLM failed: %s — template narrative", e)
            narrative = (f"Analyzed {len(field_insights)} fields across {domain}. "
                         f"Overall grade: {rec.get('overall_grade', 'unknown')}. "
                         f"Found {len(relationships)} cross-field relationships.")

        if not narrative:
            narrative = (f"Analyzed {len(field_insights)} fields across {domain}. "
                         f"Overall grade: {rec.get('overall_grade', 'unknown')}. "
                         f"Found {len(relationships)} cross-field relationships.")

        # ── 组装 DataInsightsReport ──
        report = {
            "research_domain": domain,
            "generated_at": datetime.datetime.now().isoformat(),
            "field_insights": field_insights,
            "cross_field_relationships": relationships,
            "usage_recommendations": rec,
            "overall_narrative": narrative,
            "insufficient_context_fields": missing,
        }

        # V3.5 fix: Pydantic 强校验 — 防止非法结构/非字符串写入正式结果
        try:
            from models.insights import DataInsightsReport
            validated = DataInsightsReport.model_validate(report)
            report = validated.model_dump()
        except Exception as e:
            logger.warning("[Synthesis] Pydantic 校验失败: %s — 保留原始 dict", e)

        # ── 文件写入 (复用 export 输出目录) ──
        output_dir = _resolve_output_dir(state, wf)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir, f"insights_{ts}.json")
        written = []
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            written.append(path)
            logger.info("[Synthesis] Insights written: %s", path)
        except Exception as e:
            logger.warning("[Synthesis] 文件写入失败: %s", e)

        # ── 更新 manifest (若存在) ──
        try:
            manifest_path = _find_manifest(output_dir)
            if manifest_path:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                manifest.setdefault("files", []).append(os.path.basename(path))
                manifest["insights_written"] = True
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("[Synthesis] manifest 更新失败: %s", e)

        elapsed = round(time.time() - t0, 3)
        logger.info("[Synthesis] report: %d insights, %d rels, narrative=%d chars (%.2fs)",
                    len(field_insights), len(relationships), len(narrative), elapsed)

        return {
            "output_state": {
                "insights": report,
                "exported_files": written,  # 追加到既有文件列表 (reducer 覆盖, 与 export 文件共存)
            },
            "report_state": {"insights": insights_state},
            "workflow_state": {
                "route_decision": "",
                "execution_status": "Success",
                "current_node": "synthesis",
                "llm_call_count": llm_count,
                "phase": "done",
                "workflow_history": [{
                    "agent": "SynthesisAgent", "stage": "Synthesis",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": elapsed,
                    "reason": f"insights={len(field_insights)}, rels={len(relationships)}",
                }],
            },
        }


def _resolve_output_dir(state, wf) -> str:
    """解析输出目录 — 优先复用 export 的 output_dir, 否则新建。"""
    output_state = state.get("output_state", {}) or {}
    existing = output_state.get("output_dir")
    if existing:
        return existing
    run_id = wf.get("run_id", datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir = run_id[:8] if len(run_id) >= 8 else run_id
    base = os.environ.get("EXPORT_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR)
    output_dir = os.path.join(os.path.abspath(base), run_dir)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _find_manifest(output_dir: str) -> str | None:
    """查找 output_dir 中最新的 manifest 文件。"""
    try:
        files = [f for f in os.listdir(output_dir) if f.startswith("manifest_") and f.endswith(".json")]
        if not files:
            return None
        files.sort(reverse=True)
        return os.path.join(output_dir, files[0])
    except OSError:
        return None
