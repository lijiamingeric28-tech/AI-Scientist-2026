下面这份文档可以直接交给本地 AI 修改。它不是简单列出问题，而是按照**软件工程 Code Review + 架构整改任务书**的形式编写，包含**修改目标、原因、实现要求、验收标准**，本地 AI 可以直接据此完成修改。

---

# routers.py 修改执行说明（V1.1）

## 文档目的

本次修改 **不是重写 Router**，而是在保持现有整体架构（Main Graph + SubGraph + Router + Loop Controller）的基础上，修复当前实现中的逻辑缺陷，并进一步提高代码的可维护性。

修改完成后，应保证：

* Router 只负责流程路由；
* Retry Controller 负责重试；
* Loop Controller 负责循环控制；
* 三者职责完全解耦；
* Workflow History 能完整记录整个执行过程。

---

# 一、Loop Controller 必须真正维护 iteration_counter（最高优先级，必须修改）

## 当前问题

当前 `loop_controller_node()` 中：

```python
iteration = wf.get("iteration_counter", 0)
```

仅仅读取了计数器。

随后直接：

```python
if iteration >= MAX_ITERATIONS:
```

进行判断。

但是整个函数中：

没有任何地方：

```python
iteration += 1
```

也没有：

```python
"iteration_counter": iteration + 1
```

因此：

Workflow 中：

```text
iteration_counter
```

永远保持：

```text
0
```

导致：

```python
iteration >= MAX_ITERATIONS
```

永远不会成立。

Loop Controller 实际失效。

---

## 修改要求

Loop Controller 每进入一次：

必须：

生成新的：

```python
next_iteration = iteration + 1
```

然后写回：

```python
workflow_state.iteration_counter
```

例如：

```text
0

↓

1

↓

2

↓

3

↓

Export
```

必须保证：

Workflow State 中：

iteration_counter

始终反映：

当前真实循环次数。

---

## 验收标准

满足：

```text
第一次进入
iteration_counter = 1

第二次进入
iteration_counter = 2

第三次进入
iteration_counter = 3

第四次进入
LoopController
↓

route_decision="Export"
```

---

# 二、Workflow History 不允许覆盖（必须修改）

## 当前问题

Loop Controller：

目前：

直接：

返回：

```python
workflow_history = [
    ...
]
```

由于：

workflow_state

采用：

```python
_merge_dict
```

Reducer。

list：

不会：

自动：

append。

而是：

整体覆盖。

导致：

之前：

Assessment

Normalization

Conflict

所有：

历史。

全部丢失。

最终：

workflow_history

只有：

最后：

一条。

---

## 修改要求

进入：

LoopController

以后：

先读取：

已有：

History。

例如：

```python
history = list(
    wf.get("workflow_history", [])
)
```

然后：

```python
history.append(...)
```

最后：

返回：

```python
workflow_history = history
```

不要：

直接：

新建：

list。

---

## 验收标准

Workflow：

完整结束以后：

workflow_history：

应包含：

```text
Assessment

↓

Normalization

↓

LoopController

↓

Conflict

↓

LoopController

↓

Export
```

完整执行轨迹。

不能：

只保留：

最后：

一条。

---

# 三、Route Map 空决策统一处理（建议修改）

## 当前问题

目前：

Assessment：

RouteMap：

包含：

```python
""
```

Normalization：

没有。

Conflict：

没有。

导致：

如果：

LLM：

输出：

空字符串。

不同：

Stage。

行为：

不一致。

---

## 修改要求

统一：

所有：

Route Map。

显式：

增加：

```python
"": NODE_HUMAN_REVIEW
```

或者：

统一：

默认：

进入：

HumanReview。

不要：

依赖：

dict.get()

默认值。

---

## 验收标准

无论：

Assessment

Normalization

Conflict

任何：

route_decision

为空。

均进入：

HumanReview。

行为一致。

---

# 四、Retry Controller 与 Router 职责进一步解耦（建议修改）

## 当前问题

目前：

```python
route_with_retry()
```

同时：

负责：

Retry

Router

两个职责。

例如：

里面：

既：

检查：

```python
execution_status
```

又：

读取：

```python
route_decision
```

职责：

略重。

---

## 修改建议

建议：

拆成：

两个函数。

例如：

```text
Retry Controller

↓

Router
```

例如：

```python
check_retry()

↓

route()
```

Graph：

统一：

先：

Retry。

再：

Router。

---

## 注意

此项：

不是：

必须。

属于：

V2。

工程优化。

---

# 五、HumanReview 默认路由更加保守（建议修改）

## 当前问题

目前：

HumanReview：

默认：

```python
route_decision="Normalization"
```

意味着：

如果：

人工：

没有：

真正：

给：

Decision。

Graph：

仍然：

继续：

Workflow。

存在：

误执行：

风险。

---

## 修改建议

默认：

保持：

HumanReview。

例如：

```python
route_decision="HumanReview"
```

或者：

直接：

抛：

异常。

要求：

必须：

人工：

返回：

合法：

Decision。

---

## 验收标准

人工：

未完成：

Workflow：

不得：

继续。

---

# 六、Loop Controller 更新 current_node（建议修改）

LoopController：

目前：

虽然：

写：

```python
current_node="loop_controller"
```

但是：

建议：

统一：

记录：

Loop：

开始。

Loop：

结束。

方便：

Workflow：

Replay。

---

# 七、统一 Workflow History 格式（建议修改）

建议：

LoopController：

新增：

统一：

History。

例如：

字段：

保持：

完全一致。

统一：

```text
agent

stage

status

timestamp

duration

reason
```

不要：

以后：

不同：

Node。

写：

不同：

格式。

---

# 八、Logger 输出统一（建议修改）

建议：

统一：

格式：

```text
[Router]

[Retry]

[Loop]
```

例如：

```text
[Retry] ConflictGraph (2/3)

[Loop] iteration 2/3

[Router] Assessment -> Normalization
```

方便：

排查：

Workflow。

---

# 九、Route Map 建议统一集中管理（建议修改）

目前：

RouteMap：

已经：

集中。

很好。

建议：

保持：

不要：

以后：

写：

```python
if

elif

else
```

Router：

所有：

Decision。

都：

来自：

RouteMap。

方便：

扩展：

新：

Stage。

---

# 十、Loop Controller 只修改 WorkflowState（设计约束）

Loop Controller：

以后：

禁止：

修改：

```text
report_state

data_state

output_state
```

只能：

修改：

```text
workflow_state
```

保证：

职责：

单一。

---

# 修改完成后的目标架构

最终：

routers.py：

职责：

应如下：

```text
Retry Controller
        │
        ▼
读取 execution_status

↓

Retry?

↓

Yes → 当前 SubGraph

↓

No

↓

Router

↓

读取 route_decision

↓

RouteMap

↓

下一节点

↓

LoopController

↓

iteration++

↓

超过次数？

↓

修改 route_decision=Export

↓

返回 Workflow
```

---

# 验收标准（必须满足）

修改完成后，应满足以下要求：

### Retry

* ✅ Retry 真正生效；
* ✅ 超过最大重试次数进入 HumanReview；
* ✅ Retry 不参与业务判断。

---

### Router

* ✅ Router 仅根据 `route_decision` 查表路由；
* ✅ 不包含 Quality、Conflict 等业务规则；
* ✅ Route Map 行为一致。

---

### Loop

* ✅ 每次进入 Loop Controller 必须递增 `iteration_counter`；
* ✅ 超过最大循环次数后统一修改 `route_decision="Export"`；
* ✅ Loop Controller 不修改任何业务数据，仅维护 Workflow 状态。

---

### Workflow History

* ✅ 每个节点执行都会追加记录，而不是覆盖历史；
* ✅ 最终能够完整还原整个 Workflow 执行轨迹；
* ✅ History 字段格式保持统一。

---

## 最终目标

修改完成后的 `routers.py` 应成为一个**纯 Workflow 控制层**：

* **Router**：负责路由，不做决策；
* **Retry Controller**：负责重试控制；
* **Loop Controller**：负责循环控制；
* **Workflow History**：负责记录执行轨迹；

整个文件不应包含任何业务逻辑、LLM 调用、Tool 调用或数据处理逻辑，完全符合 **LangGraph Orchestrator** 的设计原则。
