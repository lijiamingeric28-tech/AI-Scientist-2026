# Data Variance & Anomaly Detection SubGraph 设计报告 V3.0

> **版本**: V3.0 — 多源方差特征化 + 异常检测 + 全量保留标注
> **核心变更**: 从 V1.0 "冲突检测+裁决淘汰" 改为 "多源方差特征化+异常检测+全量保留标注"。同一天体的多源观测差异不再视为冲突需要裁决，而是分类原因后全量保留。
> **设计原则**: 一个 Stage = 一个 Node = 一个 Agent
> **对应文件**: `Data_Conflict_agentV1/conflict_graph.py` + `agents/*.py` + `legacy/resolution_reasoning_agent.py` + `tools/conflict/*.py` (顶层 `tools/conflict/`)
> **更新 (2026-08-03, V4.2)**: 与代码全面对齐（Stage 结构/工具清单/State 键/legacy 迁移/B→C 桥接/finalize 出口）
> **更新 (2026-08-04, V4.3)**: 上游字段名标准化增强 — 23 个 VizieR 目录列名纳入规范化映射（1178 别名: 标准字段 +259、database_catalog_properties +919），B→C 数据流字段名更规整（catalog 列保留原始名）

---

## 0. 变更记录 (V4.3)

本文档 (V3.0 设计报告) 于 2026-08-03 重新读取全部源码后逐段对齐更新。源码为最终事实，文档与源码冲突处以源码为准。各版本变更要点（从代码注释与 git 历史推断）：

### V4.3 (2026-08-04) — VizieR 目录 schema 扩展

| 版本 | 变更内容 |
|------|---------|
| V4.2 → V4.3 | 上游（Normalization/Assessment）字段名映射增强：VizieR 目录列名（Fnu_60/J.K20e/Plx/Teff/logg 等 1178 个别名）映射到标准字段或 database_catalog_properties 保留 → Variance 聚合按标准字段名分组更规整；catalog 原始列经 schema_mapping 保留 `_raw_field` |
|  | 对 Conflict 模块本身无代码改动（输入数据字段名更标准化） |

| 版本 | 变更内容 |
|------|---------|
| V1.0 → V2.3 | 冲突检测 + 6 Stage 裁决体系 (Identify/Classify/Evidence/Reasoning/Confidence/Report)，`resolution_reasoning_agent.py` 承载 Node 4 裁决推理 |
| V2.3 → V3.0 | **体系重构**：从"冲突裁决淘汰"改为"多源方差特征化 + 异常检测 + 全量保留标注"；6 Stage 减为 5 Stage (移除 ResolutionReasoning)；5 个 Agent 全部重写并内联逻辑 (Tools: 0)；`tools/conflict/` 8 个工具按 V3.0 重命名重写 (VarianceExtractor 等) 但已不再被 Agent 调用；`resolution_reasoning_agent.py` 移入 `legacy/` |
| V3.0 → V3.1 | `retry_count` 递增修复 (防止无限重入)；Conflict→Normalization 数据契约：`resolution_plan.actions_to_normalize` 供 SourceRouterAgent 消费 |
| V3.1 → V3.2 | 生成精确的 `resolution_plan.actions_to_normalize` (unit_error 时每个来源生成一个 action，`from_unit` 为字符串而非列表，目标单位优先取 target_schema 标准单位) |
| V3.2 → V3.3 | 子图统一出口 `finalize` 节点 (透传 execution_status，供主图 Stage Gate 消费) |
| V3.3 → V4.x | **B→C 数据断链桥接**：Normalization 复检冲突 (needs_conflict_analysis + conflict_check) 与 Assessment 的 multi_source_variance 是两套检测，B→C 派发后优先读 `normalization.validation.conflict_check`；主图 Gate 不再覆写业务 route_decision；HumanReview 经 loop_controller 簿记 |
| V4.2 (本次) | 文档与代码全面对齐 (本文档) |

## 1. Agent 元信息

### 1.1 基本属性

| 属性 | 内容 |
|------|------|
| **Agent 名称** | Data Variance & Anomaly Detection Agent (原名 Conflict Resolution Agent) |
| **SubGraph 名称** | Data_Conflict_agentV1 |
| **所属子图** | SubGraph 4 (数据清洗与质检) |
| **版本** | V3.0 |
| **核心职责** | 对 Assessment 检测出的多源方差和异常进行分析、分类、验证和标注。**所有多源测量值全量保留**，仅标注差异原因和异常标记。 |
| **关键约束** | **负责差异分析和标注，不负责数据淘汰。** 不决定"哪个值对"——天文学中所有观测值都是有效的。仅真正的异常（提取错误/单位错误/交叉ID错误）才触发路由动作。 |
| **修改数据** | ❌ 否 — 只写 report，不修改 data_state.current_data |

### 1.2 前后置条件

| 条件类型 | 条件 |
|---------|------|
| **前置条件 (A→C 路径)** | `report_state.quality` 已被 Assessment 填充 |
|  | `report_state.quality.multi_source_variance` 含方差/异常 |
|  | 主图 `dispatch` 按 `per_source_routes` 将来源放入 `pending_sources["Conflict"]` 队列 |
| **前置条件 (B→C 路径)** | `report_state.normalization` 已被 Normalization 填充 |
|  | `report_state.normalization.validation.needs_conflict_analysis == True` (V3.0 兼容旧字段 `needs_variance_analysis`) |
|  | `report_state.normalization.validation.conflict_check` 含复检方差/异常 (V4 桥接, B→C 优先读此) |
| **后置条件** | `report_state.conflict` 包含完整 Variance Annotation Report |
|  | `workflow_state.route_decision` 已设置为 "Export" / "Normalization" / "HumanReview" |

### 1.3 在总图中的位置

```
START → Assessment → Gate(A) → Dispatch
  ├── Conflict → Gate(C) → LoopController → Export → Insights → END   (C→D)
  ├── ... (Normalization 复检发现冲突 → LoopController → Conflict, B→C)
  ├── LoopController → pre_normalization → Normalization → LoopController (C→B 循环, 最多3次)
  └── LoopController → HumanReview   (C→E, 经 loop 簿记清理 pending_sources)
```

---

## 2. 架构概览 — 5 Stage 流水线

```
START → VarianceAggregation → DifferenceClassification
      → AnomalyVerification → AnnotationConfidence → AnnotationReport
      → finalize → END

条件边:
  - Aggregation: total_variances==0 && total_anomalies==0 → finalize (route=Export, 跳过 Stage 2-5)
  - Confidence: 分类置信度不足 + retry<2 → 重入 Verification (最多2次)
  - finalize (V3.3 统一出口): 透传子图最终 execution_status (Retry/Failed 冒泡到主图 Stage Gate)
```

### V3.0 vs V1.0 关键差异

| 方面 | V1.0 (旧) | V3.0 (新) |
|------|----------|----------|
| Stage 数量 | 6 (含 ResolutionReasoning) | 5 (移除 ResolutionReasoning) |
| 核心逻辑 | 冲突检测 → 裁决淘汰 | 方差分析 → 分类标注 |
| 数据操作 | 裁决后可能丢弃低置信度数据 | 全量保留, action=preserve_all |
| 输出 | resolution_plan (adopt/prefer/weighted_avg) | annotations (methodological/condition/temporal...) |
| 路由 | Export / Normalization / HumanReview | 同 (语义不同: Normalization=修单位, HumanReview=交叉ID错误) |
| LLM 节点 | Node 2,4,5,6 | Node 2 (分类), Node 5 (摘要) |

---

## 3. Stage 1: VarianceAggregationAgent

**原**: ConflictIdentificationAgent (V1.0)
**现**: VarianceAggregationAgent (V3.0)
**LLM**: 否 | **文件**: `agents/conflict_identification_agent.py`

### 3.1 职责

接收 Assessment 的 `multi_source_variance` 数据（B→C 时优先 Normalization 复检结果），按 `(entity_type, entity_name, field_name)` 聚合，构建差异摘要卡片，确定触发路径。

### 3.2 处理流程

```
1. 读取 quality.multi_source_variance → variances + anomalies
2. 确定触发路径 (V4 fix: B→C 数据断链桥接):
   - normalization.validation.needs_conflict_analysis 或 needs_variance_analysis → "B→C"
   - B→C 时: 若 validation.conflict_check 含 variance_count/anomaly_count > 0,
     则以 conflict_check 覆盖 msv (Normalization 复检与 Assessment 检测是两套系统)
   - 否则 → "A→C"
3. 无方差/异常 → 快速出口 (route=Export, 跳过 Stage 2-5)
   - 仍写入 report_state.conflict.resolution_report {route_decision: "Export", status: "No_Variance"}
4. 聚合: 收集 involved_sources / involved_fields / involved_entities
5. 构建 variance_cards:
   - entity_type, entity_name, field_name, source_count, source_ids
   - value_range, max_cohens_d, inferred_cause, cause_confidence
   - source_details: per-source mean/std/n, measurement_methods, condition_tags, year, unit
   - unit_mismatch (unit_mismatch_detected), cross_id_risk
```

### 3.3 输出

```
report_state.conflict.aggregation = {
  trigger_path: "A→C" | "B→C" | "none",
  total_variances, total_anomalies,
  variances: [variance_cards],
  anomalies: [anomalies],
  involved_sources, involved_fields, involved_entities,
  summary
}
# 快速出口时额外写入:
report_state.conflict.resolution_report = {route_decision: "Export", status: "No_Variance", summary}
workflow_state.route_decision = "Export"
```

---

## 4. Stage 2: DifferenceClassificationAgent

**原**: ConflictClassificationAgent (V1.0)
**现**: DifferenceClassificationAgent (V3.0)
**LLM**: 是 (仅 undetermined 案例) | **文件**: `agents/conflict_classification_agent.py`

### 4.1 职责

对每组多源差异分类原因（methodological / condition / temporal / uncertainty / duplicate）。

### 4.2 分类体系 (V3.0)

| 原因类型 | 说明 | 置信度来源 |
|---------|------|-----------|
| `methodological_variance` | 不同观测方法/仪器导致的系统性差异 | measurement_method 不同 |
| `condition_variance` | 不同观测条件/波段导致的差异 | condition_tags 不同 |
| `temporal_variation` | 不同时间观测导致的变化 (year差>5年) | year 差值 |
| `measurement_uncertainty` | 测量误差范围内的正常波动 | 同方法+同条件+小d值 |
| `duplicate_observation` | 同一测量在多个论文中重复收录 | 值完全相同+不同source |
| `unknown` | 无法确定差异原因 | — |

### 4.3 处理流程

```
1. 规则分类 (优先, 无 LLM):
   - 读取 Assessment 阶段 inferred_cause + cause_confidence
   - cause_confidence >= 0.65 → 直接采用规则分类
   - 否则 → 标记为 needs_llm

2. LLM 补充 (仅 undetermined 案例):
   - 从 data_state 读取 context_snippet (V2 Record 字段, 每条截断 300 字符, 最多 2 条)
   - 构建 LLM input: methods_used, condition_tags, years, max_cohens_d, context_snippets
   - LLM 输出 JSON: {classifications: [{entity_type, entity_name, field_name, cause, confidence, reason}]}
   - LLM 返回但未匹配到对应条目 → fallback: cause="unknown", confidence=0.3
   - LLM 调用异常 → fallback: cause="unknown", confidence=0.2

3. 分组统计: by_cause + by_entity
```

### 4.4 输出

```
report_state.conflict.classification = {
  classified_variances: [{..., classified_cause, cause_confidence_final, classification_method, classification_reason}],
  anomalies: [...],
  by_cause: {"methodological_variance": [...], ...},
  by_entity: {"FRB:FRB121102": {total, by_cause}}
}
```

---

## 5. Stage 3: AnomalyVerificationAgent

**原**: EvidenceCollectionAgent (V1.0)
**现**: AnomalyVerificationAgent (V3.0)
**LLM**: 否 | **文件**: `agents/evidence_collection_agent.py`

### 5.1 职责

对标记为异常的记录做 4 类确定性验证 (按 anomaly_type 分支) + 重复记录检测：
1. **提取质量检查** (extraction_error): extraction_confidence < 0.3 → confirmed, < 0.5 → likely
2. **单位一致性检查** (unit_error): 跨源单位维度是否匹配 (多维度 → confirmed)
3. **统计异常检查** (statistical_outlier): 同方法+同条件+同单位 且 Cohen's d > 2.0 → confirmed
4. **交叉ID检查** (cross_id_error): 同实体名出现多种 entity_type → confirmed
5. **重复记录检测** (独立于 anomaly 列表): 相同值 + 相同entity + 不同source → duplicate_observation

### 5.2 异常验证阈值

```
_EXTRACTION_CONFIDENCE_CRITICAL = 0.3   # confirmed anomaly
_EXTRACTION_CONFIDENCE_LIKELY = 0.5     # likely anomaly
_COHENS_D_CONFIRMED = 2.0              # same method+condition+unit + d>2.0 → confirmed
_COHENS_D_LIKELY = 3.0                 # d>3.0 → likely even without same method
```

### 5.3 异常验证逻辑

```
for each anomaly:
  if extraction_error:
    confidence < 0.3 → verdict="confirmed", severity="critical"
    confidence < 0.5 → verdict="likely", severity="high"
    else → verdict="borderline", severity="medium"

  elif unit_error:
    有意义维度 > 1 → verdict="confirmed", severity="critical"
    else → verdict="false_positive", severity="low"

  elif statistical_outlier:
    same_method + same_conditions + same_unit + d>2.0 → verdict="confirmed"
    d>3.0 → verdict="likely"
    else → verdict="borderline"

  elif cross_id_error:
    entity_types > 1 → verdict="confirmed", severity="critical"
    else → verdict="false_positive"
```

### 5.4 重复检测

```
扫描所有 records, 按 (entity_type, entity_name, field_name, field_value) 分组
同一值在多个 source 出现 → duplicate_observation (置信度 0.95, classification_method=rule)
最多记录 10 组 (_DUPLICATE_MAX_GROUPS=10)
重复组同时追加进 classified_variances, 供 Stage 4/5 统一处理
```

---

## 6. Stage 4: AnnotationConfidenceAgent

**原**: ConfidenceEvaluationAgent (V1.0)
**现**: AnnotationConfidenceAgent (V3.0)
**LLM**: 否 | **文件**: `agents/confidence_evaluation_agent.py`

### 6.1 职责

评估差异原因分类的置信度和异常验证的置信度。低于阈值 → Retry (重新分类/验证, 最多 2 次)。

### 6.2 分类置信度评估

```
_CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.55

统计每个 classified_variance 的 cause_confidence_final
低于阈值 → low_confidence_variances 列表
计算平均分类置信度
```

### 6.3 异常验证置信度评估

```
verdict → 置信度映射:
  confirmed: 0.95, likely: 0.75, borderline: 0.45
  false_positive: 0.10, unverified: 0.30

borderline/unverified → unverified_anomalies 列表
```

### 6.4 重试逻辑

```
needs_retry = (
  (low_confidence_variances > 0 or unverified_anomalies > 0)
  AND retry_count < 2
  AND (有方差或异常)
)
needs_retry → retry_count += 1 (V3.1 fix: 递增防无限重入)
         → execution_status="Retry" → graph 回退到 anomaly_verification
```

---

## 7. Stage 5: AnnotationReportAgent

**原**: ResolutionReportAgent (V1.0)
**现**: AnnotationReportAgent (V3.0)
**LLM**: 是 (LLM 摘要生成) | **文件**: `agents/resolution_report_agent.py`

### 7.1 核心原则

**所有多源测量值全量保留，只标注差异原因。** action 统一为 `preserve_all`。

### 7.2 标注构建

```
for each classified_variance:
  annotations.append({
    entity_type, entity_name, field_name,
    annotation_type: "multi_source_variance",
    cause, cause_label,
    value_range, source_count, source_ids,
    confidence, action: "preserve_all"
  })
```

### 7.3 异常处理

```
confirmed/likely anomalies → anomaly_flags:
  unit_error:
    → action: "normalize_unit" (route=Normalization)
  cross_id_error:
    → action: "human_review" (route=HumanReview)
  extraction_error / statistical_outlier:
    → action: "flag_for_review" (标记但不删除, severity 保留)

false_positives → 忽略 (不生成 flag)
borderline → 保留但标记 (计入 borderline_anomalies, 不触发路由)
```

### 7.3.1 resolution_plan (V3.1/V3.2: Conflict→Normalization 数据契约, SourceRouterAgent 消费)

```
resolution_plan = {
  actions_to_normalize: [   # 仅 unit_error 生成 (V3.2: 每个来源一个 action, 不再只处理第一个)
    {
      source_id, target_source, record_ids, field, field_name,
      entity_type, entity_name,
      from_unit: "<字符串>",          # V3.2: 字符串而非列表
      to_unit:   "<target_schema 标准单位, 找不到则取第一个来源单位>",
      action: "normalize_unit",
      reason: "Unit dimension mismatch across sources: {...}"
    }, ...
  ],
  annotations_to_add: [],   # 当前恒为空 (全量保留原则, 无删除/覆盖动作)
  human_review_items: [     # 仅 cross_id_error 生成
    {conflict_id, field_name, entity_name, reason, evidence_summary}, ...
  ],
}
```

### 7.4 路由决策

```
if total_variances==0 and total_anomalies==0:
  route="Export", status="No_Variance"
elif has_cross_id or has_critical:
  route="HumanReview", status="Unresolved_Anomalies"
elif has_unit_issues:
  route="Normalization", status="Needs_Unit_Fix"
else:
  route="Export", status="Annotated"
```

### 7.5 LLM 摘要

```
LLM 生成 2-3 句英文摘要, 强调所有测量值已保留, 差异归因于观测因素
LLM 失败 → 模板 fallback
```

### 7.6 Per-entity 路由

```
方差 → Export (保留)
confirmed/likely anomaly:
  unit_error → Normalization
  cross_id_error → HumanReview
  其他 (extraction_error / statistical_outlier) → Export (标记但不阻塞, 不覆盖已有 HumanReview)
```

---

## 8. 输入输出规范

### 8.1 读取的 State

| State 路径 | 用途 |
|-----------|------|
| `report_state.quality.multi_source_variance` | 方差分析结果 (A→C 核心输入) |
| `report_state.normalization.validation.needs_conflict_analysis` / `needs_variance_analysis` | B→C 路径触发判定 |
| `report_state.normalization.validation.conflict_check` | B→C 复检方差/异常 (V4 桥接, 存在时覆盖 msv) |
| `data_state.current_data.records` | 读取 context_snippet (LLM 分类用) + 重复检测扫描 |
| `context_state.research_domain` | 领域上下文 (Stage 5 摘要) |
| `context_state.target_schema.fields[].standard_unit` | Stage 5 生成 normalize_unit action 的目标单位 |

> 注: V3.0 的 5 个 Agent **不再读取** `report_state.quality.sources[sid].conflict_risk`（V1.0 遗留字段，仅 Assessment 侧保留）。

### 8.2 写入的 State

| State 路径 | 写入者 | 内容 |
|-----------|--------|------|
| `report_state.conflict.aggregation` | Stage 1 | 方差聚合结果 |
| `report_state.conflict.resolution_report` | Stage 1 (快速出口) | `{route_decision: "Export", status: "No_Variance"}` |
| `report_state.conflict.classification` | Stage 2 | 差异原因分类 |
| `report_state.conflict.verification` | Stage 3 | 异常验证结果 |
| `report_state.conflict.annotation_confidence` | Stage 4 | 置信度评估 + retry_count |
| `report_state.conflict.resolution_report` | Stage 5 | 完整标注报告 (annotations/anomaly_flags/resolution_plan/route_decision) |
| `workflow_state.route_decision` | Stage 1/5 | Export / Normalization / HumanReview |
| `workflow_state.execution_status` | Stage 4 | "Retry" (置信度不足) 或 "Success" |
| `workflow_state.llm_call_count` | Stage 2/5 | 累计 LLM 调用次数 |
| `workflow_state.workflow_history` | 全部 Stage | 执行记录 (agent/stage/status/duration/reason) |
| `workflow_state.current_node` | 全部 Stage | 当前节点名 |

---

## 9. 差异原因标签

| 内部标识 | 中文标签 | 说明 |
|---------|---------|------|
| `methodological_variance` | 观测方法/仪器差异 | 不同仪器或方法间的系统差异 |
| `condition_variance` | 观测条件/波段差异 | 不同波段、频率、条件下的差异 |
| `temporal_variation` | 时间演化 | 不同历元观测到的真实变化 |
| `measurement_uncertainty` | 测量误差范围 | 正常误差范围内的波动 |
| `duplicate_observation` | 重复收录 | 同一测量值在不同来源中出现 |
| `unknown` | 未知原因 | 无法确定差异原因 |

---

## 10. 异常处理矩阵

| 层级 | 异常 | 策略 |
|------|------|------|
| Stage 1 | 无方差/异常 | 快速出口 → finalize → END (route=Export, 仍写 resolution_report) |
| Stage 1 | B→C 但复检无方差/异常 | 同上 (route=Export) |
| Stage 2 | LLM 分类异常 | fallback: cause="unknown", confidence=0.2, method=fallback |
| Stage 2 | LLM 返回但未匹配条目 | fallback: cause="unknown", confidence=0.3, method=fallback |
| Stage 3 | 单位维度一致 / 交叉ID仅1类 | verdict="false_positive", severity="low" → 跳过 |
| Stage 3 | 重复记录过多 | 最多记录 10 组 (_DUPLICATE_MAX_GROUPS) |
| Stage 4 | 分类/验证置信度不足 | execution_status="Retry" → graph 重入 Verification (retry_count<2, V3.1: 每次递增) |
| Stage 5 | LLM 摘要失败 | 模板 fallback (仍设置 route) |
| Graph 层 | finalize 透传 | 子图最终 execution_status 冒泡到主图 Gate (Retry/Failed/HumanReview → 对应处理) |
| Graph 层 | Retry (Gate) | retry_by_node < MAX_RETRIES → 重入子图; 耗尽或 Failed → HumanReview |
| Graph 层 | Failed | → HumanReview (Gate 显式路由) |
| 主图 | C→B/C→D/C→E | loop_controller 读 resolution_report.route_decision; 超限 (MAX_ITERATIONS/MAX_LOOP=3) → force Export |

---

## 11. 工具清单 (8 个, 顶层 `tools/conflict/`)

> ⚠️ **重要事实 (V4.2 核对)**: 8 个工具文件均存在且已按 V3.0 重写 (文件头注释: VarianceExtractor / VarianceCauseClassifier 等)，但 **V3.0 的 5 个 Agent 均不再调用它们** (每个 Agent 头注释 "LLM: 是/否 | Tools: 0"，逻辑已全部内联进 Agent)。工具保留为可复用库 (含向后兼容旧 API 的函数名)，当前 SubGraph 运行时不经过工具层。路径为**顶层** `tools/conflict/` (不属于 `Data_Conflict_agentV1/` 包)。

| Tool | 文件 | V3.0 职责 (按文件头注释) |
|------|------|---------|
| VarianceExtractor | `tools/conflict/conflict_extractor.py` | 提取方差+异常 (替代冲突提取), 按 (entity_type, entity_name, field_name, source_ids) 去重 |
| VarianceContextBuilder | `tools/conflict/context_builder.py` | 构建差异上下文 (直接读 V2 Record 字段: measurement_method/condition_tags/extraction_confidence) |
| VarianceCauseClassifier | `tools/conflict/rule_classifier.py` | 规则分类差异原因 (5类 + unknown), 时间差阈值 5 年 |
| DomainRuleEngine | `tools/conflict/domain_rule_engine.py` | 领域规则匹配 (field_category 推断, 不绑定实体类型; quality_rules.yaml 优先) |
| StatisticalEvidenceAnalyzer | `tools/conflict/statistical_evidence.py` | 分析冲突的统计证据: 统计显著性/样本量充分性/效应量解释 (旧裁决体系保留) |
| SourceReliabilityAnalyzer | `tools/conflict/source_reliability_analyzer.py` | 来源可靠性评分 (质量×0.4 + 期刊×0.35 + 时效×0.25, 期刊分级从 yaml 加载) |
| VarianceCauseEvidence | `tools/conflict/contextual_evidence.py` | 差异原因证据汇总 (variance_cause_evidence + annotation_suggestions) |
| AnnotationConfidenceEvaluator | `tools/conflict/confidence_evaluator.py` | 分类置信度评估 (3维: metadata_completeness + cause_consistency + domain_support) |

### 已移除 / 归档

| 旧工具/Agent | 现状 |
|-------------|------|
| ResolutionReasoningAgent | V3.0 不再做裁决推理 (全部保留); 代码移入 `legacy/resolution_reasoning_agent.py` |
| 裁决策略 (prefer_source/weighted_avg/retain_range/escalate) | 替代为 preserve_all + annotation (仅 legacy 文件内残留) |
| `Data_Conflict_agentV1/tools/conflict/` 目录 | **不存在** — 工具位于顶层 `tools/conflict/` |

---

## 12. 文件清单

```
Data_Conflict_agentV1/
├── conflict_graph.py                        # V3.0: 5 Stage 编排 + finalize 出口 (V3.3)
├── CONFLICT_DESIGN_REPORT.md                # 本报告 (V3.0 设计, V4.2 对齐更新)
├── CONFLICT_DESIGN_REPORT_V2.3.md           # V2.3 历史文档 (过时, 保留参考)
├── __init__.py
├── agents/
│   ├── conflict_identification_agent.py     # Stage 1: VarianceAggregationAgent
│   ├── conflict_classification_agent.py     # Stage 2: DifferenceClassificationAgent
│   ├── evidence_collection_agent.py         # Stage 3: AnomalyVerificationAgent
│   ├── confidence_evaluation_agent.py       # Stage 4: AnnotationConfidenceAgent
│   ├── resolution_report_agent.py           # Stage 5: AnnotationReportAgent
│   └── __init__.py
└── legacy/
    └── resolution_reasoning_agent.py        # V1.0 ResolutionReasoningAgent (裁决推理, 已废弃, graph 不引用)

tools/conflict/                              # 顶层目录 (不属于 Data_Conflict_agentV1 包)
├── __init__.py                              # "tools/conflict — Conflict Resolution Tool 集合 (8 Tools)"
├── conflict_extractor.py                    # VarianceExtractor (V3.0 重写)
├── context_builder.py                       # VarianceContextBuilder (V3.0 重写)
├── rule_classifier.py                       # VarianceCauseClassifier (V3.0 重写)
├── domain_rule_engine.py                    # DomainRuleEngine (V3.0 修改)
├── contextual_evidence.py                   # VarianceCauseEvidence (V3.0 修改)
├── confidence_evaluator.py                  # AnnotationConfidenceEvaluator (V3.0 重写)
├── source_reliability_analyzer.py           # SourceReliabilityAnalyzer (保留)
└── statistical_evidence.py                  # StatisticalEvidenceAnalyzer (保留)

注: 5 个 Agent 均不导入 tools/conflict (Tools: 0, 逻辑内联); 工具为备用库。
主图路由: graph.py (V3.4) + routers.py (V3.1, 唯一路由来源)。
```
