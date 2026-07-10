我看完你的设计后，有一个非常明确的结论：

> **你现在的 `assessment_graph.py` 已经不是代码写得好不好的问题，而是架构和设计文档不一致。**

如果按照你们这个设计文档来看，我会建议**不要再修改几个函数，而是重新调整整个 Assessment SubGraph 的职责划分。**。

---

# Assessment SubGraph 修改建议（V1.1）

## 一、总体目标

当前 `assessment_graph.py` 已实现基本 Workflow，但整体实现仍偏向**Pipeline（流水线）**，未完全符合《Data Quality Assessment Agent》设计文档。

修改目标：

* Assessment SubGraph 仅负责 Workflow 编排。
* 每个 Stage 对应一个独立 Agent。
* Agent 内部负责 LLM 推理、Tool 调用、结果汇总。
* Graph 不再承担业务逻辑，仅负责节点调度与 State 更新。

最终目标如下：

```
AssessmentGraph
│
├── ProfilingAgent
│
├── QualityAssessmentAgent
│
├── QualityScoringAgent
│
└── DecisionReasoningAgent
```

Graph 不再直接调用 Tool。

---

# 二、重新划分职责

当前：

```
Graph

↓

Tool

↓

State
```

建议修改为：

```
Graph

↓

Agent

↓

Planner（可选）

↓

Tool

↓

LLM Summary

↓

State
```

即：

Graph 永远不知道 Tool。

Graph 永远不知道 Prompt。

Graph 永远不知道评分规则。

Graph 只负责：

```
State
↓

调用 Agent

↓

写回 State
```

---

# 三、Stage 1 修改建议

## 当前实现

```
Profiling Node

↓

data_profiling()

↓

结束
```

这是 Tool。

不是 Agent。

---

## 建议

建立：

```
assessment/
    agents/
        profiling_agent.py
```

Graph：

只调用：

```
ProfilingAgent.run(state)
```

ProfilingAgent 内部：

```
LLM

↓

分析数据类型

↓

调用 Profiling Tool

↓

生成 Profiling Summary

↓

返回 Profile
```

最终 Report：

```
profile

profile_summary

dataset_type

record_statistics

field_statistics

source_statistics
```

不要让 Graph 自己生成 Summary。

---

# 四、Stage 2 修改建议

目前：

Quality Assessment：

直接：

```
check_completeness()

check_consistency()

check_format()

...
```

建议全部迁移到：

```
QualityAssessmentAgent
```

Graph：

只：

```
AssessmentAgent.run()
```

AssessmentAgent 内部：

```
Planning

↓

决定需要哪些 Tool

↓

调用 Tool

↓

Merge Result

↓

LLM Explain

↓

输出 Quality Report
```

---

## Assessment Agent 内建议流程

```
QualityAssessmentAgent

↓

Schema Validation

↓

Missing Value Detection

↓

Consistency Checker

↓

Unit Checker

↓

Duplicate Detection

↓

Source Validation

↓

Conflict Detection

↓

LLM Summary
```

Graph 不参与。

---

# 五、Stage 3 修改建议

目前：

Graph：

```
load_yaml()

↓

compute_quality_score()
```

建议：

Graph 不允许：

```
读取配置
```

应该：

```
QualityScoringAgent

↓

Load Rules

↓

Compute Score

↓

Generate Quality Level

↓

Generate Confidence
```

Graph：

只：

```
ScoringAgent.run()
```

---

评分 Agent 输出：

```
quality_score

quality_level

dimension_score

dimension_weight

confidence
```

---

# 六、Stage 4 修改建议

目前：

Decision Node：

已经开始像 Agent。

但是：

仍然存在几个问题。

---

## Prompt

不要放 Graph。

例如：

现在：

```
_DECISION_SYSTEM
```

建议：

移动：

```
assessment/prompts/

decision_prompt.py
```

---

## Decision

Graph：

不要：

拼：

```
user_prompt
```

Graph：

只：

```
DecisionAgent.run()
```

DecisionAgent：

负责：

```
Prompt

↓

LLM

↓

Reasoning

↓

Route

↓

Confidence
```

---

## Rule Engine

Fallback：

也建议：

移动：

```
DecisionAgent
```

Graph：

不要：

知道：

```
Conflict

Normalization

Export
```

Graph：

只：

读取：

```
workflow_state.route_decision
```

---

# 七、Issue List 构建

当前：

Graph：

自己：

```
quality["issue_list"]
```

建议：

Issue List：

属于：

Assessment Report。

应该：

AssessmentAgent：

负责生成。

Graph：

不要：

遍历：

```
issues
```

Graph：

不要：

Merge：

Issue。

---

Issue Report：

建议：

统一：

```
issue_list

[
    {
        dimension,
        severity,
        field,
        value,
        reason,
        suggestion
    }
]
```

后续：

Normalization

直接：

读取。

---

# 八、Assessment Summary

目前：

Graph：

拼：

```
Assessment Summary
```

建议：

LLM：

生成：

Summary。

Summary：

包含：

```
Overall Quality

Major Issues

Need Normalization

Need Conflict

Recommendation
```

以后：

Export

直接：

引用。

---

# 九、Workflow History

目前：

Graph：

每个 Node：

自己：

追加：

History。

建议：

增加：

统一：

```
History Helper
```

例如：

```
append_workflow_history(...)
```

所有：

Agent：

统一调用。

Graph：

不要：

重复：

写：

```
workflow_history
```

---

# 十、Execution Status

目前：

所有：

Node：

默认：

```
Success
```

建议：

所有 Agent：

统一：

返回：

```
Success

Retry

Failed
```

Graph：

不判断。

Graph：

直接：

写：

```
workflow_state.execution_status
```

---

# 十一、LLM 调用统计

目前：

Graph：

```
llm_call_count += 1
```

建议：

Agent：

自己：

统计：

```
llm_call_count

tool_call_count
```

Graph：

不要：

知道：

Agent：

调用：

几个 Tool。

---

# 十二、Graph 需要保持极简

最终：

Assessment Graph：

应该：

类似：

```
Profiling

↓

QualityAssessment

↓

QualityScoring

↓

Decision
```

但是：

每个 Node：

只剩：

类似：

```python
def profiling_node(state):

    return ProfilingAgent().run(state)
```

整个 Graph：

不要：

出现：

```
Tool

Prompt

Rule

Issue

Summary

Score

Threshold

Config
```

这些：

全部：

属于：

Agent。

---

# 十三、建议新增目录结构

建议重构为：

```
assessment/

├── assessment_graph.py          # Workflow
│
├── agents/
│   ├── profiling_agent.py
│   ├── quality_assessment_agent.py
│   ├── quality_scoring_agent.py
│   └── decision_reasoning_agent.py
│
├── prompts/
│   ├── profiling_prompt.py
│   ├── assessment_prompt.py
│   ├── scoring_prompt.py
│   └── decision_prompt.py
│
├── tools/
│   ├── completeness.py
│   ├── consistency.py
│   ├── format_checker.py
│   ├── duplicate_checker.py
│   ├── schema_validator.py
│   ├── source_checker.py
│   ├── conflict_detector.py
│   └── quality_scoring.py
│
└── utils/
    ├── history.py
    └── report_builder.py
```

---

# 十四、最终目标（符合设计文档）

完成以上调整后，Assessment 模块将完全符合你们文档中定义的 **Data Quality Assessment Agent** 架构：

* **Assessment Graph**：仅负责 Stage 编排与状态流转。
* **ProfilingAgent**：负责数据 Profiling、数据类型识别与 Profiling Summary。
* **QualityAssessmentAgent**：负责调用各类质量检测工具，汇总五维质量评估结果，并生成标准化 Quality Report。
* **QualityScoringAgent**：负责综合评分、质量等级与置信度计算。
* **DecisionReasoningAgent**：负责基于 Quality Report 进行 LLM 推理，输出 Workflow 路由（Conflict → Normalization → Export），并提供可解释的决策理由。
* **Graph 不再包含任何 Tool 调用、Prompt、评分规则或业务逻辑**，真正实现 **"一个 Stage = 一个 Agent"** 的架构目标，也为后续扩展动态 Planner、Memory 和多 Agent 协作打下基础。




请阅读V1\pipeline\quality\profilingagent设计文档.md严格按照其要求实现改子模块，并按照新的代码架构重建我们第一个子图。
然后仿照改设计文档设计剩下三个**QualityAssessmentAgent***QualityScoringAgent**DecisionReasoningAgent三个子模块。