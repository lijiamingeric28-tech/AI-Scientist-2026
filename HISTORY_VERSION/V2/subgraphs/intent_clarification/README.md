"""
子图1：意图澄清 (Intent Clarification)

## 职责

将用户的自然语言查询转化为结构化的检索参数。

## 流程

```
START → 评估意图 → [槽位完整？] 
         ↓ 否           ↓ 是
    引导追问 ←      最终确认 → END
```

## Agent列表

| Agent | 文件 | 类型 | 职责 |
|-------|------|------|------|
| Evaluate_Intent_Agent | nodes/evaluate_intent.py | 普通 | 意图评估与填槽 |
| Ask_User_Guided | nodes/ask_user.py | HITL | 引导式追问 |
| Confirm_Intent | nodes/confirm_intent.py | HITL | 最终确认 |

## 输入输出

**输入 (IntentState)**:
- `original_query`: str - 用户原始查询

**输出 (IntentState)**:
- `extracted_parameters`: Dict - 结构化参数
- `compromise_flag`: bool - 是否包含AI推测

## 迁移来源

从 `subgraph_1-3_v1.0/pipeline/intent/` 迁移

## 迁移待办

- [ ] 迁移 graph.py
- [ ] 迁移 state.py
- [ ] 迁移 nodes/evaluate_intent.py
- [ ] 迁移 nodes/ask_user.py
- [ ] 迁移 nodes/confirm_intent.py
- [ ] 修复所有import路径
- [ ] 运行测试
