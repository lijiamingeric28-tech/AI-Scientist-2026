"""
human_review_agent.py — Human Review Agent (V1.0)

命令行交互式人工审核。展示 Conflict 无法自动裁决的冲突，
收集人工决策，路由回 Normalization。

交互流程:
  1. 展示冲突摘要
  2. 逐条展示 + 用户选择
  3. 确认汇总
  4. 写入 __human_review_decision__
"""
from __future__ import annotations

import datetime
import sys
from typing import Any

from langgraph.types import interrupt

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

_SEP = "=" * 80
_SEP2 = "-" * 80
_SEP3 = "-" * 60


def _build_human_review_support(state: dict) -> dict:
    """P2-3: HumanReview 出口的确定性洞察支持 (0 LLM)。

    完整 4 节点 Insights 只在 Export 路径运行; 人工评审 (A→E/C→E) 的数据
    用确定性组件 (field_summaries + 模板 merge) 生成 human_review_support,
    供 UI 展示人工审核上下文, 不强制跑 LLM 洞察。
    """
    try:
        from quality_pipeline.tools.insight.context_builder import build_field_summaries
        from subgraphs.data_insights.agents.field_insight_agent import _merge_with_deterministic
        summaries = build_field_summaries(state)
        if not summaries:
            return {}
        field_insights = _merge_with_deterministic(summaries, [], None)
        return {
            "field_insights": field_insights,
            "coverage": f"{len(field_insights)} fields (deterministic only)",
            "generated_by": "human_review_support (P2-3, 0 LLM)",
        }
    except Exception as e:
        logger.warning("[HumanReview] 确定性洞察支持生成失败: %s", e)
        return {}


class HumanReviewAgent:
    """命令行人工审核 Agent。"""

    def run(self, state: QualityGraphState) -> dict[str, Any]:
        wf = state.get("workflow_state", {})
        rs = state.get("report_state", {})
        ds = state.get("data_state", {})

        # ── Step 1: 已有决策 → 直接应用 ──
        human_decision = wf.get("__human_review_decision__")
        if human_decision is not None:
            route = human_decision.get("route_decision", "Normalization") if isinstance(human_decision, dict) else "Normalization"
            logger.info("[HumanReview] Previous decision found → route to %s", route)
            return {
                "workflow_state": {
                    "route_decision": route,
                    "execution_status": "Success",
                    "current_node": "human_review",
                    "__human_review_needed__": False,
                    "__human_review_decision__": None,
                    "__human_review_data__": None,
                    "from_conflict": False,  # H2 fix: 原 typo 键 _from_conflict 被 schema 静默丢弃 (routers.py 读 from_conflict)
                    "workflow_history": [{
                        "agent": "HumanReview", "stage": "Resolved",
                        "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "duration": 0.0,
                        "reason": f"Human chose → {route}",
                    }],
                },
            }

        # ── Step 2: 提取待审核冲突 ──
        conflicts = self._extract_pending(state)
        if not conflicts:
            logger.warning("[HumanReview] No pending conflicts → Export")
            return self._no_conflicts_result(state)

        # ── Step 3: 命令行交互 ──
        print(f"\n{_SEP}")
        print(f"  HUMAN REVIEW — {len(conflicts)} 个冲突需要人工裁决")
        print(f"{_SEP}")

        quality = rs.get("quality", {}) or {}
        # V3.5 fix: conflict 可能为 None (dispatch 清理后) — 空值保护
        conflict_state = rs.get("conflict") or {}
        resolution_report = conflict_state.get("resolution_report") or {}
        auto_resolved = resolution_report.get("metadata", {}).get("auto_resolved", 0)
        total = resolution_report.get("metadata", {}).get("total_conflicts", 0)
        print(f"\n  摘要: {auto_resolved}/{total} 冲突已自动解决, {len(conflicts)} 个需要人工判断")
        fields = list(set(c.get("field_name", "?") for c in conflicts))
        print(f"  涉及字段: {', '.join(fields)}")
        print()

        decisions = {}
        for i, c in enumerate(conflicts):
            cid = c.get("conflict_d", f"CF-{i+1:03d}")
            print(f"\n  {_SEP2}")
            self._print_conflict(c, i + 1, len(conflicts))
            print(f"  {_SEP2}")

            choice = self._get_user_choice(c)
            reason = self._get_user_reason()
            # V3.2: 携带冲突详情, 供 _decisions_to_actions 生成可执行动作
            decisions[cid] = {
                **choice, "reason": reason, "conflict_d": cid,
                "source_id": (c.get("source_a") or {}).get("source_id", ""),
                "field_name": c.get("field_name", ""),
                "entity_name": c.get("entity_name", ""),
                "record_ids": [r.get("record_id") for r in
                               (c.get("source_a") or {}).get("records", [])]
                               if isinstance((c.get("source_a") or {}).get("records"), list)
                               else [],
            }

        # ── Step 4: 确认汇总 ──
        print(f"\n{_SEP}")
        print("  决策汇总")
        print(f"{_SEP}")
        for cid, d in decisions.items():
            action_label = {
                "adopt_source_a": f"采用 Source A = {d.get('selected_value', '?')}",
                "adopt_source_b": f"采用 Source B = {d.get('selected_value', '?')}",
                "custom_value": f"自定义值 = {d.get('selected_value', '?')}",
                "retain_both": "保留两者",
                "skip": "跳过",
            }.get(d.get("action", "?"), d.get("action", "?"))
            print(f"  [{cid}]: {action_label}")
            if d.get("reason"):
                print(f"    理由: {d['reason']}")

        # ── Step 4b: 全局出口选择（Phase 4c: input() → interrupt() HITL）──
        _hr_text = (f"\n  {_SEP3}\n  请选择下一步:\n"
                    f"    [1] 提交裁决 → Normalization 执行修改 (E→B)\n"
                    f"    [2] 无法判断 → 送回 Assessment 重新评估 (E→A)\n"
                    f"    [3] 取消 (保留状态)\n  {_SEP3}\n  请输入选项 [1-3]: ")
        next_step = interrupt({"type": "human_review_next", "text": _hr_text, "options": ["1", "2", "3"]})
        if next_step is None:
            next_step = ""
        next_step = str(next_step).strip()

        if next_step == "3":
            print("  X 已取消。保留当前状态，下次可恢复。")  # V3.5: ASCII 安全
            return {
                "workflow_state": {
                    "execution_status": "HumanReview",
                    "current_node": "human_review",
                    "__human_review_needed__": True,
                },
            }
        elif next_step == "2":
            target_route = "Assessment"
            print("  → 送回 Assessment 重新评估 (E→A)")
        else:
            target_route = "Normalization"
            print("  → 提交裁决到 Normalization 执行修改 (E→B)")

        # ── Step 5: 写入决策 ──
        decision_record = {
            "decisions": decisions,
            "route_decision": target_route,
            "reviewer_notes": "",
            "reviewed_at": datetime.datetime.now().isoformat(),
        }

        # V3.2 fix: 人工决策转换为可执行的 normalization_ctions
        # (E→B 时 SourceRouterAgent 消费 resolution_plan.actions_to_normalize)
        actions = self._decisions_to_actions(decisions)

        # V3.1 fix: 使用用户选择的 target_route (E→A 或 E→B), 不再硬编码 Normalization
        logger.info("[HumanReview] %d conflicts reviewed → %s", len(decisions), target_route)

        # V3.3: 人工审核完成 — 清除 pending_sources["HumanReview"] + 写 phase
        pending = dict(wf.get("pending_sources") or {})
        pending["HumanReview"] = []

        ret = {
            # P2-3: 人工审核数据也产出确定性洞察支持 (供 UI 展示, 0 LLM)
            "output_state": {"human_review_support": _build_human_review_support(state)},
            "workflow_state": {
                "route_decision": target_route,
                "execution_status": "Success",
                "current_node": "human_review",
                "phase": "human_review",
                "pending_sources": pending,
                "from_conflict": False,  # V3.1 fix: 人工决策后是新流程, 清除循环标记
                "__human_review_needed__": False,
                "__human_review_decision__": decision_record,
                "__human_review_data__": None,
                "workflow_history": [{
                    "agent": "HumanReview", "stage": "Resolved",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": 0.0,
                    "reason": f"Human resolved {len(decisions)} conflicts → {target_route}",
                }],
            },
        }
        if actions:
            ret["report_state"] = {"conflict": {
                "resolution_report": {
                    "resolution_plan": {"actions_to_normalize": actions},
                }
            }}
        return ret

    def _decisions_to_actions(self, decisions: dict) -> list[dict]:
        """将人工决策转换为 NormalizationAction 列表 (V3.2)。"""
        actions = []
        for cid, d in decisions.items():
            action = d.get("action", "skip")
            if action in ("adopt_source_a", "adopt_source_b", "custom_value"):
                # C-01 fix: 生成 human_replace 前强制校验作用域 (record_ids + field_name 非空),
                # 空作用域 (如 QHR 质量类审核项) 会导致整 source 全部记录被单值覆盖 → 降级 annotate
                record_ids = d.get("record_ids") or []
                field_name = d.get("field_name") or ""
                if not record_ids or not field_name:
                    logger.warning(
                        "[HumanReview] 决策 %s 缺少 record_ids/field_name, human_replace 降级为 annotate: "
                        "action=%s field_name=%r record_ids=%r entity_name=%r",
                        cid, action, field_name, record_ids, d.get("entity_name", ""))
                    actions.append({
                        "source_id": d.get("source_id", ""),
                        "field": field_name,
                        "field_name": field_name,
                        "entity_name": d.get("entity_name", ""),
                        "action": "annotate",
                        "reason": f"Human decision [{cid}]: {action} degraded to annotate (missing scope)",
                    })
                    continue
                # 需要写回目标值 → Normalization 执行替换
                actions.append({
                    "source_id": d.get("source_id", ""),
                    "target_source": d.get("source_id", ""),
                    "record_ids": record_ids,
                    "field": field_name,
                    "field_name": field_name,
                    "entity_type": d.get("entity_type", ""),
                    "entity_name": d.get("entity_name", ""),
                    "new_value": d.get("selected_value"),
                    "action": "human_replace",
                    "reason": f"Human decision [{cid}]: {action}",
                })
            elif action == "retain_both":
                actions.append({
                    "source_id": d.get("source_id", ""),
                    "field": d.get("field_name", ""),
                    "field_name": d.get("field_name", ""),
                    "entity_name": d.get("entity_name", ""),
                    "action": "annotate",
                    "reason": f"Human decision [{cid}]: retain both values",
                })
            # skip → 无动作
        return actions

    # ── Helpers ──

    def _extract_pending(self, state) -> list[dict]:
        """提取所有待人工审核的冲突/异常 (V3.1: 兼容 resolution_plan.human_review_items)。"""
        # V3.3 fix: conflict 可能为 None (dispatch 清理后) — 空值保护
        conflict = state.get("report_state", {}).get("conflict") or {}
        resolution_report = conflict.get("resolution_report") or {}
        pending = []

        # 从 resolution_plan.human_review_items (V3.1 fix: 由 resolution_report_agent 生成)
        plan = resolution_report.get("resolution_plan", {})
        for item in plan.get("human_review_items", []):
            # 补全 per_conflict 中的详细信息
            per_conflict_ap = {r.get("conflict_d", ""): r for r in resolution_report.get("per_conflict", [])}
            full = per_conflict_ap.get(item.get("conflict_d", ""), {})
            # H-04 fix: V3.0 报告不产出 per_conflict 键 → full 恒空,
            # 以 item.source_ids 回填 source_a (至少 source_a={"source_id": 首个})
            src_ids = item.get("source_ids", []) or []
            src_ids = src_ids if isinstance(src_ids, list) else []
            source_a = full.get("source_a", {}) or {}
            if not source_a and src_ids:
                source_a = {"source_id": src_ids[0]}
            pending.append({
                "conflict_d": item.get("conflict_d", "?"),
                "field_name": full.get("field_name", item.get("field_name", "?")),
                "entity_name": item.get("entity_name", ""),
                "reason": item.get("reason", full.get("reasoning_chain", [""])[0] if full.get("reasoning_chain") else ""),
                "evidence_summary": item.get("evidence_summary", {}),
                "source_a": source_a,
                "source_b": full.get("source_b", {}),
                "cohens_d": full.get("cohens_d", 0),
                "effect_size": full.get("effect_size", ""),
                "reasoning_chain": full.get("reasoning_chain", []),
                "risk_assessment": full.get("risk_assessment", ""),
                "confidence": full.get("confidence", 0),
                "strategy": full.get("strategy", "escalate_to_human"),
            })

        # V3.1 fix: 从 anomaly_flags 中筛选 action=human_review (cross_id_error)
        # H-13 fix: critical 级 flag_for_review 也兜底提取 (critical 异常必须人工介入)
        if not pending:
            for flag in resolution_report.get("anomaly_flags", []):
                if flag.get("action") != "human_review" and not (
                        flag.get("action") == "flag_for_review" and flag.get("severity") == "critical"):
                    continue
                # H-04 fix: cross_id 异常自带 source_ids → 回填 source_a (至少 source_a={"source_id": 首个})
                src_ids = flag.get("source_ids", []) or []
                src_ids = src_ids if isinstance(src_ids, list) else []
                source_a = {"source_id": src_ids[0]} if src_ids else {}
                pending.append({
                    "conflict_d": f"ANOM-{flag.get('anomaly_type', '?')}-{flag.get('entity_name', '?')}",
                    "field_name": flag.get("field_name", ""),
                    "entity_name": flag.get("entity_name", ""),
                    "reason": f"{flag.get('anomaly_type')} requires human review: {flag.get('detail', {})}",
                    "evidence_summary": flag.get("detail", {}),
                    "source_a": source_a, "source_b": {},
                    "cohens_d": 0, "effect_size": "",
                    "reasoning_chain": [], "risk_assessment": "",
                    "confidence": 0, "strategy": "escalate_to_human",
                })

        # 备选: 从 reasoning.per_conflict 中筛选 escalated_to_human (旧报告兼容)
        if not pending:
            reasoning = conflict.get("reasoning", {})
            for r in reasoning.get("per_conflict", []):
                if r.get("resolution") == "escalated_to_human":
                    pending.append({
                        "conflict_d": r.get("conflict_d", "?"),
                        "field_name": r.get("field_name", "?"),
                        "reason": r.get("reasoning_chain", [""])[0] if r.get("reasoning_chain") else "",
                        "evidence_summary": {},
                        "source_a": r.get("source_a", {}),
                        "source_b": r.get("source_b", {}),
                        "cohens_d": r.get("cohens_d", 0),
                        "effect_size": r.get("effect_size", ""),
                        "reasoning_chain": r.get("reasoning_chain", []),
                        "risk_assessment": r.get("risk_assessment", ""),
                        "strategy": r.get("strategy", "escalate_to_human"),
                    })

        # V3.5 fix: review_items 抽象 — Assessment 触发 HR (提取质量过低/严重质量问题)
        # 但无 conflict 报告时, 从 quality 构造质量类审核项, 不能直接跳过人工审核
        if not pending:
            quality = state.get("report_state", {}).get("quality") or {}
            per_source_routes = quality.get("per_source_routes", {})
            sources = quality.get("sources", {})
            for sid, route in per_source_routes.items():
                if route != "HumanReview":
                    continue
                sr = sources.get(sid, {})
                reasons = []
                extr = (sr.get("extraction_quality") or {}).get("score")
                if extr is not None and extr < 0.3:
                    reasons.append(f"提取质量极低 (score={extr:.2f})")
                comp = (sr.get("completeness") or {}).get("score")
                if comp is not None and comp < 0.5:
                    reasons.append(f"数据完整性严重不足 (score={comp:.2f})")
                ql = (sr.get("quality_scoring") or {}).get("quality_level")
                if ql == "poor":
                    reasons.append("质量等级 poor")
                if not reasons:
                    reasons.append("Assessment 判定需人工审核")
                pending.append({
                    "conflict_d": f"QHR-{sid[:20]}",
                    "field_name": "",
                    "entity_name": "",
                    "reason": "; ".join(reasons),
                    "evidence_summary": {
                        "extraction_quality": extr,
                        "completeness": comp,
                        "quality_level": ql,
                    },
                    "source_a": {"source_id": sid},
                    "source_b": {},
                    "cohens_d": 0, "effect_size": "",
                    "reasoning_chain": reasons,
                    "risk_assessment": "quality_issue",
                    "confidence": 0,
                    "strategy": "escalate_to_human",
                })

        return pending

    def _print_conflict(self, c: dict, idx: int, total: int):
        """格式化打印单条冲突信息。"""
        fn = c.get("field_name", "?")
        cid = c.get("conflict_d", "?")

        print(f"  冲突 {idx}/{total}: [{cid}] {fn}")
        print(f"  原因: {c.get('reason', '?')[:120]}")
        print()

        # Source 对比
        sa = c.get("source_a", {})
        sb = c.get("source_b", {})
        if isinstance(sa, dict) and isinstance(sb, dict):
            print(f"  {'Source A':25s} │ {'Source B':25s}")
            print(f"  {'-'*25}─┼─{'─'*25}")
            print(f"  {'ID: ' + str(sa.get('source_id','?'))[:23]:25s} │ {'ID: ' + str(sb.get('source_id','?'))[:23]:25s}")
            print(f"  {'值: ' + str(sa.get('value','?')) + ' ' + str(sa.get('unit','')):25s} │ {'值: ' + str(sb.get('value','?')) + ' ' + str(sb.get('unit','')):25s}")
            print(f"  {'可靠性: ' + str(sa.get('reliability','?')):25s} │ {'可靠性: ' + str(sb.get('reliability','?')):25s}")
            print()

        # 统计证据
        cohens_d = c.get("cohens_d", 0)
        effect = c.get("effect_size", "")
        if cohens_d:
            print(f"  Cohen's d: {cohens_d:.2f} ({effect})")

        chain = c.get("reasoning_chain", [])
        if chain:
            print("\n  Agent 推理链:")
            for step in chain[:5]:
                print(f"    - {step[:100]}")  # V3.5: ASCII 安全 (GBK 终端不支持 •)

    def _get_user_choice(self, c: dict) -> dict:
        """获取用户选择。"""
        sa = c.get("source_a", {})
        sb = c.get("source_b", {})

        options = [
            ("1", "adopt_source_a", f"采用 Source A 的值 ({sa.get('value','?')} {sa.get('unit','')})" if isinstance(sa, dict) else "采用 Source A"),
            ("2", "adopt_source_b", f"采用 Source B 的值 ({sb.get('value','?')} {sb.get('unit','')})" if isinstance(sb, dict) else "采用 Source B"),
            ("3", "custom_value", "输入自定义值"),
            ("4", "retain_both", "保留两者 (标注差异)"),
            ("5", "skip", "跳过 (保留原样)"),
        ]
        # C-01 fix: QHR 质量类审核项 (field_name/entity_name 均空) 无具体字段/记录可写回,
        # 禁用 adopt_source_a/b 与 custom_value 裁决 — 仅允许 retain_both (降级为 annotate) / skip
        if not c.get("field_name") and not c.get("entity_name"):
            options = [o for o in options if o[1] in ("retain_both", "skip")]

        print(f"\n  {_SEP3}")
        print("  请选择裁决方式:")
        for key, action, label in options:
            print(f"    [{key}] {label}")
        print(f"  {_SEP3}")

        for _ in range(3):
            choice = interrupt({"type": "human_review_verdict", "text": "  请输入选项 [1-5]: ",
                                "options": [o[0] for o in options]})
            if choice is None:
                choice = ""
            choice = str(choice).strip()
            if not choice:
                # C-01 fix: 空串输入视为无效 → 回退重问
                print("  无效选项，请重新输入")
                continue
            for key, action, label in options:
                if choice == key:
                    if action == "custom_value":
                        # C-01 fix: 自定义值空串视为无效, 重问 (最多 3 次后降级 skip)
                        for _ in range(3):
                            val = interrupt({"type": "human_review_custom_value", "text": "  请输入自定义值: "})
                            if val is None:
                                val = ""
                            val = str(val).strip()
                            if not val:
                                print("  无效输入，请重新输入")
                                continue
                            try:
                                selected = float(val) if "." in val or "e" in val.lower() else int(val)
                            except ValueError:
                                selected = val
                            return {"action": action, "selected_value": selected}
                        print("  3 次无效输入，默认跳过")
                        return {"action": "skip", "selected_value": None}
                    elif action == "adopt_source_a":
                        val = sa.get("value") if isinstance(sa, dict) else None
                        if val is None:
                            # M1 fix: 源无具体值 → 降级走自定义值流程, 避免决策静默丢失
                            # C-01 fix: 空串视为无效, 重问 (最多 3 次后降级 skip)
                            for _ in range(3):
                                val = interrupt({"type": "human_review_custom_value",
                                                 "text": "  该源无具体值, 请输入自定义值: "})
                                if val is None:
                                    val = ""
                                val = str(val).strip()
                                if not val:
                                    print("  无效输入，请重新输入")
                                    continue
                                try:
                                    val = float(val) if "." in val or "e" in val.lower() else int(val)
                                except (ValueError, TypeError):
                                    pass
                                return {"action": action, "selected_value": val}
                            print("  3 次无效输入，默认跳过")
                            return {"action": "skip", "selected_value": None}
                        return {"action": action, "selected_value": val}
                    elif action == "adopt_source_b":
                        val = sb.get("value") if isinstance(sb, dict) else None
                        if val is None:
                            # M1 fix: 同上
                            # C-01 fix: 空串视为无效, 重问 (最多 3 次后降级 skip)
                            for _ in range(3):
                                val = interrupt({"type": "human_review_custom_value",
                                                 "text": "  该源无具体值, 请输入自定义值: "})
                                if val is None:
                                    val = ""
                                val = str(val).strip()
                                if not val:
                                    print("  无效输入，请重新输入")
                                    continue
                                try:
                                    val = float(val) if "." in val or "e" in val.lower() else int(val)
                                except (ValueError, TypeError):
                                    pass
                                return {"action": action, "selected_value": val}
                            print("  3 次无效输入，默认跳过")
                            return {"action": "skip", "selected_value": None}
                        return {"action": action, "selected_value": val}
                    else:
                        return {"action": action, "selected_value": None}
            print("  无效选项，请重新输入")

        # 默认: 跳过
        print("  3 次无效输入，默认跳过")
        return {"action": "skip", "selected_value": None}

    def _get_user_reason(self) -> str:
        """获取用户理由（Phase 4c: interrupt() HITL）。"""
        reason = interrupt({"type": "human_review_reason", "text": "  请输入理由 (可选, 直接回车跳过): "})
        if reason is None:
            reason = ""
        reason = str(reason).strip()
        return reason[:500] if reason else ""

    def _no_conflicts_result(self, state: dict) -> dict:
        """无冲突时的跳过结果 (V3.3: 清除 pending_sources['HumanReview'] 防死循环)。"""
        pending = dict((state.get("workflow_state") or {}).get("pending_sources") or {})
        pending["HumanReview"] = []
        return {
            "workflow_state": {
                "route_decision": "Export",
                "execution_status": "Success",
                "current_node": "human_review",
                "phase": "human_review",
                "pending_sources": pending,
                "__human_review_needed__": False,
                "__human_review_decision__": None,
                "__human_review_data__": None,
                "workflow_history": [{
                    "agent": "HumanReview", "stage": "Skipped",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": 0.0,
                    "reason": "No conflicts to review → Export",
                }],
            },
        }
