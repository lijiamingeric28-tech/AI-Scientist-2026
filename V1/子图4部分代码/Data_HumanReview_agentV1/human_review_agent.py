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

from quality_state import QualityGraphState
from utils.logger import get_logger

logger = get_logger(__name__)

_SEP = "=" * 80
_SEP2 = "-" * 80
_SEP3 = "-" * 60


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
            return self._no_conflicts_result()

        # ── Step 3: 命令行交互 ──
        print(f"\n{_SEP}")
        print(f"  HUMAN REVIEW — {len(conflicts)} 个冲突需要人工裁决")
        print(f"{_SEP}")

        quality = rs.get("quality", {}) or {}
        resolution_report = rs.get("conflict", {}).get("resolution_report", {})
        auto_resolved = resolution_report.get("metadata", {}).get("auto_resolved", 0)
        total = resolution_report.get("metadata", {}).get("total_conflicts", 0)
        print(f"\n  摘要: {auto_resolved}/{total} 冲突已自动解决, {len(conflicts)} 个需要人工判断")
        fields = list(set(c.get("field_name", "?") for c in conflicts))
        print(f"  涉及字段: {', '.join(fields)}")
        print()

        decisions = {}
        for i, c in enumerate(conflicts):
            cid = c.get("conflict_id", f"CF-{i+1:03d}")
            print(f"\n  {_SEP2}")
            self._print_conflict(c, i + 1, len(conflicts))
            print(f"  {_SEP2}")

            choice = self._get_user_choice(c)
            reason = self._get_user_reason()
            decisions[cid] = {**choice, "reason": reason, "conflict_id": cid}

        # ── Step 4: 确认汇总 ──
        print(f"\n{_SEP}")
        print(f"  决策汇总")
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

        # ── Step 4b: 全局出口选择 ──
        print(f"\n  {_SEP3}")
        print(f"  请选择下一步:")
        print(f"    [1] 提交裁决 → Normalization 执行修改 (E→B)")
        print(f"    [2] 无法判断 → 送回 Assessment 重新评估 (E→A)")
        print(f"    [3] 取消 (保留状态)")
        print(f"  {_SEP3}")
        next_step = input("  请输入选项 [1-3]: ").strip()

        if next_step == "3":
            print("  ✗ 已取消。保留当前状态，下次可恢复。")
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

        logger.info("[HumanReview] %d conflicts reviewed → Normalization", len(decisions))

        return {
            "workflow_state": {
                "route_decision": "Normalization",
                "execution_status": "Success",
                "current_node": "human_review",
                "__human_review_needed__": False,
                "__human_review_decision__": decision_record,
                "__human_review_data__": None,
                "workflow_history": [{
                    "agent": "HumanReview", "stage": "Resolved",
                    "status": "Success",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "duration": 0.0,
                    "reason": f"Human resolved {len(decisions)} conflicts → Normalization",
                }],
            },
        }

    # ── Helpers ──

    def _extract_pending(self, state) -> list[dict]:
        """提取所有待人工审核的冲突。"""
        conflict = state.get("report_state", {}).get("conflict", {})
        resolution_report = conflict.get("resolution_report", {})
        pending = []

        # 从 resolution_plan.human_review_items
        plan = resolution_report.get("resolution_plan", {})
        for item in plan.get("human_review_items", []):
            # 补全 per_conflict 中的详细信息
            per_conflict_map = {r.get("conflict_id", ""): r for r in resolution_report.get("per_conflict", [])}
            full = per_conflict_map.get(item.get("conflict_id", ""), {})
            pending.append({
                "conflict_id": item.get("conflict_id", "?"),
                "field_name": full.get("field_name", item.get("field_name", "?")),
                "reason": item.get("reason", full.get("reasoning_chain", [""])[0] if full.get("reasoning_chain") else ""),
                "evidence_summary": item.get("evidence_summary", {}),
                "source_a": full.get("source_a", {}),
                "source_b": full.get("source_b", {}),
                "cohens_d": full.get("cohens_d", 0),
                "effect_size": full.get("effect_size", ""),
                "reasoning_chain": full.get("reasoning_chain", []),
                "risk_assessment": full.get("risk_assessment", ""),
                "confidence": full.get("confidence", 0),
                "strategy": full.get("strategy", "escalate_to_human"),
            })

        # 备选: 从 reasoning.per_conflict 中筛选 escalated_to_human
        if not pending:
            reasoning = conflict.get("reasoning", {})
            for r in reasoning.get("per_conflict", []):
                if r.get("resolution") == "escalated_to_human":
                    pending.append({
                        "conflict_id": r.get("conflict_id", "?"),
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

        return pending

    def _print_conflict(self, c: dict, idx: int, total: int):
        """格式化打印单条冲突信息。"""
        fn = c.get("field_name", "?")
        cid = c.get("conflict_id", "?")

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
            print(f"\n  Agent 推理链:")
            for step in chain[:5]:
                print(f"    • {step[:100]}")

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

        print(f"\n  {_SEP3}")
        print(f"  请选择裁决方式:")
        for key, action, label in options:
            print(f"    [{key}] {label}")
        print(f"  {_SEP3}")

        for _ in range(3):
            choice = input("  请输入选项 [1-5]: ").strip()
            for key, action, label in options:
                if choice == key:
                    if action == "custom_value":
                        val = input("  请输入自定义值: ").strip()
                        try:
                            selected = float(val) if "." in val or "e" in val.lower() else int(val)
                        except ValueError:
                            selected = val
                        return {"action": action, "selected_value": selected}
                    elif action == "adopt_source_a":
                        return {"action": action, "selected_value": sa.get("value") if isinstance(sa, dict) else None}
                    elif action == "adopt_source_b":
                        return {"action": action, "selected_value": sb.get("value") if isinstance(sb, dict) else None}
                    else:
                        return {"action": action, "selected_value": None}
            print("  无效选项，请重新输入")

        # 默认: 跳过
        print("  3 次无效输入，默认跳过")
        return {"action": "skip", "selected_value": None}

    def _get_user_reason(self) -> str:
        """获取用户理由。"""
        reason = input("  请输入理由 (可选, 直接回车跳过): ").strip()
        return reason[:500] if reason else ""

    def _no_conflicts_result(self) -> dict:
        """无冲突时的跳过结果。"""
        return {
            "workflow_state": {
                "route_decision": "Export",
                "execution_status": "Success",
                "current_node": "human_review",
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
