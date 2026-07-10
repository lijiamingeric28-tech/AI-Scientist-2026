# Assessment SubGraph — 优化路线图

> 版本: V2.0 Roadmap  
> 当前版本: V1.2 (Per-Source Assessment)  
> 目标: 从硬编码规则引擎升级为 LLM 增强的自适应评估系统

---

## 1. 现状诊断

### 1.1 四个 Agent 的能力缺口

| Agent | 当前方法 | 主要问题 |
|-------|---------|---------|
| ProfilingAgent | 5 个纯统计 Tool | 只做 count/min/max/mean，不检测异常值、不推断语义类型 |
| QualityAssessmentAgent | 5 个固定规则 Tool | 阈值硬编码 (completeness<0.9 → issue)，不理解领域语义 |
| QualityScoringAgent | 固定权重线性加权 | 不考虑领域差异，对所有科学领域用同一套权重 |
| DecisionReasoningAgent | if-else 规则引擎 + LLM 摘要 | LLM 只写摘要不参与决策，规则阈值不可自适应 |

### 1.2 四个核心瓶颈

```
瓶颈 1: 阈值硬编码
  completeness < 0.9 → "需要规范化"
  问题: 天体物理数据的 completeness 60% 即优秀，材料科学 95% 才算合格

瓶颈 2: 缺乏语义理解
  "density = 2.7"  → 不知道单位是 g/cm³ 还是 kg/m³
  "temperature = 300" → 不知道是 K 还是 °C
  无法判断数值是否在物理可行范围内

瓶颈 3: 静态决策
  固定优先级: Conflict > Normalization > Export
  无法处理: "3% 记录有冲突但其余完美 → 可 Export with warnings"

瓶颈 4: 无自适应
  10 条记录 vs 10000 条记录，使用完全相同的阈值
  小样本时 statistical significance 不足，应有更宽松的阈值
```

---

## 2. 优化总览

```
                    V1.2 (当前)          →        V2.0 (目标)
                    
ProfilingAgent         纯统计                  LLM 增强统计 + 异常检测 + 语义推断
QualityAssessmentAgent  5 固定规则 Tool         规则基座 + LLM 覆写 + 领域适配
QualityScoringAgent      固定权重加权             领域自适应权重 + 置信度校准
DecisionReasoningAgent   if-else + LLM 摘要       LLM 多维推理 + 结构化决策 + 可解释
```

---

## 3. ProfilingAgent 优化 (5 项)

### 3.1 优化 P1: 分布分析替代简单统计

**当前问题**:
```
当前: {min: 100, max: 800, mean: 420}
只能回答"范围是多少"，无法回答"是正态分布还是双峰分布？"
```

**优化方案**:
```python
# profiling_agent.py 新增 Tool: DistributionProfiler

class DistributionProfiler:
    """统计分析工具：不只 min/max/mean，还分析分布形态。

    Algorithm:
      1. Histogram binning (Sturges' rule: k = ceil(log2(n) + 1))
      2. Skewness (Pearson's moment coefficient):
         skew = (n / ((n-1)(n-2))) * Σ((xi - x̄)³) / s³
         - skew > 0: 右偏 (多数值偏低, 少数极高)
         - skew < 0: 左偏
         - skew ≈ 0: 对称
      3. Kurtosis (excess):
         kurt = (n(n+1)/((n-1)(n-2)(n-3))) * Σ((xi - x̄)⁴) / s⁴ - 3(n-1)²/((n-2)(n-3))
         - kurt > 0: 厚尾 (有极端值)
         - kurt ≈ 0: 正态
         - kurt < 0: 薄尾
      4. Quantile summary: P10, P25, P50, P75, P90
      5. IQR = Q3 - Q1

    Output:
      {
        "field": "yield_strength",
        "distribution": {
          "skewness": 0.35,          # 轻微右偏
          "kurtosis": -0.12,         # 接近正态
          "quantiles": {P10: 120, P25: 250, P50: 420, P75: 580, P90: 720},
          "iqr": 330,
          "histogram_bins": [0, 100, 200, 300, ...],
          "distribution_type": "unimodal"   # unimodal / bimodal / uniform / skewed
        }
      }

    Uses:
      - AssessmentAgent: 用 IQR 替代固定阈值做异常检测
      - DecisionAgent: 分布形态影响路由 (双峰 → 可能有混合样本 → HumanReview)
    """
```

### 3.2 优化 P2: 异常值检测

**当前问题**: 没有异常值检测，极端值会拉偏 mean 但不被标记。

**优化方案**:
```python
# profiling_agent.py 新增 Tool: OutlierDetector

class OutlierDetector:
    """异常值检测工具。

    Algorithm (双策略，互补):
      
      Method A — IQR 法 (稳健, 不受极端值影响):
        1. Q1 = P25, Q3 = P75, IQR = Q3 - Q1
        2. 下界 = Q1 - 1.5 * IQR
        3. 上界 = Q3 + 1.5 * IQR
        4. 低于下界或高于上界 → outlier
        
      Method B — Modified Z-Score (适合小样本):
        1. MAD = median(|xi - median(x)|)
        2. Mi = 0.6745 * (xi - median(x)) / MAD
        3. |Mi| > 3.5 → outlier

      Consensus:
        - 两种方法都判定为 outlier → "definite_outlier"
        - 一种判定 → "suspected_outlier"
        - 都未判定 → "normal"

    Output:
      {
        "field": "yield_strength",
        "outliers": {
          "count": 2,
          "records": [
            {"record_id": "doi_A_yield_5", "value": 1200, "z_score": 4.2, "label": "definite_outlier"}
          ],
          "outlier_ratio": 0.04
        }
      }

    Uses:
      - AssessmentAgent: outlier_ratio > 10% → issue (可能的数据录入错误)
      - DecisionAgent: 大量 outlier → 建议 HumanReview
    """
```

### 3.3 优化 P3: 语义类型推断

**当前问题**: 不知道 temperature=300 是 °C 还是 K，无法做物理合理性检查。

**优化方案**:
```python
# profiling_agent.py 新增 Tool: SemanticTypeInferrer

class SemanticTypeInferrer:
    """语义类型推断工具。

    不依赖 LLM 的规则版本 (V2.0), LLM 增强版 (V3.0).

    Algorithm — Rule-based (V2.0):
      
      Step 1: 从 field_name + field_unit 推断物理量类型
      
      Rules Table (可扩展):
        field_name contains "temp"  + unit in {"°C","C","K","F"} → "temperature"
        field_name contains "strength" + unit in {"MPa","GPa","psi"} → "mechanical_stress"
        field_name contains "density" + unit in {"g/cm³","kg/m³"} → "density"
        field_name contains "rate" + unit in {"s⁻¹","/s","1/s"} → "strain_rate"
      
      Step 2: 根据物理量类型获取物理可行范围
      
      Domain Knowledge Base:
        "temperature":
          °C:  [-273.15, 6000]    # 绝对零度到太阳表面
          K:   [0, 6273]
          F:   [-459.67, 10832]
        "mechanical_stress":
          MPa: [0, 5000]          # 已知最强材料 ~4000 MPa
          GPa: [0, 500]
        "density":
          g/cm³: [0.5, 22.6]     # 锂到锇
          kg/m³: [500, 22600]
        "strain_rate":
          s⁻¹: [1e-10, 1e8]      # 蠕变到冲击
      
      Step 3: 标记物理不可行的值
        if value NOT in feasible_range:
          → flag "physically_implausible"

    Algorithm — LLM Enhanced (V3.0):
      Prompt: "这条记录的 field_name='density', value=2.7, unit='g/cm³'。
               这个值在物理上是否合理？该材料通常的密度范围是多少？"
      LLM 返回: {is_plausible: true, typical_range: [2.6, 2.8], confidence: 0.95}

    Output:
      {
        "field": "density",
        "semantic_type": "density",
        "unit_normalized": "g/cm³",
        "physically_plausible": true,
        "feasible_range": [0.5, 22.6],
        "out_of_range_count": 0
      }

    Uses:
      - AssessmentAgent: physically_implausible → 严重 issue
      - NormalizationAgent: 知道物理量类型后可智能选择单位转换策略
    """
```

### 3.4 优化 P4: 字段关联分析

**当前问题**: 每个字段独立分析，不知道 "yield_strength < tensile_strength" 是物理必然成立的约束。

**优化方案**:
```python
# profiling_agent.py 新增 Tool: InterFieldChecker

class InterFieldChecker:
    """字段间关联关系检查工具。

    Algorithm:
      Physical Constraints (可扩展规则库):
        - yield_strength < tensile_strength (对于大多数材料)
        - density > 0
        - 0 < elongation < 100 (百分比)
        - |strain_rate| > 0

      Statistical Correlation:
        - Pearson r 检验: |r| > 0.7 且 p < 0.05 → 显著相关
        - 例如: hardness 与 tensile_strength 正相关是预期行为
        - 如果 expected_correlation 但实际 |r| < 0.3 → 数据可能有问题

    Output:
      {
        "constraint_violations": [
          {"type": "physical", "detail": "yield_strength(520) >= tensile_strength(480) for record X"}
        ],
        "correlation_anomalies": [
          {"pair": ["hardness", "tensile_strength"], "expected_r": 0.7, "actual_r": 0.15,
           "p_value": 0.4, "severity": "warning"}
        ]
      }
    """
```

### 3.5 优化 P5: LLM 增强的 Profile Summary

**当前问题**: ProfilingAgent 只输出数字，无自然语言摘要。

**优化方案**:
```python
# profiling_agent.py: 在 run() 末尾新增 LLM Summary
def _generate_llm_profile_summary(profile: dict) -> str:
    prompt = f"""
    Data profile: {profile['dataset_summary']['record_count']} records,
    {profile['dataset_summary']['field_count']} fields.
    
    Key observations:
    - Field distribution: {profile['field_statistics']}
    - Schema gaps: {profile['schema_summary']['missing_fields']}
    - Outliers: {profile.get('outliers', {})}
    
    In 2-3 sentences, describe the dataset quality at a glance.
    Focus on what a downstream data scientist would want to know immediately.
    """
    # LLM call with structured output
```

---

## 4. QualityAssessmentAgent 优化 (4 项)

### 4.1 优化 A1: 自适应阈值替代硬编码

**当前问题**:
```python
# 当前: 所有字段、所有领域用同一个阈值
if completeness["score"] < 0.9:  → issue
if rel_diff > 0.20:              → conflict
```

**优化方案**:
```python
# quality_assessment_agent.py: 新增 AdaptiveThresholdEngine

class AdaptiveThresholdEngine:
    """自适应阈值引擎。

    根据三个维度动态调整阈值:
    
    Dimension 1 — Field Criticality (从 target_schema 获取):
      关键字段 (如 yield_strength, temperature):
        completeness_threshold = 0.95
        conflict_threshold = 0.10
      辅助字段 (如 journal, year):
        completeness_threshold = 0.70
        conflict_threshold = 0.30
    
    Dimension 2 — Sample Size:
      小样本 (n < 10):  阈值 × 1.3 (更宽松, 统计不显著)
      中样本 (10-100):  阈值 × 1.0
      大样本 (n > 100): 阈值 × 0.8 (更严格)
    
    Dimension 3 — Domain Tightness:
      精确定量科学 (材料力学): 阈值 × 0.8 (严格)
      探索性科学 (天文观测):   阈值 × 1.3 (宽松)
      从 context_state.research_domain 获取

    Algorithm:
      base_threshold = config_base_value
      criticality_factor = (1.0 for critical, 1.3 for auxiliary)
      sample_factor = clamp(0.8, (30 / n_samples) ** 0.3, 1.3)
      domain_factor = (0.8 for precise, 1.0 for normal, 1.3 for exploratory)
      adaptive_threshold = base_threshold * criticality_factor * sample_factor * domain_factor

    Config (quality_rules.yaml 新增):
      adaptive_thresholds:
        enabled: true
        field_criticality:
          critical_fields: ["yield_strength", "tensile_strength", "temperature"]
          auxiliary_fields: ["journal", "authors", "access_path"]
        sample_size:
          small_n: 10
          large_n: 100
        domain_tightness:
          materials_science: "precise"
          astrophysics: "exploratory"
    """
```

### 4.2 优化 A2: 基于统计的异常检测替代规则检测

**当前问题**:
```python
# 当前: 固定阈值判断冲突
if rel_diff > 0.20: → conflict
```
问题是 "0.19 差异" 和 "0.21 差异" 真的有那么大区别吗？

**优化方案**:
```python
# tools/assessment/conflict_detector.py: 新增 StatisticalConflictDetector

class StatisticalConflictDetector:
    """基于统计学的冲突检测。

    替代当前简单的相对差异比较。

    Algorithm — Cohen's d Effect Size:
      
      Step 1: 按 field_name + material 分组
      Step 2: 对每个 source 组计算: mean_i, std_i, n_i
      Step 3: 两两比较:
      
        pooled_std = sqrt(((n_a-1)*std_a² + (n_b-1)*std_b²) / (n_a+n_b-2))
        cohens_d = |mean_a - mean_b| / pooled_std
        
        判定:
          |d| < 0.2  → negligible (不是冲突, 是正常测量误差)
          0.2 ≤ |d| < 0.5 → small (可能冲突, 需要更多数据)
          0.5 ≤ |d| < 0.8 → medium (确实存在差异, 标记为冲突)
          |d| ≥ 0.8        → large (严重冲突)
      
      Step 4: 报告 effect_size + confidence_interval
        CI = cohens_d ± 1.96 * sqrt((n_a+n_b)/(n_a*n_b) + d²/(2*(n_a+n_b)))
      
      如果 CI 跨过 0 → 统计不显著 → 不标记为冲突

    Why This Is Better:
      1. 考虑了组内方差 (测量误差)
      2. 考虑了样本量 (小样本更宽松)
      3. 提供置信区间 (not just binary yes/no)
      4. 效应量分级 (small/medium/large)

    Example:
      Source A: yield_strength = [450, 460, 440]  mean=450, std=10, n=3
      Source B: yield_strength = [500, 510, 490]  mean=500, std=10, n=3
      
      旧方法: |450-500|/500 = 10% < 20% → NOT a conflict ❌ (false negative!)
      新方法: cohens_d = |450-500|/10 = 5.0 → LARGE conflict ✅ (正确检测)
      
      为什么旧方法漏报？
      因为组内方差很小(std=10)，50的差异在统计上非常显著，即使相对差异只有10%。
    """
```

### 4.3 优化 A3: LLM 增强的 Completeness 评估

**当前问题**: Completeness 检查只看字段存在与否，不理解"为什么缺失"。

**优化方案**:
```python
# quality_assessment_agent.py: LLMCompletenessAnalyzer

class LLMCompletenessAnalyzer:
    """LLM 增强的完整性分析。

    当前 check_completeness() 只回答 "缺什么"。
    LLM 增强版回答 "缺得是否合理"。

    Algorithm:
      Step 1: 规则引擎 (当前) → 列出 missing_fields
      Step 2: LLM 分析 → 判断每个缺失是否合理

    LLM Prompt:
      "这篇论文 '{title}' 是关于 {material} 的 {property} 研究。
       提取到的字段: {present_fields}
       未提取到的字段: {missing_fields}
       
       请判断每个缺失字段:
       - 'expected': 这种研究通常应该包含此数据
       - 'optional': 这种研究可能包含, 但不一定
       - 'irrelevant': 这种研究不太可能包含此数据"

    Output:
      {
        "missing_fields_analysis": {
          "hardness": {"status": "expected", "reason": "材料力学研究通常报告硬度"},
          "fatigue_life": {"status": "optional", "reason": "可能测试但非必需"},
          "thermal_conductivity": {"status": "irrelevant", "reason": "室温力学测试不涉及热导率"}
        },
        "completeness_adjusted_score": 0.85  # 仅对 'expected' 缺失扣分
      }

    Uses:
      - 修正 completeness score (irrelevant 的缺失不扣分)
      - 提供 context-aware 的评估
    """
```

### 4.4 优化 A4: 来源可信度加权机制

**当前问题**: 来源可信度只看 metadata 完整性(doi/author/year)，不看实际质量。

**优化方案**:
```python
# tools/assessment/source_checker.py: SourceReliabilityScorer V2

class SourceReliabilityScorerV2:
    """多维来源可信度评分 V2。

    当前 (V1): 仅检查 metadata 存在性
    V2: metadata + citation + recency + journal_prestige

    Algorithm:
      Score = w1 * metadata_score + w2 * citation_score 
            + w3 * recency_score + w4 * journal_score

      metadata_score (V1, 保留):
        doi + title + authors + year + journal → 0-1

      citation_score (需要外部数据, V3 实现):
        从 Semantic Scholar / OpenAlex 获取引用次数
        log_normalize(citation_count) → 0-1
        V2 可用 retrieval_priority 作为 proxy

      recency_score:
        材料科学: last 5 years = 1.0, 5-10 = 0.7, 10-20 = 0.4, >20 = 0.2
        天文学:    last 2 years = 1.0, 2-5 = 0.8, 5-10 = 0.5, >10 = 0.3
        退化函数: score = exp(-λ * age_years)

      journal_score (规则版本, V2):
        tier1: ["Nature", "Science", "Acta Materialia"] → 1.0
        tier2: ["MSEA", "MMTA", "Scripta Materialia"] → 0.8
        tier3: known journals → 0.6
        unknown → 0.5

      Default weights (configurable):
        {metadata: 0.3, citation: 0.25, recency: 0.25, journal: 0.2}
    """
```

---

## 5. QualityScoringAgent 优化 (3 项)

### 5.1 优化 S1: 领域自适应权重

**当前问题**: 所有科学领域用同一套权重，天体物理和材料科学的"好数据"标准完全不同。

**优化方案**:
```python
# quality_scoring_agent.py: DomainAdaptiveWeightEngine

class DomainAdaptiveWeightEngine:
    """领域自适应权重引擎。

    Algorithm:
      Step 1: 从 context_state.research_domain 识别领域
      Step 2: 加载领域特定的权重配置

    Config (quality_rules.yaml 新增):
      domain_weights:
        materials_science:
          completeness:        0.30   # 材料数据完整性最重要
          consistency:         0.30   # 跨文献一致性同样重要
          format:              0.05   # 格式相对不重要
          source_reliability:  0.15
          conflict_risk:       0.20
        astrophysics:
          completeness:        0.15   # 天文数据不完整是常态
          consistency:         0.20
          format:              0.10
          source_reliability:  0.30   # 来源可信度最重要 (观测设备)
          conflict_risk:       0.25
        genomics:
          completeness:        0.25
          consistency:         0.20
          format:              0.15   # 基因数据格式规范性重要
          source_reliability:  0.15
          conflict_risk:       0.25
        default:
          completeness:        0.25
          consistency:         0.30
          format:              0.10
          source_reliability:  0.15
          conflict_risk:       0.20

      Step 3: 如 LLM 可用, 可动态微调权重
        Prompt: "用户研究目标是 {properties}, 最关心 {conditions}。
                 在当前上下文中, 哪个质量维度最重要？为什么？"
        LLM 输出: {primary: "completeness", secondary: "conflict_risk", reasoning: "..."}
        微调: primary_weight *= 1.2, secondary_weight *= 1.1, 其余归一化
    """
```

### 5.2 优化 S2: 非线性惩罚

**当前问题**: 
```python
overall_score = Σ(dimension_score_i × weight_i)  # 线性
```
所有维度独立, 没有"一文劣则整体劣"的乘性惩罚。

**优化方案**:
```python
# quality_scoring_agent.py: 新增 PenaltyFunctions

class NonlinearPenaltyEngine:
    """非线性惩罚引擎。

    Algorithm — 两种惩罚公式:

    Penalty 1 — Systematic Failure Penalty (乘性):
      如果某个维度得分为 0 (系统性失败):
        overall_score *= 0.5

      示例: 所有记录的 source 都不可靠 → 即使其他维度满分, 数据也不可用
            completeness=1.0, consistency=1.0, source_reliability=0.0
            → linear_score = 0.85 (误导)
            → penalized_score = 0.85 × 0.5 = 0.425 (正确反映严重性)

    Penalty 2 — Concentration Penalty (指数):
      如果所有 issue 集中在少数 source 上:
        concentration = max(issues_in_source / total_issues)
        if concentration > 0.5:
          penalty = exp(-2 * concentration)  # 集中度越高, 惩罚越重
          overall_score *= penalty

      示例: 10 个 issues 全部来自 Source A, 其他 9 个 Source 完美
            → 建议: 只剔除 Source A, 其余直接可用
            → 不应拉低整体评分

    Penalty 3 — Sparsity Penalty (对数):
      样本过少时, 降低置信度而非降低评分:
        if total_records < 10:
          confidence_multiplier = log10(total_records) / log10(10)
          # 10 条 → 1.0, 5 条 → 0.7, 2 条 → 0.3
          scoring.confidence *= confidence_multiplier
    """
```

### 5.3 优化 S3: 置信度校准

**当前问题**: 置信度来自各维度分的标准差，过于简单。

**优化方案**:
```python
# quality_scoring_agent.py: ConfidenceCalibrator

class ConfidenceCalibrator:
    """置信度校准。

    Algorithm:
      confidence = w1 * data_volume_factor + w2 * cross_validation_factor
                 + w3 * agreement_factor + w4 * llm_factor

      data_volume_factor:
        records: < 10  → 0.3, 10-100 → 0.7, 100-1000 → 0.9, >1000 → 0.99
        
      cross_validation_factor:
        如果多个 source 对同一 field 的值一致 → 0.9
        如果仅一个 source → 0.5
        
      agreement_factor:
        规则引擎和 LLM 对 route 判断一致 → 1.0
        不一致 → 0.5 (需要人工确认)

      llm_factor (可选, V3):
        LLM 直接评估: "基于以上数据, 你对评估结果的自信程度如何 (0-1)?"
        LLM 给出 self_assessment_confidence

    Output:
      confidence: 0.78
      confidence_factors: {
        data_volume: 0.7,
        cross_validation: 0.9,
        agreement: 1.0
      }
      recommendation: "置信度 acceptable, 但建议增加样本量提升可靠性"
    """
```

---

## 6. DecisionReasoningAgent 优化 (3 项)

### 6.1 优化 D1: LLM 结构化决策替代规则引擎

**当前问题**: per-source 决策是纯 if-else，LLM 只写摘要。

**优化方案**:
```python
# decision_reasoning_agent.py: LLMDecisionEngine

class LLMDecisionEngine:
    """LLM 结构化决策引擎。

    替代当前 if-else 规则引擎, LLM 直接输出 per-source 决策。

    Structured Output Schema:
      class SourceDecision(BaseModel):
          source_id: str
          route: Literal["Export", "Normalization", "Conflict", "HumanReview"]
          confidence: float
          reasoning: str
          conditions: list[str]   # 附带条件, 如 "Export if temperature_unit_fixed"

    LLM Prompt:
      """
      你是科学数据质量评估专家。

      数据源: {title} ({year})
      记录数: {record_count}
      质量评分: {quality_scoring}
      问题: {issues}

      请决定该来源的路由:
      - Export: 数据可直接使用
      - Normalization: 需要字段映射/单位转换/缺失值处理
      - Conflict: 存在需要解决的数据冲突
      - HumanReview: 问题严重, 需人工介入

      考虑因素:
      1. 该领域对完整性的容忍度
      2. 样本量是否足够支撑统计结论
      3. 是否存在系统性而非偶然性问题
      4. 修复成本 vs 数据价值

      返回结构化决策。
      """
    """
```

### 6.2 优化 D2: 多准则决策矩阵

**当前问题**: 只有 Conflict > Normalization > Export 一条优先级链。

**优化方案**:
```python
# decision_reasoning_agent.py: MultiCriteriaDecisionMatrix

class MultiCriteriaDecisionMatrix:
    """多准则决策矩阵。

    不是简单线性优先级, 而是二维决策:

    Axis 1 — Data Quality (质量轴):
      excellent → 可直接使用
      good      → 可小修后使用
      fair      → 需要规范化
      poor      → 需人工审查

    Axis 2 — Repair Cost (修复成本轴):
      low      → 自动修复成本低 (如单位转换)
      medium   → 自动修复有一定风险 (如字段映射)
      high     → 自动修复风险高 (如冲突解决)
      extreme  → 无法自动修复 (如数据完全缺失)

    决策矩阵:
                    Quality
                  excel  good  fair  poor
      Repair    ┌──────┬─────┬─────┬──────┐
      Cost low  │Export│Export│Norm │Norm  │
                ├──────┼─────┼─────┼──────┤
           med  │Export│Norm │Norm │Conf  │
                ├──────┼─────┼─────┼──────┤
           high │Norm  │Conf │Conf │Human │
                ├──────┼─────┼─────┼──────┤
         extreme│Conf  │Human│Human│Human │
                └──────┴─────┴─────┴──────┘

    示例:
      Quality=excellent, Repair=low  → Export (数据好, 无需修)
      Quality=excellent, Repair=high → Normalization (数据好但格式乱, 修一下)
      Quality=poor, Repair=low       → Normalization (质量差但易修, 试试自动)
      Quality=poor, Repair=extreme   → HumanReview (放弃)
    """
```

### 6.3 优化 D3: 条件路由 (Conditional Route)

**当前问题**: 路由是固定的单一值, 无法表达 "A 条件下 Export, B 条件下 Conflict"。

**优化方案**:
```python
# decision_reasoning_agent.py: ConditionalRoute

class ConditionalRoute:
    """条件路由。

    替代单一 route_decision, 支持条件分支。

    Schema:
      {
        "primary_route": "Normalization",
        "conditional_routes": [
          {
            "condition": "temperature_unit_is_C",
            "route": "Export",
            "reason": "如果温度单位已是°C, 则不需要单位转换"
          },
          {
            "condition": "yield_strength_records < 3",
            "route": "Normalization",
            "reason": "样本太少, 需要从其他来源补充"
          }
        ],
        "fallback_route": "HumanReview"
      }

    Uses:
      - Main Graph Router 读取后做分支路由
      - Normalization SubGraph 根据条件只处理需要处理的字段
      - 支持部分数据快速通道 (fast path for clean data)
    """
```

---

## 7. 优化优先级矩阵

```
                       Impact
                   Low    Med    High
    Effort  ┌────────┬────────┬────────┐
    Low     │S1 领域 │D3 条件 │A1 自适 │
            │权重    │路由    │应阈值  │
            ├────────┼────────┼────────┤
    Medium  │P3 语义 │P1 分布 │A2 统计 │
            │类型    │分析    │冲突检测│
            ├────────┼────────┼────────┤
    High    │P2 异常 │D1 LLM  │A3 LLM  │
            │值检测  │决策    │完整性  │
            └────────┴────────┴────────┘
    
    建议实施顺序:
      Phase 1 (Quick Wins): A1 > P3 > S1   — 1-2 天
      Phase 2 (Core Upgrades): A2 > P1 > D3 — 2-3 天
      Phase 3 (LLM Integration): A3 > D1 > P2 — 3-5 天
      Phase 4 (Advanced): S2 > S3 > D2 — 2-3 天
```

---

## 8. Phase 1 实施完成 (2026-07-10)

### 8.1 ✅ P3: 语义类型推断

**新增文件**: `tools/assessment/semantic_type.py`
- 10 种物理量规则库 (temperature/density/stress/hardness/...)
- 关键词 + 单位双重匹配, 置信度评分
- 物理可行性范围验证 (如 density 0.5-22.6 g/cm³)
- `infer_semantic_type()` + `infer_all_fields()` 两个 API
- 集成到 `ProfilingAgent.run()` (新增 semantic_types + out_of_range_count)

### 8.2 ✅ A1: 自适应阈值引擎

**新增文件**: `tools/assessment/adaptive_threshold.py`
- `AdaptiveThresholdEngine` 类: 三维度动态阈值
- 公式: `threshold = base × criticality_factor × sample_factor × domain_factor`
- 集成到 `QualityAssessmentAgent` (冲突检测 + completeness 阈值)
- 集成到 `DecisionReasoningAgent` (规则引擎使用自适应阈值替代硬编码 0.9)
- 配置: `quality_rules.yaml` 新增 `adaptive_thresholds` 段

### 8.3 ✅ S1: 领域自适应权重

**修改文件**: `pipeline/quality/assessment/agents/quality_scoring_agent.py`
- 从 `domain_weights` 配置读取领域特定权重
- materials_science → completeness=0.30, astrophysics → source_reliability=0.30
- 回退: domain_weights.default → quality_scoring.weights
- 配置: `quality_rules.yaml` 新增 `domain_weights` 段

### 8.4 验证结果

| 指标 | 优化前 (V1.2) | 优化后 (Phase 1) |
|------|-------------|-----------------|
| 9-record source threshold | 固定 0.90 | 自适应 0.81 (0.95 × 0.85) |
| Source routing | 全部 0.00 → Normalization | comp=0.97 > 0.81 → Export ✅ |
| Domain weights | 统一 0.25/0.30/0.10/0.15/0.20 | 按领域自适应 |
| Semantic detection | 无 | temperature/density/stress 等 10 种物理量识别 |

---

## 9. 附录: 需要新增的配置项

```yaml
# quality_rules.yaml 新增内容

# ── V2.0 自适应阈值 ──
adaptive_thresholds:
  enabled: true
  field_criticality:
    critical_fields: ["yield_strength", "tensile_strength", "temperature", "density"]
    auxiliary_fields: ["journal", "authors", "access_path", "retrieval_priority"]
  sample_size:
    small_n: 10
    large_n: 100
    small_n_multiplier: 1.3
    large_n_multiplier: 0.8
  domain_tightness:
    materials_science: "precise"
    astrophysics: "exploratory"
    default: "normal"

# ── V2.0 领域自适应权重 ──
domain_weights:
  materials_science:
    completeness: 0.30
    consistency: 0.30
    format: 0.05
    source_reliability: 0.15
    conflict_risk: 0.20
  astrophysics:
    completeness: 0.15
    consistency: 0.20
    format: 0.10
    source_reliability: 0.30
    conflict_risk: 0.25
  default:
    completeness: 0.25
    consistency: 0.30
    format: 0.10
    source_reliability: 0.15
    conflict_risk: 0.20

# ── V2.0 物理可行性规则 ──
semantic_types:
  temperature:
    units: ["°C", "C", "K", "F", "℃"]
    feasible_ranges:
      "°C": [-273.15, 6000]
      "K": [0, 6273]
  mechanical_stress:
    units: ["MPa", "GPa", "psi", "ksi"]
    feasible_ranges:
      "MPa": [0, 5000]
      "GPa": [0, 500]
  density:
    units: ["g/cm^3", "g/cm³", "kg/m^3", "kg/m³"]
    feasible_ranges:
      "g/cm^3": [0.5, 22.6]

# ── V2.0 非线性惩罚 ──
nonlinear_penalties:
  systematic_failure:
    enabled: true
    multiplier: 0.5
  concentration_penalty:
    enabled: true
    threshold: 0.5
  sparsity_penalty:
    enabled: true
    small_n: 10
```

---

## 10. 总结

### 从 V1.2 到 V2.0 的关键转变

| 维度 | V1.2 (当前) | V2.0 (目标) |
|------|------------|------------|
| 阈值 | 硬编码 0.9 | 自适应 (领域×样本量×关键性) |
| 冲突检测 | 相对差异 > 20% | Cohen's d 效应量 + 置信区间 |
| 完整性 | 字段存在性计数 | LLM 语义理解"为什么缺失" |
| 评分 | 固定权重线性求和 | 领域自适应 + 非线性惩罚 |
| 决策 | if-else + LLM 摘要 | LLM 多维推理 + 条件路由 |
| Profile | min/max/mean | 分布分析 + 异常值 + 语义推断 |
| 置信度 | 维度标准差 | 数据量×交叉验证×一致性 |

### 预期效果

- **误报率**: 减少 40-60% (自适应阈值消除一刀切)
- **漏报率**: 减少 30-50% (统计方法检测到规则引擎漏掉的冲突)
- **可解释性**: 显著提升 (每个决策附带 LLM reasoning + confidence factors)
- **领域泛化**: 从天体物理到材料科学无需改代码, 只改配置

---

## 10. Phase 2 实施完成 (2026-07-10)

### 10.1 P1: 分布分析

**新增**: `tools/assessment/distribution.py`
- skewness (Pearson系数), kurtosis (excess), quantiles (P10/P25/P50/P75/P90), IQR
- Histogram binning (Sturges' rule)
- 分布类型分类: normal / skewed / heavy_tailed / bimodal_like
- 集成到 ProfilingAgent → `profile.distributions`

### 10.2 A2: 统计学冲突检测

**新增**: `tools/assessment/statistical_conflict.py`
- Cohen's d 效应量: `|mean_a - mean_b| / pooled_std`
- 判定: <0.2 negligible, 0.2-0.5 small, 0.5-0.8 medium(conflict), >0.8 large(conflict)
- 置信区间: CI = d ± 1.96 × SE; 如果 CI 跨过 0.5 → 统计不显著 → 不报冲突
- 替换 QualityAssessmentAgent 中 detect_conflicts → detect_conflicts_statistical

### 10.3 D3: 条件路由

**修改**: `decision_reasoning_agent.py`
- 每个 source 新增 `conditional_routes` 数组
- {condition, route, reason} 三元组
- 示例: `"completeness_low" → "Normalization" → "需补充缺失数据"`

### 10.4 验证

| 指标 | V1.2 | Phase 2 |
|------|------|---------|
| 分布分析 | min/max/mean | skewness/kurtosis/quantiles/histogram |
| 冲突检测 | 相对差异>20% | Cohen's d + 效应量 + CI |
| 路由粒度 | 单一 route | 主路由 + 条件路由数组 |
| 语义检测字段 | 0 | 4 个物理量识别 |

---

## 11. Phase 3 实施完成 (2026-07-10)

### 11.1 P2: 异常值检测

**新增**: `tools/assessment/outlier.py`
- Method A: IQR (Q1-1.5*IQR, Q3+1.5*IQR)
- Method B: Modified Z-Score (|Mi| > 3.5, MAD-based)
- Consensus: 两法都判→definite_outlier; 一法→suspected_outlier
- `detect_all_fields()` 批量分析所有数值字段
- 集成到 ProfilingAgent → `profile.outliers`

### 11.2 A3: LLM 增强完整性分析

**新增**: `tools/assessment/llm_completeness.py`
- LLM 分类每个缺失字段: expected(扣分) / optional(30%扣分) / irrelevant(不扣)
- 计算 adjusted_completeness (仅 expected 缺失扣分)
- 集成到 QualityAssessmentAgent per-source 循环
- 示例: "材料类型缺失→expected, 硬度→optional, 应变率→expected"

### 11.3 D1: LLM 结构化决策

**修改**: `decision_reasoning_agent.py`
- Per-source 路由优先使用 LLM 决策 (get_structured_llm → AssessmentDecision)
- LLM 考虑: 样本量、异常值、数据研究价值
- LLM 失败时 → 回退规则引擎 (自适应阈值)
- 置信度 <0.5 → 降级 HumanReview

### 11.4 验证结果

| 指标 | Phase 2 | Phase 3 |
|------|---------|---------|
| 异常值检测 | 无 | IQR + Modified Z-Score, 4 字段分析 |
| 完整性分析 | 字段存在性计数 | LLM 语义分类 (expected/optional/irrelevant) |
| Per-source 决策 | 规则引擎 | LLM 推理 + 规则回退 |
