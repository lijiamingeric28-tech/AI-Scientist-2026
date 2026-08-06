"""
llm_completeness.py

LLMCompletenessAnalyzer — LLM 增强的完整性分析 (V2.0 A3)

当前 check_completeness() 只回答 "缺什么"。
LLM 增强版回答 "缺得是否合理"。

Expected 的缺失 → 扣分; optional 的缺失 → 标记不扣分; irrelevant 的缺失 → 忽略。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...utils.llm import set_agent_context, get_llm
from ...utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """你是科学数据完整性分析专家。

对于给定的研究论文, 判断每个缺失字段的预期状态:
- "expected": 这种研究通常应该包含此数据 (缺失说明数据不完整)
- "optional": 可能包含但不一定 (缺失可以理解)
- "irrelevant": 该研究不太可能包含此数据 (缺失是正常的)

返回 JSON: {"analysis": {"field_name": {"status": "expected/optional/irrelevant", "reason": "..."}}, "summary": "..."}"""


def analyze_missing_fields(
    title: str,
    present_fields: list[str],
    missing_fields: list[str],
    year: int | None = None,
) -> dict[str, Any]:
    """
    LLM 分析缺失字段的合理性。

    Args:
        title: 论文标题
        present_fields: 已提取到的字段
        missing_fields: 缺失的字段
        year: 出版年份

    Returns:
        {
            "analysis": {field: {status, reason}},
            "adjusted_completeness": float,  # 仅对 'expected' 缺失扣分
            "summary": str
        }
    """
    if not missing_fields:
        return {"analysis": {}, "adjusted_completeness": 1.0, "summary": "无缺失字段"}

    try:
        prompt = (
            f"Paper: '{title}' ({year or 'unknown year'})\n"
            f"Extracted fields: {present_fields}\n"
            f"Missing fields: {missing_fields}\n\n"
            f"For each missing field, classify: expected / optional / irrelevant."
        )

        set_agent_context("assessment")
        llm = get_llm(temperature=0.0)
        resp = llm.invoke([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        content = resp.content if hasattr(resp, "content") else str(resp)
        data = _parse_json(content)

        analysis = data.get("analysis", {})

        # 计算 adjusted score
        expected_count = sum(1 for v in analysis.values() if isinstance(v, dict) and v.get("status") == "expected")
        optional_count = sum(1 for v in analysis.values() if isinstance(v, dict) and v.get("status") == "optional")
        total = len(missing_fields)
        # 仅 expected 的缺失扣分; optional 扣 30%; irrelevant 不扣
        adjusted = 1.0 - (expected_count + optional_count * 0.3) / max(total, 1) * 0.5
        adjusted = round(max(0.0, adjusted), 4)

        summary = data.get("summary", "")
        logger.info("[LLMCompleteness] %d missing: expected=%d optional=%d irrelevant=%d → adjusted=%.2f",
                    total, expected_count, optional_count,
                    total - expected_count - optional_count, adjusted)

        return {
            "analysis": analysis,
            "adjusted_completeness": adjusted,
            "expected_count": expected_count,
            "optional_count": optional_count,
            "irrelevant_count": total - expected_count - optional_count,
            "summary": summary or f"{expected_count} expected missing, {optional_count} optional",
        }

    except Exception as e:
        logger.warning("[LLMCompleteness] LLM unavailable (%s), using raw completeness", e)
        return {"analysis": {}, "adjusted_completeness": 1.0,
                "summary": f"LLM不可用, {len(missing_fields)} fields missing (unclassified)"}


def _parse_json(text: str) -> dict:
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}
