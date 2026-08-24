"""接缝适配器：上游 final_output → 子图4 quality_pipeline 的输入

职责：
1. 从 PropertySpec 生成 target_schema（字段名 = property_id，标准单位 = unit）
2. 生成 standard_units 映射（field_name → standard_unit）
3. 调用 quality_pipeline.make_initial_state 构建初始状态
4. 注入 context_state（research_domain / target_schema / standard_units）
5. 运行 build_quality_graph 并返回结果

设计原则：
- 子图4 源码零改动：只用其公开入口 make_initial_state + build_quality_graph
- 上游 final_output 直接作为 grounded_data 传入（含 sources / records / research_domain）
"""

import logging
import traceback
from datetime import datetime
from typing import Dict, List, Optional

from .config import get_settings
from .adapters import _shared_checkpointer
from .state import MainGraphState

try:
    from langgraph.errors import GraphInterrupt
except ImportError:  # pragma: no cover — 旧版 langgraph 兼容
    GraphInterrupt = Exception

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# context_state 生成
# ══════════════════════════════════════════════════════════════

def generate_target_schema(property_spec: List[Dict]) -> Dict:
    """
    从 PropertySpec 生成 target_schema

    字段名 = property_id，标准单位 = unit。
    每个字段附带 semantic_type（用 RAG 的 category 作为粗粒度语义类，
    子图4 的 unit_converter 靠它做同名单位消歧）。
    """
    fields = []
    for p in property_spec or []:
        fields.append({
            "name": p["property_id"],
            "standard_unit": p.get("unit", ""),
            "semantic_type": p.get("category", ""),
            "ucd": p.get("ucd", ""),
            "description": p.get("description", ""),
            "criticality": "important",
        })
    return {"fields": fields}


def generate_standard_units(property_spec: List[Dict]) -> Dict[str, str]:
    """生成 field_name → standard_unit 映射（PropertySpec 直通 — RAG 性质库
    是标准单位的唯一权威，2026-08-24 回退 Aug 23 设计）。"""
    return {p["property_id"]: p.get("unit", "") for p in (property_spec or [])}


# ══════════════════════════════════════════════════════════════
# quality 节点
# ══════════════════════════════════════════════════════════════

def quality_node(state: MainGraphState, config: RunnableConfig = None) -> Dict:
    """
    调用子图4 质量管线。

    H1 fix: config 注入 — quality_pipeline 内 HumanReview 用 interrupt() HITL,
    必须与子图1/2/3 一样从主图 config 取共享 checkpointer, 否则嵌套图的
    GraphInterrupt 被 except 吞掉, 整条质量管线静默跳过。

    输入：state.final_output（grounded_data）+ state.property_spec
    输出：state.quality_report（子图4 的完整输出状态）
    """
    logger.info("[Quality Adapter] 开始质量管线")

    final_output = state.get("final_output") or {}
    property_spec = state.get("property_spec") or []

    if not final_output.get("records") and not final_output.get("sources"):
        logger.warning("[Quality Adapter] 无数据（final_output 为空），跳过质量管线")
        return {"quality_report": {"skipped": True, "reason": "empty_final_output"}}

    try:
        # 延迟导入子图4（避免循环依赖 + 让包迁移独立可测）
        from quality_pipeline.quality_state import make_initial_state
        from quality_pipeline.graph import build_quality_graph
    except Exception as exc:
        logger.error(f"[Quality Adapter] 导入 quality_pipeline 失败: {exc}")
        return {
            "error_log": [{
                "node": "quality_adapter",
                "error": f"导入 quality_pipeline 失败: {exc}",
                "timestamp": datetime.now().isoformat(),
            }],
            "quality_report": {"skipped": True, "reason": "import_failed"},
        }

    # 1. 构建初始状态（grounded_data）
    try:
        # M-18: run_id 绑定 query_id（Web 任务 = task_id）→ 导出目录
        # output/{task_id[:8]}/ 与任务可关联（此前随机 UUID 与任务完全解耦，
        # /exports 恒空）；CLI 无 query_id 时保持随机（行为不变）
        initial_state = make_initial_state(final_output, run_id=state.get("query_id") or None)
    except Exception as exc:
        logger.error(f"[Quality Adapter] make_initial_state 失败: {exc}")
        logger.debug(traceback.format_exc())
        return {
            "error_log": [{
                "node": "quality_adapter",
                "error": f"make_initial_state 失败: {exc}",
                "timestamp": datetime.now().isoformat(),
            }],
            "quality_report": {"skipped": True, "reason": "initial_state_failed"},
        }

    # 2. 注入 context_state（RAG 标准性质 → target_schema / standard_units）
    try:
        target_schema = generate_target_schema(property_spec)
        standard_units = generate_standard_units(property_spec)

        initial_state["context_state"]["target_schema"] = target_schema
        initial_state["context_state"]["standard_units"] = standard_units
        research_domain = get_settings().default_research_domain
        initial_state["context_state"]["research_domain"] = research_domain
        # Web 埋点定位：quality 子图无 query_id，注入以便 agent 事件关联任务
        initial_state["context_state"]["query_id"] = str(state.get("query_id", ""))

        # P2-1: SIMBAD otype 覆盖注入 — 上游 P1 已解析出 otype 时, 写入
        # entity_type_overrides 供 insights 实体类型推断优先采用 SIMBAD 结果。
        # 未传 (无 simbad_info / 无 otype) 时零影响: 不写该键, 推断链不变。
        simbad_info = state.get("simbad_info")
        otype = ""
        if isinstance(simbad_info, dict):
            otype = simbad_info.get("otype") or simbad_info.get("object_type") or ""
        if otype:
            overrides: Dict[str, str] = {}
            # source_id 级映射: database 类型 source 全部用该 otype
            for src in (final_output.get("sources") or []):
                if src.get("source_type") == "database" and src.get("source_id"):
                    overrides[str(src["source_id"])] = str(otype)
            # 无 source 级信息时用 default 键
            if not overrides:
                overrides["default"] = str(otype)
            initial_state["context_state"]["entity_type_overrides"] = overrides
            logger.info(
                "[Quality Adapter] SIMBAD otype 覆盖注入: otype=%s, %d 个 source",
                otype, len(overrides)
            )

        # 同步设置 configs 的全局领域（子图4 内部靠 get_research_domain 决定加载哪个配置段）
        from quality_pipeline.configs import set_research_domain
        set_research_domain(research_domain)
    except Exception as exc:
        logger.error(f"[Quality Adapter] context 注入失败: {exc}")
        return {
            "error_log": [{
                "node": "quality_adapter",
                "error": f"context 注入失败: {exc}",
                "timestamp": datetime.now().isoformat(),
            }],
            "quality_report": {"skipped": True, "reason": "context_inject_failed"},
        }

    logger.info(
        "[Quality Adapter] context 注入完成: target_schema %d 字段, standard_units %d 条",
        len(target_schema.get("fields", [])), len(standard_units)
    )

    # 3. 运行质量管线 (H1 fix: 共享 checkpointer 注入, 支持 quality 层 HITL)
    try:
        quality_graph = build_quality_graph().compile(
            checkpointer=_shared_checkpointer(config)
        )
        result = quality_graph.invoke(initial_state, config)
        logger.info("[Quality Adapter] 质量管线完成")
        return {"quality_report": result}
    except GraphInterrupt:
        # H1 fix: HumanReview 的 interrupt 不是失败 — 上浮主图 HITL 循环。
        if _shared_checkpointer(config) is None:
            logger.warning("[Quality Adapter] HITL 需要 checkpointer, 降级跳过质量管线")
            return {
                "error_log": [{
                    "node": "quality_adapter",
                    "error": "HumanReview HITL 需要 checkpointer (config 未注入)",
                    "timestamp": datetime.now().isoformat(),
                }],
                "quality_report": {"skipped": True, "reason": "hitl_needs_checkpointer"},
            }
        raise
    except Exception as exc:
        # 2026-08-13: traceback 从 debug 升为 error — 此前 INFO 级日志不落堆栈,
        # RecursionError 复现时无法定位（任务 7601ee09 仅见一行错误信息）。
        logger.error(f"[Quality Adapter] 质量管线执行失败: {exc}")
        logger.error("[Quality Adapter] 质量管线失败堆栈:\n%s", traceback.format_exc())
        return {
            "error_log": [{
                "node": "quality_adapter",
                "error": f"质量管线执行失败: {exc}",
                "timestamp": datetime.now().isoformat(),
            }],
            "quality_report": {"skipped": True, "reason": "pipeline_failed"},
        }


# ══════════════════════════════════════════════════════════════
# quality_finalize 节点（Phase 4: 集成断链修复）
# ══════════════════════════════════════════════════════════════

def quality_finalize_node(state: MainGraphState) -> Dict:
    """
    把 quality_pipeline 结果并入 final_output（主图最后一步）。

    历史断链：aggregator 在 quality 之前就拼完 final_output，quality 结果
    从不进入最终 JSON。此节点作为 quality 的后置节点，把 quality_report
    写入 final_output.quality_report，保证下游 JSON 含质量报告。
    """
    final_output = dict(state.get("final_output") or {})
    quality_report = state.get("quality_report")
    if quality_report is not None:
        final_output["quality_report"] = quality_report
    else:
        # 防御：quality 节点未运行/未产出时也写一个显式标记
        final_output["quality_report"] = {"skipped": True, "reason": "no_quality_report"}
    return {"final_output": final_output}
