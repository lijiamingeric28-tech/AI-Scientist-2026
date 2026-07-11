# Assessment SubGraph 设计报告 V2.1

> **版本**: V2.1 — 严格路由策略  
> **核心变更**: Export 仅对完美数据开放。任何别名/格式/缺失单位/缺失溯源 → Normalization。  
> **对应文件**: `Data_Assessment_agentV1/assessment_graph.py` + `agents/*.py` + `tools/assessment/*.py`

---

## 1. 架构概览

```
Main Graph
    │
    ▼
AssessmentGraph (4 Stage Nodes)
    │
    ├── Stage 1: ProfilingAgent        (8 Tools, 0 LLM)
    ├── Stage 2: QualityAssessmentAgent (5 Tools × N_sources, 1 LLM × N_missing)
    ├── Stage 3: QualityScoringAgent    (N_sources 次评分, 0 LLM)
    └── Stage 4: DecisionReasoningAgent (LLM × N_sources + 1 LLM 聚合)
    │
    ▼
workflow_state.route_decision  →  Main Graph Router
report_state.quality           →  下游模块 (Normalization / Conflict / Export)
```

---

## 2. Stage 1: ProfilingAgent — 数据画像

**职责**: 纯统计观测，绝不评价质量。  
**LLM**: 无 | **Tools**: 8 | **文件**: `assessment/agents/profiling_agent.py`

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
     a. 过滤出 int/float 类型值 → numeric_vals
     b. dtype = "numeric" if numeric_vals 非空 else "string"
     c. null_ratio = sum(1 for v if v is None) / count
     d. unique_ratio = len(set(str(v))) / count
     e. sample_values = 前 5 个值
     f. 如有 numeric_vals: min, max, mean
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
  2. 检查每个 source 的 doi/title/authors/year/journal/access_path 是否存在
  3. 统计每个字段完整度: "present/total"

输出: {total_sources, metadata_completeness, fields_present}
```

### 2.6 Tool 6: DistributionProfiler (V2.0 P1)

**文件**: `tools/assessment/distribution.py`

```
函数: analyze_distribution(values: list[float])

逻辑:
  1. 排序 → sorted_vals
  
  2. 分位数 (线性插值):
     Q(p) = sorted_vals[lo] × (1-frac) + sorted_vals[hi] × frac
     其中 idx = p × (n-1), lo = floor(idx), hi = lo+1, frac = idx - lo
     计算 P10, P25, P50, P75, P90
     IQR = Q75 - Q25

  3. 标准差:
     variance = Σ(xi - x̄)² / (n-1)
     std = sqrt(variance)

  4. Pearson Skewness (偏度):
     skew = [n / ((n-1)(n-2))] × Σ((xi - x̄)/σ)³
     含义: skew>0 右偏(长尾在右), skew<0 左偏, skew≈0 对称

  5. Excess Kurtosis (峰度):
     kurt = [n(n+1) / ((n-1)(n-2)(n-3))] × Σ((xi - x̄)/σ)⁴
            - 3(n-1)² / ((n-2)(n-3))
     含义: kurt>0 厚尾(有极端值), kurt≈0 正态, kurt<0 薄尾

  6. Histogram Binning (Sturges' Rule):
     n_bins = ceil(log₂(n) + 1), min=4
     bin_width = (max - min) / n_bins
     bins = [min + i × bin_width for i in range(n_bins+1)]

  7. 分布类型分类:
     |skew|<0.3 & |kurt|<0.5  → "normal"
     |skew|≥0.5 & kurt≥1.0   → "skewed_heavy_tailed"
     |skew|≥0.5              → "skewed"
     kurt≥1.0                → "heavy_tailed"
     skew>0.3 & kurt<-0.5    → "bimodal_like"
     其他                     → "other"

输出: {count, mean, median, std, skewness, kurtosis,
       quantiles:{P10,P25,P50,P75,P90}, iqr, histogram_bins,
       distribution_type, summary}

函数: profile_field_distributions(records)
  对所有数值字段调用 analyze_distribution(), 返回 {field_name: result}
```

### 2.7 Tool 7: SemanticTypeInferrer (V2.0 P3)

**文件**: `tools/assessment/semantic_type.py`

```
函数: infer_semantic_type(field_name, field_unit, field_value)

逻辑:
  1. 规则匹配 (10 种物理量, 可扩展):
     - temperature:    keywords=["temp","temperature","T"],
                       units=["°C","C","K","F","℃"]
     - mechanical_stress: keywords=["strength","stress","yield","tensile"],
                       units=["MPa","GPa","psi","ksi"]
     - density:        keywords=["density","rho","ρ"],
                       units=["g/cm^3","g/cm³","kg/m^3"]
     - elongation:     keywords=["elongation","strain","elong","EL"],
                       units=["%","mm/mm"]
     - strain_rate:    keywords=["strain_rate","strain rate","rate"],
                       units=["s^-1","s⁻¹","/s"]
     - hardness:       keywords=["hardness","HV","HRC","HB"],
                       units=["HV","HRC","HB","GPa"]
     - thermal_conductivity: keywords=["thermal_conductivity"],
                       units=["W/mK"]
     - fatigue_life:   keywords=["fatigue","cycles","N_f"],
                       units=["cycles"]
     - fracture_toughness: keywords=["fracture","toughness","K_IC"],
                       units=["MPa√m"]

  2. 匹配规则:
     field_name.lower() 包含关键词 → score+=1, matched_by="keyword"
     field_unit 在 units 列表中 → score+=1, matched_by+="unit"
     
  3. 置信度:
     keyword+unit 命中 → 1.00
     仅 keyword       → 0.75
     仅 unit          → 0.75
     无匹配           → 0.00

  4. 物理可行性验证:
     if field_value 是数值 AND 规则有 feasible_ranges[unit]:
       if value in [min, max] → physically_plausible=True
       else → physically_plausible=False, out_of_range=True

  5. feasible_ranges 示例:
     temperature/°C:   [-273.15, 6000]     (绝对零度到太阳表面)
     mechanical_stress/MPa: [0, 5000]       (已知最强材料 ~4GPa)
     density/(g/cm³):  [0.5, 22.6]         (锂到锇)
     elongation/%:     [0, 100]
     hardness/HV:      [1, 3000]

输出: {semantic_type, confidence, physically_plausible,
       feasible_range, out_of_range, unit_recognized, matched_by}
```

### 2.8 Tool 8: OutlierDetector (V2.0 P2)

**文件**: `tools/assessment/outlier.py`

```
函数: detect_outliers(values: list[float])

逻辑 — 双策略互补:

  Method A — IQR 法:
    1. Q1 = P25, Q3 = P75
    2. IQR = Q3 - Q1
    3. 下界 = Q1 - 1.5 × IQR
    4. 上界 = Q3 + 1.5 × IQR
    5. value < 下界 or value > 上界 → IQR_outlier

  Method B — Modified Z-Score (MAD-based, 适合小样本):
    1. median = P50
    2. abs_devs = [|xi - median|]
    3. MAD = median(abs_devs)
    4. Mi = 0.6745 × (xi - median) / MAD
    5. |Mi| > 3.5 → Z_outlier
    (0.6745 是正态分布下 MAD→σ 的转换因子)

  Consensus 判定:
    IQR_outlier AND Z_outlier → "definite_outlier"
    IQR_outlier XOR Z_outlier → "suspected_outlier"
    都不满足                → 不标记

  前提: n >= 4 (不够计算稳健统计量)

输出: {count, outliers:[{index, value, label, modified_z_score, iqr_bounds}],
       definite_count, suspected_count, outlier_ratio}
```

---

## 3. Stage 2: QualityAssessmentAgent — 质量评估

**职责**: 每个 source 独立评估, 调用 5 个质量 Tool + 自适应引擎。  
**LLM**: A3 完整性分析 (per missing source) | **文件**: `assessment/agents/quality_assessment_agent.py`

### 3.1 处理流程

```
for each source_id:
  1. 提取该 source 的 records 和 source 元数据
  2. 构建 sub_data = {sources: [source], records: [records]}
  3. 调用 5 个 Tool 对 sub_data 评估
  4. 调用 AdaptiveThresholdEngine 计算动态阈值
  5. 调用 LLMCompletenessAnalyzer (如有缺失字段)
  6. 构建该 source 的 issues list
  7. 存储到 quality.sources[source_id]
```

### 3.2 Tool 1: check_completeness

**文件**: `tools/assessment/completeness.py`

```
输入: sub_data (单 source 的 records + sources), target_schema

处理规则 (逐条 record):
  规则 A (外键检查):
    if record.source_id not in source_ids
      → records_missing_source += 1
      
  规则 B (单位检查):
    if isinstance(record.field_value, (int,float))
       AND record.field_unit is None
      → records_missing_unit += 1
    (字符串值如 "~505" 不检查单位, 留给 format_checker)
    
  规则 C (溯源检查):
    if record.provenance is None
       OR record.provenance.page is None
       OR record.provenance.bbox is None
      → records_missing_provenance += 1

  规则 D (Schema 覆盖):
    expected = target_schema.fields[*].name
    actual = records 中出现的 field_name 去重
    missing_expected = expected - actual

评分公式:
  penalty_source = records_missing_source / total_records
  penalty_unit   = records_missing_unit   / total_records
  penalty_prov   = records_missing_provenance / total_records

  score = 1.0 - (0.4 × penalty_source + 0.3 × penalty_unit + 0.3 × penalty_prov)
  score = clamp(0.0, 1.0)

  (注: missing_expected_fields 不参与 score, 仅追加到 issues)

Issue 生成:
  records_missing_source > 0   → "{n} 条记录 source_id 外键无法匹配"
  records_missing_unit > 0     → "{n} 条数值记录的 field_unit 缺失"
  records_missing_provenance > 0 → "{n} 条记录的溯源信息不完整"
  missing_expected_fields 非空 → "目标 Schema 字段缺失: [...]"

输出: {score, total_records, records_missing_source, records_missing_unit,
       records_missing_provenance, expected_fields, present_fields,
       missing_expected_fields, field_completeness, summary}
```

### 3.3 Tool 2: check_consistency

**文件**: `tools/assessment/consistency.py`

```
处理规则:
  规则 A — Schema 一致性:
    检查每条 record 是否包含必填字段:
      required_keys = {record_id, source_id, field_name, field_value,
                       trace_id, extraction_method}
    if 任何 record 缺少任一必填字段:
      schema_consistency.is_consistent = False

  规则 B — 字段类型一致性:
    按 field_name 分组, 收集所有 field_value 的 type
    if len(types) > 1:
      field_type_consistency[field_name] = False
      例: yield_strength 既有 int(450) 又有 str("~505") → False

  规则 C — 单位一致性:
    按 field_name 分组, 收集所有 field_unit
    if len(units) > 1:
      unit_consistency[field_name] = "inconsistent: {MPa, GPa}"

评分:
  passed = 0
  if schema_consistency: passed += 1
  if all(field_type_consistency): passed += 1
  if all(unit_consistency != "inconsistent"): passed += 1
  score = passed / 3

输出: {score, schema_consistency, field_type_consistency, unit_consistency, issues, summary}
```

### 3.4 Tool 3: check_format

**文件**: `tools/assessment/format_checker.py`

```
处理规则:
  规则 A — record_id 格式:
    期望格式: {source_id}_{field_name}_{n}
    if not re.match(r'.+_.+_\d+$', record_id): → issue

  规则 B — 数值格式:
    if isinstance(value, str):
      if value contains NaN/Inf → issue
      stripped = lstrip("~≈<>≤≥")
      if stripped 不可转为 float → issue

  规则 C — 字符串格式:
    无额外检查 (V1)

评分:
  total_issues = count of all format issues
  score = 1.0 if total_issues == 0 else 0.9 if total_issues <= 2 else 0.7

输出: {score, record_id_issues, numeric_issues, string_issues, total_issues, summary}
```

### 3.5 Tool 4: check_source_reliability

**文件**: `tools/assessment/source_checker.py`

```
处理规则:
  对每个 source:
    score_i = 0.0
    if doi exists:    score_i += 0.2
    if title exists:  score_i += 0.2
    if authors list 非空: score_i += 0.15
    if year exists:   score_i += 0.15
    if journal exists: score_i += 0.15
    if retrieval_priority exists: score_i += 0.15
    source_scores[source_id] = min(1.0, score_i)

  overall_score = mean(source_scores)

输出: {score, source_scores, issues, summary}
```

### 3.6 Tool 5: Statistical Conflict Detector (V2.0 A2)

**文件**: `tools/assessment/statistical_conflict.py`

```
函数: detect_conflicts_statistical(data, threshold, use_advanced=True)

逻辑 — Cohen's d 效应量:

  1. 分组:
     按 (field_name, source_id) 分组, 收集数值列表
     例: {"yield_strength": {"doi_A": [450,460,440], "doi_B": [500,510,490]}}

  2. 两两比较:
     for each (source_a, source_b) pair:
       n_a, n_b = len(vals_a), len(vals_b)
       if n_a < 2 or n_b < 2: skip (不够计算标准差)

       mean_a = sum(vals_a) / n_a
       mean_b = sum(vals_b) / n_b

       var_a = Σ(xi - mean_a)² / (n_a - 1)
       var_b = Σ(xi - mean_b)² / (n_b - 1)

       pooled_std = sqrt(((n_a-1)×var_a + (n_b-1)×var_b) / (n_a + n_b - 2))

       cohens_d = |mean_a - mean_b| / pooled_std

  3. 效应量判定:
       |d| < 0.2  → "negligible"  (不报冲突)
       0.2 ≤ |d| < 0.5 → "small" (可能只是测量误差, 不报)
       0.5 ≤ |d| < 0.8 → "medium" (确实存在差异, 报冲突)
       |d| ≥ 0.8 → "large" (严重冲突)

  4. 置信区间:
       SE = sqrt((n_a+n_b)/(n_a×n_b) + d²/(2×(n_a+n_b)))
       CI = [d - 1.96×SE, d + 1.96×SE]
       if CI_low < 0.5 AND effect was "medium"/"large":
         → 降级为 "not significant", 不报冲突

  5. 与传统方法比较:
     旧: |450-500|/500=10% < 20% → NOT conflict (漏报!)
     新: |450-500|/10=5.0 → LARGE conflict (正确检测)
     因为组内方差小(std=10), 50的差异在统计上极显著

输出: {has_conflicts, conflict_count, conflicts:[{cohens_d, effect_size, ci_95,
       mean_a, mean_b, std_a, std_b, n_a, n_b, pooled_std}],
       risk_level, method:"cohens_d"}
```

### 3.7 Engine E1: AdaptiveThresholdEngine (V2.0 A1)

**文件**: `tools/assessment/adaptive_threshold.py`

```
阈值公式:
  threshold = base × criticality_factor × sample_factor × domain_factor

  1. base (字段关键性):
     关键字段 (yield_strength, tensile_strength, temperature, density, hardness):
       completeness_threshold = 0.95
       conflict_threshold = 0.10
     辅助字段 (journal, authors, access_path, retrieval_priority, doi):
       completeness_threshold = 0.70
       conflict_threshold = 0.30
     默认:
       completeness_threshold = 0.90
       conflict_threshold = 0.20

  2. sample_factor (样本量):
     n < 10   → 0.85  (小样本放宽, 统计不显著)
     10 ≤ n ≤ 100 → 线性插值: 0.85 + (1.0-0.85)×(n-10)/(100-10)
     n > 100  → 1.0   (大样本标准化)

  3. domain_factor (领域):
     materials_science → 0.80 (精确科学, 严格)
     astrophysics      → 1.30 (探索科学, 宽松)
     default           → 1.00

  4. clamp:
     completeness_threshold = clamp(0.30, 0.99)
     conflict_threshold     = clamp(0.05, 0.50)

  示例:
     材料科学, yield_strength, n=5:
       threshold = 0.95 × 0.85 × 0.80 = 0.646
       → comp score 需要 >0.646 才通过
     材料科学, yield_strength, n=50:
       threshold = 0.95 × 0.91 × 0.80 = 0.692
     天体物理, 辅助字段, n=5:
       threshold = 0.70 × 0.85 × 1.30 = 0.774
```

### 3.8 Engine E2: LLMCompletenessAnalyzer (V2.0 A3)

**文件**: `tools/assessment/llm_completeness.py`

```
函数: analyze_missing_fields(title, present_fields, missing_fields, year)

逻辑:
  1. LLM Prompt:
     "Paper: '{title}' ({year})
      Extracted fields: {present_fields}
      Missing fields: {missing_fields}
      For each missing field, classify: expected / optional / irrelevant.
      {
        'analysis': {
          'field_name': {'status': 'expected|optional|irrelevant', 'reason': '...'},
          ...
        },
        'summary': '...'
      }"

  2. LLM 分类规则 (隐含在 prompt 中):
     - expected:  该研究领域通常应包含此数据, 缺失 = 不完整
     - optional:  可能包含但不一定, 缺失 = 可理解
     - irrelevant: 该研究不太可能包含此数据, 缺失 = 正常

  3. Adjust Completeness:
     expected_count  = sum(status == 'expected')
     optional_count  = sum(status == 'optional')
     total           = len(missing_fields)
     
     adjusted = 1.0 - (expected_count + optional_count×0.3) / total × 0.5
     (expected 缺失全扣, optional 缺失扣 30%, irrelevant 不扣)

  4. Fallback:
     LLM 不可用时 → adjusted_completeness=1.0, 标记 "LLM 不可用"

输出: {analysis, adjusted_completeness, expected_count,
       optional_count, irrelevant_count, summary}
```

---

## 4. Stage 3: QualityScoringAgent — 评分

**职责**: Per-source 独立评分 + 全局聚合 + 惩罚 + 校准。  
**LLM**: 无 | **文件**: `assessment/agents/quality_scoring_agent.py`

### 4.1 加权评分 (compute_quality_score)

**文件**: `tools/assessment/quality_scoring.py`

```
输入: metrics = {completeness:{score}, consistency:{score}, format:{score},
                source_reliability:{score}, conflict_risk:{score}}
      weights = {completeness:w1, consistency:w2, ...}

公式:
  overall_score = Σ(dimension_score_i × weight_i) / Σ(weight_i)
  overall_score = clamp(0.0, 1.0)

等级判定:
  ≥0.90 → "excellent"
  ≥0.75 → "good"
  ≥0.60 → "fair"
  <0.60 → "poor"

置信度 (未校准):
  confidence = 1.0 - std(dimension_scores)  (标准差越小越自信)
```

### 4.2 领域自适应权重 (V2.0 S1)

```
配置 (quality_rules.yaml → domain_weights):
  materials_science:
    completeness: 0.30, consistency: 0.30, format: 0.05,
    source_reliability: 0.15, conflict_risk: 0.20
  astrophysics:
    completeness: 0.15, consistency: 0.20, format: 0.10,
    source_reliability: 0.30, conflict_risk: 0.25
  default:
    completeness: 0.25, consistency: 0.30, format: 0.10,
    source_reliability: 0.15, conflict_risk: 0.20

逻辑:
  1. 读取 context_state.research_domain
  2. 查找 domain_weights[domain]
  3. 找不到 → domain_weights['default']
  4. 找不到 → quality_scoring.weights (旧配置)
```

### 4.3 非线性惩罚 (V2.0 S2)

```
S2-1: Systematic Failure Penalty (系统性失败):
  遍历所有 source 的所有维度,
  if any dimension_score == 0.0:
    overall_score *= 0.7
    penalty_reason = "Systematic failure in {source_id}"
  含义: 某个维度全部 record 都失败 → 整体不可信, 强制降分

S2-2: Sparsity Penalty (稀疏性):
  total_records = sum(source.record_count)
  if total_records < 10:
    sparsity_factor = log(total_records) / log(10)
    例: 5 records → log(5)/log(10) = 0.699
    confidence_multiplier = max(0.3, sparsity_factor)
  含义: 样本太少 → 降低置信度 (不降低评分, 因为数据本身可能正确)
```

### 4.4 置信度校准 (V2.0 S3)

```
校准公式:
  calibrated_confidence = 0.4 × volume_factor
                        + 0.4 × agreement_factor
                        + 0.2 × sparsity_factor

  volume_factor (数据量):
    total_records < 10  → 0.3
    10 ≤ n < 100        → 0.7
    n ≥ 100             → 0.9

  agreement_factor (per-source 评分一致性):
    if len(source_scores) ≥ 2:
      σ = stdev(source_scores)
      agreement_factor = max(0.3, 1.0 - σ × 2)
      例: 评分 [0.95, 0.94, 0.96] → σ=0.01 → agreement=0.98
      例: 评分 [0.99, 0.50, 0.80] → σ=0.25 → agreement=0.50
    else:
      agreement_factor = 0.5 (单 source, 无法评估一致性)

  sparsity_factor (来自 S2-2):
    直接使用 S2-2 计算的 sparsity_factor
```

---

## 5. Stage 4: DecisionReasoningAgent — 决策

**职责**: Per-source LLM 决策 + 聚合 + 决策矩阵 + 条件路由。  
**LLM**: D1 (per-source) + 聚合摘要 | **文件**: `assessment/agents/decision_reasoning_agent.py`

### 5.1 Strict Route Decision (V2.1)

**核心原则**: Export 仅对完美数据开放。任何可修复问题 → Normalization。

```
严格 Export 条件 (全部必须满足):
  1. field_name 为标准名 (无 YS/UTS/EL/σ_y 等别名)
  2. 所有数值字段都有 field_unit
  3. 所有数值值为干净数字 (无 ~ ≈ approx 前缀)
  4. 所有记录有完整 provenance (page + bbox)
  5. 无跨来源冲突
  6. completeness=1.0, consistency=1.0, format=1.0

违反任意一条 → Normalization
有冲突 → Conflict
质量等级=poor → HumanReview
全部满足 → Export
```

**问题检测清单**:

| 检查项 | 检测方式 | 判定 |
|--------|---------|------|
| 别名字段 | per-source `present_fields - expected_fields` 非空 | → Normalization |
| 格式问题 | `format.total_issues > 0` | → Normalization |
| 缺失单位 | `completeness.records_missing_unit > 0` | → Normalization |
| 缺失溯源 | `completeness.records_missing_provenance > 0` | → Normalization |
| 跨来源冲突 | `conflict_risk.has_conflicts` | → Conflict |
| 完整性不完美 | `completeness.score < 1.0` | → Normalization |

### 5.2 实现: 确定性规则引擎 (V2.1 默认)

V2.1 主路径是确定性规则引擎 (见 5.1)。LLM 仅用于生成聚合摘要。规则引擎在 per-source 循环内直接运行:

```python
for each source:
    # 1. 收集 per-source 问题
    aliases = set(actual_fields) - set(expected_fields)
    missing_units = completeness.records_missing_unit
    missing_prov = completeness.records_missing_provenance
    has_conflict = conflict_risk.has_conflicts
    comp_imperfect = completeness.score < 1.0

    # 2. 判断
    if has_conflict:     → Conflict
    elif any(issues):    → Normalization
    elif quality==poor:  → HumanReview
    else:                → Export  (全部检查通过)
```

### 5.3 决策矩阵 (V2.0 D2)

```
二维决策: Quality (4级) × Repair Cost (3级)

Repair Cost 估算:
  issues≥10 or conflicts≥3 → "high"
  issues≥3 or conflicts≥1  → "medium"
  否则                      → "low"

矩阵:
                Quality
              excel  good  fair  poor
  Repair ┌──────┬─────┬─────┬──────┐
  Cost   │Export│Export│Norm │Norm  │
  low    ├──────┼─────┼─────┼──────┤
         │Export│Norm │Norm │Conf  │
  medium ├──────┼─────┼─────┼──────┤
         │Norm  │Conf │Conf │Human │
  high   └──────┴─────┴─────┴──────┘

输出: quality.decision_matrix = {
    source_id: {quality_level, repair_cost, matrix_route, rule_route}
}
```

### 5.4 条件路由 (V2.0 D3)

```
逻辑:
  for each source:
    conditions = []

    if route == "Normalization":
      if completeness < 0.9:
        conditions += {condition:"completeness_low",
                       route:"Normalization",
                       reason:"需补充缺失数据或修复溯源信息"}
      if format_issues > 0:
        conditions += {condition:"format_issues",
                       route:"Normalization",
                       reason:"需标准化字段格式"}
      if not conditions:
        conditions += {condition:"general",
                       route:"Normalization",
                       reason:"需字段映射和单位转换"}

    elif route == "Conflict":
      conditions += {condition:"has_conflict",
                     route:"Conflict",
                     reason:"存在{n}个跨来源冲突"}

    elif route == "Export":
      conditions += {condition:"clean",
                     route:"Export",
                     reason:"数据可直接使用"}

    conditional_routes += {source_id, primary_route, conditions}

输出: quality.conditional_routes = [{source_id, primary_route, conditions:[...]}]
```

### 5.5 聚合决策

```
Per-source 路由 → 全局路由:
  _ROUTE_SEVERITY = {"Export": 0, "Normalization": 1, "Conflict": 2, "HumanReview": 3}

  遍历所有 per-source routes:
    if severity[current_route] > severity[worst_route]:
      worst_route = current_route

  例: [Export, Export, Normalization] → overall = Normalization
  例: [Export, Conflict, Export]       → overall = Conflict

LLM 聚合摘要:
  Prompt: "{n} sources assessed. Routes: {summary}. Overall: {worst_route}.
           Generate 1-2 sentence assessment summary."
  
  最终写入 workflow_state.route_decision = worst_route
```

---

## 6. 下游模块接口

### 6.1 路由分流

```
workflow_state.route_decision  →  Main Graph Router
  "Export"         → ExportGraph
  "Normalization"  → NormalizationGraph
  "Conflict"       → ConflictGraph
  "HumanReview"    → HumanReview Node
```

### 6.2 各下游模块可读取的 State

```
NormalizationGraph:
  report_state.quality.sources[sid].completeness     → 缺失信息
  report_state.quality.sources[sid].issues           → 待修复问题
  report_state.quality.sources[sid].route_decision   → per-source 路由
  report_state.quality.conditional_routes[*]         → 按 condition 修复
  report_state.quality.profile.semantic_types        → unit 类型指导转换
  report_state.quality.profile.schema_summary        → Schema Mapping
  data_state.current_data                             → 操作数据

ConflictGraph:
  report_state.quality.sources[sid].conflict_risk    → 冲突详情
    .conflicts[*].source_a / source_b                → 冲突双方
    .conflicts[*].cohens_d / effect_size / ci_95     → 效应量
  report_state.quality.decision_matrix                → 决策参考
  data_state.current_data                             → 冲突数据

ExportGraph:
  report_state.quality.profile                        → 数据集概况
  report_state.quality.quality_scoring                → 质量评分
  report_state.quality.assessment_summary             → LLM 摘要
  report_state.quality.decision_reasoning             → 决策理由
  report_state.quality.per_source_routes              → 区分 Export/其他
  report_state.quality.sources[sid].quality_scoring   → per-source 评分
  workflow_state.llm_call_count / tool_call_count     → 统计
  data_state.current_data                             → 导出数据
```

### 6.3 条件路由使用示例

```python
# Normalization 按条件只处理需要的 sources
for cr in quality["conditional_routes"]:
    if cr["primary_route"] == "Normalization":
        for cond in cr["conditions"]:
            if cond["condition"] == "completeness_low":
                handle_missing_data(cr["source_id"])
            elif cond["condition"] == "format_issues":
                standardize_format(cr["source_id"])
```

---

## 7. 异常处理矩阵

| 层级 | 异常 | 策略 |
|------|------|------|
| ProfilingAgent | 单个 Tool 异常 | catch → 注册 error → 继续下一个 Tool |
| ProfilingAgent | ≥3 个 Tool 失败 | execution_status = "Failed" |
| QualityAssessmentAgent | Tool 异常 | Tool 内部有 fallback, 不抛出 |
| QualityAssessmentAgent | A3 LLM 失败 | 跳过 LLM 完整性, 使用 raw completeness |
| QualityScoringAgent | 规则加载失败 | 使用 compute_quality_score 默认权重 |
| DecisionReasoningAgent | D1 LLM 失败 | 回退 A1 自适应规则引擎 |
| DecisionReasoningAgent | D1 LLM 置信度 < 0.5 | 降级 route = "HumanReview" |
| Graph 层 | execution_status = "Retry" | Router 重入当前 SubGraph (最多 3 次) |
| Graph 层 | execution_status = "Failed" | Router → HumanReview |

---

## 8. 文件清单

```
pipeline/quality/
├── assessment_graph.py                          # 74 行, 纯编排
└── assessment/
    ├── ASSESSMENT_DESIGN_REPORT.md              # 本报告
    ├── OPTIMIZATION_ROADMAP.md                  
    └── agents/
        ├── profiling_agent.py                   # Stage 1: 8 Tools
        ├── quality_assessment_agent.py          # Stage 2: 5 Tools + A1+A2+A3
        ├── quality_scoring_agent.py             # Stage 3: S1+S2+S3
        └── decision_reasoning_agent.py          # Stage 4: D1+D2+D3

tools/assessment/
├── profiling.py              # FieldProfiler 基础统计
├── completeness.py           # 完整性评估 (4规则 + 评分公式)
├── consistency.py            # 一致性评估 (3规则)
├── format_checker.py         # 格式检查 (2规则)
├── source_checker.py         # 来源可信度 (6维评分)
├── quality_scoring.py        # 加权评分 + 等级判定
├── conflict_detector.py      # 传统冲突检测 (相对差异)
├── distribution.py           # V2.0 P1: 分布分析 (skew/kurt/quantile/IQR)
├── outlier.py                # V2.0 P2: 异常值检测 (IQR + Z-Score)
├── semantic_type.py          # V2.0 P3: 语义推断 (10种物理量)
├── adaptive_threshold.py     # V2.0 A1: 自适应阈值 (3维动态)
├── statistical_conflict.py   # V2.0 A2: Cohen's d 冲突检测
└── llm_completeness.py       # V2.0 A3: LLM 完整性分析
```

---

## 9. 配置体系设计 (V2.1)

### 9.1 配置分层

```
configs/
├── quality_rules.yaml      # 质量规则: 阈值/权重/语义类型/异常检测/惩罚
├── schema_mapping.yaml     # Schema 定义: 字段/别名/单位转换/标准化规则
└── llm_config.yaml         # LLM 配置: model/api_key/base_url
```

### 9.2 quality_rules.yaml 结构

| 配置段 | 用途 | 条目数 |
|--------|------|--------|
| `missing_value` | 缺失值策略 (mark/drop/fill) | 2 |
| `duplicate` | 去重规则 | 3 |
| `consistency` | Schema/Type/Unit 检查开关 | 3 |
| `format` | 格式校验规则 + 前后缀列表 | 5 |
| `source_reliability` | 期刊分级 (tier1/2/3, 16种期刊) + recency 退化 | 7 |
| `conflict_detection` | 传统阈值 + Cohen's d 统计参数 | 6 |
| `quality_scoring` | 评分权重 + 等级阈值 | 8 |
| `adaptive_thresholds` | 三维自适应: critical/important/auxiliary 三档 + 5领域紧密度 | 15+ |
| `domain_weights` | 5领域权重 (材料/天文/化学/生物/默认) | 25 |
| `semantic_types` | 11 种物理量完整规则 (keywords + units + feasible_ranges + expected_in_study) | 60+ |
| `outlier_detection` | IQR/Z-Score 参数 + per-field 阈值 | 6+ |
| `nonlinear_penalties` | 系统性失败/集中度/稀疏性惩罚参数 | 6 |

### 9.3 schema_mapping.yaml 结构

| 配置段 | 用途 | 条目数 |
|--------|------|--------|
| `target_schema.fields` | 13 个材料科学标准字段, 含 aliases + criticality | 13 |
| `unit_conversions` | 8 类单位转换规则 (strength/hardness/temperature/percentage/density/strain_rate/fracture_toughness/modulus) | 40+ |
| `field_standardization` | 数值清洗前后缀 + 字符串标准化规则 | 6 |

### 9.4 领域可扩展性

添加新领域只需在 3 个配置文件中注册, **无需改代码**:

```
# 例: 添加"天体物理"领域
quality_rules.yaml:
  domain_weights.astrophysics          ← 权重定义
  adaptive_thresholds.domain_tightness ← 紧密度: "exploratory"
  semantic_types.redshift              ← 物理量: keywords + feasible_ranges
  semantic_types.luminosity            ← 同上
  semantic_types.parallax              ← 同上

schema_mapping.yaml:
  target_schema.fields:
    - name: "redshift"
      aliases: ["z", "spectroscopic_redshift"]
      standard_unit: null
    - name: "luminosity"
      aliases: ["L", "bolometric_luminosity"]
      standard_unit: "erg/s"
      ...
  unit_conversions.astronomy:          ← 新领域转换规则
    ...

llm_config.yaml:
  (无需改动)
```

### 9.5 材料科学配置完整度

| 维度 | 覆盖 |
|------|------|
| 标准字段 | 13 个 (yield/tensile/elongation/hardness/temperature/strain_rate/density/thermal_conductivity/fatigue_life/fracture_toughness/grain_size/elastic_modulus/material) |
| 别名 | 79 个 (如 yield_strength 有 8 个别名: YS/σ_y/σy/Rp0.2...) |
| 单位转换 | 8 类 40+ 条规则 (含 offset 转换: K↔°C, °F↔°C) |
| 物理可行性范围 | 11 种物理量 (0K~6273K, 0~5000MPa, 0.5~22.6g/cm³...) |
| 期刊分级 | 16 种期刊 3 tier |
| 异常值检测 | 全局参数 + temperature/elongation/strain_rate per-field 阈值 |
| 自适应阈值 | critical/important/auxiliary 三档 × 样本量 × 领域紧密度 |
| 领域权重 | 5 套 (材料/天文/化学/生物/默认) |
| 惩罚参数 | 系统性失败×0.7 + 集中度 + 稀疏性 |
