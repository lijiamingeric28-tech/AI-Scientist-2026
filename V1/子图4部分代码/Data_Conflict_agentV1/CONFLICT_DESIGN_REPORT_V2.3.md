# Conflict Resolution SubGraph 设计报告 V2.3 — grounded_data 感知冲突裁决

> **版本**: V2.3 — 面向 grounded_data 格式的跨来源冲突裁决
> **核心变更**: Conflict 在 grounded_data 格式内工作，不修改 trace_id/provenance/extraction_method，裁决结果交给 Normalization 执行。
> **对应文件**: `Data_Conflict_agentV1/conflict_graph.py` + `agents/*.py` + `tools/conflict/*.py`

---

## 1. 核心原则

### 1.1 Conflict 在 grounded_data 中的角色

```
grounded_data records:
  Source A: yield_strength = 450 MPa (trace_id: doc1_p3_tb2_r1, extraction: llm_table)
  Source B: yield_strength = 520 MPa (trace_id: doc2_p5_tb1_r3, extraction: llm_table)
                                     ↑
                            Conflict: 同一 field_name, 不同 field_value

Conflict 裁决: "prefer Source A (MSEA, more reliable)"
  → 不直接修改 record
  → 写入 resolution_plan: {source_id: B, field: yield_strength, new_value: 450, trace_id: doc2_p5_tb1_r3}
  → Normalization 读取 resolution_plan, 修改 Source B 的 field_value
  → trace_id/provenance/extraction_method 全程不动
```

### 1.2 修改范围

| grounded_data 字段 | Conflict 能否读取 | Conflict 能否修改 |
|-------------------|------------------|------------------|
| `record_id` | ✅ 标识记录 | ❌ |
| `source_id` | ✅ 分组来源 | ❌ |
| `field_name` | ✅ 匹配冲突字段 | ❌ |
| `field_value` | ✅ 冲突分析 | ❌ (仅写 resolution_plan) |
| `field_unit` | ✅ 单位一致性检查 | ❌ |
| `trace_id` | ✅ 溯源参考 | ❌ |
| `provenance` | ✅ 上下文 (材料/条件推断) | ❌ |
| `extraction_method` | ✅ 来源可信度参考 | ❌ |

---

## 2. 6 Stage 修改详情

### 2.1 Stage 1: ConflictIdentificationAgent (微调)

**原**: 从 Quality/Normalization Report 提取冲突
**改**: 提取冲突时保留 grounded_data 上下文

每个冲突增加:
```python
{
    "conflict_id": "CF-001",
    "field_name": "yield_strength",
    "source_a": {source_id, trace_ids: [...], extraction_methods: [...]},
    "source_b": {source_id, trace_ids: [...], extraction_methods: [...]},
    ...
}
```

### 2.2 Stage 2: ConflictClassificationAgent (微调)

无变化。分类逻辑与数据格式无关。

### 2.3 Stage 3: EvidenceCollectionAgent (修改)

**来源可信度**: 增加 `extraction_method` 维度
- `llm_table` 提取 → 可信度 +0.05 (表格提取更结构化)
- `llm_text` 提取 → 不变
- 多 trace_id 覆盖 → 可信度 +0.03 (多次提取同一值更可靠)

### 2.4 Stage 4: ResolutionReasoningAgent (微调)

无变化。推理逻辑与数据格式无关。

### 2.5 Stage 5: ConfidenceEvaluationAgent (微调)

无变化。

### 2.6 Stage 6: ResolutionReportAgent (修改)

**resolution_plan 加入 grounded_data 引用**:
```json
{
  "actions_to_normalize": [
    {
      "conflict_id": "CF-001",
      "source_id": "doi_B",
      "field_name": "yield_strength",
      "new_value": 450,
      "affected_trace_ids": ["doc2_p5_tb1_r3"],
      "reason": "Prefer source A (MSEA, higher reliability)"
    }
  ]
}
```

---

## 3. 新增: extraction_method 可信度加成

在 `source_reliability_analyzer.py` 的 `_compute_reliability` 中:

```python
# V2.3: extraction_method 加成
records_for_source = [r for r in all_records if r.get("source_id") == source_id]
table_count = sum(1 for r in records_for_source if r.get("extraction_method") == "llm_table")
text_count = sum(1 for r in records_for_source if r.get("extraction_method") == "llm_text")
if table_count + text_count > 0:
    table_ratio = table_count / (table_count + text_count)
    extraction_bonus = 0.05 * table_ratio  # 最多 +0.05
    reliability += extraction_bonus
```

---

## 4. 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `tools/conflict/source_reliability_analyzer.py` | extraction_method 可信度加成 |
| `Data_Conflict_agentV1/agents/resolution_report_agent.py` | resolution_plan 加入 trace_id 引用 |

---

## 5. 与其他模块的契约

### Conflict → Normalization (C→B)
```
resolution_plan.actions_to_normalize = [
  {source_id, field_name, new_value, affected_trace_ids, reason}
]
Normalization 读取后: 只修改 field_value, 不动 trace_id
```

### Conflict → Export (C→D)
```
resolution_report 写入 report_state.conflict
Export 读取后: 将裁决记录写入 traceability
```
