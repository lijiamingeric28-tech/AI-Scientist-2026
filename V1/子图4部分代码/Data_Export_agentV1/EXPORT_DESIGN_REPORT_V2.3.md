# Export SubGraph 设计报告 V2.3 — grounded_data 结构化输出

> **版本**: V2.3 — 面向 grounded_data 格式的最终结构化输出
> **核心原则**: Export 输出 cleaned grounded_data + 分离的 metadata/traceability/quality_summary
> **对应文件**: `Data_Export_agentV1/export_graph.py` + `agents/*.py` + `tools/export/*.py`

---

## 1. 输出格式定义

### 1.1 核心输出: cleaned grounded_data

Export 产出的 `structured_data` 仍然是 `grounded_data` 格式，但数据已清洗:

```json
{
  "schema_version": "1.0.0",
  "sources": [...],       // 原样保留
  "records": [
    {
      "record_id": "doi_A_yield_strength_1",
      "source_id": "doi_A",
      "field_name": "yield_strength",     // ← 已标准化
      "field_value": 450,                 // ← 已清理
      "field_unit": "MPa",               // ← 已标准化
      "trace_id": "doc1_p3_tb2_r1",      // ← 原样保留
      "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},  // ← 原样保留
      "extraction_method": "llm_table"   // ← 原样保留
    }
  ]
}
```

### 1.2 分离输出

| 输出组件 | 内容 | 格式 |
|---------|------|------|
| `structured_data` | cleaned grounded_data (records + sources) | JSON + CSV |
| `metadata` | 字段定义、来源汇总、处理记录 | JSON |
| `traceability` | trace_id 索引、逐条记录溯源、Agent 决策链 | JSON |
| `quality_summary` | 综合评分、置信度、处理统计、风险指标 | JSON |

---

## 2. 6 Stage 修改详情

### 2.1 Stage 1: DataOrganizationAgent (修改)

**原**: 过滤临时字段 + schema 对齐
**V2.3**: 明确 grounded_data 的保留/过滤策略

```
保留 (clean output):
  record_id, source_id, field_name, field_value, field_unit,
  trace_id, provenance, extraction_method

过滤 (内部临时):
  _modified, _conflict_cache, _temp_score, _normalized,
  _resolution_status, _source_path, _missing_unit
```

### 2.2 Stage 2: SchemaFormattingAgent (微调)

**原**: JSON/CSV/Wide 多格式导出
**改**: CSV 导出增加 grounded_data 列

CSV 长表列: `record_id, source_id, field_name, field_value, field_unit, trace_id, page, extraction_method`

### 2.3 Stage 3: MetadataGenerationAgent (微调)

**原**: 字段定义 + LLM 描述 + 处理记录
**改**: 增加 extraction 统计

```json
{
  "extraction_summary": {
    "total_trace_ids": 22,
    "unique_trace_ids": 22,
    "extraction_method_distribution": {"llm_table": 15, "llm_text": 7},
    "provenance_coverage": 0.85
  }
}
```

### 2.4 Stage 4: TraceabilityConstructionAgent (修改)

**原**: 数据世系 + 逐条溯源
**V2.3**: 以 `trace_id` 为主线组织溯源

```json
{
  "by_trace_id": {
    "doc1_p3_tb2_r1": {
      "record_id": "doi_A_yield_strength_1",
      "original_value": "~450",
      "final_value": 450,
      "modifications": [
        {"stage": "normalization", "tool": "field_standardizer", "change": "~450 → 450"}
      ]
    }
  }
}
```

### 2.5 Stage 5: OutputValidationAgent (修改)

**V2.3**: 增加 grounded_data 完整性最终校验

```
校验项:
  - 所有 record 有 trace_id
  - 所有 record 有 provenance (page 或 null)  
  - extraction_method 全为合法值
  - record_id 格式正确
  - 无残留别名
  - 无残留 ~ 前缀
```

### 2.6 Stage 6: StructuredExportGenerationAgent (微调)

无变化。组装 Output State。

---

## 3. 数据流: trace_id 贯穿全链路

```
grounded_data (输入)
  trace_id: "doc1_p3_tb2_r1"
    ↓
Assessment: 检查 trace_id 完整性 → quality.extraction_quality
    ↓
Normalization: 修改 field_value, 保留 trace_id
    ↓
Conflict: 裁决时引用 trace_id → resolution_plan.affected_trace_ids
    ↓
Export: trace_id → traceability.by_trace_id 索引
```

---

## 4. 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `tools/export/data_organizer.py` | 明确 grounded_data 字段保留列表 |
| `tools/export/traceability_builder.py` | 以 trace_id 为主线组织溯源 |
| `tools/export/output_validator.py` | 增加 grounded_data 完整性校验 |
| `tools/export/metadata_generator.py` | 增加 extraction 统计 |
