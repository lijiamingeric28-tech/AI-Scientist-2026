# Export SubGraph 设计报告 V1.0

> **版本**: V1.0 — 数据组织与结构化输出 (V2 Schema 兼容)
> **设计原则**: 一个 Stage = 一个 Node = 一个 Agent
> **核心原则**: Export 是 Workflow 最终节点，**仅负责数据组织与输出，绝不修改数据内容。**
> **对应文件**: `Data_Export_agentV1/export_graph.py` + `agents/*.py` + `tools/export/*.py`
> **更新 (2026-08-03, V4.2)**: 与代码全面对齐（三路汇聚/6 Stage/工具清单/State 键/schema 对齐）
> **更新 (2026-08-04, V4.3)**: database_catalog_properties aliases 扩展至 919（23 个 VizieR 目录全量列名）— 正向白名单覆盖全部目录列, 防 Export 丢弃

---

## 0. 变更记录 (V4.2)

本报告已按当前源码逐段核对更新。以下为源码注释中 V3.1 → V4 的关键修复记录:

| 版本 | 变更 |
|------|------|
| V3.1 | `trace_completeness` 内嵌进 `traceability` dict (不再冗余写入); `output_state` 增加 `exported_files` / `output_dir`; `report_state.export` 由各 Export Agent 写入中间结果 |
| V3.2 | 校验闸门: 校验失败仍进入 export_generation 构建 output_state, 但标记 `quarantine` (`consumable=false`); Schema 字段缺失降级为 warning 不阻塞; `data_trace` 只计带 `record_id` 的事件 |
| V3.3 | 子图出口新增 `finalize` 节点, 透传 `execution_status` (Retry/Failed 冒泡到主图 Stage Gate) |
| V3.5 | 正向白名单过滤 (替代"仅排除临时字段", 防内部字段泄露); 单一终点边 `export_generation → finalize → END` (删除重复边); trace 语义区分 (有 trace 事件 ≠ 值有修改); 引入 trace_id / DB provenance 校验 |
| V4 | `_raw_field` 保留 catalog 原始列名; CSV 编码可配置 (默认 `utf-8-sig` 含 BOM); 宽表折叠统计 `wide_collapse` (json_wide 保留全部值, 零丢失); `has_unconverted_units` 只统计 `kind=unconverted_unit` 错误; `quality_consistency` 改为事件去重口径; `lineage.output.generated_at` 回填 (此前硬编码空串); manifest 含 `wide_collapse` / `csv_encoding` |

### V4.3 (2026-08-04) — VizieR 目录 schema 扩展

| 版本 | 变更 |
|------|------|
| V4.3 | target_schema_astrophysics aliases 349 → 1178: database_catalog_properties +919 (23 个 VizieR 目录 1072 列中未覆盖部分) + 标准字段 +259 (BPmag/W1mag/Fnu_*/Teff/logg/[Fe/H]/Mass/Plx/pmRA 等) |
| V4.3 | 与 data_organizer 正向白名单联动: 全部目录列经 schema_mapping 映射为标准字段或 database_catalog_properties 后, Export 白名单过滤不再丢弃任何目录列 (V4.3 前未覆盖列会被丢弃) |
| V4.3 | 零 LLM 全链路验证 (test_real_data_e2e_mock.py): 10 条抽样 + 全量 219 条真实数据 ALL CHECKS PASSED, DB 记录 119/159 保留无丢失 |

---

## 1. Agent 元信息

### 1.1 基本属性

| 属性 | 内容 |
|------|------|
| **Agent 名称** | Structured Export Agent |
| **SubGraph 名称** | Data_Export_agentV1 |
| **所属子图** | SubGraph 4 (数据清洗与质检) — 最终节点 |
| **版本** | V1.0 |
| **核心职责** | 对已完成规范化处理及冲突/方差分析的数据进行统一组织与结构化输出，生成标准格式的数据文件、元数据、数据溯源信息及最终质量摘要 |
| **关键约束** | **仅负责数据组织与输出，绝不修改数据内容。** 不调用任何数据修改工具。 |
| **修改数据** | ❌ 否 — 只读数据，只写 Output State |
| **V2 Schema 支持** | ✅ 完整支持 V2.0 grounded_data Schema (entity_type/entity_name/extraction_confidence/context_snippet/measurement_method/condition_tags 等字段全部保留到输出) |

### 1.2 前后置条件

| 条件类型 | 条件 |
|---------|------|
| **前置条件 (A→D 路径)** | `report_state.quality` 已被 Assessment 填充且 per_source_routes 含 Export |
|  | `data_state.current_data` 为通过检测的数据 |
| **前置条件 (B→D 路径)** | `report_state.normalization` 已被 Normalization 填充且 `route_decision="Export"` |
|  | `data_state.current_data` 为规范化后的数据 |
| **前置条件 (C→D 路径)** | `report_state.conflict` 已被 Conflict 填充且 `resolution_report.route_decision="Export"` |
|  | 或 `workflow_state.iteration_counter >= MAX_ITERATIONS` / `force_export=True` (LoopController 强制 Export) |
| **后置条件** | `output_state` 包含完整的 `structured_data` / `metadata` / `traceability` / `quality_summary` (+ `exported_files` / `output_dir`) |
|  | `workflow_state.execution_status` 透传到主图 Stage Gate (V3.3: `finalize` 节点), Failed → 主图 Gate → HumanReview |

### 1.3 上下游及总图位置

```
上游 (三路汇聚):
  Assessment (A→D): 无问题数据
  Normalization (B→D): 规范化完成的数据
  Conflict (C→D): 冲突已解决 (resolution_report.route_decision="Export"),
                  或 LoopController 强制终止 (iteration_counter 超限 / force_export)

下游 (V3.4): DataInsights 子图 (insights_graph) — 主图边 Export → Insights → END
  导出文件落盘: output/{run_id[:8]}/ 下的 JSON/CSV/manifest 文件 (供前端展示)
```

---

## 2. 架构概览 — 6 Stage 流水线

```
START → DataOrganizationAgent → SchemaFormattingAgent
      → MetadataGenerationAgent → TraceabilityConstructionAgent
      → OutputValidationAgent → StructuredExportGenerationAgent
      → finalize → END

线性流水线, 无条件分支 (export_graph.py 共 110 行, 纯编排)。
```

**finalize 节点 (V3.3)**: 子图出口状态透传 — 读取 `workflow_state.execution_status`
(Retry/Failed 冒泡到主图 Stage Gate), 主图据此决定重入 / HumanReview / 继续。

**V3.2 校验闸门**: `output_validation → export_generation` 恒连边 — 校验失败时
仍进入 export_generation 构建 output_state (含 partial 数据), 但标记
`quarantine=True` (`consumable=false`), 且 `execution_status="Failed"` 经 finalize
冒泡 → 主图 Gate 路由 HumanReview (保留 partial_output)。

**V3.5 fix**: 单一终点边 `export_generation → finalize → END` (删除历史重复边)。

---

## 3. Stage 1: DataOrganizationAgent

**LLM**: 否 | **文件**: `agents/data_organization_agent.py`

### 3.1 职责

去除 Workflow 中间临时字段，按 Target Schema 组织数据，按 source 分组排序，构建 field_index。

### 3.2 处理流程

```
1. 正向白名单过滤 (V3.5 fix: 替代"仅排除临时字段", 防内部字段泄露到最终导出)
   _GROUNDED_DATA_RECORD_FIELDS: record_id, source_id, entity_type, entity_name,
     field_name, field_value, field_unit, trace_id, provenance, extraction_method,
     extraction_confidence, context_snippet, measurement_method, condition_tags,
     _uncertainty, _raw_field
   (V4: _raw_field — schema_mapping 保留的 catalog 原始列名, 随导出带出,
    解决 database_catalog_properties 坍缩为裸数值丢失原始身份)
   (V4.3: database_catalog_properties aliases 扩展至 919 — 23 个 VizieR 目录
    1072 列全量覆盖, 目录列经 schema_mapping 映射为标准字段或
    database_catalog_properties 后, Export 白名单过滤不再丢弃任何目录列;
    V4.3 前未覆盖列会被静默丢弃)
   _TEMP_RECORD_FIELDS (仅用于识别, 不再逐一排除): _modified, _conflict_cache,
     _temp_score, _normalized, _resolution_status, _source_path, _prefer_a, _missing_unit

2. 过滤 source 字段: _PUBLIC_SOURCE_FIELDS
   (source_id, doi, title, authors, year, journal, source_type, access_path,
    retrieval_priority, abstract, keywords, search_query, search_rank
    + V3.1 Database 类型字段: vizier_table_id, description, reference_paper,
      bibcode, research_methodology, observation_facility, waveband, research_content)

3. Schema 对齐: 区分 standard_fields vs extra_fields (对比 target_schema.fields)

4. 排序: sources 按 year desc + title, records 按 source_id + field_name + record_id

5. 构建 field_index: 每字段的 record_count, source_count, sources, units_used,
   standard_unit (来自 target_schema), data_type (numeric/string/mixed/empty),
   sample_values (前 5 条), is_extra
   summary: total_sources, total_records, standard_fields, extra_fields,
            records_filtered, sources_trimmed
```

---

## 4. Stage 2: SchemaFormattingAgent

**LLM**: 否 | **文件**: `agents/schema_formatting_agent.py`

### 4.1 职责

JSON/CSV/Wide-Table 多格式导出 + Schema 对齐格式化。

### 4.2 多格式导出

```
FormatExporter 输出:
  - json: {schema_version: "2.0.0", sources, records} — 完整 grounded_data JSON
    (V3.1 fix: 补全顶层 schema_version)
  - csv: 长表格式 (15 列, 含 V2 字段; V4: 增加 raw_field 原始列名)
    CSV header: source_id, entity_type, entity_name, field_name, field_value,
                field_unit, page, bbox, trace_id, extraction_method,
                extraction_confidence, measurement_method, condition_tags,
                context_snippet (截断 200 字符), raw_field
  - csv_wide: Pivot 宽表 (每个 field 一列 + {field}_unit 列)
  - json_wide: Pivot JSON 宽表 (V4 fix: 多值记录每格保留全部值 all_values, 零丢失)
  - row_count / column_count / wide_collapse (V4: {groups, overwritten_values} 折叠统计)
```

**V4 fix — 宽表折叠**: 同一 (source, field) 多值此前 last-write-wins 静默丢失
(23 组/187 条记录受影响)。现 CSV 宽表保持 LWW (聚合视图), 但 `json_wide` 每格改
list 完整保留, 并输出 `wide_collapse` 统计供 manifest 展示/告警。

### 4.3 Schema 对齐

```
SchemaFormatter (无 target_schema 时跳过格式校验):
  - 值格式化: 浮点数截断到 6 位小数 (round(fv, 6))
  - 单位检查: 比较 field_unit vs standard_unit, 标准化比较后仍不等 → 记 format_issues
    issue = {record_id, field, issue: "unit_mismatch", current, expected}
  - 宽表列排序: 按 target_schema.fields 顺序重排 json_wide (schema 外字段追加在后)
```

### 4.4 单位标准化检查 (schema_formatter._norm)

```
单位比较前先做字符级标准化:
  _norm(u) = u.replace("°", "").replace("℃", "C").strip()
  (去除度符号 °, ℃ 归一为 C — 使 "°C" 与 "C" / "℃" 与 "C" 视为一致)

例: field_unit="℃" vs standard_unit="°C" → _norm("℃")="C" == _norm("°C")="C" → 通过
    field_unit="K"  vs standard_unit="°C" → "K" != "C" → 记 unit_mismatch issue
```

**标准单位来源**: `context_state.target_schema` — 由主图载入领域 target_schema 配置。
天体物理 (target_schema_astrophysics, **28 字段**) 代表性标准单位:

| 字段 | standard_unit | 字段 | standard_unit |
|------|---------------|------|---------------|
| dispersion_measure | `cm^-3 pc` | luminosity | `erg/s` |
| flux_density | `Jy` | parallax | `mas` |
| rotation_measure | `rad/m^2` | distance | `pc` |
| effective_temperature | `K` | stellar_mass / stellar_radius | `Msun` / `Rsun` |
| radial/rotational_velocity | `km/s` | proper_motion_ra/dec | `mas/yr` |
| surface_gravity / metallicity / alpha_abundance | `dex` | planet_mass / planet_radius | `M_earth` / `R_earth` |
| orbital_period | `d` | extinction / 星等 | `mag` |
| age | `Gyr` | 无量纲字段 (redshift/spectral_type/RA/Dec/catalog) | `""` |

---

## 5. Stage 3: MetadataGenerationAgent

**LLM**: 是 (1 次字段描述生成) | **文件**: `agents/metadata_generation_agent.py`

### 5.1 职责

生成字段定义/描述 + 来源汇总 + 处理记录 (Tool 4 确定性生成 + 1 次 LLM 描述)。

### 5.2 输出

```
metadata = {
  field_definitions: {field_name: {standard_unit, semantic_type, criticality,
                                   aliases, in_schema, is_extra_field | in_data, description}},
  source_summary: {total_sources, sources_exported, sources_human_review,
                   per_source: [{source_id, title, year, journal, record_count,
                                 quality_grade, final_route}]},
  processing_record: {
    assessment: {status, sources_assessed, overall_quality, total_issues},
    normalization: {status, modifications, by_layer, errors} | {status: "Skipped"},
    conflict: {status, total_conflicts, auto_resolved, human_required}
              | {status: "Partially_Analyzed"} | {status: "Skipped"}
  },
  run_info: {generated_at, run_id, graph_version: "V2.1", research_domain}
}
```

**V4 fix — 字段定义以实际数据字段为基础**: 此前只遍历静态 target_schema — 数据中
实际字段 (如 distance_modulus / database_catalog_properties) 未定义, schema-only
字段 (如 redshift) 却全部"被定义", 定义集与数据脱节。现:
- 遍历数据实际 field_name 构建定义 (in_schema / is_extra_field 标注)
- schema-only 字段标注 `in_data: False` (而非凭空"被定义")
- semantic_types 兼容 entity-aware 键 `"{entity_type}:{entity_name}/{field}"` (V4 fix:
  此前按纯 field_name 查找恒 miss, 补丁从未生效; 现取末段匹配)

### 5.3 LLM 字段描述

```
LLM (temperature=0.0, agent_context="export_metadata"):
  输入: 各字段 name / semantic_type / standard_unit / criticality
  输出: JSON {"field_descriptions": {"field_name": "1 句英文描述 (含标准单位与测量内容)"}}
  成功 → field_definitions[*].description 回填 + field_descriptions_llm=True
  失败 → 模板 fallback: "{field_name} ({semantic_type}), measured in {unit}"
         (无 unit 时省略), field_descriptions_llm=False
  LLM 调用计入 workflow_state.llm_call_count (utils/llm 调用统计)
```

---

## 6. Stage 4: TraceabilityConstructionAgent

**LLM**: 否 | **文件**: `agents/traceability_construction_agent.py`

### 6.1 职责

构建完整数据溯源链: 数据世系 + 逐条记录溯源 + Agent 决策链 + 来源-记录映射 + 溯源完整度统计。

### 6.2 4 维溯源 (+ trace_completeness)

```
1. data_lineage: input (sources/records/grounded_data_version/received_at)
                 → processing (workflow_history 处理链)
                 → output (sources/records/standard_compliant,
                            generated_at — V4 fix: 回填 UTC 时间戳, 此前硬编码空串)
2. per_record_trace: {record_id: {original_value, original_unit, original_field_name,
                                  final_value, final_unit, final_field_name,
                                  modified, modifications[]}}
   (original_unit/final_unit 来自记录 field_unit, 供单位溯源核对)
   data_trace 事件按 record_id 归组 (V3.2: 只有带 record_id 的事件才计入)
   已删除记录 (input→current 差集): modified=True, modifications=[{stage: "removed", ...}]
3. agent_decision_trail: workflow_history 中各 Agent 的决策记录 (agent/stage/status/timestamp/duration/reason)
4. source_record_map: {source_id → [record_ids]}

trace_completeness (V3.1: 内嵌进 traceability dict, 供 validator/export_generation 统一读取):
  records_with_trace / records_with_modification_trace / records_without_trace
  modified_count / unmodified_count / deleted_count
  + V4: records_with_trace_id, paper_records_missing_trace_id,
        database_records, db_provenance_complete
```

**V3.5 fix — trace 语义区分**: 记录存在 ≠ 有真实 trace 事件。
`records_with_trace` = 有任意 trace 事件; `records_with_modification_trace` = 有
修改 trace 且值确实变化; `records_without_trace` = 值变化但无 trace 事件
(导致维度 4 校验失败)。

**V4 fix — 实际 trace_id 覆盖**: 此前 `records_without_trace` 只统计"被改但无 trace
事件", 从不检查记录的实际 trace_id 字段 (159 条 database 记录无 trace_id 却自报
0 缺失)。现按设计 (models/record.py): **paper 记录必有 trace_id, DB 记录靠
provenance 四要素 (db_table/key_column/key_value/raw_column) 锚定**。

---

## 7. Stage 5: OutputValidationAgent

**LLM**: 否 | **文件**: `agents/output_validation_agent.py`

### 7.1 5 维校验

`is_valid = 所有维度 passed`; 校验失败 → `execution_status="Failed"` (经 finalize
冒泡主图 Gate → HumanReview, 但 Stage 6 仍构建 output_state 并标记 quarantine)。

| # | 维度 | 检查内容 | 阻塞性 |
|---|------|---------|--------|
| 1 | Schema 完整性 | expected - actual 缺失字段 (V3.2: 部分提取合法, missing 只报告) | 不阻塞 |
| 2 | 数据完整性 | source_id 缺失 (error) / provenance 缺失 (error, V3.2 参与校验) / 数值记录缺 unit (仅统计不阻塞 — catalog 字段可无量纲) | 阻塞 (前两项) |
| 3 | 格式一致性 | 别名残留 (V2.2: 从 target_schema 动态取 aliases; V3.2 fix: 排除标准字段名自身) / ~前缀残留 | 阻塞 |
| 4 | 溯源一致性 | records_without_trace > 0 或 paper 记录缺 trace_id (V4: DB 记录按 provenance 四要素统计, 不阻塞自身) | 阻塞 |
| 5 | 质量一致性 | (records_modified + records_without_trace) >= unique_event_records (V4: 修改事件按 record_id 去重, 同口径比较; 此前 modifications.total 事件数与记录数直接比较, 0.8 容差掩盖口径错配 → 真实 e2e 恒失败) | 阻塞 |

```
checks 输出:
  schema: {passed, missing_fields, extra_fields}
  data_integrity: {passed, records_without_source, records_missing_unit, records_missing_provenance}
  format_consistency: {passed, alias_fields_remaining, residual_tilde_values}
  traceability_consistency: {passed, traced_records, untraced_records,
                             records_with_trace_id, paper_records_missing_trace_id,
                             database_records, db_provenance_complete}   (V4)
  quality_consistency: {passed, overall_score, modifications_reported,
                        unique_event_records, records_modified}          (V4)
  validation_errors: [{dimension, field, expected, actual, severity}]
  summary: "N/5 checks passed, M issue(s)"
```

---

## 8. Stage 6: StructuredExportGenerationAgent

**LLM**: 否 | **文件**: `agents/export_generation_agent.py`

### 8.1 职责

构建 quality_summary + 组装 Output State + 导出 CSV/JSON 文件到磁盘。

### 8.2 Quality Summary

```
quality_summary = {
  overall_score, quality_level, calibrated_confidence, confidence_breakdown,
  processing_statistics: {total_llm_calls, total_tool_calls, total_elapsed_seconds
                          (workflow_history duration 累加), b_c_loop_iterations},
  issues_summary: {assessment_issues, normalization_modifications,
                   conflicts_resolved (resolution_report.metadata.auto_resolved),
                   remaining_issues},
  risk_indicators: {
    has_human_review_items, has_unresolved_conflicts (resolution_report.status ∉
                      {"All_Resolved", "No_Conflicts", None}),
    has_unconverted_units,      # V4 fix: 只统计 kind=unconverted_unit 错误,
                                # 此前误把 Layer-3 生成工具运行时报错当单位转换失败
    unconverted_unit_count,
    data_completeness_warning (overall_score < 0.7),
    validation_passed
  },
  recommendation: "Data ready for analysis..." | "Data exported with N warning(s)..."
}
```

### 8.3 文件导出

```
输出目录: $EXPORT_OUTPUT_DIR / 默认 output/ + {run_id[:8]}/
  (os.makedirs 自动创建; 文件带 {timestamp} 时间戳避免覆盖)

导出文件 (7 个):
  - grounded_data_{ts}.json   (完整数据, utf-8 + indent=2 + ensure_ascii=False)
  - data_long_{ts}.csv        (长表)
  - data_wide_{ts}.csv        (宽表)
  - quality_summary_{ts}.json (质量摘要)
  - metadata_{ts}.json        (元数据)
  - traceability_{ts}.json    (溯源信息 — 简化版: data_lineage + trace_completeness
                                + modified_count + decision_count, 避免过大)
  - manifest_{ts}.json        (导出清单: exported_at/output_dir/files/validation_passed/
                                row_count/quality_level + V4: wide_collapse/csv_encoding)

V4 fix — CSV 编码可配置: 默认 utf-8-sig (含 BOM, Excel 直接打开中文不乱码);
需要无 BOM 输出时设环境变量 EXPORT_CSV_ENCODING=utf-8 (pandas 默认读取)。
```

### 8.4 Output State

```
output_state = {
  structured_data: {json, csv, csv_wide, json_wide, row_count, column_count},
  metadata: {...},
  traceability: {...},
  quality_summary: {...},
  schema_version: "2.0.0",
  export_format: "json",
  exported_files: [...],          # V3.1: 实际写入磁盘的文件路径
  output_dir: "...",              # V3.1
  consumable: bool,               # V3.2: 校验通过 = true
  quarantine: bool,               # V3.2: 校验失败 = true (不静默产出)
}
```

---

## 9. State 读写

### 9.1 读取的 State

| State 路径 | 读取者 | 用途 |
|-----------|--------|------|
| `data_state.current_data` | Stage 1, 3, 4 | 最终处理完成的数据 |
| `data_state.input_data` | Stage 4 | 原始输入数据 (对比溯源) |
| `data_state.data_trace` | Stage 4 | 数据处理全链路轨迹 (按 record_id 归组) |
| `report_state.quality` | Stage 3, 5, 6 | Quality Report (semantic_types/scoring/per_source_routes/total_issues) |
| `report_state.normalization` | Stage 5, 6 | Normalization Report (modifications/validation) |
| `report_state.conflict` | Stage 6 | Conflict Report (resolution_report) |
| `report_state.export` | Stage 2-6 | 上一 Stage 的中间结果 (organized_data/organization_summary/formatted_data/format_issues/metadata/traceability/validation) |
| `context_state.target_schema` | Stage 1, 2, 3, 5 | 目标 Schema (28 字段含 standard_unit/aliases/criticality) |
| `context_state.research_domain` | Stage 3 | 领域名 (LLM prompt) |
| `workflow_state.*` | Stage 3, 4, 6 | run_id/llm_call_count/created_at/workflow_history |

### 9.2 写入的 State

| State 路径 | 写入者 | 内容 |
|-----------|--------|------|
| `report_state.export.organized_data` + `organization_summary` | Stage 1 | 过滤/对齐后的数据 + 统计 |
| `report_state.export.formatted_data` + `format_issues` | Stage 2 | 多格式导出结果 + unit_mismatch 列表 |
| `report_state.export.metadata` | Stage 3 | 元数据 (字段定义/来源汇总/处理记录) |
| `report_state.export.traceability` | Stage 4 | 完整溯源链 (含内嵌 trace_completeness) |
| `report_state.export.validation` | Stage 5 | 5 维校验结果 |
| `output_state.structured_data` | Stage 6 | 最终结构化数据 |
| `output_state.metadata` | Stage 6 | 数据说明 |
| `output_state.traceability` | Stage 6 | 完整数据溯源链 |
| `output_state.quality_summary` | Stage 6 | 质量摘要 |
| `output_state.schema_version` | Stage 6 | "2.0.0" |
| `output_state.export_format` | Stage 6 | "json" |
| `output_state.exported_files` / `output_dir` | Stage 6 | 磁盘文件路径列表 / 输出目录 (V3.1) |
| `output_state.consumable` / `quarantine` | Stage 6 | 校验通过/隔离标记 (V3.2) |
| `workflow_state.execution_status` | Stage 5, 6 | Success / Failed (V3.3: 经 finalize 透传主图) |

---

## 10. V2 Schema 字段保留

Export 模块确保以下 V2 字段完整保留到输出:

| V2 Record 字段 | CSV 列 (15 列) | JSON 路径 |
|:--|:--|:--|
| `entity_type` | entity_type | records[].entity_type |
| `entity_name` | entity_name | records[].entity_name |
| `extraction_confidence` | extraction_confidence | records[].extraction_confidence |
| `context_snippet` | context_snippet (截断 200 字符) | records[].context_snippet |
| `measurement_method` | measurement_method | records[].measurement_method |
| `condition_tags` | condition_tags (分号拼接) | records[].condition_tags |

| 附加保留字段 | CSV 列 | 说明 |
|:--|:--|:--|
| `_uncertainty` | (仅 JSON) | 不确定度 — 白名单保留, 不进 CSV 长表 |
| `_raw_field` | raw_field | V4: catalog 原始列名 (数据库来源的原始身份) |
| `page` / `bbox` | page / bbox | 来自 provenance 的提取位置 |

| V2 Source 字段 | JSON 路径 |
|:--|:--|
| `abstract` / `keywords` | sources[].abstract / keywords |
| `search_query` / `search_rank` | sources[].search_query / search_rank |
| V3.1 Database 字段: `vizier_table_id` / `description` / `reference_paper` / `bibcode` / `research_methodology` / `observation_facility` / `waveband` / `research_content` | sources[].* |

---

## 11. 异常处理

| 层级 | 异常 | 策略 |
|------|------|------|
| Stage 1 | 数据为空 | organize_data 返回空结构 (空 records/sources), 流程继续; Stage 2 检测无 organized_data → warning 后跳过格式转换 (而非"输出空 Output State") |
| Stage 2 | 无 organized data | warning + 仅更新 current_node, 不产生 formatted_data |
| Stage 3 | LLM 字段描述失败 | try/except → 模板 fallback, `field_descriptions_llm=False`, 不中断流程 |
| Stage 5 | 校验不通过 | 不静默: `execution_status="Failed"` + Stage 6 标记 quarantine (`consumable=false`); 仍构建完整 output_state 保留 partial_output |
| Stage 6 | 文件写入失败 | 无单文件 try/except — 单文件失败直接抛异常, 由主图 Retry/Gate 兜底 (Retry 耗尽 → HumanReview) |
| Graph 层 | Failed (经 finalize 透传) | 主图 Stage Gate → HumanReview, 保留 partial_output (V3.3) |

---

## 12. 工具清单 (6 个)

| Tool | 文件 | 功能 |
|------|------|------|
| DataOrganizer | `tools/export/data_organizer.py` | 过滤临时字段 + Schema 对齐 + 排序 + field_index |
| FormatExporter | `tools/export/format_exporter.py` | JSON/CSV/CSV-Wide/JSON-Wide 多格式 |
| SchemaFormatter | `tools/export/schema_formatter.py` | 列排序 + 单位标准化 + 值格式化 |
| MetadataGenerator | `tools/export/metadata_generator.py` | 字段定义/来源汇总/处理记录 |
| TraceabilityBuilder | `tools/export/traceability_builder.py` | 数据世系/逐条溯源/决策链 |
| OutputValidator | `tools/export/output_validator.py` | 5 维校验 |

---

## 13. 文件清单

```
Data_Export_agentV1/
├── export_graph.py                        # 110 行, 纯编排 (6 Agent + finalize)
├── EXPORT_DESIGN_REPORT.md                # 本报告 (V1.0, V4.2 更新)
└── agents/
    ├── data_organization_agent.py         # Stage 1: 数据组织
    ├── schema_formatting_agent.py         # Stage 2: 多格式导出
    ├── metadata_generation_agent.py       # Stage 3: 元数据生成 (LLM)
    ├── traceability_construction_agent.py # Stage 4: 溯源构建
    ├── output_validation_agent.py         # Stage 5: 输出校验
    └── export_generation_agent.py         # Stage 6: 最终输出 + 文件导出

tools/export/
├── data_organizer.py                      # Tool 1: 数据组织
├── format_exporter.py                     # Tool 2: 多格式导出
├── schema_formatter.py                    # Tool 3: Schema 对齐
├── metadata_generator.py                  # Tool 4: 元数据生成
├── traceability_builder.py                # Tool 5: 溯源构建
└── output_validator.py                    # Tool 6: 5维校验
```
