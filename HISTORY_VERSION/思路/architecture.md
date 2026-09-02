### 1. 定义全局状态 (State)

状态 (State) 是整个系统的共享数据存储。图中的每个节点在执行时都会读取该字典，并将处理结果通过更新对应字段的方式传递给下游。

```python
from typing import TypedDict, List, Dict
from langgraph.graph import StateGraph, START, END

class ResearchState(TypedDict):
    query: str                      # 用户输入的查询意图
    pdf_paths: List[str]            # 下载完成的本地 PDF 路径列表
    extracted_data: List[Dict]      # 提取的数据及物理坐标 (如 bbox)
    has_hallucination: bool         # 标记是否存在数据捏造/幻觉
    has_conflict: bool              # 标记是否存在多源数据矛盾
    final_output: str               # 最终交付的结构化数据
```

### 2. 定义节点 (Nodes)

节点 (Node) 负责具体的业务执行。每个节点是一个 Python 函数，接收当前 `state`，执行内部逻辑（如调用 API 或大模型），并返回需要更新的字典内容。

```python
def search_node(state: ResearchState):
    # 实现网络搜索与 PDF 下载逻辑
    # TODO: 接入网络检索和文件下载工具
    return {"pdf_paths": ["paper1.pdf", "paper2.pdf"]}

def parse_node(state: ResearchState):
    # 实现文档解析与坐标定位
    # TODO: 使用 PyMuPDF 等库提取文本及 bbox 坐标
    return {"extracted_data": [{"value": "1.2", "bbox": [10, 20, 50, 60]}]}

def validate_node(state: ResearchState):
    # 实现防幻觉校验
    # TODO: 调用 LLM 对比 extracted_data 与原 PDF 文本块
    return {"has_hallucination": False} 

def clean_node(state: ResearchState):
    # 实现数据清洗与格式对齐
    # TODO: 处理多源数据整合，排查逻辑或单位冲突
    return {"has_conflict": False} 

def human_intervention_node(state: ResearchState):
    # 人工干预节点
    # 挂起恢复后执行，接收前端回传的修正数据
    return {"has_conflict": False} 

def output_node(state: ResearchState):
    # 数据格式化与输出
    # 构造最终供前端渲染的 JSON 数据结构
    return {"final_output": "最终的结构化科研数据"}
```

### 3. 定义条件路由逻辑 (Conditional Edges)

条件路由是一个判断函数，用于决定当前节点执行完毕后，控制流走向哪一个分支。这里主要处理“循环重试”和“流程挂起”两个核心逻辑。

```python
def check_hallucination(state: ResearchState):
    """防幻觉分支：判断是否需要打回重做"""
    if state.get("has_hallucination"):
        # 存在幻觉，退回解析节点重新执行
        return "parse_node"
    # 验证通过，进入清洗节点
    return "clean_node"

def check_conflict(state: ResearchState):
    """人工介入分支：判断是否需要中断等待"""
    if state.get("has_conflict"):
        # 存在数据矛盾，导向人工干预节点
        return "human_intervention_node"
    # 无异常，直接进入输出节点
    return "output_node"
```

### 4. 构建与编译图 (Build & Compile)

将上述定义的节点与路由逻辑注册到 StateGraph 中，配置有向无环/有环图的连线关系，并设置中断断点（Breakpoint），最后编译实例化。

```python
# 初始化图
builder = StateGraph(ResearchState)

# 注册所有节点
builder.add_node("search_node", search_node)
builder.add_node("parse_node", parse_node)
builder.add_node("validate_node", validate_node)
builder.add_node("clean_node", clean_node)
builder.add_node("human_intervention_node", human_intervention_node)
builder.add_node("output_node", output_node)

# 基础流程连线
builder.add_edge(START, "search_node")
builder.add_edge("search_node", "parse_node")
builder.add_edge("parse_node", "validate_node")

# 注册条件路由分支
builder.add_conditional_edges(
    "validate_node",
    check_hallucination,
    {"parse_node": "parse_node", "clean_node": "clean_node"}
)

builder.add_conditional_edges(
    "clean_node",
    check_conflict,
    {"human_intervention_node": "human_intervention_node", "output_node": "output_node"}
)

builder.add_edge("human_intervention_node", "output_node")
builder.add_edge("output_node", END)

# 编译图实例：在人工干预节点前设置强制中断断点 (Breakpoint)
graph = builder.compile(interrupt_before=["human_intervention_node"])


# ==============================
# 本地测试启动入口
# ==============================
if __name__ == "__main__":
    initial_state = {"query": "提取最新固态电池电导率数据"}
    # 必须配置 thread_id 以维持状态和支持断点恢复
    config = {"configurable": {"thread_id": "test_thread_001"}}

    for event in graph.stream(initial_state, config=config):
        for node_name, node_state in event.items():
            print(f"节点完成: {node_name}")
```
