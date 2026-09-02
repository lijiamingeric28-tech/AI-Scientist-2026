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
import os
import sys
from typing import Any

from langgraph.types import interrupt

from quality_pipeline.quality_state import QualityGraphState
from quality_pipeline.utils.logger import get_logger

logger = get_logger(__name__)

_SEP = "=" * 80
_SEP2 = "-" * 80
_SEP3 = "-" * 60

# 2026-09-02: 批量裁决协议开关（回滚通道——置 "0" 走旧逐条循环，无需 git revert）
_BATCH_ENABLED = os.environ.get("HUMAN_REVIEW_BATCH_ENABLED", "1") != "0"


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

        # ── Step 3: 人工裁决（2026-09-02 批量协议：单次 interrupt 承载全部冲突）──
        if _BATCH_ENABLED:
            try:
                decisions = self._interact_batch(conflicts)
            except Exception:
                # 批量构建/渲染异常 → 降级 legacy 逐条（不阻塞流程）
                logger.exception("[HumanReview] 批量交互失败，降级逐条")
                decisions = self._run_legacy_interaction(conflicts, rs)
        else:
            decisions = self._run_legacy_interaction(conflicts, rs)

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
                    f"    [3] 取消 → 放弃人工审核, 数据原样交付\n  {_SEP3}\n  请输入选项 [1-3]: ")
        # H-10: Web 端 HITL 指引 — question 键（取指引文本去分隔符）
        _hr_question = ("请选择下一步：[1] 提交裁决（Normalization 执行修改 E→B） "
                        "[2] 无法判断（送回 Assessment 重新评估 E→A） "
                        "[3] 取消（放弃人工审核，数据原样交付）")
        next_step = interrupt({"type": "human_review_next", "text": _hr_text,
                               "question": _hr_question, "options": ["1", "2", "3"]})
        if next_step is None:
            next_step = ""
        next_step = str(next_step).strip()

        if next_step == "3":
            # 2026-09-02 fix: 取消 = 放弃本轮人工审核、继续交付（数据原样导出，不标注差异）。
            # 旧语义"保留状态待恢复"会因 pending["HumanReview"] 未清而整批重审死循环；
            # 任务级中止仍走 web executor 的 cancel 按钮，不经过本节点。
            print("  X 已取消。放弃人工审核，数据原样交付。")
            _pending = dict(wf.get("pending_sources") or {})
            _pending["HumanReview"] = []
            return {
                "workflow_state": {
                    "execution_status": "Success",
                    "route_decision": "Export",
                    "current_node": "human_review",
                    "phase": "human_review",
                    "pending_sources": _pending,
                    "__human_review_needed__": False,
                    "workflow_history": [{
                        "agent": "HumanReview", "stage": "Cancelled",
                        "status": "Success",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "duration": 0.0,
                        "reason": "Human cancelled review → Export (data as-is)",
                    }],
                },
            }
        elif next_step == "2":
            target_route = "Assessment"
            print("  → 送回 Assessment 重新评估 (E→A)")
        else:
            target_route = "Normalization"
            print("  → 提交裁决到 Normalization 执行修改 (E→B)")

        # ── Step 5: 写入决策 ──
        # 2026-09-02: reviewer_notes 聚合非空理由（不再硬编码 ""）
        _notes = "; ".join(f"{cid}: {d.get('reason')}" for cid, d in decisions.items() if d.get("reason"))
        decision_record = {
            "decisions": decisions,
            "route_decision": target_route,
            "reviewer_notes": _notes,
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
        """将人工决策转换为 NormalizationAction 列表 (V3.2)。

        2026-09-02: 用户理由打通下游——三处 reason 基础模板追加 `理由: {r}` 后缀，
        理由流经 actions[].reason → source_plan → data_trace/_annotation → 导出溯源。
        """
        actions = []
        for cid, d in decisions.items():
            action = d.get("action", "skip")
            # 用户理由后缀（无理由 → 仅基础模板）
            _r = d.get("reason") or ""
            _suffix = f" 理由: {_r[:200]}" if _r else ""
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
                        "reason": f"Human decision [{cid}]: {action} degraded to annotate (missing scope){_suffix}",
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
                    "reason": f"Human decision [{cid}]: {action}{_suffix}",
                })
            elif action == "retain_both":
                actions.append({
                    "source_id": d.get("source_id", ""),
                    "field": d.get("field_name", ""),
                    "field_name": d.get("field_name", ""),
                    "entity_name": d.get("entity_name", ""),
                    "action": "annotate",
                    "reason": f"Human decision [{cid}]: retain both values{_suffix}",
                })
            # skip → 无动作
        return actions

    # ── 2026-09-02 批量裁决协议 ──

    def _run_legacy_interaction(self, conflicts: list[dict], rs: dict) -> dict:
        """旧逐条交互（回滚通道）：每冲突 _get_user_choice + _get_user_reason。
        HUMAN_REVIEW_BATCH_ENABLED=0 时启用。deprecated: 仅回滚/单测用。"""
        decisions = {}
        for i, c in enumerate(conflicts):
            cid = c.get("conflict_d", f"CF-{i+1:03d}")
            print(f"\n  {_SEP2}")
            self._print_conflict(c, i + 1, len(conflicts))
            print(f"  {_SEP2}")
            choice = self._get_user_choice(c)
            reason = self._get_user_reason()
            decisions[cid] = {
                **choice,
                "reason": reason, "conflict_d": cid,
                "source_id": (c.get("source_a") or {}).get("source_id", ""),
                "field_name": c.get("field_name", ""),
                "entity_name": c.get("entity_name", ""),
                "record_ids": [r.get("record_id") for r in
                               (c.get("source_a") or {}).get("records", [])]
                               if isinstance((c.get("source_a") or {}).get("records"), list)
                               else [],
            }
        return decisions

    def _interact_batch(self, conflicts: list[dict]) -> dict:
        """单次批量 interrupt + 解析 + 重问（≤3 次）→ decisions dict。

        强制逐项裁决（用户决策：无"全部保留/全部跳过"批量按钮）；
        每项由后端判断给出 1-5 选项（QHR 项仅 4/5）。
        decisions 形状与逐条版完全一致（record_ids/source_id 等由后端回填）。
        """
        payload = self._build_batch_payload(conflicts)
        invalid = []
        for attempt in range(3):
            attempt_payload = dict(payload)
            if invalid:
                attempt_payload["error"] = f"以下项裁决无效: {', '.join(invalid)}，请重新提交（第 {attempt+1}/3 次）"
            raw = interrupt(attempt_payload)
            decisions, invalid = self._parse_batch_answer(raw, conflicts)
            if not invalid:
                return decisions
            print(f"  无效项: {invalid}，请重新输入（{attempt+1}/3）")
        # 3 次无效 → 未落定项按 skip 落定（批量失败兜底，数据原样交付）
        return self._default_decisions(conflicts, "skip", "批量跳过（3 次无效输入自动降级）")

    def _build_batch_payload(self, conflicts: list[dict]) -> dict:
        """批量 interrupt payload：text 给 CLI，conflicts[].markdown+结构字段给 Web。

        纯函数（conflicts 来自 _extract_pending 的确定读取）——interrupt 重试重放
        依赖 payload 逐字节稳定，禁止全局/可变状态。
        """
        n = len(conflicts)
        return {
            "type": "human_review_batch",
            "title": f"人工审核（{n} 个冲突）",
            "question": f"请对 {n} 个冲突逐一进行人工裁决：每项需选择裁决方式（1-5），并可选填理由。",
            "text": self._render_batch_text(conflicts),
            "count": n,
            "summary_markdown": self._render_summary_markdown(conflicts),
            "conflicts": [
                {
                    "conflict_d": c.get("conflict_d", f"CF-{i+1:03d}"),
                    "field_name": c.get("field_name", ""),
                    "entity_name": c.get("entity_name", ""),
                    "reason": (c.get("reason") or "")[:300],
                    "markdown": self._render_conflict_markdown(c, i + 1, n),
                    "source_a": self._slim_source(c.get("source_a")),
                    "source_b": self._slim_source(c.get("source_b")),
                    "cohens_d": c.get("cohens_d") or 0,
                    "effect_size": c.get("effect_size", ""),
                    "options": self._conflict_options(c),
                }
                for i, c in enumerate(conflicts)
            ],
        }

    @staticmethod
    def _slim_source(src) -> dict:
        """精简 source 字典（仅 id/value/unit/reliability，控 checkpoint 体积）。"""
        if not isinstance(src, dict):
            return {}
        return {k: src.get(k) for k in ("source_id", "value", "unit", "reliability") if src.get(k) is not None or k == "source_id"}

    def _conflict_options(self, c: dict) -> list[str]:
        """逐项合法选项（C-01 防护与 _get_user_choice 行 480-481 一致）：
        QHR 类（无 field/entity）仅 retain_both/skip；否则 1-5 全量。"""
        if not c.get("field_name") and not c.get("entity_name"):
            return ["4", "5"]
        return ["1", "2", "3", "4", "5"]

    def _render_summary_markdown(self, conflicts: list[dict]) -> str:
        """整批 markdown 汇总（前端顶部展示）。"""
        n = len(conflicts)
        fields = sorted({c.get("field_name") for c in conflicts if c.get("field_name")})
        lines = [f"### 人工审核 · {n} 个冲突"]
        if fields:
            lines.append(f"**涉及字段**：{'、'.join(fields)}")
        lines.append("请逐项裁决：每项选择裁决方式（1-5），可选填理由。")
        return "\n\n".join(lines)

    def _render_conflict_markdown(self, c: dict, idx: int, total: int) -> str:
        """单条冲突 markdown（字段/实体/原因/Source 对照/Cohen's d/推理链/风险）。"""
        cid = c.get("conflict_d", f"CF-{idx:03d}")
        fld = c.get("field_name") or "（质量类审核项）"
        ent = c.get("entity_name") or ""
        lines = [f"**冲突 {idx}/{total}：`{cid}`** 字段 `{fld}`" + (f" · 实体 `{ent}`" if ent else "")]
        if c.get("reason"):
            lines.append(f"\n**原因**：{c.get('reason')[:300]}")
        # Source 对照表
        sa, sb = c.get("source_a") or {}, c.get("source_b") or {}
        if sa or sb:
            rows = ["|  | Source A | Source B |", "|---|---|---|"]
            def _cell(src):
                if not isinstance(src, dict):
                    return "-"
                v = f"{src.get('value','?')} {src.get('unit','')}".strip()
                return f"{v}<br><sub>{src.get('source_id','?')}</sub>"
            rows.append(f"| 值 | {_cell(sa)} | {_cell(sb)} |")
            lines.append("\n" + "\n".join(rows))
        if c.get("cohens_d"):
            lines.append(f"\n**Cohen's d**：{c.get('cohens_d'):.2f}" + (f"（{c.get('effect_size')}）" if c.get("effect_size") else ""))
        chain = c.get("reasoning_chain") or []
        if chain:
            steps = chain[:5]
            lines.append("\n**推理链**：" + "；".join(f"({i+1}) {str(s)[:100]}" for i, s in enumerate(steps)))
        if c.get("risk_assessment"):
            lines.append(f"\n**风险**：{str(c.get('risk_assessment'))[:150]}")
        return "\n".join(lines)

    def _render_batch_text(self, conflicts: list[dict]) -> str:
        """CLI 完整提示文本：逐条冲突块 + 输入协议（逐项，无批量速记）。"""
        n = len(conflicts)
        out = [f"{_SEP}", f"  HUMAN REVIEW — {n} 个冲突需要人工裁决", f"{_SEP}"]
        for i, c in enumerate(conflicts, 1):
            cid = c.get("conflict_d", f"CF-{i:03d}")
            out.append(f"\n  [冲突 {i}/{n}] {cid} {c.get('field_name','?')} {c.get('entity_name','')}")
            out.append(f"    原因: {(c.get('reason') or '')[:120]}")
            sa, sb = c.get("source_a") or {}, c.get("source_b") or {}
            if sa or sb:
                out.append(f"    A={sa.get('value','?')}{sa.get('unit','')} B={sb.get('value','?')}{sb.get('unit','')}")
            opts = self._conflict_options(c)
            out.append(f"    选项: {'/'.join(opts)}")
        out.append(f"\n  {_SEP}")
        out.append("  输入协议（逐项裁决，无批量速记）：")
        out.append("    CF-001:2            采用 Source B")
        out.append("    CF-001:3:770        自定义值 770")
        out.append("    CF-001:2|理由文本    裁决 + 可选理由")
        out.append("    CF-001:4,CF-002:5   多项逗号分隔")
        out.append("    JSON            也可粘贴 {\"verdicts\":{...}}")
        out.append(f"  {_SEP}")
        return "\n".join(out)

    def _parse_batch_answer(self, raw, conflicts: list[dict]) -> tuple[dict, list[str]]:
        """解析批量答案 → (decisions, invalid_ids)。

        Web 面板恒发 JSON 字符串；CLI 速记同解析器（决策：CLI/Web 统一）。
        返回的 decisions 形状与逐条版一致（154-164 行原样字段，作用域由后端回填）。
        """
        decisions = {}
        invalid = []
        is_json_channel = False
        if raw is None:
            raw = ""
        raw = str(raw).strip()
        # 1) JSON 通道
        if raw.startswith("{"):
            is_json_channel = True
            try:
                import json as _json
                data = _json.loads(raw)
                verdicts = data.get("verdicts", {}) if isinstance(data, dict) else {}
                for cid, v in verdicts.items():
                    if not isinstance(v, dict):
                        invalid.append(str(cid)); continue
                    action = str(v.get("action", ""))
                    c = self._find_conflict(conflicts, cid)
                    if c is None:
                        invalid.append(str(cid)); continue
                    opts = self._conflict_options(c)
                    if action not in ("adopt_source_a", "adopt_source_b", "custom_value", "retain_both", "skip"):
                        invalid.append(str(cid)); continue
                    key = {"adopt_source_a": "1", "adopt_source_b": "2", "custom_value": "3",
                           "retain_both": "4", "skip": "5"}[action]
                    if key not in opts:
                        invalid.append(str(cid)); continue
                    val = None
                    if action == "custom_value":
                        val = v.get("selected_value")
                        if val is None or val == "":
                            invalid.append(str(cid)); continue
                    elif action in ("adopt_source_a", "adopt_source_b"):
                        # 后端权威读取，不信任前端传值
                        val = (c.get("source_a") or {}).get("value") if action == "adopt_source_a" else (c.get("source_b") or {}).get("value")
                    decisions[str(cid)] = self._build_decision(c, action=action, selected_value=val,
                                                               reason=str(v.get("reason") or ""))
                # JSON 通道未裁决项强制 invalid（Web 面板必选校验兜底）
                for c in conflicts:
                    cid = c.get("conflict_d", "?")
                    if cid not in decisions:
                        invalid.append(str(cid))
                return decisions, invalid
            except Exception:
                invalid.append("JSON 解析失败")
                # JSON 解析失败不继续走速记（防歧义）——除非整个 raw 是 JSON
                return decisions, invalid
        # 2) CLI 速记通道
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            # 裸 1-5 且单冲突批次（legacy 兼容——旧 in-flight 任务与 CLI 直觉）
            if token in ("1", "2", "3", "4", "5") and len(conflicts) == 1:
                c = conflicts[0]
                cid = c.get("conflict_d", "CF-001")
                key = token
                _val_part = ""
                _reason = ""
            elif ":" in token:
                cid, _, rest = token.partition(":")
                c = self._find_conflict(conflicts, cid)
                if c is None:
                    invalid.append(token); continue
                # rest 形如 "2" / "3:770" / "2|理由"
                _key_part = rest.split("|")[0].strip()
                key = _key_part.split(":")[0].strip()          # 自定义值前缀：3:770 → 3
                _val_part = _key_part.split(":", 1)[1] if ":" in _key_part else ""
                _reason = rest.split("|", 1)[1].strip() if "|" in rest else ""
                val_seg = ""
            else:
                invalid.append(token); continue
            opts = self._conflict_options(c)
            if key not in opts:
                invalid.append(token); continue
            action = {"1": "adopt_source_a", "2": "adopt_source_b", "3": "custom_value",
                      "4": "retain_both", "5": "skip"}[key]
            val = None
            if action == "custom_value":
                val = self._coerce_value(_val_part) if _val_part else None
                if val is None:
                    invalid.append(token); continue
            elif action in ("adopt_source_a", "adopt_source_b"):
                val = (c.get("source_a") or {}).get("value") if action == "adopt_source_a" else (c.get("source_b") or {}).get("value")
            decisions[str(cid)] = self._build_decision(c, action=action, selected_value=val, reason=_reason)
        # CLI 速记通道宽容：未列项默认 skip（不阻塞；Web JSON 通道由前端必选校验兜底，
        # 后端对 JSON 未覆盖项仍判 invalid——两者行为按通道区分）
        if is_json_channel:
            for c in conflicts:
                cid = c.get("conflict_d", "?")
                if cid not in decisions:
                    invalid.append(str(cid))
        else:
            for c in conflicts:
                cid = c.get("conflict_d", "?")
                if cid not in decisions:
                    decisions[str(cid)] = self._build_decision(c, action="skip", selected_value=None, reason="")
        return decisions, invalid

    @staticmethod
    def _find_conflict(conflicts, cid) -> dict:
        for c in conflicts:
            if c.get("conflict_d") == str(cid):
                return c
        return None

    @staticmethod
    def _coerce_value(s: str):
        """值类型推断（复用 _get_user_choice 行 539 逻辑）：含 ./e → float，可 int → int，否则 str。"""
        s = str(s or "").strip()
        if not s:
            return None
        try:
            if "." in s or "e" in s.lower():
                return float(s)
            return int(s)
        except ValueError:
            return s

    def _build_decision(self, c: dict, action: str, selected_value, reason: str) -> dict:
        """构造规范 decision 条目（与逐条版 154-164 字段一致，作用域由后端可信回填）。"""
        return {
            "action": action,
            "selected_value": selected_value,
            "reason": reason,
            "conflict_d": c.get("conflict_d", "?"),
            "source_id": (c.get("source_a") or {}).get("source_id", ""),
            "field_name": c.get("field_name", ""),
            "entity_name": c.get("entity_name", ""),
            "record_ids": [r.get("record_id") for r in (c.get("source_a") or {}).get("records", [])]
                           if isinstance((c.get("source_a") or {}).get("records"), list)
                           else [],
        }

    def _default_decisions(self, conflicts: list[dict], action: str, reason: str) -> dict:
        """全部按 action 落定（含默认 reason）。"""
        return {c.get("conflict_d", f"CF-{i+1:03d}"): self._build_decision(c, action=action, selected_value=None, reason=reason)
                for i, c in enumerate(conflicts)}

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

        # H-10: question 键带裁决方式列表（Web 端人工审核指引）
        # 2026-09-02: 附带冲突详情（source_a/b 的值），前端输入框不再"不知在给谁裁决"
        _detail = ""
        if isinstance(sa, dict) and sa.get("value") is not None:
            _detail += f"A=`{sa.get('value')}`{sa.get('unit','')}"
        if isinstance(sb, dict) and sb.get("value") is not None:
            _detail += f" B=`{sb.get('value')}`{sb.get('unit','')}"
        verdict_question = "请选择裁决方式：" + " / ".join(
            f"[{k}] {lbl}" for k, _action, lbl in options)
        if _detail:
            verdict_question += f"（{_detail}）"
        # 2026-09-02: structured fields——前端澄清卡渲染"需要裁决的数据"对比
        _fields = []
        if c.get("field_name"):
            _fields.append({"label": "冲突字段", "value": c.get("field_name")})
        if c.get("entity_name"):
            _fields.append({"label": "实体", "value": c.get("entity_name")})
        if isinstance(sa, dict):
            _fields.append({"label": "Source A", "value": f"{sa.get('value','?')} {sa.get('unit','')}".strip()})
        if isinstance(sb, dict):
            _fields.append({"label": "Source B", "value": f"{sb.get('value','?')} {sb.get('unit','')}".strip()})
        _cd = c.get("cohens_d") or 0
        if _cd:
            _fields.append({"label": "Cohen's d", "value": f"{float(_cd):.2f}"})
        for _ in range(3):
            choice = interrupt({"type": "human_review_verdict", "text": "  请输入选项 [1-5]: ",
                                "question": verdict_question,
                                "fields": _fields,
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
                            val = interrupt({"type": "human_review_custom_value", "text": "  请输入自定义值: ",
                                             "question": "请输入自定义值（数值或文本）"})
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
                                                 "text": "  该源无具体值, 请输入自定义值: ",
                                                 "question": "该源无具体值，请输入自定义值（数值或文本）"})
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
                                                 "text": "  该源无具体值, 请输入自定义值: ",
                                                 "question": "该源无具体值，请输入自定义值（数值或文本）"})
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
        reason = interrupt({"type": "human_review_reason", "text": "  请输入理由 (可选, 直接回车跳过): ",
                            "question": "请输入理由（可选，直接回车跳过）"})
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
