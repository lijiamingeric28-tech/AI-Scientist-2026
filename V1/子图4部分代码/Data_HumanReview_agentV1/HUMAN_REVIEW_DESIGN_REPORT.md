# Human Review SubGraph 设计报告 V1.0

> **版本**: V1.0 — 命令行交互式人工审核
> **设计原则**: 展示 Conflict Agent 无法自动处理的异常/冲突 + Assessment 判定的质量问题，收集人工决策，路由到目标模块
> **交互方式**: 命令行对话（无 UI），逐条展示 + 用户选择
> **对应文件**: `Data_HumanReview_agentV1/` + `graph.py` 中的 `human_review_node`
> **更新 (2026-08-03, V4.2)**: 与代码全面对齐
> **更新 (2026-08-04, V4.3)**: 上游字段名标准化增强（VizieR 目录 1178 别名映射）— 本模块无代码改动, 待审核项字段名更规整

---

## 0. 变更记录 (V4.2 → V4.3)

### V4.3 (2026-08-04) — VizieR 目录 schema 扩展

| 变更 | 内容 |
|------|------|
| 上游字段名映射增强 | `target_schema_astrophysics` aliases 349 → 1178（覆盖 23 个 VizieR 目录列名）→ 人工审核展示的字段名更规整（catalog 列保留原始名）；本模块无代码改动 |

本报告已按当前源码逐段核对更新。以下为源码注释中 V3.0 → V4 的关键修复记录:

| 版本 | 变更 |
|------|------|
| V3.0 | E→A 路径: 用户可选"送回 Assessment 重新评估"; `anomaly_flags` 筛选 `action=human_review` (cross_id_error) |
| V3.1 | 主来源改为 `resolution_plan.human_review_items` (由 resolution_report_agent 生成); 兼容 anomaly_flags; 人工决策后清除循环标记 `from_conflict=False`; 使用用户选择的 target_route (E→A / E→B), 不再硬编码 Normalization |
| V3.2 | 人工决策转换为可执行 `normalization_actions` (`actions_to_normalize`, E→B 时由 SourceRouterAgent 消费); 决策携带冲突详情 (source_id/field_name/entity_name/record_ids) |
| V3.3 | 人工审核完成/无冲突时清除 `pending_sources["HumanReview"]` (防死循环); `conflict` 空值保护 (dispatch 清理后可能为 None); 无冲突 → Export; 写 `phase="human_review"` |
| V3.5 | `review_items` 抽象: Assessment 触发 HR (提取质量过低/严重质量问题) 但无 conflict 报告时, 从 `quality.per_source_routes` 构造质量类审核项 (QHR-*); 取消时保留状态 (`execution_status="HumanReview"`); ASCII 安全输出 (GBK 终端兼容) |
| V4 | `_route_after_gate`: HumanReview 不再直达 — Assessment gate 经 dispatch (队列路由 + 计数器重置), Norm/Conflict gate 经 loop (pending_sources 簿记清理); 跳过簿记会导致 C→E 后 `pending["Conflict"]` 残留 → 无限循环 |

---

## 1. Agent 元信息

### 1.1 基本属性

| 属性 | 内容 |
|------|------|
| **Agent 名称** | Human Review Agent |
| **模块名称** | Data_HumanReview_agentV1 |
| **所属子图** | SubGraph 4 (数据清洗与质检) — 人工审核节点 |
| **版本** | V1.0 |
| **核心职责** | 展示无法自动处理的异常/冲突 (Conflict 的 human_review_items / anomaly_flags + Assessment 判定的质量问题)，收集人工决策，将决策结果路由到 Normalization 或 Assessment |
| **关键约束** | **不修改数据**，只收集决策并写入 `workflow_state` (+ 可执行的 normalization_actions) |
| **修改数据** | ❌ 否 — 只写入路由决策与动作计划，数据修改由 Normalization 执行 |
| **交互方式** | 命令行 stdin/stdout 对话 |

### 1.2 前后置条件

| 条件类型 | 条件 |
|---------|------|
| **前置条件 (A→E)** | Assessment 决策矩阵判定 HumanReview (严重问题/重试耗尽/Failed), 经 Gate(A) → Dispatch (V4: HR 经 dispatch 队列路由 + 计数器重置, `pending_sources["HumanReview"]` 非空 → 优先路由 HR) |
| **前置条件 (C→E)** | Conflict 裁决 `escalate_to_human` / `resolution_report.route_decision="HumanReview"`, 经 Gate(C) → LoopController (V4: 经 loop 簿记清理 pending) |
| **前置条件 (其他)** | 任一子图 `execution_status` 为 Retry 超限 / Failed → Stage Gate 写 `route_decision="HumanReview"` |
| **后置条件** | `workflow_state.__human_review_decision__` 包含人工决策 `{decisions, route_decision, reviewer_notes, reviewed_at}` |
|  | `workflow_state.route_decision = "Normalization"` / `"Assessment"` / `"Export"` (无待审核项) |
|  | `workflow_state.__human_review_needed__ = False`; `pending_sources["HumanReview"] = []` (V3.3); `from_conflict=False` (V3.1) |

### 1.3 上下游关系

```
上游:
  Assessment SubGraph → (A→E): 决策矩阵判定严重问题 / Retry 耗尽 / Failed
  Conflict SubGraph → (C→E): escalate_to_human / 无法自动裁决的异常
  Stage Gate → (簿记路径): 子图 Failed / 重试超限 → Gate 写 HumanReview

下游:
  Normalization SubGraph → (E→B): 人工决策后执行数据修改 (消费 actions_to_normalize)
  Assessment SubGraph → (E→A): 人工判断需重新评估 (V3.0 新增)
  Export → (无待审核项): route_decision="Export"
```

### 1.4 在总图中的位置

```
Assessment → Gate(A) → Dispatch → HumanReview (A→E, 队列优先)
Conflict   → Gate(C) → LoopController → HumanReview (C→E, V4: 经 loop 簿记)
Retry 耗尽 / Failed → Gate → (Dispatch | Loop) → HumanReview

HumanReview 完成后 (route_after_human_review):
  ├── "Normalization" → Normalization (E→B, 直接路由)
  ├── "Assessment"    → Assessment   (E→A, 直接路由; Dispatch 在下一轮重置计数器)
  └── 其他 → 复用 Dispatch 队列逻辑, 继续处理剩余来源 (pending_sources["HumanReview"] 已清空)
```

---

## 2. 输入输出规范

### 2.1 读取的 State

| State 路径 | 类型 | 必读 | 用途 |
|-----------|------|------|------|
| `report_state.conflict.resolution_report.resolution_plan.human_review_items` | `list` | ✅ | V3.1: 主来源 — 由 resolution_report_agent 生成的待人工审核项 |
| `report_state.conflict.resolution_report.anomaly_flags` | `list` | ❌ | V3.0: 异常标记 (action=human_review, cross_id_error) |
| `report_state.conflict.resolution_report.per_conflict` | `list` | ❌ | 补全待审核项详情 (source_a/source_b/cohens_d/reasoning_chain) |
| `report_state.conflict.reasoning.per_conflict[*]` | `dict` | ❌ | 旧报告兼容: 筛选 `resolution=escalated_to_human` |
| `report_state.quality.per_source_routes` + `sources` | `dict` | ❌ | V3.5: Assessment 触发 HR 时构造质量类审核项 (QHR-*, 提取质量/完整度/等级) |
| `report_state.quality` | `dict` | ❌ | 质量报告 (上下文参考) |
| `data_state.current_data` | `dict` | ❌ | 当前数据 |
| `workflow_state.__human_review_decision__` | `dict\|None` | ✅ | 已有人工决策（恢复时读取, 非 None → 跳过交互直接应用） |
| `workflow_state.__human_review_needed__` | `bool` | ✅ | 是否需要人工审核 |
| `workflow_state.pending_sources` | `dict` | ✅ | V3.3: 来源处理队列 (完成/取消时清空 HumanReview 项) |

### 2.2 写入的 State

| State 路径 | 类型 | 写入者 | 内容 |
|-----------|------|--------|------|
| `workflow_state.__human_review_decision__` | `dict` | HumanReview | `{decisions: {cid: {action, selected_value, reason, conflict_id, source_id, field_name, entity_name, record_ids}}, route_decision, reviewer_notes, reviewed_at}` |
| `workflow_state.route_decision` | `str` | HumanReview | "Normalization" / "Assessment" / "Export" (无待审核项) |
| `workflow_state.execution_status` | `str` | HumanReview | "Success" (取消时 "HumanReview", V3.5) |
| `workflow_state.__human_review_needed__` | `bool` | HumanReview | False (已处理); 取消时保留 True |
| `workflow_state.__human_review_data__` | `Any` | HumanReview | 置 None (清理) |
| `workflow_state.pending_sources` | `dict` | HumanReview | V3.3: `pending_sources["HumanReview"] = []` (防死循环) |
| `workflow_state.phase` | `str` | HumanReview | V3.3: "human_review" |
| `workflow_state.from_conflict` | `bool` | HumanReview | V3.1 fix: False (人工决策后是新流程, 清除循环标记) |
| `report_state.conflict.resolution_report.resolution_plan.actions_to_normalize` | `list` | HumanReview | V3.2: 可执行动作 (E→B 时写入, 供 SourceRouterAgent 消费) |

---

## 3. 内部处理流程

### 3.1 流程概览

```
Human Review (命令行交互)

Step 1: 检查是否已有决策 (恢复模式)
  if __human_review_decision__ is not None:
    → 直接应用已有决策 (route_decision = 决策中的目标), 跳过交互
    → 清除 __human_review_decision__ / __human_review_data__ / 标记
    return

Step 2: 提取待审核项目 (_extract_pending, 依次尝试 4 个来源)
  1. resolution_plan.human_review_items          (V3.1 主来源, per_conflict 补全详情)
  2. anomaly_flags 中 action=human_review        (V3.1 兼容, ANOM-* ID)
  3. reasoning.per_conflict 中 escalated_to_human (旧报告兼容)
  4. quality.per_source_routes 中 HumanReview 路由 (V3.5: Assessment 触发 HR 时
     从 quality 构造质量类审核项 QHR-*, 不跳过人工审核)
  全部为空 → route_decision="Export" (V3.3: 并清空 pending_sources["HumanReview"])

Step 3: 展示摘要
  打印: "N 个冲突需要人工裁决" / "X/Y 冲突已自动解决" / 涉及字段列表

Step 4: 逐条展示 + 收集决策
  for each conflict/anomaly:
    展示详情:
      - 冲突 ID + 字段名 + 原因 (截断 120 字符)
      - Source A vs Source B (ID、值+单位、可靠性)
      - Cohen's d + 效应量解释
      - Agent 推理链 (前 5 条)
    用户选择 [1-5]: (最多 3 次重输, 无效 → 默认跳过)
      [1] 采用 Source A 的值
      [2] 采用 Source B 的值
      [3] 输入自定义值 (自动识别 int/float/字符串)
      [4] 保留两者 (标注差异)
      [5] 跳过 (保留原样)
    决策携带冲突详情 (V3.2): conflict_id/source_id/field_name/entity_name/record_ids

Step 4b: 全局出口选择 [1-3]
  [1] 提交裁决 → Normalization 执行修改 (E→B)
  [2] 无法判断 → 送回 Assessment 重新评估 (E→A) — V3.0 新增
  [3] 取消 (保留状态, __human_review_needed__=True, execution_status="HumanReview")

Step 5: 写入决策 (V3.2: 同时生成可执行动作)
  __human_review_decision__ = {decisions, route_decision, reviewer_notes, reviewed_at}
  actions = _decisions_to_actions(decisions)   # V3.2, 仅 E→B 时消费
  report_state.conflict.resolution_report.resolution_plan.actions_to_normalize = actions
  清理: pending_sources["HumanReview"]=[], phase="human_review",
        from_conflict=False, __human_review_needed__=False
```

### 3.2 V3.0 新增: E→A 路径

```
V3.0 支持人工判断 "数据问题太严重, 需要重新评估":
  - 用户选择 [2] "送回 Assessment 重新评估"
  - route_decision = "Assessment"
  - routers.py route_after_human_review: "Assessment" → NODE_ASSESSMENT (直接路由)

适用场景:
  - 数据经过 Normalization 后仍存在严重问题
  - 人工发现异常标记有误 (false_positive 应重新评估)
  - 需要更换评估策略

E→A 后: Assessment 完成 → Gate(A) → Dispatch 重置计数器/清空 route_decision
(V3.5/V4 fix — 防止上一轮 HumanReview 写入的 "Normalization" 残留被误读为 C→B)
```

### 3.3 V3.2: 决策 → 可执行动作转换 (_decisions_to_actions)

| 用户动作 | normalization_action | 说明 |
|---------|---------------------|------|
| adopt_source_a / adopt_source_b / custom_value | `human_replace` | 写回目标值 (new_value + record_ids), Normalization 执行替换 |
| retain_both | `annotate` | 标注差异, 不修改值 |
| skip | (无动作) | 保留原样 |

动作由 SourceRouterAgent 在 E→B 时消费 (`resolution_plan.actions_to_normalize`)。

---

## 4. 交互命令设计

### 4.1 冲突展示格式 (纯文本, V3.5: ASCII 安全 — GBK 终端兼容)

```
================================================================================
  HUMAN REVIEW — N 个冲突需要人工裁决
================================================================================
  摘要: X/Y 冲突已自动解决, N 个需要人工判断
  涉及字段: field_a, field_b, ...

--------------------------------------------------------------------------------
  冲突 i/N: [CF-xxx] field_name
  原因: ... (截断 120 字符)

  Source A                    │ Source B
  ---------------------------─┼─---------------------------
  ID: source_a_id             │ ID: source_b_id
  值: value unit              │ 值: value unit
  可靠性: reliability         │ 可靠性: reliability

  Cohen's d: 3.50 (LARGE)

  Agent 推理链:
    - step 1 (前 5 条, 各截断 100 字符)
--------------------------------------------------------------------------------
```

说明: 表格分隔保留 `│` / `─┼─` 框线字符; V3.5 fix — 推理链条目符号 (此前 `•`)
与取消提示 (此前 `✗`) 改为 ASCII `-` / `X`, 避免 GBK 终端乱码; 用户选项 [1-5]
与全局出口 [1-3] 均通过 `input()` 读取。

### 4.2 用户选项

| 选项 | 动作 | 说明 |
|------|------|------|
| 1 | 采用 Source A | 以 A 的值为准 |
| 2 | 采用 Source B | 以 B 的值为准 |
| 3 | 自定义值 | 用户手动输入 |
| 4 | 保留两者 | 标记差异不修改 |
| 5 | 跳过 | 保留原样 |

### 4.3 全局出口

| 选项 | 路由 | 说明 |
|------|------|------|
| 1 | Normalization (E→B) | 执行人工裁决的修改 |
| 2 | Assessment (E→A) | 送回重新评估 (V3.0 新增) |
| 3 | 取消 | 保留状态, 下次可恢复 |

---

## 5. 异常处理

| 场景 | 处理 |
|------|------|
| 无待审核项 | `route_decision = "Export"` (V3.3: 同时清空 `pending_sources["HumanReview"]` 防死循环) |
| 用户输入无效选项 | 提示重新输入，最多 3 次 → 默认跳过 (skip) |
| Conflict Report 缺失 | 空值保护 (V3.3: dispatch 清理后 conflict 可能为 None); V3.5: 从 `quality.per_source_routes` 构造质量审核项; 仍为空 → Export (不报 Failed) |
| 已有决策 → 恢复 | 直接应用, 跳过交互, 清除决策标记 |
| 用户取消 | 保留 `__human_review_needed__ = True`, `execution_status="HumanReview"` (V3.5), 状态保留下次可恢复 |
| 3 次无效裁决输入 | 默认 skip (保留原样) |

---

## 6. 文件清单

```
Data_HumanReview_agentV1/
├── HUMAN_REVIEW_DESIGN_REPORT.md    # 本报告 (V1.0, V4.2 → V4.3 更新)
├── __init__.py
└── human_review_agent.py            # 命令行交互 Agent (HumanReviewAgent)

graph.py 中:
  human_review_node()                # 调用 HumanReviewAgent

routers.py 中 (V3.1 图路由分离后, 路由全部集中于此):
  route_after_human_review()         # E→A / E→B 直接路由, 其他 → Dispatch 队列逻辑
  route_after_dispatch()             # HumanReview 队列优先 (V3.3)
  route_after_loop()                 # next_route="HumanReview" → HR (C→E)
  loop_controller_node()             # 状态机: route=="HumanReview" → next_route
  dispatch_node()                    # pending_sources 队列初始化 + 旧报告清理 (V3.2)
  _make_stage_gate()                 # Retry 耗尽 / Failed → route_decision="HumanReview"
  check_retry()                      # Failed → NODE_HUMAN_REVIEW

graph.py 中:
  _route_after_gate(node, next_node, human_target)  # V4: Gate 条件边
    - human_target: assessment→NODE_DISPATCH, norm/conflict→NODE_LOOP
      (HR 不再直达 — 经 dispatch/loop 簿记清理, 防止 pending 残留死循环)
```
