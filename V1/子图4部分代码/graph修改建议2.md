

---

# graph.py 修改执行说明（V1.2）

## 文档目标

本次修改 **不是重写 Graph**。

保持目前：

* Main Graph + SubGraph 的架构
* State 定义
* SubGraph 接口
* Workflow

全部不变。

本次修改目标：

> **让 graph.py 真正成为 LangGraph 的 Workflow Orchestrator（工作流编排器）**。

---

# 一、Router 去业务化（最高优先级，必须修改）

## 当前问题

目前三个 Router：

```python
route_after_assessment()

route_after_normalization()

route_after_conflict()
```

除了读取：

```python
workflow_state.route_decision
```

之外，

还负责：

```python
iteration 判断

retry 判断

failed 判断

HumanReview 判断
```

例如：

```python
if iteration >= MAX_ITERATIONS:
    return NODE_EXPORT
```

例如：

```python
if status in ("Retry","Failed"):
    return NODE_HUMAN_REVIEW
```

这些属于业务逻辑。

---

## 为什么这是问题？

Router 应该只是：

```text
State
↓

读取 route_decision
↓

返回下一节点
```

而不是：

```text
State

↓

分析状态

↓

重新推理

↓

决定下一节点
```

否则：

以后：

Decision Node

和

Router

都会决定：

Workflow。

职责冲突。

---

## 修改要求

所有：

```python
route_after_*
```

统一改成：

只读取：

```python
workflow_state.route_decision
```

例如：

```python
decision = state["workflow_state"]["route_decision"]

mapping = {
    ...
}

return mapping[decision]
```

不要：

增加：

```python
if

for

while
```

业务判断。

---

## 业务判断放哪里？

统一放到：

对应：

SubGraph

最后：

Decision Stage。

例如：

Assessment

最后：

Decision Node：

输出：

```python
route_decision
```

Graph：

只负责：

读取。

---

# 二、Retry 机制真正接入 Graph（必须修改）

## 当前问题

已经实现：

```python
_check_retry()
```

但是：

Graph

没有任何地方调用。

导致：

Retry

逻辑完全失效。

---

## 修改要求

Graph

每一个：

SubGraph

结束以后。

统一：

先：

Retry。

再：

Router。

例如：

```text
AssessmentGraph

↓

Retry Check

↓

Router
```

Normalization

也是。

Conflict

也是。

---

## 建议实现方式

增加：

三个：

Retry Router。

例如：

```python
route_after_assessment()

↓

retry_router()

↓

decision_router()
```

或者：

直接：

在：

Conditional Edge

里面：

先：

Retry。

不要：

Node

自己：

Retry。

---

## 原则

Retry

属于：

Workflow。

不是：

Agent。

---

# 三、HumanReview 不要固定返回 Normalization（必须修改）

## 当前问题

目前：

```python
graph.add_edge(
    NODE_HUMAN_REVIEW,
    NODE_NORMALIZATION
)
```

意味着：

人工结束。

永远：

Normalization。

这是错误的。

---

## 为什么？

例如：

人工：

修改：

Assessment。

为什么：

还要：

Normalization？

例如：

人工：

直接：

确认：

Export。

怎么办？

---

## 修改要求

HumanReview

结束以后：

不要：

固定：

Edge。

而是：

增加：

Conditional Edge。

例如：

HumanReview：

返回：

```python
route_decision
```

Graph：

读取：

```python
route_decision
```

可以：

跳：

```text
Assessment

Normalization

Conflict

Export
```

任意。

---

# 四、Iteration 控制从 Router 中移除（建议修改）

## 当前问题

Router：

目前：

负责：

```python
iteration>=3
```

然后：

Export。

实际上：

Iteration

属于：

Workflow。

不是：

Router。

---

## 修改要求

增加：

单独：

Loop Controller。

例如：

```text
Normalization

↓

LoopController

↓

Conflict
```

LoopController：

负责：

```python
iteration_counter++

超过：

3

↓

修改：

route_decision

↓

Export
```

Graph：

继续：

Router。

Router：

不要：

知道：

Iteration。

---

# 五、Router 独立成 routers.py（建议修改）

## 当前问题

graph.py

目前：

超过：

200

行。

里面：

包含：

Workflow

Router

Retry

HumanReview。

职责：

过多。

---

## 修改要求

新增：

```text
pipeline/

quality/

routers.py
```

里面：

统一：

```python
route_after_assessment

route_after_normalization

route_after_conflict

check_retry
```

graph.py

最后：

应该：

只有：

```python
builder

↓

add_node

↓

add_edge

↓

add_conditional_edge
```

---

# 六、增加 Loop Controller（建议修改）

建议：

新增：

一个：

Workflow Node。

例如：

```text
Normalization

↓

LoopController

↓

Conflict
```

LoopController：

负责：

```python
iteration++

workflow_history

logger
```

不要：

Router：

负责。

---

# 七、Retry Controller 独立（建议修改）

建议：

新增：

```text
RetryController
```

负责：

```python
retry++

logger

history

error
```

Graph：

统一：

调用。

不要：

每一个：

Router：

重复：

Retry。

---

# 八、HumanReview Node 优化（建议修改）

目前：

HumanReview：

只是：

```python
return
```

建议：

增加：

Workflow History。

增加：

Logger。

增加：

Review Context。

例如：

```python
reason

current_node

last_error

current_data

report
```

方便：

UI。

---

# 九、Workflow History 记录统一（建议修改）

目前：

只有：

HumanReview：

写：

History。

建议：

所有：

SubGraph

结束。

统一：

Graph：

记录：

History。

例如：

```python
Assessment

↓

WorkflowHistory

↓

Router
```

不要：

每一个：

Node：

自己：

写。

否则：

格式：

容易：

不一致。

---

# 十、Logger 统一格式（建议修改）

建议：

统一：

```python
[Workflow]

[Router]

[Retry]

[Loop]

[Interrupt]
```

例如：

```python
[Router] Assessment → Normalization

[Retry] Conflict (2/3)

[Loop] Iteration 2

[Interrupt] Human Review
```

方便：

后期：

定位。

---

# 十一、类型增强（建议修改）

目前：

```python
build_quality_graph()

-> StateGraph
```

建议：

增加：

更精确：

类型。

例如：

```python
StateGraph[QualityGraphState]
```

或者：

CompiledStateGraph。

---

# 十二、Graph 不允许出现业务代码（设计约束）

graph.py

以后：

禁止：

出现：

```python
Schema

Quality Score

Confidence

Threshold

Normalization Rule

Conflict Rule

LLM Prompt

Tool Call
```

Graph

只允许：

```python
Node

Edge

Conditional Edge

Retry

Loop

Interrupt
```

---

# 十三、建议增加统一 Workflow Controller（长期优化）

随着项目扩展，建议新增一个统一的 **WorkflowController**，集中处理所有与流程相关的状态更新，包括：

* `iteration_counter`
* `retry_counter`
* `workflow_history`
* `last_error`
* `execution_status`
* `current_node`

这样 Graph 和各 SubGraph 都只负责调用 Controller，而不直接修改 WorkflowState，后续增加新的流程控制逻辑时也只需要修改一处。

---

# 修改完成后的目标架构

最终 `graph.py` 应达到如下职责划分：

```text
Main Graph
│
├── AssessmentGraph
│
├── Router（只读取 route_decision）
│
├── Retry Controller
│
├── Loop Controller
│
├── NormalizationGraph
│
├── Router
│
├── ConflictGraph
│
├── Router
│
├── ExportGraph
│
└── HumanReview
```

其中：

* **Graph**：仅负责工作流编排（Workflow Orchestration）
* **SubGraph**：负责 Agent 的完整推理流程
* **Decision Node**：负责生成 `route_decision`
* **Tool**：负责执行具体操作
* **LLM**：负责规划、推理与决策

---

## 验收标准（必须满足）

修改完成后，应满足以下要求：

* ✅ Main Graph 不包含任何业务规则判断。
* ✅ Router 仅根据 `route_decision` 完成路由，不参与决策。
* ✅ Retry 已真正接入 Graph，而不是保留未使用的方法。
* ✅ HumanReview 支持条件恢复，而不是固定返回 `Normalization`。
* ✅ Loop 与 Retry 的流程控制职责明确，与 Router 解耦。
* ✅ `graph.py` 仅承担 LangGraph Workflow Orchestrator 的职责，符合层次化（Hierarchical）SubGraph 架构设计。
