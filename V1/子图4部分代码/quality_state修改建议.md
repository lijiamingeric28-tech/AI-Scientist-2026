我建议你直接把下面这份作为 **Code Review 修改说明** 发给本地 AI。这不是让它"自由发挥"，而是明确告诉它哪些地方必须改、哪些地方不能改，避免它把整个 State 推倒重来。

---

# `quality_state.py` 修改建议（V1）

## 修改原则（必须遵守）

本次修改目标：

* **保持现有接口兼容**（不能影响其他模块）
* **不改变整体架构**
* **不增加新的 State 层级**
* **只提升类型安全、可维护性和工程质量**

禁止：

* ❌ 修改 State 的整体结构
* ❌ 删除现有字段
* ❌ 修改 `make_initial_state()` 返回格式
* ❌ 修改 reducer 的行为
* ❌ 引入新的 Workflow

---

# 修改一：真正使用 TypedDict（最高优先级）

## 当前问题

目前虽然定义了：

```python
class ContextState(TypedDict):
...

class DataState(TypedDict):
...

class WorkflowState(TypedDict):
...
```

但是在 `QualityGraphState` 中却全部写成：

```python
Annotated[
    dict[str, Any],
    _merge_dict
]
```

这样 TypedDict 完全失去了意义。

IDE 无法提供字段补全。

MyPy 无法检查字段。

Pylance 无法提示错误。

例如：

```python
state["workflow_state"]["xxxx"]
```

不会报错。

实际上：

```python
xxxx
```

根本不存在。

---

## 修改要求

将：

```python
context_state: Annotated[dict[str, Any], _merge_dict]
```

修改为：

```python
context_state: Annotated[
    ContextState,
    _merge_dict
]
```

其它全部同理：

```
DataState
ReportState
WorkflowState
OutputState
```

全部使用对应 TypedDict。

---

## 注意

Reducer 保持：

```python
_merge_dict
```

不要修改。

---

# 修改二：WorkflowHistory 使用 TypedDict

## 当前问题

目前：

```python
workflow_history: list[dict[str, Any]]
```

任何格式都可以放进去。

例如：

```python
{
    "abc":123
}
```

也不会报错。

后期 Debug 会非常困难。

---

## 修改要求

新增：

```python
class WorkflowRecord(TypedDict, total=False):

    agent: str
    stage: str
    status: str
    timestamp: str
    duration: float
    reason: str
```

然后修改：

```python
workflow_history
```

为：

```python
workflow_history:
list[WorkflowRecord]
```

---

## 字段说明

agent：

当前 Agent

例如：

```
AssessmentAgent
```

---

stage：

当前 Stage

例如：

```
QualityAssessment
```

---

status：

执行结果

例如：

```
Success

Retry

Failed
```

---

timestamp：

ISO 时间

例如：

```
2026-07-10T13:24:11
```

---

duration：

耗时

单位：

```
seconds
```

---

reason：

为什么跳转

例如：

```
Need normalization

Need conflict resolution

Quality passed
```

---

## 不需要实现日志

这里只定义数据结构。

---

# 修改三：DataTrace 使用 TypedDict

## 当前问题

目前：

```python
data_trace:
list[dict]
```

没有任何规范。

后面 Traceability 无法生成。

---

## 修改要求

新增：

```python
class TraceRecord(TypedDict, total=False):

    field: str
    before: Any
    after: Any
    agent: str
    tool: str
    reason: str
    confidence: float
```

然后：

```python
data_trace
```

改成：

```python
list[TraceRecord]
```

---

## 字段解释

field

修改字段

例如：

```
Temperature
```

---

before

修改前

例如：

```
37℃
```

---

after

修改后

例如：

```
310.15K
```

---

agent

哪个 Agent 修改

例如：

```
NormalizationAgent
```

---

tool

哪个 Tool

例如：

```
UnitConverter
```

---

reason

修改原因

例如：

```
Standard Unit Conversion
```

---

confidence

修改可信度

例如：

```
0.98
```

---

这里只建立结构。

不要实现记录逻辑。

---

# 修改四：WorkflowState 增加运行信息

## 当前问题

WorkflowState 信息过少。

后面：

日志

统计

Benchmark

全部无法实现。

---

## 修改要求

在：

```python
WorkflowState
```

增加：

```python
run_id: str
```

整个 Workflow 唯一 ID

UUID。

---

```python
graph_version: str
```

例如：

```
V1.0
```

以后升级：

```
V1.1

V2.0
```

不用改代码。

---

```python
created_at: str
```

ISO 时间。

Workflow 创建时间。

---

```python
last_error: str | None
```

最近一次错误。

例如：

```
JSON Parse Error
```

没有：

```
None
```

---

```python
llm_call_count: int
```

统计：

整个 Workflow

调用了多少次 LLM。

初始：

```
0
```

---

```python
tool_call_count: int
```

统计：

调用多少 Tool。

初始：

```
0
```

---

## 注意

这里只增加字段。

不要增加新的逻辑。

---

# 修改五：OutputState 增加版本信息

增加：

```python
schema_version: str
```

例如：

```
grounded_data_v1
```

---

增加：

```python
export_format: str
```

例如：

```
csv

json

xlsx
```

默认：

```
json
```

---

不要增加：

```
export_path

checksum

storage
```

V1 不需要。

---

# 不要修改的内容

下面这些保持原样：

```
✓ reducer

✓ make_initial_state()

✓ RouteDecision

✓ ExecutionStatus

✓ ContextState

✓ DataState 的整体结构

✓ OutputState 的整体结构

✓ ReportState

✓ QualityGraphState 层级

✓ current_data

✓ input_data
```

---

# 修改目标

完成修改后，应满足：

* ✅ TypedDict 真正参与类型检查。
* ✅ Workflow History 与 Data Trace 具有明确的数据结构。
* ✅ WorkflowState 支持运行统计与日志扩展。
* ✅ OutputState 具备基本的版本信息。
* ✅ 与现有 Graph、Agent、Tool 保持完全兼容，不影响其他模块。
