# Human Review SubGraph 设计报告 V1.0

> **版本**: V1.0 — 命令行交互式人工审核
> **设计原则**: 展示 Conflict 无法自动裁决的冲突，收集人工决策，路由回 Normalization
> **交互方式**: 命令行对话（无 UI），逐条冲突展示 + 用户选择
> **对应文件**: `Data_HumanReview_agentV1/` + `graph.py` 中的 `human_review_node`

---

## 1. Agent 元信息

### 1.1 基本属性

| 属性 | 内容 |
|------|------|
| **Agent 名称** | Human Review Agent |
| **模块名称** | Data_HumanReview_agentV1 |
| **所属子图** | SubGraph 4 (数据清洗与质检) — 人工审核节点 |
| **版本** | V1.0 |
| **核心职责** | 展示 Conflict Resolution Agent 无法自动裁决的冲突，收集人工决策，将决策结果路由回 Normalization 执行 |
| **关键约束** | **不修改数据**，只收集决策并写入 `workflow_state.__human_review_decision__` |
| **修改数据** | ❌ 否 — 只写入路由决策，数据修改由 Normalization 执行 |
| **交互方式** | 命令行 stdin/stdout 对话 |

### 1.2 前后置条件

| 条件类型 | 条件 |
|---------|------|
| **前置条件** | Conflict Resolution Agent 执行完成，`route_decision = "HumanReview"` |
|  | `report_state.conflict.resolution_report` 包含 `human_review_items` |
|  | 或 `report_state.conflict.reasoning.per_conflict[*].resolution = "escalated_to_human"` |
| **后置条件** | `workflow_state.__human_review_decision__` 包含人工决策 |
|  | `workflow_state.route_decision = "Normalization"` |
|  | `workflow_state.__human_review_needed__ = False` |

### 1.3 上下游关系

```
上游:
  Conflict Resolution SubGraph (Data_Conflict_agentV1)
    → C→E: 冲突无法自动裁决，提交人工

下游:
  Normalization SubGraph (Data_Normalization_agentV1)
    → E→B: 人工裁决后，由 Normalization 执行数据修改
```

### 1.4 在总图中的位置

```
ConflictGraph → Router → HumanReview → NormalizationGraph
                              ↑            ↓
                              └────────────┘ (E→B，人工决策后回流)

注意: V1 规格中，Human Review 不回流到 Assessment (E→A 不存在)
```

---

## 2. 输入输出规范

### 2.1 读取的 State

| State 路径 | 类型 | 必读 | 用途 |
|-----------|------|------|------|
| `report_state.conflict.resolution_report` | `dict` | ✅ | 冲突裁决报告，提取待人工审核项 |
| `report_state.conflict.resolution_report.status` | `str` | ✅ | 裁决状态 (Partially_Resolved / All_Escalated) |
| `report_state.conflict.resolution_report.per_conflict` | `list` | ✅ | 每条冲突的详细推理信息 |
| `report_state.conflict.resolution_report.resolution_plan.human_review_items` | `list` | ✅ | 需要人工审核的冲突列表 |
| `report_state.conflict.evidence` | `dict` | ✅ | 每条冲突的证据详情 |
| `report_state.conflict.reasoning.per_conflict[*]` | `dict` | ❌ | 备选: 筛选 escalated_to_human 的冲突 |
| `report_state.quality` | `dict` | ❌ | 质量报告 (上下文参考) |
| `data_state.current_data` | `dict` | ✅ | 当前数据 (含冲突字段) |
| `workflow_state.iteration_counter` | `int` | ❌ | 循环次数 (上下文参考) |
| `workflow_state.__human_review_needed__` | `bool` | ✅ | 是否需要人工审核 |
| `workflow_state.__human_review_decision__` | `dict\|None` | ✅ | 已有人工决策（恢复时读取） |

### 2.2 写入的 State

| State 路径 | 类型 | 写入者 | 内容 |
|-----------|------|--------|------|
| `workflow_state.__human_review_decision__` | `dict` | HumanReview | 人工决策结果 |
| `workflow_state.route_decision` | `str` | HumanReview | "Normalization" |
| `workflow_state.execution_status` | `str` | HumanReview | "Success" |
| `workflow_state.__human_review_needed__` | `bool` | HumanReview | False (已处理) |
| `workflow_state.__human_review_data__` | `dict\|None` | HumanReview | None (已处理) |

### 2.3 输入数据示例

```json
{
  "report_state": {
    "conflict": {
      "resolution_report": {
        "status": "Partially_Resolved",
        "total_conflicts": 2,
        "auto_resolved": 1,
        "human_required": 1,
        "resolution_plan": {
          "human_review_items": [
            {
              "conflict_id": "CF-002",
              "reason": "Cannot auto-resolve: both sources equally reliable, large Cohen's d",
              "evidence_summary": {
                "source_verdict": "equally_reliable",
                "statistical": "Cohen's d=2.1, large effect size"
              }
            }
          ]
        },
        "per_conflict": [
          {
            "conflict_id": "CF-002",
            "field_name": "yield_strength",
            "source_a": {"source_id": "doi_A", "value": 450, "unit": "MPa", "reliability": 0.85},
            "source_b": {"source_id": "doi_B", "value": 520, "unit": "MPa", "reliability": 0.83},
            "strategy": "escalate_to_human",
            "resolution": "escalated_to_human",
            "reasoning_chain": [
              "Both sources are from similar-tier journals",
              "Cohen's d=2.1 indicates genuine difference",
              "Same material (Al-7075) and same condition (T6)",
              "Cannot determine which value is correct without domain expertise"
            ]
          }
        ]
      },
      "evidence": {
        "CF-002": {
          "source_reliability": {
            "source_a_reliability": 0.85, "source_b_reliability": 0.83,
            "reliability_gap": 0.02, "verdict": "equally_reliable"
          },
          "statistical_evidence": {
            "cohens_d": 2.1, "effect_size_interpretation": "Very large difference",
            "statistically_significant": true
          },
          "contextual_evidence": {
            "same_material": true, "same_condition": true,
            "materials_detail": "Same material(s): ['Al-7075']"
          }
        }
      }
    }
  }
}
```

### 2.4 输出数据示例 (人工决策后)

```json
{
  "workflow_state": {
    "route_decision": "Normalization",
    "execution_status": "Success",
    "__human_review_needed__": false,
    "__human_review_decision__": {
      "decisions": {
        "CF-002": {
          "action": "adopt_source_a",
          "selected_value": 450.0,
          "reason": "Source A uses ASTM E8 standard, Source B uses non-standard method"
        }
      },
      "route_decision": "Normalization",
      "reviewer_notes": "Checked original papers — Source B measured at different strain rate"
    },
    "__human_review_data__": null
  }
}
```

---

## 3. 内部处理流程

### 3.1 流程概览

```
Human Review (命令行交互)

Step 1: 检查是否已有决策
  if __human_review_decision__ is not None:
    → 恢复模式: 直接应用已有决策, 路由到 Normalization
    return

Step 2: 提取待审核冲突
  从 resolution_report 中收集所有 human_review_items
  + 从 reasoning.per_conflict 中筛选 escalated_to_human 的

Step 3: 展示冲突摘要
  打印冲突数量、涉及字段、原因

Step 4: 逐条展示 + 收集决策
  for each conflict:
    展示冲突详情:
      - 冲突字段 + 语义类型
      - Source A vs Source B (值、单位、来源、可靠性)
      - Cohen's d + 效应量解释
      - 证据摘要 (来源可靠性、领域规则、统计证据、上下文)
      - Agent 推理链 (为什么无法自动裁决)
    
    用户选择:
      [1] 采用 Source A 的值
      [2] 采用 Source B 的值
      [3] 输入自定义值
      [4] 保留两者 (标注差异)
      [5] 跳过 (保留原样, Export 时标记)

    用户输入理由 (可选)

Step 5: 确认 + 汇总
  展示所有决策汇总
  用户确认 → 写入 __human_review_decision__

Step 6: 路由
  route_decision = "Normalization"
```

### 3.2 命令行交互示例

```
================================================================================
  HUMAN REVIEW — 1 个冲突需要人工裁决
================================================================================

  摘要: 1/2 冲突已自动解决, 1 个需要人工判断
  涉及字段: yield_strength
  原因: Both sources equally reliable, cannot auto-determine correct value

────────────────────────────────────────────────────────────────────────────────
  冲突 CF-002: yield_strength (mechanical_stress, critical)
────────────────────────────────────────────────────────────────────────────────

  Source A (doi_A):
    标题: High-temperature tensile of Al-7075... (2024)
    期刊: Materials Science and Engineering: A
    可靠性: 0.85
    值: 450 MPa

  Source B (doi_B):
    标题: Enhanced strength of Al-7075... (2025)
    期刊: Materials Science and Engineering: A
    可靠性: 0.83
    值: 520 MPa

  统计证据: Cohen's d = 2.1 (Very large difference — likely genuine)
  上下文: 相同材料 (Al-7075), 相同条件 (T6)
  领域规则: 机械性能优先级 — 倾向更可靠来源
  可靠性差距: 0.02 (极小, 两者同等可信)

  Agent 推理链:
    1. Both sources from similar-tier journals
    2. Cohen's d=2.1 indicates genuine difference
    3. Same material and condition
    4. Cannot determine which value is correct

  ────────────────────────────────────────────────────────────────────────────
  请选择裁决方式:
    [1] 采用 Source A 的值 (450 MPa)
    [2] 采用 Source B 的值 (520 MPa)
    [3] 输入自定义值
    [4] 保留两者 (标注差异)
    [5] 跳过 (保留原样)
  ────────────────────────────────────────────────────────────────────────────
  请输入选项 [1-5]: 1
  请输入理由 (可选): ASTM E8 standard vs non-standard method
  ────────────────────────────────────────────────────────────────────────────

================================================================================
  决策汇总
================================================================================

  CF-002 (yield_strength):
    裁决: 采用 Source A = 450 MPa
    理由: ASTM E8 standard vs non-standard method

================================================================================
  确认提交? [y/n]: y

  ✓ 人工审核完成, 1/1 冲突已裁决
  → 路由到 Normalization 执行数据修改
```

---

## 4. 交互命令设计

### 4.1 冲突展示格式

每条冲突展示以下信息块：

```
┌─ 冲突 ID + 字段名 ─────────────────────────────┐
│ 语义类型 + 关键性                                │
├─ Source A ──────────────────────────────────────┤
│ 标题 (年份) | 期刊                               │
│ 可靠性: 0.XX  |  值: XXX 单位                    │
├─ Source B ──────────────────────────────────────┤
│ 标题 (年份) | 期刊                               │
│ 可靠性: 0.XX  |  值: XXX 单位                    │
├─ 证据摘要 ──────────────────────────────────────┤
│ Cohen's d: X.X (效应量解释)                      │
│ 统计显著性: Yes/No/Borderline                    │
│ 相同材料: Yes/No — 材料详情                       │
│ 相同条件: Yes/No — 条件详情                       │
│ 领域规则: 规则名 — 指导                           │
│ 可靠性差距: X.XX (verdict)                       │
├─ Agent 推理链 ──────────────────────────────────┤
│ Step 1: ...                                     │
│ Step 2: ...                                     │
└─────────────────────────────────────────────────┘
```

### 4.2 用户选项

| 选项 | 动作 | resolution_plan 产出 | 说明 |
|------|------|---------------------|------|
| 1 | 采用 Source A | `{action: adopt_source_a, selected_value: ...}` | 以 A 的值为准 |
| 2 | 采用 Source B | `{action: adopt_source_b, selected_value: ...}` | 以 B 的值为准 |
| 3 | 自定义值 | `{action: custom_value, selected_value: ...}` | 用户手动输入 |
| 4 | 保留两者 | `{action: retain_both, annotation: ...}` | 标记差异不修改 |
| 5 | 跳过 | `{action: skip, annotation: ...}` | 保留原样 |

### 4.3 全局命令

| 命令 | 动作 |
|------|------|
| `summary` | 重新打印冲突摘要 |
| `skip-all` | 全部跳过 (标记所有冲突为 retain_both) |
| `auto` | 全部采用可靠性更高来源的值 |
| `quit` | 退出并保留当前状态 (下次可恢复) |

---

## 5. 异常处理

| 场景 | 处理 |
|------|------|
| 无待审核冲突 | `route_decision = "Export"` (不应发生，但防御性处理) |
| 用户输入无效选项 | 提示重新输入，最多 3 次 |
| 用户输入 `quit` | 保留 `__human_review_needed__ = True`，下次进入时恢复 |
| Conflict Report 缺失 | `execution_status = "Failed"`, 记录错误 |
| 用户确认后 | 写入 `__human_review_decision__`，清空 `__human_review_data__` |

---

## 6. 工具清单

Human Review 模块不需要独立的 Tool 文件。核心逻辑在 Agent 内部：

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 冲突展示 | `human_review_agent.py` | 格式化打印冲突信息 |
| 用户交互 | `human_review_agent.py` | stdin 读取选项 + 验证 |
| 决策写入 | `human_review_agent.py` | 构建 __human_review_decision__ |
| 路由设置 | `graph.py human_review_node` | 设置 route_decision |

---

## 7. 文件清单

```
Data_HumanReview_agentV1/
├── HUMAN_REVIEW_DESIGN_REPORT.md    # 本报告 (V1.0)
├── __init__.py
└── human_review_agent.py            # 命令行交互 Agent

graph.py 中:
  human_review_node()                # 已有，需微调适配新冲突报告结构
```

---

## 8. 与总图的接口

### 8.1 触发条件

```python
# graph.py 中 route_after_conflict 或 merge_node
if route_decision == "HumanReview":
    return NODE_HUMAN_REVIEW
```

### 8.2 路由目标

```python
# 人工决策后总是路由到 Normalization
workflow_state.route_decision = "Normalization"
```

### 8.3 V1 规格约束

```
V1 总图中的 Human Review:
  C → Human Required → E
  E → B (人工修改后重新清洗)

不存在的路径:
  A → E  ❌ (Assessment 不触发 Human Review — V1 §3.4)
  E → A  ❌ (Human Review 不回到 Assessment — V1 §3.4)
```
