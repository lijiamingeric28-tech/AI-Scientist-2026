"""
子图2：检索 (Retrieval)

## 职责

从多个数据源（学术文献、数据库、网页）检索相关资料。

## 流程

```
START → 扩展查询 → [并行检索]
                    ├─ 论文检索
                    ├─ 数据库检索
                    └─ 网页检索
                         ↓
                    引用扩展 → 去重聚类 → END
```

## Agent列表

| Agent | 文件 | 职责 |
|-------|------|------|
| Expand_Query | nodes/expand_query.py | 查询扩展 |
| Paper_Search | nodes/search_papers.py | 论文检索 |
| Database_Search | nodes/search_databases.py | 数据库检索 |
| Web_Search | nodes/search_web.py | 网页检索 |
| Citation_Expansion | nodes/citation_expand.py | 引用链扩展 |
| Deduplicate | nodes/deduplicate.py | 去重聚类 |

## 输入输出

**输入**:
- `intent_params`: Dict - 结构化意图参数

**输出**:
- `papers`: List[Dict] - 论文列表
- `filtered_papers`: List[Dict] - 去重后的资产清单

## 迁移来源

从 `subgraph_1-3_v1.0/pipeline/retrieval/` 迁移
