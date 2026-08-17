"""LLM 总结生成（模块 ⑤，契约 D1-5/D6-3/D8-2）：
- 卡 7 最终总结：任务完成后 qwen3.7-flash 生成自然语言总结（唯一保留 LLM 处）
- 任务标题摘要：侧边栏 title（异步 SSE 补发 task_title_ready）

失败降级：LLM 不可用时返回模板文本（不击穿任务）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from astroquery_ai.config import get_settings

logger = logging.getLogger(__name__)

_SUMMARY_MODEL = "qwen3.7-flash"  # 契约 D1-5


def _llm_client():
    """OpenAI 兼容客户端（DashScope 兼容模式，复用统一 Settings）。"""
    from openai import OpenAI
    s = get_settings()
    return OpenAI(
        api_key=s.dashscope_api_key or "EMPTY",
        base_url=s.dashscope_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def _try_llm(prompt: str, max_tokens: int = 400) -> str:
    try:
        client = _llm_client()
        resp = client.chat.completions.create(
            model=_SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_tokens,
            timeout=60,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("[Summary] LLM 调用失败，降级模板: %s", exc)
        return ""


def _is_usable_summary(text: str) -> bool:
    """总结文本可用性校验：拒绝 JSON/代码/过短（防 VCR 错位响应透传）。"""
    if not text:
        return False
    t = text.strip()
    if len(t) < 8:
        return False
    if t.startswith(("{", "[")):  # JSON 错位响应
        return False
    if '"query"' in t or '"tool_code"' in t or 'abs:' in t:  # 检索/工具 JSON 泄漏
        return False
    if t.count("\n") > 12:  # 疑似代码块
        return False
    return True


def _quality_scoring_text(state: Dict[str, Any]) -> str:
    """从质量管线报告提取可读评分文本。

    实际结构：final_output.quality_report.report_state.quality.quality_scoring
      = {overall_score, quality_level, per_source_scores, dimension_scores, ...}
    （此前误读 quality_report.quality_summary.scores → 恒为空 → 总结恒报「无质量评分」）
    返回空串表示无评分（调用方降级为「无」）。
    """
    final = (state or {}).get("final_output") or {}
    quality = final.get("quality_report") or {}
    report = (quality.get("report_state") or {}).get("quality") or {}
    scoring = report.get("quality_scoring") or {}
    if not isinstance(scoring, dict) or not scoring:
        return ""
    level = scoring.get("quality_level")
    overall = scoring.get("overall_score")
    dims = scoring.get("dimension_scores") or {}
    parts = []
    if overall is not None:
        try:
            parts.append(f"综合 {float(overall):.2f}" + (f"（{level}）" if level else ""))
        except (TypeError, ValueError):
            if level:
                parts.append(f"等级 {level}")
    elif level:
        parts.append(f"等级 {level}")
    if isinstance(dims, dict) and dims:
        dim_parts = []
        for k, v in dims.items():
            try:
                dim_parts.append(f"{k} {float(v):.2f}")
            except (TypeError, ValueError):
                continue
        if dim_parts:
            parts.append("，".join(dim_parts))
    # 最差源告警（2026-08-17 新增字段：不参与等级判定，仅提示下游关注）
    weakest = scoring.get("weakest_source")
    if isinstance(weakest, dict) and weakest.get("source_id"):
        try:
            parts.append(f"最差源 {str(weakest['source_id'])[:24]}"
                         f"（{weakest.get('quality_level', 'poor')} {float(weakest.get('score', 0)):.2f}）")
        except (TypeError, ValueError):
            parts.append(f"最差源 {str(weakest['source_id'])[:24]}")
    return " · ".join(parts)


def generate_final_summary(task_id: str, state: Dict[str, Any]) -> str:
    """卡 7 最终总结（契约 D6-3：阶段级前端拼字段，仅此处走 LLM）。"""
    final = (state or {}).get("final_output") or {}
    records = final.get("records", []) or []
    sources = final.get("sources", []) or []
    n_records = len(records)
    n_sources = len(sources)
    scores_text = _quality_scoring_text(state)

    # M-17: prompt 模板化——用 state.target_entity（或 user_query 兜底），
    # 非 M13 查询不再错误引用硬编码天体名（与 generate_task_title 同模式）
    target = (state or {}).get("target_entity") or (state or {}).get("user_query") or "本次查询"
    prompt = (
        f"你是天文数据检索助手。请用简洁的中文总结一次「{target}」数据检索任务的结果。\n"
        f"数据：{n_sources} 个数据源，{n_records} 条记录。\n"
        f"质量评分：{scores_text or '无'}。\n"
        f"要求：2-3 句话，突出关键结论（提取了多少数据、质量如何、是否可直接使用），"
        f"结尾提示用户可在右侧面板查看完整结果与输出文件。不要使用 Markdown 标题。"
    )
    text = _try_llm(prompt)
    if _is_usable_summary(text):
        return text
    logger.warning("[Summary] LLM 输出不可用（可能回放错位），降级模板")
    # 降级模板
    return f"任务完成：共提取 {n_sources} 个数据源、{n_records} 条记录，全部通过质量检查。完整结果可在右侧面板查看与下载。"


def generate_task_title(query: str, state: Dict[str, Any]) -> str:
    """侧边栏任务标题摘要（契约 D8-2：异步生成，SSE 补发 task_title_ready）。"""
    final = (state or {}).get("final_output") or {}
    target = final.get("target_entity") or (state or {}).get("target_entity") or ""
    prompt = (
        f"为用户查询生成一个简短的中文任务标题（≤20 字，不用标点）。\n"
        f"用户查询：{query}\n"
        f"目标天体：{target or '未知'}\n"
        f"只输出标题本身。"
    )
    text = _try_llm(prompt, max_tokens=50)
    if text:
        # 去引号/换行
        return text.strip('"').strip()[:40]
    return query.strip()[:40]