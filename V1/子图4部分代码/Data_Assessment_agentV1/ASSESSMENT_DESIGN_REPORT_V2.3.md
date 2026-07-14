# Assessment SubGraph 设计报告 V2.3 — grounded_data 感知评估

> **版本**: V2.3 — 面向 grounded_data 格式的提取质量 + 数据质量双重评估
> **核心变更**: Assessment 不再泛化评估 "input data"，而是针对提取子图产出的 `grounded_data` 格式，分别评估提取质量（trace_id / provenance / extraction_method）与数据质量（格式 / 单位 / 冲突）。
> **对应文件**: `Data_Assessment_agentV1/assessment_graph.py` + `agents/*.py` + `tools/assessment/*.py`

---

## 1. 问题诊断

### 1.1 原架构的问题

V2.1 的 Assessment 将输入数据视为泛化的 "records + sources" 结构，不感知数据来源格式：

| 层面 | 原做法 | 问题 |
|------|--------|------|
| 数据感知 | 只读 `field_name` / `field_value` / `field_unit` | 不识别 `trace_id`、`extraction_method`、`provenance.bbox` 等提取特有字段 |
| 完整性检查 | 检查 source_id / unit / provenance | provenance 只检查 page，不涉及 bbox 和 trace_id |
| 格式检查 | 检查 record_id 基本格式 | 不校验 `{source_id}_{field_name}_{n}` 的严格格式 |
| 输出 | 输出泛化的 quality report | 没有区分"提取质量问题"和"数据值质量问题" |

### 1.2 grounded_data 格式要求

输入 Assessment 的数据必须符合 SubGraph 3（提取子图）的 `grounded_data` JSON Schema：

```
grounded_data:
  sources[]:
    source_id (PK), doi, title, authors, year, journal, access_path, retrieval_priority
  records[]:
    record_id        → 格式 {source_id}_{field_name}_{n}
    source_id        → FK → sources[].source_id
    field_name       → snake_case 科学字段名
    field_value      → number | string (非 null)
    field_unit       → string | null
    trace_id         → 提取溯源 ID (如 doc1_p3_tb2_r1)
    provenance:
      page           → int | null  (PDF 页码)
      bbox           → [x0,y0,x1,y1] | null  (PDF 坐标)
    extraction_method → "llm_text" | "llm_table"
```

---

## 2. V2.3 设计：双重评估体系

### 2.1 核心思想

Assessment 同时评估两个维度的质量：

```
┌─────────────────────────────────────────────────────────┐
│  Assessment V2.3                                        │
│                                                         │
│  ┌── Extraction Quality ──┐  ┌── Data Quality ──────┐  │
│  │ trace_id 完整性         │  │ field_value 格式      │  │
│  │ provenance(page+bbox)  │  │ field_unit 完整性      │  │
│  │ extraction_method 有效  │  │ 跨来源数值冲突         │  │
│  │ record_id 格式正确      │  │ schema 字段覆盖       │  │
│  │ source_id 外键完整性    │  │ 语义类型可行性         │  │
│  └────────────────────────┘  └───────────────────────┘  │
│                                                         │
│  输出:                                                   │
│    - extraction_quality:  提取阶段的信任度               │
│    - data_quality:        数据值本身的质量               │
│    - per_source_routes:   每个 source 的路由决策          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 评估维度对照

| grounded_data 字段 | 评估维度 | 检查内容 | 影响 |
|-------------------|---------|---------|------|
| `record_id` | 格式检查 | 是否匹配 `{source_id}_{field_name}_{n}` | 数据溯源可信度 |
| `source_id` | 外键检查 | 是否在 sources[] 中存在 | 数据完整性 |
| `field_name` | Schema 检查 | 是否在 target_schema 中 / 是否为别名 | 路由：Normalization |
| `field_value` | 格式+冲突 | 是否含 ~≈ 前缀 / 跨来源数值差异 | 路由：Normalization / Conflict |
| `field_unit` | 完整性检查 | 数值字段是否缺失单位 | 路由：Normalization |
| `trace_id` | 提取质量 | 是否存在 | 提取过程可信度 |
| `provenance.page` | 提取质量 | 是否存在 | 数据可追溯性 |
| `provenance.bbox` | 提取质量 | 是否存在 | 前端 PDF 高亮可用性 |
| `extraction_method` | 提取质量 | 是否为 "llm_text" 或 "llm_table" | 提取方式可信度 |

---

## 3. Stage 修改详情

### 3.1 Stage 1: ProfilingAgent (修改)

**原**: 8 Tools，纯统计观测
**改**: 增加 grounded_data 特有的画像维度

| # | Tool | 原有 | V2.3 新增 |
|---|------|------|-----------|
| 1 | DatasetProfiler | record/source/field 数量 | + trace_id 覆盖率 |
| 2 | SchemaProfiler | actual vs expected fields | 无变化 |
| 3 | FieldProfiler | dtype/null_ratio/unique_ratio | + extraction_method 分布 (llm_text vs llm_table 比例) |
| 4 | SourceProfiler | source_type 分布 | 无变化 |
| 5 | MetadataProfiler | doi/title/authors/year/journal | 无变化 |
| 6 | DistributionProfiler | 分布统计 | 无变化 |
| 7 | SemanticTypeInferrer | 语义类型推断 | 无变化 |
| 8 | OutlierDetector | 异常值检测 | 无变化 |

### 3.2 Stage 2: QualityAssessmentAgent (核心修改)

**原**: 5 Tools + 2 Engines，泛化评估
**改**: 拆分为提取质量 + 数据质量两组

```
QualityAssessmentAgent V2.3:

  对每个 source 的 records:

  ── 提取质量 (Extraction Quality) ──
  check_extraction_quality(records):
    1. trace_id_present_rate:  有 trace_id 的记录比例
    2. provenance_page_rate:   有 provenance.page 的记录比例
    3. provenance_bbox_rate:   有 provenance.bbox 的记录比例
    4. extraction_method_valid: extraction_method 是否全为合法值
    5. record_id_format_valid:  record_id 是否全符合格式
    → extraction_quality_score (0-1)

  ── 数据质量 (Data Quality) ──
  check_completeness:  外键/单位/溯源覆盖
  check_consistency:   Schema/Type/Unit 一致性
  check_format:        数值格式 (NaN/Inf/~≈前缀)
  check_source_reliability: 来源可信度
  detect_conflicts:    Cohen's d 跨来源冲突 (全局)
    → data_quality_score (0-1)

  ── 综合 ──
  quality_score = 0.3 × extraction_quality + 0.7 × data_quality
```

### 3.3 Stage 3: QualityScoringAgent (微调)

权重中加入 extraction_quality 维度：
```
weights:
  extraction_quality:    0.15  ← V2.3 新增
  completeness:          0.25
  consistency:           0.25
  format:                0.05
  source_reliability:    0.10
  conflict_risk:         0.20
```

### 3.4 Stage 4: DecisionReasoningAgent (微调)

路由决策增加提取质量问题：
```
- extraction_quality < 0.5  AND 有其他问题 → HumanReview
- extraction_quality < 0.8  AND  无其他问题 → Export (提取质量低但数据本身可用)
- 其余沿用 8 项检查 + 决策矩阵
```

---

## 4. 新增 Tool: check_extraction_quality

```
函数: check_extraction_quality(records)

逻辑:
  total = len(records)
  if total == 0: return perfect

  missing_trace_id = sum(1 for r if not r.get("trace_id"))
  missing_page = sum(1 for r if not r.get("provenance", {}).get("page"))
  missing_bbox = sum(1 for r if not r.get("provenance", {}).get("bbox"))
  bad_extraction_method = sum(1 for r
    if r.get("extraction_method") not in ("llm_text", "llm_table"))
  bad_record_id = sum(1 for r
    if not r.get("record_id","").startswith(f"{r['source_id']}_{r['field_name']}_"))

  # 加权评分
  score = 1.0 - (
    0.25 * (missing_trace_id / total) +
    0.20 * (missing_page / total) +
    0.15 * (missing_bbox / total) +
    0.20 * (bad_extraction_method / total) +
    0.20 * (bad_record_id / total)
  )
  score = clamp(0.0, 1.0)

输出: {
  score, total_records,
  missing_trace_id, missing_page, missing_bbox,
  bad_extraction_method, bad_record_id,
  trace_id_coverage, provenance_coverage,
  extraction_method_distribution: {llm_text: N, llm_table: M},
  issues: [...]
}
```

---

## 5. 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `tools/assessment/extraction_quality.py` | **新增**: grounded_data 提取质量检查 |
| `Data_Assessment_agentV1/agents/profiling_agent.py` | 2 处: DatasetProfiler 加 trace_id 覆盖率，FieldProfiler 加 extraction_method 分布 |
| `Data_Assessment_agentV1/agents/quality_assessment_agent.py` | 加 extraction_quality 调用，拆为两组评估 |
| `Data_Assessment_agentV1/agents/quality_scoring_agent.py` | 评分权重加入 extraction_quality |
| `Data_Assessment_agentV1/agents/decision_reasoning_agent.py` | 提取质量过低 → HumanReview |

---

## 6. 与其他模块的契约

### 6.1 输入契约

Assessment 必须接收符合 `grounded_data` schema 的数据：
```json
{
  "schema_version": "1.0.0",
  "sources": [...],
  "records": [
    {
      "record_id": "{source_id}_{field_name}_{n}",
      "source_id": "...",
      "field_name": "...",
      "field_value": ...,
      "field_unit": "..." | null,
      "trace_id": "...",
      "provenance": {"page": int|null, "bbox": [4]|null},
      "extraction_method": "llm_text" | "llm_table"
    }
  ]
}
```

### 6.2 输出契约

Quality Report 新增字段：
```json
{
  "quality": {
    "sources": {
      "source_id": {
        "extraction_quality": {
          "score": 0.85,
          "missing_trace_id": 0,
          "missing_page": 2,
          "missing_bbox": 3,
          "bad_extraction_method": 0,
          "bad_record_id": 0
        },
        "completeness": {...},   // 不变
        "consistency": {...},    // 不变
        "format": {...},         // 不变
        "source_reliability": {...}, // 不变
        "conflict_risk": {...}    // 不变
      }
    },
    "per_source_routes": {...}    // 不变
  }
}
```
