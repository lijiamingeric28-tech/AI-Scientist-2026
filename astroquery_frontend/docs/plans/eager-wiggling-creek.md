# HumanReview HITL 前后端批量重构实施计划

## Context

质量管线人工审核（HumanReview）在 Web 端不可用，实测三个 bug 叠加：

1. **无限堆积循环**：SN 2011fe 任务触发 14 项异常归类，逐项 interrupt 提问（每冲突 2-3 个微步 ≈ 3N+ 次），前端"澄清 1-17"逐条堆积；Step 4b"取消"路径不清 `pending["HumanReview"]`（human_review_agent.py:197-205）导致整批重审循环。resume 机制本身正常（langgraph 1.2.8 实测重放正确，`set_shared_checkpointer` 已修复 config 键剥离）。
2. **看不到要裁决什么**：ClarificationCard.jsx:99 `{isConfirm && payload.fields && ...}`——isConfirm 只认 final_confirm，human_review 的 fields（后端已生成透传）被 gate 挡住永不渲染。
3. **无统一裁决**：14 项同类异常（均只 retain_both/skip 可选）被逐条询问，应为一次"全部保留/全部跳过"。

**用户决策**：
- 去掉"全部跳过/全部保留"批量按钮——**强制逐项裁决**，每项 = 后端判断给出的 1-5 选项卡 + 可选理由
- 冲突数据 markdown 化展示；CLI/Web 统一协议
- **理由传递链**（Plan 探索确认）：用户理由 → `decisions[cid]["reason"]` → `_decisions_to_actions`(262-309) 三处 action 模板追加 `理由: {文本}` 后缀 → `actions[].reason` → `source_router_agent.py:76/94` 复制进 source_plan → `normalization_agent.py:161/181/184/226` 写入 data_trace 与记录 `_annotation` → `traceability_builder` 进入**最终导出溯源**（最终表现形式 = 导出数据该记录"修改/标注原因"文本，前端溯源详情可见）
- 逐项不填理由 → `reason=""`，动作 reason 仅基础模板无后缀

## 新协议（契约层）

### 单次 interrupt（type: `human_review_batch`，新独立 type 名，避免与历史事件混淆）

```python
interrupt({
  "type": "human_review_batch",
  "title": "人工审核（N 个冲突）",
  "question": "请对 N 个冲突逐一进行人工裁决…",
  "text": "<CLI 完整提示文本：全部冲突列表 + 输入协议（逐项，无批量速记）>",
  "count": N,
  "summary_markdown": "<整批 markdown 汇总>",
  "conflicts": [{conflict_d, field_name, entity_name, reason(300字),
                 markdown(单条), source_a{id/value/unit/reliability}, source_b, cohens_d,
                 options:[1-5或4-5]}],
})
```
- payload 双通道：`text` 给 CLI（`_prompt_for_interrupt` 只读 text/question），`conflicts[].markdown`+结构字段给 Web。agent 无需探测运行模式。
- reasoning_chain/risk_assessment 烘焙进 markdown，不进 payload 顶层空间（控 checkpoint 体积）。
- **无顶层 options 键**（批量按钮已废）；逐项 options 在 conflicts[i].options

### resume answer（ResumeBody.answer 是 str，放 JSON 字符串；CLI/Web 同一解析器）

```
Web 面板生成（CLI 可粘贴）:  {"verdicts": {"CF-001": {"action":"adopt_source_a","reason":"..."}, ...}}
CLI 速记:  CF-001:2 | CF-001:3:770 | CF-001:2|理由 | CF-001:4,CF-002:5 | 裸"4"(单冲突兼容)
```
- **无 all:4/all:5 批量速记**（用户已否：强制逐项）
- 校验：action 必须在冲突 options 内（QHR 项 adopt/custom 无效）；adopt 的 selected_value 由后端从 conflict.source_a/b 读取（不信任前端）；custom_value 缺值无效；无效/未裁决项默认 skip，返回 invalid 列表重问（≤3 次，3 次后全部 skip 降级）
- 每项裁决**必须显式选择**后才算提交（未裁决项提交时提示，不静默跳过）

### human_review_next 保留为第二个 interrupt（每次 HR 固定 2 次 interrupt，原 ≈3N+）

## Phase 1 — 协议层透传（web_runner.py）

- `_CLAR_TITLES` 加 `"human_review_batch": "人工审核"`（老 4 个 key 保留供历史重放）
- `_CLAR_STAGES` 加 `"human_review_batch": "clean"`（**关键：漏了会渲染到 understand 卡**）
- `_clarification_payload` 白名单透传 `conflicts/summary_markdown/count`（行 128-145）
- 风险低，可独立合入。

## Phase 2 — HumanReviewAgent 重构（核心，human_review_agent.py）

1. **Step 3 重写为 `_interact_batch(conflicts)`**：单次批量 interrupt → `_parse_batch_answer` 解析 → 无效重问（≤3）→ 3 次无效全部 skip 降级
2. **新私有方法**：`_build_batch_payload` / `_render_conflict_markdown`（markdown 表格式：冲突标题+原因+Source A/B 对照表+Cohen's d+推理链）/ `_render_batch_text`（CLI 文本）/ `_parse_batch_answer` / `_coerce_value`（复用现有值类型推断逻辑）/ `_default_decisions` / `_conflict_options`（QHR→["4","5"]，否则 1-5）
3. **decisions 形状与现 154-164 行完全一致**（record_ids/source_id 等作用域由后端从 conflict 回填）
4. **reason 下游打通**（`_decisions_to_actions` 行 262-309）：三处 reason 模板追加用户理由后缀 `理由: {r[:200]}`——理由流经 actions[].reason → source_plan(normalization) → data_trace/_annotation → 最终导出溯源。逐项不填理由 → `reason=""` 无后缀；`reviewer_notes`（行 217）聚合非空理由，不再硬编码 ""
5. **Step 4b 取消路径修复**（行 197-205）：取消 = 放弃本轮审核 → 清 `pending["HumanReview"]` + `route_decision="Export"` + `execution_status="Success"`（**语义变更，需用户确认**；任务级中止仍走 executor cancel 按钮）
6. **兼容/回滚**：`_get_user_choice/_get_user_reason/_print_conflict` 原样保留（C-01 单测直接调用，加 deprecated 注释）；`HUMAN_REVIEW_BATCH_ENABLED=0` 环境变量切回旧逐条循环（`_run_legacy_interaction` 保留现有 93-165 逻辑）；批量构建 try/except 异常 → 降级 legacy

## Phase 3 — 前端

1. **新组件 `HumanReviewPanel.jsx`**（内嵌卡片，不做弹窗，沿用 ClarificationCard 外壳）：
   - `Markdown(payload.summary_markdown)`（复用 lib/markdown.jsx）
   - **逐项裁决**（无批量按钮）：每项 `<details>` 折叠 → Markdown(c.markdown) + select(1-5 按 c.options 过滤) + 自定义值 input（选中 3 时显示）+ 理由 input（可选）
   - **必选校验**：提交时存在未选项 → 高亮提示"第 N 项未选择"，不提交（不静默 skip）
   - `提交裁决` → 组装 `JSON.stringify({verdicts})` → onSubmit 一次提交
   - ACTION_BY_KEY 映射 {1:adopt_source_a, ..., 5:skip}
2. **ClarificationCard.jsx**：
   - 修 isConfirm gate（行 99）：改为 `payload.fields && payload.fields.length > 0 &&`——历史 human_review_verdict 重放正确显示 fields
   - 顶部 batch 分支：`payload.type === 'human_review_batch'` → 渲染 HumanReviewPanel，快捷按钮/输入框不渲染
3. **usePipeline.js**：clarification 分支（589-612）与快照恢复（790-807）透传 conflicts/summary_markdown/count；quickButtons 对 batch 短路 `return []`（防"选项 4/选项 5"兜底芯片）
4. **lib/stages.js**：`CLARIFICATION_QUICK_BUTTONS` 加 `human_review_batch: []`
5. **StageCard.jsx**（可选）：history 中 batch answer 展示为"裁决 N 项冲突"
6. **web/executor.py** 行 439：`answer[:200]` → `[:4096]`（批量 JSON 不再被截断）

## Phase 4 — 测试

**必改**：
- test_b8_quality_telemetry.py:59 `test_human_review_agent_interrupts_carry_question`（断言恰 4 次）→ 重写为批量版：断言 2 次 interrupt（batch + next）、payload type/conflicts/markdown、逐项 options、route_decision="Normalization"
- test_smoke_network.py:38 `mock_hr_interrupt` 返回 "3" → 改逐项 JSON（如 `'{"verdicts":{...}}'`）或全 skip 的 CLI 速记

**新增**：batch JSON 解析 / CLI 速记（CF-001:2、CF-001:3:770 类型推断、CF-001:2|理由、逗号多项）/ QHR 选项限制 / 无效重问带 error / 3 次无效降级 / 未裁决项拒绝提交 / reason 传递到 actions / 取消清 pending / payload 透传 / 单冲突裸 answer 兼容

**零改动通过**：C-01 段（直接调 _get_user_choice/_decisions_to_actions——方法保留）、H-04/H-13（_extract_pending）、test_quality_pipeline 节点清单、test_b8 M-16（假 agent）

## Phase 5 — 迁移与回滚

- 新 type 独立注册；老 type 键/方法保留 → 历史事件重放与单测不断
- in-flight 旧 interrupt：裸 token 单冲突兼容映射；多冲突旧批次 3 次无效 → 全部 skip 交付（建议取消重跑）
- 回滚：`HUMAN_REVIEW_BATCH_ENABLED=0` 走 legacy 循环（代码级，无需 git revert）
- 失败降级链：markdown 异常 → legacy；无 checkpointer → 既有 hitl_needs_checkpointer 降级；解析 3 次失败 → 全 skip

## 验证

1. 本地跑 `SN 2011fe 的峰值绝对星等`（必触发 human_review，之前 14 项批量场景）
2. 前端验收：markdown 冲突数据可见、批量按钮可点、逐项覆盖可点、无无限堆积、2 次 interrupt 完成
3. pytest：`python -m pytest tests/test_b8_quality_telemetry.py tests/test_audit_fixes_pipeline.py tests/test_smoke_network.py -x`
4. 回归：跑一次非 human_review 任务（如 Pollux）确认无影响

## 风险清单

1. interrupt 重试确定性：`_build_batch_payload`/`_parse_batch_answer` 必须纯函数（conflicts 来源确定）——最高优先级约束
2. checkpoint 体积：markdown+精简字段控体积（单条 ~1-2KB）
3. `_CLAR_STAGES` 漏配 → batch 卡渲染到 understand 卡（Phase 1 验收项）
4. 取消语义变更需用户确认
5. CLI 速记理由含 `|`/`:` 歧义（JSON 粘贴为权威路径，文档注明）
6. 顺手修复 graph.py:221 `result.get("conflict")` 键名小 bug（与 agent 返回 report_state.conflict 不符，HumanReview reason 摘要恒走兜底分支）
