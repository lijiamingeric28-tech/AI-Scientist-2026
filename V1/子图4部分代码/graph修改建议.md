现在graph的实现与设计文档有较大差别，我的四个agent并不是四个node而是四个subgraph，请根据这个设计文档思路（\1.design清洗部分之后设计架构思路.md）进行一一对应的修改。其中的四个agent是四个subgraph，每个agent设计的stage是一个node，现在graph.py的层级不对。

我看完了整个设计文档，也结合了你前面的想法，我认为**现在已经不是修改 graph.py 的问题了，而是 graph.py 的设计思想需要升级**。

你的设计文档其实已经定义得非常清楚：

> **Agent = 一个完整的推理流程**
> **Stage = Agent 内部的推理步骤** 

而你之前 graph.py 的写法（一个 Agent 一个 Node）实际上**没有体现这些 Stage**。

---

# 我建议给本地 AI 的修改任务，不是"修改 graph.py"，而是"重构 graph.py"

下面这份就是我建议你交给本地 AI 的**详细执行脚本（Execution Script）**。

---

# Graph.py 重构执行说明（V2）

## 一、总体目标

当前 graph.py 采用：

```text
Assessment Node
↓

Normalization Node
↓

Conflict Node
↓

Export Node
```

该结构无法体现设计文档中定义的 Stage，也无法支持后续 LLM 动态规划。

因此需要重构。

---

## 二、总体设计原则（必须遵守）

### 原则一

Main Graph 只负责：

* Workflow 编排
* Conditional Edge
* Retry
* Interrupt
* Loop

不能负责：

* Agent 推理
* Tool 调用
* Rule 判断
* Prompt

---

### 原则二

一个 Stage = 一个 LangGraph Node

不要把多个 Stage 写进一个 Node。

例如：

Assessment Agent

不能：

```python
assessment_node()
```

里面：

```
Profiling

↓

Assessment

↓

Scoring

↓

Decision
```

全部完成。

必须拆开。

---

### 原则三

一个 Agent = 一个 SubGraph

Main Graph

只放：

```
AssessmentGraph

NormalizationGraph

ConflictGraph

ExportGraph
```

不要放 Stage。

---

# 三、Assessment SubGraph 重构

根据设计文档：

Assessment 包含：

Stage1

Data Profiling

↓

Stage2

Quality Assessment

↓

Stage3

Quality Evaluation

↓

Stage4

Decision Reasoning 

因此：

Assessment Graph

必须设计为：

```
START

↓

profiling_node

↓

quality_assessment_node

↓

quality_scoring_node

↓

decision_reasoning_node

↓

END
```

其中：

Quality Assessment

内部调用：

```
Missing Detection

Schema Validation

Field Consistency

Duplicate Detection

...
```

Tool。

不是 Graph。

---

# 四、Normalization SubGraph 重构

根据设计文档：

Stage：

```
Normalization Planning

↓

Data Normalization

↓

Validation

↓

Report Generation
```



因此：

Graph：

```
START

↓

planning_node

↓

normalization_node

↓

validation_node

↓

report_node

↓

END
```

Data Normalization

Node

负责：

```
Schema Mapping

Field Standardization

Missing Processing

Duplicate Merge

...
```

不要继续拆 Graph。

---

# 五、Conflict SubGraph 重构

根据文档：

```
Conflict Identification

↓

Conflict Classification

↓

Evidence Collection

↓

Resolution Reasoning

↓

Confidence Evaluation

↓

Resolution Report
```



因此：

ConflictGraph：

```
START

↓

identify_node

↓

classification_node

↓

evidence_node

↓

reasoning_node

↓

confidence_node

↓

report_node

↓

END
```

不要一个：

```
ConflictNode
```

全部完成。

---

# 六、Export SubGraph 重构

根据文档：

Structured Export

包含多个 Stage（组织、Metadata、Traceability、Quality Summary、Output）。

建议：

```
START

↓

organize_node

↓

metadata_node

↓

traceability_node

↓

summary_node

↓

output_node

↓

END
```

Export

不允许修改数据。

只能组织数据。

---

# 七、Main Graph 重构

Main Graph

只保留：

```
START

↓

AssessmentGraph

↓

Conditional Edge

↓

NormalizationGraph

↓

Conditional Edge

↓

ConflictGraph

↓

Conditional Edge

↓

ExportGraph

↓

END
```

Graph

不要知道：

Prompt

Tool

LLM

---

# 八、Conditional Edge 重构

Assessment

结束后：

读取：

```
workflow_state.route_decision
```

不要：

```
if score>80
```

Graph

里面判断。

Decision

由：

Decision Reasoning Node

生成。

Graph

只读取。

---

Normalization

结束：

根据：

Normalization Report

决定：

```
Conflict

Export
```

不要：

Graph

重新判断。

---

Conflict

结束：

根据：

Conflict Report

决定：

```
Normalization

Export
```

形成循环。

---

# 九、循环逻辑

根据设计文档：

```
Normalization

↓

Conflict

↓

Normalization

↓

Conflict
```

最大：

```
3
```

次。



Graph：

使用：

```
workflow_state.iteration_counter
```

控制。

不要：

while。

不要：

递归。

---

# 十、Retry

不要：

Node

里面：

Retry。

Graph：

统一：

```
execution_status

↓

Retry

↓

retry_counter+1

↓

重新执行当前Node
```

超过：

```
3
```

进入：

HumanReview

---

# 十一、Human Review

不要：

```
input()
```

不要：

while。

Graph：

直接：

Interrupt。

第一版：

可以：

留接口。

不用实现。

---

# 十二、LLM 规划机制（重点）

每一个：

Stage Node

都必须：

采用：

```
Prompt

↓

LLM

↓

Structured Output

↓

Tool

↓

State Update
```

而不是：

```
Python Rule
```

全部完成。

特别：

Decision Reasoning

Planning

Resolution Reasoning

必须：

LLM。

---

# 十三、Node 职责限制

每个 Node：

只完成：

一个 Stage。

不要：

一个 Node：

300 行。

例如：

```
profiling_node
```

只负责：

```
Data Profiling
```

不能：

```
Profiling

↓

Scoring

↓

Decision
```

全部做。

---

# 十四、推荐目录结构

```
quality/

graph.py                # Main Graph

assessment/
    graph.py
    nodes/
        profiling.py
        quality_assessment.py
        scoring.py
        decision.py

normalization/
    graph.py
    nodes/
        planning.py
        normalization.py
        validation.py
        report.py

conflict/
    graph.py
    nodes/
        identify.py
        classify.py
        evidence.py
        reasoning.py
        confidence.py
        report.py

export/
    graph.py
    nodes/
        organize.py
        metadata.py
        traceability.py
        summary.py
        output.py
```

---

## 我最后再补充一个建议（这是我认为整个项目档次提升最大的地方）

**你的设计文档实际上已经定义的是"Hierarchical Multi-Agent"（层次化多智能体），而不是普通 Workflow。**

也就是说：

```text
Quality Main Graph
│
├── Assessment SubGraph
│      ├── Stage1：Profiling
│      ├── Stage2：Assessment
│      ├── Stage3：Scoring
│      └── Stage4：Decision（LLM）
│
├── Normalization SubGraph
│      ├── Planning（LLM）
│      ├── Normalization
│      ├── Validation
│      └── Report
│
├── Conflict SubGraph
│      ├── Identification
│      ├── Classification
│      ├── Evidence
│      ├── Resolution（LLM）
│      ├── Confidence
│      └── Report
│
└── Export SubGraph
       ├── Organize
       ├── Metadata
       ├── Traceability
       ├── Summary
       └── Output
```

这种架构与你的设计文档是一一对应的，扩展性也最好，后续无论增加新的 Stage 还是新的 Tool，都不需要改 Main Graph，只需要修改对应 SubGraph 即可。
