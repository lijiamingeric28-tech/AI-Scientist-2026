# Assessment SubGraph 设计报告 V3.0

> **版本**: V3.0 — 天文数据多源方差分析 + 异常检测
> **更新 (2026-08-03, V4.2)**: 配置体系完整化 — semantic_types_astrophysics 21→32 键（+catalog_metadata/flux_density/dispersion_measure/rotation_measure/frequency/energy/magnetic_field/pressure/density/angle/wavelength）、entity_types_astrophysics 153 个 Simbad 对象类型、unit_conversions_astrophysics 27 组 231 条、target_schema_astrophysics 28 字段
> **更新 (2026-08-04, V4.3)**: VizieR 目录 schema 扩展 — semantic_types_astrophysics 7 键 units 同步 VizieR 记法（solMass/solRad/solLum/log(cm.s**-2)/Sun/um**-1/pc**-2）、配置文件体系数字更新（aliases 1178 / 单位 34 组 257 条）
> **核心变更**: 从"冲突检测+裁决淘汰"改为"多源方差特征化+异常检测+全量保留标注"。同一天体的多源观测差异不再视为冲突，仅真正的异常（提取错误/单位错误/交叉识别错误）路由到 Conflict。
> **对应文件**: `Data_Assessment_agentV1/assessment_graph.py` + `agents/*.py` + `tools/assessment/*.py`

---

## 0. 变更记录 (V4.3)

> 按版本记录设计演进, 只列与当前实现直接相关的变更。历史设计意图 (V2.0/V2.3/V3.0) 保留在正文相应章节。

### V4.3 (2026-08-04) — VizieR 目录 schema 扩展

- `semantic_types_astrophysics` units 同步 VizieR 目录记法: `stellar_mass`/`surface_gravity`/`metallicity`/`luminosity`/`density`/`wavelength` 7 键 units 加入 VizieR 记法 (`solMass`→stellar_mass 推断, `solRad`, `solLum`, `log(cm.s**-2)`→surface_gravity, `Sun`→metallicity, `um**-1`→wavelength, `pc**-2`/`mas**-2`→density); 推断能力增强 — 数据中 VizieR 原始单位字段可被识别
- 配置文件体系更新: `target_schema_astrophysics` aliases **349 → 1178** (`database_catalog_properties` 919 + 标准字段 259), `unit_conversions_astrophysics` **27 → 34 组, 231 → 257 条** (+7 个 VizieR 记法新组)

### V4.2 (2026-08-03) — 配置体系完整化

- `quality_rules.yaml` 全面扩充并接入 Assessment:
  - `semantic_types_astrophysics`: **21 → 32 键**, 新增 `catalog_metadata`、`flux_density`、`dispersion_measure`、`rotation_measure`、`frequency`、`energy`、`magnetic_field`、`pressure`、`density`、`angle`、`wavelength` (V4 起新增 catalog_metadata, 此前 21 键)
  - `entity_types_astrophysics`: 9 键结构 (version/source/categories/default_entity_type/catalog_inference/field_inference/field_class_inference/types/typical_ranges), `types` 含 **153 个 Simbad 对象类型**, 分 8 大类 (stars/star_sets/ism/galaxies/galaxy_sets/gravitation/spectral/misc), `typical_ranges` 18 条, `default_entity_type=galaxy`
  - 另有 `journal_tiers_astrophysics` (tier1/2/3 共 19 刊 + 评分 1.0/0.85/0.7/0.6)、`domain_weights_astrophysics`、`resolution_weights_astrophysics`、`adaptive_thresholds_astrophysics`、`entity_extraction_astrophysics`、`measurement_methods_astrophysics`
- `schema_mapping.yaml`: `target_schema_astrophysics` **28 字段** (name/aliases/standard_unit/criticality/semantic_type/description), `unit_conversions_astrophysics` **27 组 231 条**
- `configs/__init__.py` 提供领域感知加载: `load_domain_config()` (quality_rules.yaml) / `load_domain_schema_config()` (schema_mapping.yaml) — 先尝试 `{section}_{domain}` 段, 再回退通用段

### V4 修复 (2026-08-03 前, 与 Assessment 相关, 从代码注释核实)

- **语义推断** (`tools/assessment/semantic_type.py`):
  - 单字母关键词 (如 luminosity 的 'L'、stellar_mass 的 'M') 改**整串相等** — 此前子串匹配使 `database_catalog_properties` 被 'L'/'M'/'d'/'t' 误命中, 迭代序第一个 score=1 的类型胜出 → 误判为 luminosity
  - **空串单位不参与匹配** — 此前 redshift 规则 units 含 "" (无量纲), 使所有无单位字段都被 unit 匹配为 redshift; 空单位 = 无信号, 不构成证据
  - **feasible_ranges 强转 float** — PyYAML 6.x 将 `1e10`/`1.0e10` 解析为字符串, 此前科学计数法边界 (如 distance kpc 的 1e7) 触发 TypeError 被上层吞掉, 语义校验形同虚设
- **完整性** (`tools/assessment/completeness.py`): 空串 `field_unit` 也算缺失单位
- **格式检查** (`tools/assessment/format_checker.py`): 字段级数值性标记 — 数值型字段 (存在 ≥1 条数值记录) 中的无前缀非数值串 ('all'/'+40_43' 等) 不再静默通过
- **全局领域兜底** (`configs/__init__.py`): `_global_domain` — ThreadPoolExecutor 工作线程无线程本地 domain 缓存, 并行执行时 `get_research_domain()` 返回 "", 回退全局值避免加载材料规则导致天体物理单位转换全失败
- **State** (`quality_state.py`): `standard_units` 从领域 target_schema 回填 (此前恒为空 → unit_converter 无目标单位, 单位转换全部静默跳过); workflow_history 按 dict 全等去重 (子图 final-state 携带父历史前缀, 整段追加会重复)
- **路由** (`routers.py`): Stage Gate 不再覆写业务 route_decision (此前无条件覆写为 "Success", 抹掉 Normalization 复检发现的冲突 → B→C 死代码); dispatch 清空 route_decision (E→A 后 HumanReview 写入的 "Normalization" 残留不再被 loop_controller 误读为 C→B)

### 历史演进摘要

| 版本 | 变更 |
|------|------|
| V2.0 | Cohen's d 效应量冲突检测 (A2) + 自适应阈值引擎 (A1) + LLM 完整性分析 (A3) |
| V2.2 | 语义类型规则从 quality_rules.yaml 动态加载, 代码零领域强相关 |
| V2.3 | ThreadPoolExecutor 并行 per-source 评估 + LLM 完整性并行; 新增 extraction_quality; 决策层改为 per-source 路由 |
| V3.0 | 多源方差分析替代冲突裁决 (全量保留标注), 4 种异常类型 (extraction/unit/cross_id/statistical), has_conflicts = has_anomalies |
| V3.1 | paper/database 双分支: extraction_quality/source_checker/consistency/provenance 分支检查, MetadataProfiler 联合字段, standard_units 显式入 State |
| V3.2 | cross_id 检测独立化: 组内检测永远 False (组 key 已含 entity_type), 移至 Step 3.5 按 (entity_name, field_name) 独立分组 |
| V3.3 | 子图出口 finalize 节点透传 execution_status (Retry/Failed 冒泡到主图 Stage Gate) |

---

## 1. 架构概览

```
Main Graph
    │
    ▼
AssessmentGraph (4 Stage Nodes + finalize 透传节点)
    │
    ├── Stage 1: ProfilingAgent        (8 Tools, 0 LLM)
    ├── Stage 2: QualityAssessmentAgent (5 Tools × N_sources 并行 + 1 全局方差分析 + 1 LLM × N_missing)
    ├── Stage 3: QualityScoringAgent    (N_sources 次评分, 0 LLM)
    └── Stage 4: DecisionReasoningAgent (per-source 规则引擎, 0 LLM)
    │
    ▼
workflow_state → Dispatch Node (per-source 分发)
report_state.quality → 下游模块 (Normalization / Variance / Export)
```

---

## 2. Stage 1: ProfilingAgent — 数据画像

**职责**: 纯统计观测，绝不评价质量。
**LLM**: 无 | **Tools**: 8 | **文件**: `agents/profiling_agent.py`

### 2.1 Tool 1: DatasetProfiler

```
逻辑:
  1. 统计 records 列表长度 → record_count
  2. 统计 sources 列表长度 → source_count
  3. 提取所有 field_name 去重 → field_count
  4. sources 列表非空 → metadata_exists=True

输出: {record_count, source_count, field_count, metadata_exists}
```

### 2.2 Tool 2: SchemaProfiler

```
逻辑:
  1. 从 records[*].field_name 去重排序 → actual_fields
  2. 从 target_schema.fields[*].name 提取并排序 → expected_fields
  3. 集合差: expected_fields - actual_fields → missing_fields
  4. 集合差: actual_fields - expected_fields → extra_fields
  5. 不做任何判断，只列事实

输出: {expected_fields, actual_fields, missing_fields, extra_fields}
```

### 2.3 Tool 3: FieldProfiler

```
逻辑:
  1. 按 field_name 分组所有 records
  2. 对每组:
     a. 过滤出可解析为数值的值 → numeric_vals (is_numeric/parse_numeric,
        支持字符串数值, 见 tools/_parse_utils.py)
     b. dtype = "numeric" if numeric_vals 非空 else "string"
     c. null_ratio = sum(1 for v if v is None) / count
     d. unique_ratio = len(set(str(v))) / count
     e. sample_values = 前 5 个值
     f. 如有 numeric_vals: min, max, mean (保留 2 位)
  3. 按字段名排序输出

输出: [{field, dtype, count, null_ratio, unique_ratio, sample_values, min?, max?, mean?}]
```

### 2.4 Tool 4: SourceProfiler

```
逻辑:
  1. 遍历 sources[]
  2. 统计 source_type 频次 → source_distribution
  3. 收集 source_types 列表
  4. 提取前 10 个标题 → source_names

输出: {total_sources, source_types, source_distribution, source_names}
```

### 2.5 Tool 5: MetadataProfiler

```
逻辑:
  1. 遍历 sources[]
  2. 联合检查 (V3.1): paper 字段 (doi/title/authors/year/journal/access_path)
     + database 字段 (description/research_methodology/waveband/research_content/
       bibcode/vizier_table_id/reference_paper/observation_facility)
  3. 统计每个字段完整度: "present/total"

输出: {total_sources, metadata_completeness, fields_present}
```

### 2.6 Tool 6: DistributionProfiler

**文件**: `tools/assessment/distribution.py`

```
函数: analyze_distribution(values: list[float])

逻辑:
  1. 排序 → sorted_vals
  2. 分位数 (线性插值): P10, P25, P50, P75, P90, IQR = Q75 - Q25
  3. 标准差: variance = Σ(xi - x̄)² / (n-1), std = sqrt(variance)
  4. Pearson Skewness (偏度): skew > 0 右偏, skew < 0 左偏, skew ≈ 0 对称
  5. Excess Kurtosis (峰度): kurt > 0 厚尾, kurt ≈ 0 正态, kurt < 0 薄尾
  6. Histogram Binning (Sturges' Rule): n_bins = ceil(log₂(n) + 1), min=4
  7. 分布类型分类:
     |skew|<0.3 & |kurt|<0.5  → "normal"
     |skew|≥0.5 & kurt≥1.0   → "skewed_heavy_tailed"
     |skew|≥0.5              → "skewed"
     kurt≥1.0                → "heavy_tailed"
     skew>0.3 & kurt<-0.5    → "bimodal_like"
     其他                     → "other"

输出: {count, mean, median, std, skewness, kurtosis, quantiles, iqr, histogram_bins, distribution_type}
```

### 2.7 Tool 7: SemanticTypeInferrer

**文件**: `tools/assessment/semantic_type.py`

```
函数: infer_semantic_type(field_name, field_unit, field_value)
      infer_all_fields(records) — 按 (entity_type, entity_name, field_name) 去重后逐键推断

逻辑:
  1. 规则来源 (V2.2): 从 quality_rules.yaml 动态加载, 代码零领域强相关。
     当前领域 (astrophysics) 加载 semantic_types_astrophysics 段 — 32 种物理量
     (V4.2: 21 键 + 11 新增键)。每条规则含 5 个字段:
     keywords / units / feasible_ranges / unit_category / expected_in_study。
     领域感知缓存: 按领域 key 缓存, 领域切换时重新加载 (V3.1 fix)。
     32 键 (节选): redshift, luminosity, distance, stellar_mass, stellar_radius,
     effective_temperature, surface_gravity, metallicity, radial_velocity,
     rotational_velocity, proper_motion_ra/dec, parallax, apparent_magnitude,
     absolute_magnitude, extinction, orbital_period, planet_mass, planet_radius,
     age, alpha_abundance, catalog_metadata,
     新增: flux_density, dispersion_measure, rotation_measure, frequency,
     energy, magnetic_field, pressure, density, angle, wavelength

  2. 匹配规则 (逐类型打分, 取最高分):
     关键词命中: field_name.lower() 包含关键词 → score+=1, matched_by="keyword"
       (V4 fix: 单字母关键词如 'L'/'M' 改整串相等, 避免子串误命中)
     单位命中: field_unit 非空串 且 在 units 列表中 → score+=1, matched_by="unit"
       (V4 fix: 空串单位不参与匹配, 避免无单位字段被无量纲类型误判)
     置信度 = 0.5 + score × 0.25: keyword+unit=1.0, 仅其一=0.75

  3. 物理可行性验证:
     if field_value 可解析为数值 AND 规则有 feasible_ranges[unit]:
       if value in [min, max] → physically_plausible=True
       else → physically_plausible=False, out_of_range=True
       (V4 fix: 边界强转 float — PyYAML 6.x 将科学计数法解析为字符串,
       不转换会触发 TypeError 被上层吞掉, 校验形同虚设)
     无规则 → 默认 plausible=True

输出: {semantic_type, confidence, physically_plausible, feasible_range, out_of_range, unit_recognized, matched_by}
```

**领域适配**: 材料科学场景加载通用 `semantic_types` 段 (11 键); 天文场景加载 `semantic_types_astrophysics` (32 键)。领域由 `configs.get_research_domain()` 决定 (V4: 线程本地缺失时回退全局值)。

### 2.8 Tool 8: OutlierDetector

**文件**: `tools/assessment/outlier.py`

```
函数: detect_outliers(values: list[float])

逻辑 — 双策略互补:
  Method A — IQR 法:
    Q1=P25, Q3=P75, IQR=Q3-Q1
    下界=Q1-1.5×IQR, 上界=Q3+1.5×IQR
    value 越界 → IQR_outlier

  Method B — Modified Z-Score (MAD-based):
    median=P50, MAD=median(|xi-median|)
    Mi=0.6745×(xi-median)/MAD
    |Mi|>3.5 → Z_outlier

  Consensus 判定:
    IQR_outlier AND Z_outlier → "definite_outlier"
    IQR_outlier XOR Z_outlier → "suspected_outlier"

输出: {count, outliers, definite_count, suspected_count, outlier_ratio}
```

---

## 3. Stage 2: QualityAssessmentAgent — 质量评估 (V3.0)

**职责**: 每个 source 独立评估, 调用 5 个 per-source 质量 Tool + 1 个全局方差分析 Tool + 自适应引擎。并行处理 (ThreadPoolExecutor)。
**LLM**: LLM 完整性分析 (per missing source) | **文件**: `agents/quality_assessment_agent.py`

### 3.1 处理流程 (V2.3 并行)

```
1. 分组: 按 source_id 分组所有 records (空的 source 也建组)
2. 全局多源方差分析: analyze_multi_source_variance(input_data) — 必须先做, 不能并行 (tool #6)
3. 并行处理所有 sources (ThreadPoolExecutor, max 8 workers):
   for each source_id:
     a. 提取该 source 的 records 和 source 元数据
     b. 调用 5 个 per-source Tool: extraction_quality + completeness
        + consistency + format + source_reliability
     c. 筛选 per-source 异常和方差 (从全局方差结果中过滤, 见 3.10)
     d. 调用 AdaptiveThresholdEngine 计算动态阈值
     e. 构建该 source 的 issues list (anomalies=error, variances=info)
4. 并行 LLM 完整性分析 (per missing source, 同规模线程池)
5. 汇总: quality.sources + quality.multi_source_variance + 统计
```

### 3.2 Tool 1: check_extraction_quality (V2.3 新增, V3.1 支持 database)

**文件**: `tools/assessment/extraction_quality.py`

```
函数: check_extraction_quality(records)

逻辑 (V3.1 paper/database 分支):
  - paper 记录: 检查 trace_id 缺失, provenance.page 缺失, provenance.bbox
    非 4 元素列表, record_id 格式 (期望 "{source_id}_{entity_name}_{field_name}_" 前缀,
    经 '/', '.', 空格 → '_' 归一化后比对, DB 记录跳过)
  - database 记录 (extraction_method="database_query"): 检查 provenance 四要素
    (db_table/key_column/key_value/raw_column), 不检查 trace_id/page/bbox
  - 通用: entity_type/entity_name 缺失, extraction_method 合法性
    (合法值: vlm_pdf/vlm_text/llm_text/llm_table/database/csv_parsing/database_query)

  加权评分 (V3.1: paper 与 database 分别计算, 按记录数加权):
    paper_score = 1.0 - (
      0.15 × (missing_trace_id/n_paper) +
      0.10 × (missing_page/n_paper) +
      0.08 × (missing_bbox/n_paper) +
      0.10 × (bad_extraction_method/total) +
      0.10 × (bad_record_id/n_paper) +
      0.03 × (missing_entity_type/total) +
      0.03 × (missing_entity_name/total)
    )
    db_score = 1.0 - (0.33 × (missing_db_prov/n_db) + 0.10 × (bad_extraction_method/total)
                      + 0.03 × (missing_entity_type/total) + 0.03 × (missing_entity_name/total))
    score = (paper_score × n_paper + db_score × n_db) / total

输出: {score, total_records, n_paper_records, n_database_records,
       missing_trace_id, missing_entity_type, missing_entity_name,
       missing_page, missing_bbox, missing_db_prov,
       bad_extraction_method, bad_record_id,
       trace_id_coverage, entity_coverage, provenance_coverage,
       database_provenance_coverage, extraction_method_distribution,
       per_entity_scores, per_entity_issues, issues, summary}
```

### 3.3 Tool 2: check_completeness

**文件**: `tools/assessment/completeness.py`

```
输入: sub_data (单 source 的 records + sources), target_schema

处理规则 (逐条 record):
  规则 A (外键检查): record.source_id not in source_ids → records_missing_source
  规则 B (单位检查): 数值字段且 field_unit 为空 → records_missing_unit
       (V4 fix: 空串也算缺失, 使用 is_numeric + not field_unit)
  规则 C (溯源检查): provenance_is_complete() 为 False → records_missing_provenance
       (V3.1 分支: paper → page 非 None 且 bbox 为 4 元素列表;
        database → db_table/key_column/key_value/raw_column 均非空)
  规则 D (Schema 覆盖, V2 per-entity): 按 (entity_type, entity_name) 分组,
       每组检查 expected - present → per_entity_missing,
       避免 Entity-A 的字段掩盖 Entity-B 的缺失

评分公式:
  penalty_source = records_missing_source / total_records
  penalty_unit   = records_missing_unit   / total_records
  penalty_prov   = records_missing_provenance / total_records
  score = 1.0 - (0.4 × penalty_source + 0.3 × penalty_unit + 0.3 × penalty_prov)

输出: {score, total_records, records_missing_source, records_missing_unit,
       records_missing_provenance, expected_fields, present_fields,
       missing_expected_fields, field_completeness, by_entity, entity_count,
       per_entity_present, per_entity_missing, summary}
```

### 3.4 Tool 3: check_consistency

**文件**: `tools/assessment/consistency.py`

```
处理规则:
  规则 A — Schema 一致性 (V3.1 paper/database 分支):
    paper 必填: record_id, source_id, field_name, field_value, trace_id, extraction_method
    database 必填: record_id, source_id, field_name, field_value, extraction_method (无 trace_id)
  规则 B — 字段值"形状"一致性: 按 (entity_name, field_name) 分组, 收集形状
    (null / uncertainty / numeric / text, 基于 is_numeric + has_uncertainty)
  规则 C — 单位一致性: 按 (entity_name, field_name) 分组, 收集 field_unit,
    多单位 → "inconsistent: {units}" (V2: per-entity 单位一致性得分)

评分: passed/3 (每个维度通过得1分)

输出: {score, schema_consistency, field_type_consistency, unit_consistency,
       issues, per_entity_type_consistency, per_entity_unit_consistency, summary}
```

### 3.5 Tool 4: check_format

**文件**: `tools/assessment/format_checker.py`

```
处理规则:
  规则 A — record_id 格式: 正则 ^.+_.+_\d+$ (不合规 → record_id_issues)
  规则 B — 数值格式: float 类型检查 NaN/Inf (V1.1: field_value 通常为 string)
  规则 C — 字符串格式:
    - 带前缀 (~ ≈ < > ≤ ≥) 的数值串: parse_numeric 解析主体, 前缀后非数值 → issue
    - 无前缀非数值串: 若该字段存在 ≥1 条数值记录 (字段级数值性, V4 fix),
      'all'/'+40_43' 等垃圾值 → issue (此前静默通过)
  V2: per-entity 问题计数 (per_entity_issues)

评分: score = 1.0 - min(1.0, total_issues / len(records) × 0.5)

输出: {score, record_id_format_issues, numeric_format_issues, string_format_issues,
       total_issues, per_entity_issues, entity_count, summary}
```

### 3.6 Tool 5: check_source_reliability

**文件**: `tools/assessment/source_checker.py`

```
处理规则 (V3.1 按 source_type 分支):

  paper 来源 (6 项检查, 每项满分 1.0, 取平均):
    doi 非空 +1.0; title 长度 > 5 +1.0; authors 非空 +1.0;
    year 在 1500-2100 内 +1.0 (V2.2 放宽范围); journal 非空 +0.5;
    retrieval_priority 归一化 (0-100 范围除以 100, 否则原值) +0~1.0

  database 来源 (8 维评分, V3.1 新增):
    核心字段 description/research_methodology/waveband/research_content:
      长度 > 20 → 1.0, 非空 → 0.5
    title 长度 > 3 → 1.0; vizier_table_id 非空 → 1.0
    reference_paper 非空 → 0.5; bibcode 非空 → 0.5

整体评分: 各来源按 retrieval_priority 加权平均

输出: {score, source_scores, issues, summary}
```

### 3.7 Tool 6: analyze_multi_source_variance (V3.0 核心创新)

**文件**: `tools/assessment/statistical_conflict.py`

**这是 V3.0 最关键的变更**: 替代旧的 `detect_conflicts_statistical()`。

```
函数: analyze_multi_source_variance(data)

逻辑 — 多源方差特征化:

  1. 分组:
     按 (entity_type, entity_name, field_name) 分组 (field_value 需可解析为数值)
     收集每个 source 的数值, 计算 mean/std/n
     提取 measurement_method, condition_tags, year, extraction_confidence, unit
     组内 source 数 < 2 → 跳过 (无方差)

  2. 两两比较 Cohen's d:
     pooled_std = sqrt(((n_a-1)×var_a + (n_b-1)×var_b) / (n_a + n_b - 2))
     cohens_d = |mean_a - mean_b| / pooled_std
     小样本 (n<2): 无法计算组内方差, 回退 |Δmean| / max(|mean|, 0.001)
     判定: <0.2 negligible, 0.2-0.5 small, 0.5-0.8 medium, ≥0.8 large,
           ≥2.0 (D_LARGE, V3.0) 才是异常候选
     同时计算 SE 与 95% CI: ci = d ± 1.96×sqrt((n_a+n_b)/(n_a×n_b) + d²/(2(n_a+n_b)))

  3. 差异原因推断 (利用 V2 Record 字段, 两两比较后取组内多数):
     measurement_method 无重叠/部分重叠 → methodological_variance (0.85 / 0.70)
     condition_tags 无重叠/部分重叠     → condition_variance (0.85 / 0.70)
     year 差距 > 5年                    → temporal_variation (0.75)
     |value_a - value_b| < 1e-10        → duplicate_observation (0.95)
     同方法+同条件+同时间段 + d ≥ 2.0   → statistical_outlier (0.60)
     同方法+同条件+同时间段 + d ≥ 0.8   → measurement_uncertainty (0.65)
     同方法+同条件+同时间段 + d ≥ 0     → measurement_uncertainty (0.80)
     无法判断                           → unknown (0.40)

  4. 异常判定 (V3.0 新增 — 只有真正异常才标记):
     a. statistical_outlier:
        组主因 = statistical_outlier (同方法+同条件 + d ≥ 2.0),
        evidence 记录 same_method/same_conditions/same_unit
     b. extraction_error:
        某 source 平均 extraction_confidence < 0.5 且在其参与的
        pairwise 比较中存在 Cohen's d > 2.0
     c. unit_error:
        同组内各 source 单位维度不匹配 (K vs eV, _UNIT_DIMENSIONS 维度映射),
        severity=critical
     d. cross_id_error (V3.2 fix):
        组内检测永远 False (组 key 已含 entity_type);
        由独立 Step 3.5 按 (entity_name, field_name) 分组 (忽略 entity_type),
        检测"同名实体被标记为多种 entity_type" → 记录 entity_types_found + source_ids,
        severity=critical

  5. 向后兼容:
     detect_conflicts_statistical(data, threshold, use_advanced) 仍可用 —
     内部委托给 analyze_multi_source_variance() (use_advanced=False 时
     回退 tools/assessment/conflict_detector.py 的旧版 detect_conflicts)
     has_conflicts = has_anomalies (只有异常才算冲突)

输出: {
  has_variance: bool,          # 是否存在多源差异
  variance_count: int,
  variances: [{                # 每组差异详情
    entity_type, entity_name, field_name,
    source_ids, source_count,
    source_stats: {sid: {mean, std, n, measurement_methods, condition_tags,
                         year, unit, avg_extraction_confidence, record_ids}},
    value_range: [min, max],
    max_cohens_d, pairwise_comparisons: [{source_a, source_b, mean_a/b, std_a/b,
                         n_a/b, cohens_d, ci_95, absolute_difference,
                         inferred_cause, cause_confidence}],
    inferred_cause: "methodological_variance" | "condition_variance"
                   | "temporal_variation" | "measurement_uncertainty"
                   | "duplicate_observation" | "unknown",
    cause_confidence: 0.0-1.0,
    unit_mismatch_detected, cross_id_risk,   # cross_id_risk 恒 False (V3.2)
  }],
  has_anomalies: bool,         # 是否存在真正异常
  anomaly_count: int,
  anomalies: [{                # 异常详情
    anomaly_type: "extraction_error" | "unit_error" | "cross_id_error"
                | "statistical_outlier",
    record_id(s), source_id, entity_type, entity_name, field_name,
    evidence: {...}, cohens_d, ci_95, extraction_confidence, severity,
  }],
  risk_level: "none" | "low" | "medium" | "high",   # 0 / ≤2 / ≤5 / >5 异常
  method: "multi_source_variance",
  skipped_insufficient, summary: str,
}
```

### 3.8 Engine E1: AdaptiveThresholdEngine

**文件**: `tools/assessment/adaptive_threshold.py`

```
阈值公式:
  threshold = base × sample_factor × domain_factor
  completeness 阈值 clamp 到 [0.30, 0.99], conflict 阈值 clamp 到 [0.05, 0.50]

  1. base (字段关键性, 值来自 quality_rules.yaml adaptive_thresholds.field_criticality):
     completeness (get_completeness_threshold):
       字段名命中 critical_fields 列表 → critical_completeness=0.95
       字段名命中 auxiliary_fields 列表 → auxiliary_completeness=0.70
       field_criticality 参数: "critical"→0.95, "auxiliary"→0.70,
       "important"→0.85 (硬编码), 其他→0.90
     conflict (get_conflict_threshold):
       命中 critical_fields → critical_conflict=0.10, 其他→0.20
       (配置中的 important_conflict=0.15/auxiliary_conflict=0.30 未被代码读取)

  2. sample_factor (config sample_size):
     completeness: n<10→0.85, n>100→1.0, 10≤n≤100→线性插值
     conflict:     n<10→0.85, n>100→1.0, 10≤n≤100→线性插值
     (小样本阈值更低 = 更宽松, 避免小样本误判)

  3. domain_factor (config domain_tightness):
     领域 → tightness 名称 → "{tightness}_multiplier":
       materials_science→precise→0.80, astrophysics→exploratory→1.30,
       chemistry→precise→0.80, biology→normal→1.00, default→normal→1.00
```

### 3.9 Engine E2: LLMCompletenessAnalyzer

**文件**: `tools/assessment/llm_completeness.py`

```
函数: analyze_missing_fields(title, present_fields, missing_fields, year)

逻辑:
  1. LLM 对每个缺失字段分类: expected / optional / irrelevant
  2. 调整 completeness: adjusted = 1.0 - (expected + optional×0.3) / total × 0.5
     (仅 expected 缺失扣分, optional 扣 30%, irrelevant 不扣)
  3. 消费方式 (Stage 3): effective_score = raw_score × adjusted_completeness,
     raw_score 保留为 raw_score 字段, 并标记 llm_adjusted=True
  4. Fallback: LLM 不可用 → adjusted=1.0, 标记"LLM 不可用"

输出: {analysis, adjusted_completeness, expected_count, optional_count, irrelevant_count, summary}
```

### 3.10 异常过滤逻辑

```
_filter_source_anomalies(anomalies, sid):
  对全局异常列表, 筛选涉及指定 source 的异常:
  - statistical_outlier: source_a/source_b 匹配
  - extraction_error: source_id 匹配
  - unit_error: units_found 中有该 sid
  - cross_id_error: 不归属任何特定 source (pass, V3.0 fix:
    不广播到全部 source, 由 Decision Stage 做全局判定 V3.1 fix)
  - 通用 fallback: source_a/source_b/source_id 任一匹配
```

---

## 4. Stage 3: QualityScoringAgent — 评分

**职责**: Per-source 独立评分 + 全局聚合 + 惩罚 + 校准。
**LLM**: 无 | **文件**: `agents/quality_scoring_agent.py`

### 4.1 加权评分 (compute_quality_score)

**文件**: `tools/assessment/quality_scoring.py`

```
公式:
  overall_score = Σ(dimension_score_i × weight_i) / Σ(weight_i)
  overall_score = clamp(0.0, 1.0)

等级判定:
  ≥0.90 → "excellent"
  ≥0.75 → "good"
  ≥0.60 → "fair"
  <0.60 → "poor"
```

### 4.2 领域自适应权重 (S1)

权重来自 `quality_rules.yaml` 的 `domain_weights` 段 (QualityScoringAgent 读取),
领域键不存在时回退 `default`。注意: **权重表中没有 extraction_quality** —
该维度不参与加权总分, 仅在 Stage 4 直接用于路由 (extr_score < 0.3 → HumanReview)。

```
材料科学 (materials_science):
  completeness: 0.30, consistency: 0.30, format: 0.05,
  source_reliability: 0.15, conflict_risk: 0.20

天体物理 (astrophysics):
  completeness: 0.15, consistency: 0.20, format: 0.10,
  source_reliability: 0.30, conflict_risk: 0.25

默认 (default):
  completeness: 0.25, consistency: 0.30, format: 0.10,
  source_reliability: 0.15, conflict_risk: 0.20

其他已注册领域: chemistry (0.25/0.25/0.15/0.15/0.20),
  biology (0.20/0.25/0.15/0.20/0.20)
```

### 4.3 非线性惩罚 (S2)

```
S2-1: Systematic Failure Penalty:
  任何 source 的维度得分=0 → overall_score × 0.7

S2-2: Sparsity Penalty:
  total_records < 10 → sparsity_factor = log(n)/log(10)
  confidence_multiplier = max(0.3, sparsity_factor)
```

### 4.4 置信度校准 (S3)

```
校准公式:
  calibrated_confidence = 0.4 × volume_factor + 0.4 × agreement_factor + 0.2 × sparsity_factor

  volume_factor: n<10→0.3, 10≤n<100→0.7, n≥100→0.9
  agreement_factor: max(0.3, 1.0 - σ×2), 单source→0.5
  sparsity_factor: 来自 S2-2
```

### 4.5 Per-entity 评分追踪 (V2)

```
每个 source 额外记录 per-entity 评分:
  - extraction_quality per entity
  - completeness per entity
  - type_consistency per entity
  - unit_consistency per entity
  - format_issues per entity
```

---

## 5. Stage 4: DecisionReasoningAgent — 决策 (V3.0)

**职责**: Per-source 规则引擎 + 决策矩阵 + 条件路由。
**LLM**: 无 (纯规则引擎, 0 LLM 调用; _DECISION_SYSTEM prompt 已定义未接线) | **文件**: `agents/decision_reasoning_agent.py`

### 5.1 V3.0 路由原则

**核心原则**: 正常多源差异 → Export (全量保留), 只有真正异常 → Conflict。

```
路由决策逻辑 (per-source, 按优先级):

1. extraction_quality.score < 0.3:
   → HumanReview (提取质量极差: trace_id/provenance/extraction_method 大面积缺失)

2. 全局 cross_id_error 涉及该 source (V3.1 fix):
   → HumanReview (跨源异常无法自动裁决)

3. issues_found (别名/缺失期望字段/格式/单位/溯源):
   → Normalization (优先修复格式问题)

4. has_anomaly (真正的异常):
   → Conflict (需要异常分析)

5. has_variance (正常多源差异):
   → Export (全量保留+标注)

6. 全通过:
   → Export

之后用决策矩阵 (Quality × Repair Cost) 升级路由:
  matrix_route 严重度 > base_route → 取 matrix_route (escalation)
```

### 5.2 问题检测清单 (11 项)

| # | 检查项 | 检测方式 | 路由 |
|---|--------|---------|------|
| 1 | 别名字段 | per-source `present_fields - expected_fields` 非空 | → Normalization |
| 2 | 缺失期望字段 (per-entity) | `completeness.per_entity_missing` 任一实体缺失 | → Normalization |
| 3 | 格式问题 | `format.total_issues > 0` | → Normalization |
| 4 | 缺失单位 | `completeness.records_missing_unit > 0` | → Normalization |
| 5 | 缺失溯源 | `completeness.records_missing_provenance > 0` | → Normalization |
| 6 | 单位不一致 | `consistency.unit_consistency` 含 "inconsistent" | → Normalization |
| 7 | 单位不符标准 | 按 (entity_type, entity_name, field_name) 分组, 单位 ≠ target_schema standard_unit (°/℃ 归一化后比对) | → Normalization |
| 8 | 提取质量极差 | `extraction_quality.score < 0.3` | → HumanReview |
| 9 | 全局交叉识别错误 | 全局 `multi_source_variance.anomalies` 含该 source 的 cross_id_error | → HumanReview |
| 10 | 多源异常 | `conflict_risk.has_conflicts` (= has_anomalies) | → Conflict |
| 11 | 多源方差 | `conflict_risk.has_variance` | → Export (保留) |

### 5.3 决策矩阵 (Quality × Repair Cost)

```
                Quality
              excel  good  fair  poor
  Repair ┌──────┬─────┬─────┬──────┐
  Cost   │Export│Export│Norm │Norm  │
  low    ├──────┼─────┼─────┼──────┤
         │Export│Norm │Norm │Conf  │
  medium ├──────┼─────┼─────┼──────┤
         │Norm  │Conf │Conf │Human │
  high   └──────┴─────┴─────┴──────┘

Repair Cost: anomaly≥3 or issues≥10→high, anomaly≥1 or issues≥3→medium, else→low
```

### 5.4 条件路由 (D3)

```
for each source:
  if route == "Normalization":
    conditions += {condition:"missing_units"/"missing_provenance"/"unit_inconsistency"
                   /"format_issues"/"alias_fields"/"general"}
  elif route == "Conflict":
    conditions += {condition:"has_anomaly"}
  elif route == "Export":
    if has_variance: conditions += {condition:"multi_source_variance_annotated"}
    else: conditions += {condition:"clean"}

输出: quality.conditional_routes = [{source_id, primary_route, conditions:[...]}]
```

### 5.5 聚合决策 (Per-source)

V2.3+: 不再聚合为全局 worst_route。改用 per_source_routes + route_counts 统计。
下游 dispatch 节点根据 per_source_routes 分发不同类型到不同 SubGraph。

```
输出 (V2.3 起全部写入 report_state.quality):
  quality.per_source_routes    = {sid: "Normalization"/"Conflict"/"Export"/"HumanReview"}
  quality.per_source_reasons   = {sid: 路由原因说明}
  quality.route_counts         = {"Normalization": N, "Conflict": M, ...}
  quality.decision_matrix      = {sid: {quality_level, repair_cost, matrix_route, rule_route}}
  quality.conditional_routes   = [{source_id, primary_route, conditions: [...]}]  (见 5.4)
  quality.assessment_summary   = "N sources. sid1→Route1, sid2→Route2..."
```

---

## 6. 下游模块接口

### 6.1 路由分流

```
workflow_state → Dispatch Node (graph.py)
  per_source_routes[sid] = "Export"         → Export SubGraph
  per_source_routes[sid] = "Normalization"  → Normalization SubGraph
  per_source_routes[sid] = "Conflict"       → Conflict/Variance SubGraph
  per_source_routes[sid] = "HumanReview"    → Human Review Node
```

### 6.2 各下游模块可读取的 State

```
Normalization:
  quality.sources[sid].issues — 待修复问题
  quality.conditional_routes — 按 condition 修复
  quality.profile.semantic_types — unit 类型指导转换
  quality.profile.schema_summary — Schema Mapping

Variance/Conflict:
  quality.multi_source_variance — V3.0: 方差分析结果
    .variances[*] — 每组差异详情 (inferred_cause, source_stats, value_range)
    .anomalies[*] — 需分析的异常
  quality.sources[sid].conflict_risk — per-source 异常/方差 (has_conflicts/has_variance/
    conflicts/variances/risk_level/method/summary)
  quality.decision_matrix — per-source 决策矩阵记录 (quality_level/repair_cost/matrix_route)

Export:
  quality.profile — 数据集概况
  quality.quality_scoring — 质量评分
  quality.assessment_summary — 评估摘要
  quality.per_source_routes — 路由分布
```

---

## 7. 异常处理矩阵

| 层级 | 异常 | 策略 |
|------|------|------|
| ProfilingAgent | 单个 Tool 异常 | catch → 注册 error → 继续 |
| ProfilingAgent | 1-2 个 Tool 失败 | execution_status = "Retry" |
| ProfilingAgent | ≥3 个 Tool 失败 | execution_status = "Failed" |
| QualityAssessmentAgent | 单 source 评估异常 | 填充降级报告 (score=0.0 + error 字段), 不中断其他 source |
| QualityAssessmentAgent | LLM 完整性失败 | 跳过, 使用 raw completeness (llm_completeness=None) |
| QualityScoringAgent | 规则加载失败 | 使用默认权重 (0.25/0.30/0.10/0.15/0.20) |
| DecisionReasoningAgent | 规则引擎 | 确定性规则, 无 LLM 回退 (0 LLM) |
| Graph 层 | execution_status = "Retry" | finalize 透传 → 主图 Stage Gate 重入 (retry_by_node, 最多 3 次) |
| Graph 层 | execution_status = "Failed" | finalize 透传 → 主图 Stage Gate → HumanReview |

---

## 8. 配置文件体系 (V4.3)

Assessment 的规则全部来自配置文件, 代码零领域强相关 (V2.2 起)。跨领域扩展只需在 yaml 中注册, 无需改代码。

### 8.1 quality_rules.yaml (21 个顶层段)

| 段 | 内容 |
|----|------|
| `semantic_types` | 材料科学语义类型规则, 11 键 (temperature/mechanical_stress/elongation/hardness/strain_rate/density/thermal_conductivity/fatigue_life/fracture_toughness/grain_size/material) |
| `semantic_types_astrophysics` | 天文语义类型规则, **32 键** (V4.2: 21 键 + 新增 catalog_metadata/flux_density/dispersion_measure/rotation_measure/frequency/energy/magnetic_field/pressure/density/angle/wavelength; V4.3: 7 键 units 加入 VizieR 记法 solMass/solRad/solLum/log(cm.s**-2)/Sun/um**-1/pc**-2)。每条规则 5 字段: keywords / units / feasible_ranges / unit_category / expected_in_study |
| `entity_types_astrophysics` | 实体类型知识, 9 键结构 (version/source/categories/default_entity_type/catalog_inference/field_inference/field_class_inference/types/typical_ranges)。`types` 含 **153 个 Simbad 对象类型** (ots 类型代码), 分 **8 大类**: stars/star_sets/ism/galaxies/galaxy_sets/gravitation/spectral/misc; `typical_ranges` **18 条** 典型范围; `default_entity_type=galaxy` |
| `domain_weights` | 评分权重, 5 领域 (materials_science/astrophysics/chemistry/biology/default), 见 4.2 |
| `domain_weights_astrophysics` | 天文专属权重段 (astrophysics 键) |
| `journal_tiers_astrophysics` | 期刊分级: tier1 5 刊 / tier2 7 刊 / tier3 7 刊, 评分 1.0/0.85/0.7/0.6 (unknown 0.6) |
| `adaptive_thresholds` | 阈值引擎参数: enabled / field_criticality (critical/important/auxiliary 三档) / sample_size (small_n=10, large_n=100, 乘子 0.85/1.0) / domain_tightness (materials_science=precise, astrophysics=exploratory, chemistry=precise, biology=normal) |
| `loop_control` | max_iterations=3 / max_retries=3 / max_loop=3 / no_new_conflict_rounds=1 |
| 其他 | quality_scoring (weights+levels 阈值 0.90/0.75/0.60/0.40), missing_value/duplicate/consistency/format/source_reliability/conflict_detection/outlier_detection/nonlinear_penalties, adaptive_thresholds_astrophysics/entity_extraction_astrophysics/measurement_methods_astrophysics/resolution_weights_astrophysics |

### 8.2 schema_mapping.yaml (5 个顶层段)

| 段 | 内容 |
|----|------|
| `target_schema` | 材料科学目标 Schema |
| `target_schema_astrophysics` | 天文目标 Schema, **28 字段**, 每字段: name / aliases / standard_unit / criticality / semantic_type / description; aliases 合计 **1178** (V4.3: `database_catalog_properties` 919 + 标准字段 259) |
| `unit_conversions` | 通用单位转换规则 |
| `unit_conversions_astrophysics` | 天文单位转换规则, **34 组 257 条** (V4.3: 27→34 组 231→257 条, +7 个 VizieR 记法新组) |
| `field_standardization` | 字段标准化规则 |

### 8.3 configs/__init__.py — 领域感知加载

```
load_yaml(filename)                # 读取 configs/ 下 yaml
load_domain_config(section, default_section="")   # quality_rules.yaml
load_domain_schema_config(section) # schema_mapping.yaml
set_research_domain(domain) / get_research_domain()

加载优先级 (领域感知):
  1. "{section}_{domain}" 段 (如 semantic_types_astrophysics)
  2. "{section}" 通用段
  3. default_section (仅 load_domain_config)

领域来源 (V3.0+): 初始状态从 grounded_data.research_domain 推断,
写入 context_state.research_domain (V3.1 fix, 不再依赖线程全局),
同时 set_research_domain() 记录线程本地 + 全局值 (V4 fix:
ThreadPoolExecutor 工作线程无线程本地缓存 → 回退 _global_domain)。
```

---

## 9. 文件清单

```
Data_Assessment_agentV1/
├── assessment_graph.py                   # 88 行, 纯编排 (4 Agent + finalize 透传)
├── ASSESSMENT_DESIGN_REPORT.md           # 本报告 (V4.3)
└── agents/
    ├── profiling_agent.py                # Stage 1: 8 Tools (5 基础 + 3 统计增强)
    ├── quality_assessment_agent.py       # Stage 2: 5 per-source Tools + 全局方差 + E1/E2 (并行)
    ├── quality_scoring_agent.py          # Stage 3: S1 权重 + S2 惩罚 + S3 校准
    └── decision_reasoning_agent.py       # Stage 4: V3.0 异常感知路由 (0 LLM)

tools/assessment/
├── profiling.py              # V1 遗留: data_profiling 概要分析 (当前 agent 内嵌实现)
├── completeness.py           # 完整性评估 (4 规则 + per-entity Schema 覆盖)
├── consistency.py            # 一致性评估 (3 规则, paper/database 分支)
├── format_checker.py         # 格式检查 (record_id 正则 + 数值/字符串格式)
├── source_checker.py         # 来源可信度 (paper 6 项 / database 8 维评分)
├── source_utils.py           # V3.1: source_type 判断 (is_database_record/provenance_is_complete)
├── quality_scoring.py        # 加权评分 + 等级判定
├── conflict_detector.py      # 传统冲突检测 (被 statistical_conflict 替代, use_advanced=False 回退)
├── distribution.py           # 分布分析 (skew/kurt/quantile/IQR/Sturges)
├── outlier.py                # 异常值检测 (IQR + Modified Z-Score 共识)
├── semantic_type.py          # 语义推断 (32 种物理量, 配置驱动 + 可行性校验)
├── adaptive_threshold.py     # 自适应阈值引擎 (3 维动态)
├── statistical_conflict.py   # V3.0: 多源方差分析 + Cohen's d + 4 种异常检测
├── llm_completeness.py       # LLM 完整性分析 (expected/optional/irrelevant)
└── extraction_quality.py     # V2.3: grounded_data 提取质量检查 (paper/database)

共享: tools/_parse_utils.py — is_numeric/parse_numeric/has_uncertainty (所有工具共用)
```

---

## 10. V2 Spec 字段利用

| V2 Record 字段 | 在 Assessment 中的用途 |
|:--|:--|
| `entity_type` + `entity_name` | 分组多源测量值 (方差分析核心维度) + per-entity Schema 覆盖/一致性/格式统计 |
| `field_name` + `field_value` + `field_unit` | 值比较 + 单位一致性检查 + 语义类型推断 |
| `source_id` | 分组 + 外键检查, 关联 source 获取 year/retrieval_priority 等元数据 |
| `measurement_method` | 差异原因分类: methodological_variance |
| `condition_tags` | 差异原因分类: condition_variance |
| `year` (source 级) | 差异原因分类: temporal_variation (差距 > 5 年) |
| `context_snippet` | 未被 Assessment 消费 (保留给下游模块) |
| `extraction_confidence` | 异常检测: 低置信度 (< 0.5) + 统计离群 = extraction_error |
| `provenance` | 溯源完整性检查 (paper: page + bbox 4 元素; database: db_table/key_column/key_value/raw_column 四要素) |
| `trace_id` | 提取质量检查 (仅 paper 记录) |
| `extraction_method` | 决定 paper/database 分支 (database_query) + 方法合法性检查 |

---

## 11. V3.0 与旧版关键差异

| 方面 | V2.1 (旧) | V3.0 (新) |
|------|----------|----------|
| 多源差异 | Cohen's d 冲突检测 → Conflict 路由 | 方差分析 + 原因推断 → Export 路由 |
| 异常检测 | 无 | 4 种异常类型 (extraction/unit/cross_id/statistical) |
| 数据淘汰 | Conflict 裁决后可能丢弃低置信度数据 | 全量保留, 差异标注原因 |
| 路由逻辑 | has_conflicts → Conflict | has_anomaly → Conflict, has_variance → Export |
| 提取质量 | 无独立检查 | extraction_quality (V2.3 新增) |
| 并行化 | 串行 per-source | ThreadPoolExecutor 并行 (V2.3) |
| 实体感知 | 仅 source 维度 | entity_type+entity_name 双维度 (V2) |
