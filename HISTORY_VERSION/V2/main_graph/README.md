# 主图 (Main Graph)

## 职责

整合四个子图，构建完整的数据处理管道。

## 文件说明

| 文件 | 职责 | 状态 |
|------|------|------|
| `graph.py` | 主图定义和编译 | ⚠️ 待迁移 |
| `state.py` | 主State定义 | ✅ 已定义 |
| `wrappers.py` | 子图State转换包装器 | ⚠️ 待实现 |

## 使用方法

```python
from main_graph.graph import compile_main_pipeline

# 编译管道
pipeline = compile_main_pipeline()

# 运行
result = pipeline.invoke({
    "user_query": "查找材料X的性能数据"
})
```

## State流转

```
MainState (input)
    ↓ user_query
IntentState (子图1)
    ↓ intent_params
RetrievalState (子图2)
    ↓ papers
ExtractionState (子图3)
    ↓ grounded_data
QualityState (子图4)
    ↓ final_output
MainState (output)
```

## 迁移待办

- [ ] 从subgraph_1-3_v1.0/pipeline/main_graph.py迁移主图逻辑
- [ ] 实现wrappers.py中的四个包装函数
- [ ] 编写集成测试
