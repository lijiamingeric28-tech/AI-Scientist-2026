"""
子图3：提取 (Extraction)

## 职责

从文档中提取结构化数据，并进行忠实度校验。

## 流程

```
START → 格式标准化 → 相关性过滤 → 数据提取
                                    ↓
                              忠实度校验
                           ↙ 通过    ↓ 失败(重试<3)
                  溯源绑定 ←────── 重新提取
                     ↓
                    END
```

## Agent列表

| Agent | 文件 | 职责 |
|-------|------|------|
| Format_Standardization | nodes/format_standardize.py | 格式标准化 |
| Relevance_Filtering | nodes/filter_relevance.py | 相关性过滤 |
| Data_Extraction | nodes/extract_data.py | 数据提取 |
| Fidelity_Validation | nodes/validate_fidelity.py | 忠实度校验 |
| Bind_Provenance | nodes/bind_provenance.py | 溯源绑定 |

## 输入输出

**输入**:
- `intent_params`: Dict
- `filtered_papers`: List[Dict]

**输出**:
- `grounded_data`: Dict - 带溯源的结构化数据
- `verification_rate`: float

## 迁移来源

从 `subgraph_1-3_v1.0/pipeline/extraction/` 迁移
