# Insights SubGraph 设计报告 V3.4

> **版本**: V3.4 — 科学数据洞察生成
> **更新 (2026-08-03, V4.2)**: Simbad 对象类型体系 (153 类型) + 知识库 53 条扩展 + 父类匹配
> **更新 (2026-08-04, V4.3)**: 字段名映射增强 — 23 个 VizieR 目录列名纳入规范化映射（1178 别名）→ 洞察字段覆盖新 catalog 字段（2mass_photometry/catalog_identifier/cirrus_flag/color_index 等）
> **设计原则**: 一个 Stage = 一个 Node = 一个 Agent
> **对应文件**: `Data_Insights_agentV1/insights_graph.py` + `agents/*.py` + `tools/insight/*.py`

---

## 0. 变更记录 (V4.2)

### V4.3 (2026-08-04) — VizieR 目录 schema 扩展

| 变更 | 说明 |
|------|------|
| 上游字段映射增强 | `target_schema_astrophysics` aliases 349→1178（标准字段 +259、`database_catalog_properties` +919）→ FieldInsight 的 `field_summaries` 字段名更规整，洞察覆盖新 catalog 语义字段 |
| 零 LLM 全链路验证 | `test_real_data_e2e_mock.py`（mock LLM）：全量 219 条真实数据 ALL CHECKS PASSED，Insights 覆盖 26 字段（含 2mass_photometry/apparent_magnitude/catalog_identifier/cirrus_flag/color_index/declination/dispersion_measure/distance 等新映射字段） |

本报告已按当前源码逐段核对更新。以下为源码注释中 V3.4 → V4 的关键修复记录:

| 版本 | 变更 |
|------|------|
| V3.4 | 4 Node 线性流水线建立 (FieldInsight → Relationship → Recommendation → Synthesis); prompt 注入由 `format()` 改为 `replace()` (prompt 含 JSON 示例裸花括号, `format` 会抛 KeyError); `database_catalog_properties` catch-all 字段按 `raw_column` 语义聚合 (`_semantic_group`, Fnu_*→flux_density 等); DB 记录视为高置信 (`extraction_confidence=1.0`), low_confidence 仅统计 paper 记录; Relationship 复用 `schema_mapping.yaml` aliases 将 DB 列名映射到标准名; `report_state.insights` / `output_state.insights` State 键建立 |
| V3.5 | `configs/domain_config.py` Astronomy Domain Adapter — 领域常量集中 (KB_TOP_K/截断长度/检索类别/阈值); 知识库按领域缓存 (`_stores` dict, 防跨领域污染); Relationship 字段对加同实体约束 (仅 `(entity_type, entity_name)` 相同的字段配对, 防 FRB.dispersion_measure 与 Gaia.parallax 误配对) + `MIN_RECORDS_FOR_RELATION=2` (单条记录不参与); Synthesis 响应 str 类型防护 (MagicMock/非字符串 → 模板叙述) + Pydantic 强校验; 输出目录优先复用 `output_state.output_dir` |
| V4 | Simbad 对象类型体系: `entity_types_astrophysics` 配置段 (153 类型 / 8 大类), `tools/insight/entity_types.py` 消费层 (normalize/infer/ancestors/typical_range 4 函数); 知识库 25→78 条扩展 (reference_ranges 20 / measurement_theory 16 / astrophysical_models 16 / physical_laws 13 / methodology 13); 知识库检索父类匹配加分 (`ENTITY_TYPE_PARENT_SCORE=2`, 直接命中 +3); `field_insight` prompt 注入 `{entity_type_reference}` (当前数据出现的实体类型 + 典型范围, 使 LLM 按对象类型解读测量值, 如星系 stellar_mass 1e11 正常); LLM 未给 `typical_range` 时 `get_typical_range` 配置兜底; 实体类型规范化 — "Unknown"/空 → 3 级推断链 (catalog > field > field_class) |

---

## 1. Agent 元信息

### 1.1 基本属性

| 属性 | 内容 |
|------|------|
| **Agent 名称** | Data Insights Agent (科学数据洞察生成) |
| **SubGraph 名称** | Data_Insights_agentV1 |
| **所属子图** | SubGraph 4 (数据清洗与质检) — 末端节点 (Export 之后) |
| **版本** | V3.4 |
| **核心职责** | 对质检/清洗/冲突裁决完成的数据生成科学洞察: 字段级领域解读 (per-field 跨来源差异分析)、跨字段物理关系识别、数据使用建议、综合叙述报告 |
| **关键约束** | **只读数据, 绝不修改 `data_state.current_data`。** 仅累积写入 `report_state.insights` 并最终写入 `output_state.insights` + 落盘 JSON 文件 |
| **修改数据** | ❌ 否 — 只读, 不调用任何数据修改工具 |
| **LLM 调用** | 每节点 1 次 (temperature=0.0), 共 4 次; 失败全部有确定性 fallback |
| **主图位置** | `graph.py`: `NODE_INSIGHTS = "insights_graph"`, `build_insights_graph().compile()` 注册; 边 `Export → Insights → END` (V3.4) |

### 1.2 前后置条件

| 条件类型 | 条件 |
|---------|------|
| **前置条件** | `data_state.current_data` 已包含完整 records + sources (Assessment/Normalization/Conflict 处理后的数据) |
|  | `report_state.quality` 已填充 (quality_scoring / multi_source_variance / sources[*].completeness / route_counts) |
|  | (可选) `report_state.normalization` / `report_state.conflict` 已填充 (作为质量上下文) |
|  | `context_state.research_domain` 指定领域 (默认 `"astrophysics"`) |
| **后置条件** | `report_state.insights.field_insights` / `.relationships` / `.recommendations` 累积完成 |
|  | `output_state.insights` = 完整 `DataInsightsReport` (Pydantic 校验通过) |
|  | `output_state.exported_files` 追加 `insights_{timestamp}.json` 落盘文件 |
|  | `workflow_state.phase="done"`、`route_decision=""`、`execution_status="Success"` |

### 1.3 上下游及总图位置

```
上游: Export (B→D / C→D / A→D 三路汇聚后) — graph.py: NODE_EXPORT → NODE_INSIGHTS
下游: END (主图终节点)

主图 V3.4 结构:
  START → Assessment → ... → Export → Insights → END
```

---

## 2. 架构概览 — 4 Node 线性流水线

```
START → FieldInsightAgent → RelationshipAgent
      → RecommendationAgent → SynthesisAgent → END

线性流水线, 无条件分支 (insights_graph.py 共 63 行, 纯编排, 不调用
Tool/Prompt/LLM/Rule)。
```

| 节点 | 图节点名 | Agent | LLM | 职责 |
|------|---------|-------|-----|------|
| 1 | `field_insight` | FieldInsightAgent | ✅ 1 次 | per-field 领域洞察: 确定性 observation + LLM 解读 (RAG 知识库) + typical_range 兜底 |
| 2 | `relationship` | RelationshipAgent | ✅ 1 次 | 跨字段物理关系识别 (物理定律/相关性/条件依赖), 同实体字段对约束 |
| 3 | `recommendation` | RecommendationAgent | ✅ 1 次 | 数据使用建议: 适用场景/局限性/caveats + 确定性 low_confidence/coverage_gaps |
| 4 | `synthesis` | SynthesisAgent | ✅ 1 次 | 综合叙述 + DataInsightsReport 组装 + JSON 落盘 + manifest 更新 + output_state 写入 |

**V3.5 说明**: `INSIGHT_BATCH_SIZE = 6` (FieldInsight 字段分批大小) 已在 `domain_config.py`
定义, 但当前 Agent 代码尚未接入分批逻辑 (预留常量, 未使用)。

---

## 3. Node 1: FieldInsightAgent

### 3.1 职责与流程

对每个字段生成领域洞察 — 观测事实 (确定性) + LLM 解读 (结合知识库)。**一个字段必产出
一条 insight** (LLM 输出数量必须等于字段数, 缺失的由确定性模板补齐)。

```
build_field_summaries(state) ──→ 无字段? ──→ 快速返回 (reason="no_fields")
build_source_summaries(state)
build_quality_context(state)
        │
        ▼
kb.search(field_names, entity_types, measurement_methods, keywords,
          categories=KB_CATEGORIES_FIELD_INSIGHT, top_k=KB_TOP_K)   ← RAG 检索
        │
        ▼
LLM (system: {domain} + {entity_type_reference} 注入; user: field/source/quality/knowledge)
  → re.search(r'\{.*\}') 提取 JSON → insights[]
  → 失败 → insights=[] (模板 fallback)
        │
        ▼
_merge_with_deterministic(field_summaries, insights, kb)
  → 确定性 observation 补全 + typical_range 兜底 → field_insights[]
```

### 3.2 确定性 observation 合并 (`_merge_with_deterministic`)

对每个字段摘要, 按 `(entity_type, entity_name, field_name)` 匹配 LLM 输出; 缺失字段补模板:

| 字段 | 来源 |
|------|------|
| `observation` | 确定性拼接: `value range: [...]` / `N records from M sources` / `units: [...]` / `methods: [...]` / `conditions: [...]`; 无数值 → `"No numeric values for {field}"` |
| `interpretation` | LLM 缺失 → `"LLM 不可用 — 仅提供确定性观测事实"` |
| `cause_hypotheses` | LLM 缺失 → `[]` |
| `typical_range` | LLM 已给 → 保留; 否则 `_typical_range_fallback` → `get_typical_range(entity_type, field_name)` (V4 fix) |
| `confidence` | LLM 缺失 → `0.0` |
| `evidence_sources` | 有 `context_snippets` → `[{"type": "data", "ref": "context_snippet"}]` |
| `kb_references` | LLM 缺失 → `[]` |

### 3.3 知识块注入 (`_format_knowledge_block`)

```
RELEVANT DOMAIN KNOWLEDGE:
---
[kb:{id}] {title}
{content[:500]}
Source: {source}
---
Use this knowledge to inform your analysis. Cite kb:IDs in evidence_sources.
```

知识库为空 → `"RELEVANT DOMAIN KNOWLEDGE: (none available)"` (纯 LLM 模式)。

### 3.4 输入输出

- **输入**: `field_summaries` (聚合: 值域/记录数/单位/方法/条件/置信度/上下文片段) + `source_summaries` (paper: abstract; database: description/research_content/methodology/waveband) + `quality_context` + RAG 检索结果
- **输出**: `report_state.insights.field_insights[]` (List[dict], 每字段一条)
- **常量**: `KB_CATEGORIES_FIELD_INSIGHT` = [physical_law, empirical_relation, measurement_principle, reference_range, galactic_model, method_comparison] (6 类); `KB_TOP_K=8`; `MAX_FIELD_SUMMARIES_CHARS=12000`; `MAX_SOURCE_SUMMARIES_CHARS=6000`; LLM `temperature=0.0`
- **Prompt**: `insight_prompts.yaml["field_insight"]`; system 含 `{domain}` + `{entity_type_reference}` (Simbad 类型参考, V4); user 含 4 个占位符

---

## 4. Node 2: RelationshipAgent

### 4.1 职责与流程

识别跨字段物理关系 (物理定律/相关性/条件依赖)。**V3.5 fix: 仅同实体字段对**
(`(entity_type, entity_name)` 相同的字段才生成候选, 防跨对象误配对, 如 FRB.dispersion_measure 与 Gaia.parallax)。

```
_build_standard_name_map(ctx)   ← schema_mapping.yaml target_schema_astrophysics aliases
_build_field_pairs(summaries)   ← 同实体约束 + record_count ≥ MIN_RECORDS_FOR_RELATION(2)
                                    + 上限 MAX_FIELD_PAIRS(30) + 去重
        │
        ├─ distinct_fields < 2 ──→ 跳过 LLM, _kb_preset_relationships
        │                          (data_evidence="insufficient_data", confidence=0.0)
        ▼
kb.search(field_names=pair_fields, categories=KB_CATEGORIES_RELATIONSHIP, top_k=KB_TOP_K)
        ▼
LLM → relationships[] (失败 → _kb_preset_relationships 兜底)
        ▼
r.setdefault("data_evidence", "sufficient_data") → relationships[]
```

### 4.2 字段对构建 (`_build_field_pairs`)

- 按 `(entity_type, entity_name)` 分组, `record_count < 2` 的组不参与 (统计无意义)
- 组内两两配对, key = `(ekey, sorted([std_a, std_b]))` 去重
- `raw` (DB 列名) / `standard` (标准名, 经 schema_mapping) 双记录
- 截断 `pairs[:MAX_FIELD_PAIRS]` (30)

### 4.3 知识库预定义关系 (`_kb_preset_relationships`)

LLM 跳过 (样本不足) 或 LLM 失败时使用: 对每对字段 `kb.search(field_names=[a,b], top_k=2)`,
命中条目的 `applies_to.fields` 含 a/b 任一时产出关系:

```python
"relationship_type": "physical_law" if category in ("physical_law", "empirical_relation",
                                                     "cosmological_relation") else "correlation"
"description": f"[kb:{kb_id}] {title} — {content[:200]}"
"data_evidence": "insufficient_data", "confidence": 0.0
```

### 4.4 输入输出

- **输入**: `field_insights[]` (Node 1) + `field_pairs` + RAG 检索 (physical_laws / astrophysical_models)
- **输出**: `report_state.insights.relationships[]` (每对关系一条, 含 `data_evidence` 标记)
- **常量**: `KB_CATEGORIES_RELATIONSHIP` = [physical_law, empirical_relation, galactic_model, cosmological_relation, cosmological_model] (5 类); `MAX_INSIGHTS_CHARS=10000`; `MAX_PAIRS_CHARS=6000`
- **Prompt**: `insight_prompts.yaml["relationship"]`; `relationship_type` 枚举: `physical_law|correlation|conditional|no_relationship`

---

## 5. Node 3: RecommendationAgent

### 5.1 职责与流程

数据使用建议 — 适用场景/局限性/caveats。**确定性组件 + LLM 组件合并**。

```
确定性组件:
  build_quality_context(state)          ← 评分/冲突/处理统计
  build_low_confidence_records(state)   ← paper extraction_confidence < 0.7 (DB 跳过)
  build_coverage_gaps(state)            ← Assessment completeness.missing_expected_fields
        │
        ▼
kb.search(entity_types, keywords=[domain], categories=KB_CATEGORIES_RECOMMENDATION, top_k=KB_TOP_K)
        ▼
LLM → rec dict (失败 → rec={} 模板 fallback)
        ▼
确定性合并:
  rec.setdefault("overall_grade", quality_ctx["quality_level"])
  rec.setdefault("suitable_use_cases" / "limitations" / "recommended_caveats", [])
  rec["low_confidence_records"] = low_conf[:50]     # MAX_LOW_CONF_RECORDS
  rec["coverage_gaps"] = coverage[:30]              # MAX_COVERAGE_GAPS
```

### 5.2 确定性组件

| 组件 | 函数 | 规则 |
|------|------|------|
| `low_confidence_records` | `build_low_confidence_records` | 仅 paper records; `extraction_confidence < LOW_CONFIDENCE_THRESHOLD (0.7)`; DB 记录跳过 (V3.4: 结构化提取视为高置信); 字段: record_id/field_name/entity_name/extraction_confidence |
| `coverage_gaps` | `build_coverage_gaps` | 遍历 `quality.sources[*].completeness.missing_expected_fields` → `"{sid}: missing [前5项]"` |
| `overall_grade` 默认 | — | LLM 未给时取 `quality_scoring.quality_level` |

### 5.3 输入输出

- **输入**: `field_insights` + `relationships` (Node 1+2) + `quality_context` + 两个确定性列表 + RAG (methodology)
- **输出**: `report_state.insights.recommendations` (dict, 非列表)
- **常量**: `KB_CATEGORIES_RECOMMENDATION` = [methodology, best_practice, reference_range] (3 类); `MAX_LOW_CONF_RECORDS=50`; `MAX_COVERAGE_GAPS=30`
- **Prompt**: `insight_prompts.yaml["recommendation"]`; 返回 JSON: `{"overall_grade": "excellent|good|fair|poor", "suitable_use_cases": [...], "limitations": [...], "recommended_caveats": [...]}`

---

## 6. Node 4: SynthesisAgent

### 6.1 职责与流程

综合 Node 1+2+3 输出 → `overall_narrative` (LLM 1 次) → 组装 `DataInsightsReport`
→ Pydantic 校验 → 写入 `insights_{timestamp}.json` → 更新 manifest → 写 `output_state.insights`。

```
insufficient_context_fields 检查:
  field_insights 为空 → append "field_insights"
  recommendations 为空 → append "recommendations"
        │
        ▼
LLM: overall_narrative (3-5 句) — system: "executive summary";
  user: {domain}/{n_insights}/{n_relationships}/{overall_grade}/{key_observations}
  key_observations = 每条 field_insight interpretation[:200] 的前 MAX_KEY_OBSERVATIONS(5) 条
  V3.5 fix: 仅接受 str 响应 (MagicMock/非字符串 → 模板叙述); MAX_NARRATIVE_CHARS=800 截断
        │
        ▼
模板 fallback: f"Analyzed {N} fields across {domain}. Overall grade: {grade}. \
               Found {M} cross-field relationships."
        │
        ▼
report = {research_domain, generated_at, field_insights, cross_field_relationships,
          usage_recommendations, overall_narrative, insufficient_context_fields}
  → DataInsightsReport.model_validate(report)  (失败 → 保留原始 dict)
        │
        ▼
文件写入: _resolve_output_dir(state, wf) → insights_{YYYYMMDD_HHMMSS}.json (utf-8, indent=2)
  → _find_manifest() 更新最新 manifest_*.json (files += basename, insights_written=True)
        │
        ▼
返回: output_state.insights = report; output_state.exported_files += [path]
      workflow_state: route_decision="", phase="done", execution_status="Success"
```

### 6.2 输出目录解析 (`_resolve_output_dir`)

1. `output_state.output_dir` 已存在 → 复用 (与 Export 文件同目录, V3.5 fix)
2. 否则: `EXPORT_OUTPUT_DIR` 环境变量 → 默认 `output/`; 子目录 `run_id[:8]`, 不存在则创建

### 6.3 输入输出

- **输入**: `report_state.insights` (field_insights/relationships/recommendations) + `workflow_state` (llm_call_count/run_id) + `output_state` (output_dir)
- **输出**: `output_state.insights` (完整 DataInsightsReport dict) + `output_state.exported_files` (追加) + 磁盘 `insights_{ts}.json`
- **常量**: `MAX_NARRATIVE_CHARS=800`; `MAX_KEY_OBSERVATIONS=5`; `_DEFAULT_OUTPUT_DIR = ../output`

---

## 7. 知识库体系

### 7.1 概览

`data/insight_knowledge/{domain}/*.yaml` — 存储理论性知识 (物理定律/测量理论/标准模型/
参考范围/方法论), 供洞察节点检索引用。**共 78 条, 5 个文件** (实测统计):

| 文件 | 条数 | category 分布 |
|------|------|--------------|
| `reference_ranges.yaml` | 20 | reference_range × 20 |
| `measurement_theory.yaml` | 16 | measurement_principle × 16 |
| `astrophysical_models.yaml` | 16 | galactic_model × 6, physical_law × 5, cosmological_model × 2, empirical_relation × 2, cosmological_relation × 1 |
| `physical_laws.yaml` | 13 | physical_law × 7, empirical_relation × 4, galactic_model × 1, method_comparison × 1 |
| `methodology.yaml` | 13 | methodology × 6, best_practice × 5, method_comparison × 2 |
| **合计** | **78** | |

### 7.2 条目结构

公共键 (除 physical_laws.yaml 外的 4 个文件):

| 键 | 说明 |
|----|------|
| `id` | 唯一 ID (如 `FRB_DM_range`, `NE2001_model`, `blackbody_radiation_law`) |
| `title` | 标题 (中文) |
| `category` | 类别 (10 种: physical_law / empirical_relation / measurement_principle / reference_range / galactic_model / cosmological_relation / cosmological_model / methodology / best_practice / method_comparison) |
| `tags` | 关键词列表 (检索匹配) |
| `applies_to` | 适用条件: `fields[]` / `entities[]` / `methods[]` |
| `content` | 正文 (中文, 含具体数值范围) |
| `source` | 出处 (如 "CHIME/FRB Catalog 2024; FRBSTATS.org") |
| `confidence` | 置信等级 (如 `established`) |

`physical_laws.yaml` 额外含: `version` / `last_updated` / `hypothetical_queries` / `related_entries`。

典型条目示例 (`reference_ranges.yaml` 首条):

```yaml
- id: FRB_DM_range
  title: FRB 色散量参考范围
  category: reference_range
  tags: [FRB, DM, range, typical, extreme]
  applies_to: {fields: [dispersion_measure], entities: [FRB]}
  content: '已知 FRB DM 范围 (截至 2024 年, >800 FRBs): ...'
  source: CHIME/FRB Catalog 2024; FRBSTATS.org
  confidence: established
```

### 7.3 检索评分 (`KnowledgeStore.search`, V1 关键词匹配)

权重从 `knowledge_store.py` 源码核实:

| 匹配维度 | 权重常量 | 值 | 匹配方式 |
|---------|---------|----|---------|
| `applies_to.fields` ∩ field_names | `_FIELD_SCORE` | **+5** | 双向子串 (`fn == ef or fn in ef or ef in fn`) |
| `tags` ∩ keywords | `_TAG_SCORE` | **+3** | 双向子串 |
| `applies_to.entities` ∩ entity_types | `_ENTITY_SCORE` | **+3** | 双向子串 |
| **父类匹配** (V4 fix) | `_PARENT_SCORE` = `ENTITY_TYPE_PARENT_SCORE` | **+2** | 查询实体的 Simbad 祖先链 (如 quasar → [agn, galaxy]) 命中条目; 低于直接命中, 不压过精确匹配 |
| `applies_to.methods` ∩ measurement_methods | `_METHOD_SCORE` | **+3** | 双向子串 |
| `category` ∩ categories | `_CATEGORY_SCORE` | **+2** | 精确匹配 |

- `score > 0` 的条目按分数降序, 取 `top_k` (KB_TOP_K=8), 返回含 `score` 字段 (round 2)
- 祖先链缓存: `_family_cache` (V4 fix, 一次配置加载 N 次查询复用), 取 `entity_ancestors(et)[1:]` (不含自身)
- `get_entry(kb_id)`: 按 id 取条目 (evidence_sources 引用解析用)

### 7.4 加载与降级

- `_KB_ROOT = <项目根>/data/insight_knowledge`; 加载 `{domain}` 目录下所有 `*.yaml` 的 `entries` (有序 glob)
- **按领域缓存**: `_stores: dict[str, KnowledgeStore]` (V3.5 fix — 每领域独立实例, 防跨领域复用污染); `get_knowledge_store(domain)`
- **降级链**: 目录不存在 / 文件解析失败 → 跳过 (警告) 不崩溃; 全部为空 → `search()` 返回 `[]` → 各节点注入 `"(none available)"` → 纯 LLM 模式
- `entry_count` 属性暴露加载条数

---

## 8. Simbad 对象类型体系

### 8.1 配置段 (`quality_rules.yaml` → `entity_types_astrophysics`)

消费方: `tools/insight/entity_types.py` (normalize/infer/ancestors/typical_range)。
实测统计: **153 个类型, 8 大类** (文件尾注释 "共 153 个类型 (8 大类)" 一致):

| 大类 | code | 类型数 | 典型类型 (code) |
|------|------|-------|-----------------|
| stars | `stars` | 67 | `*` star, `Ma*` massive_star, `WR*` wolf_rayet_star, `N*` neutron_star, `Psr` pulsar, `WD*` white_dwarf, `SN*` supernova, `BD*` brown_dwarf, `Pl` exoplanet, `Ce*` cepheid... |
| spectral | `spectral` | 22 | `Rad` radio_source, `IR` infrared_source, `X` xray_source, `gam` gamma_ray_source, `gB` gamma_ray_burst, `rB` radio_burst... |
| galaxies | `galaxies` | 19 | `G` galaxy, `AGN` agn, `QSO` quasar, `Bla` blazar, `SyG` seyfert_galaxy, `SBG` starburst_galaxy, `rG` radio_galaxy... |
| ism | `ism` | 16 | `ISM` ism_object, `HII` hii_region, `SNR` supernova_remnant, `Cld` cloud, `MoC` molecular_cloud... |
| gravitation | `gravitation` | 9 | `BH` black_hole, `gLS` gravitational_lens_system, `GWE` gravitational_wave_event, `Lev` microlensing_event... |
| galaxy_sets | `galaxy_sets` | 8 | `ClG` galaxy_cluster, `GrG` galaxy_group, `SCG` supercluster, `PaG` galaxy_pair... |
| star_sets | `star_sets` | 6 | `Cl*` cluster_of_stars, `GlC` globular_cluster, `OpC` open_cluster... |
| misc | `misc` | 6 | `mul` blend, `err` not_an_object, `?` unknown_object, `reg` sky_region... |
| **合计** | | **153** | |

- 头部: `version: "1.0"`, `source: "Simbad otypes.list, generated 2026-07-30"`, `default_entity_type: galaxy`
- 条目结构: `{code: {name, desc, cat, parent, candi, bad, kws[], sem[]}}` (code 为 YAML 键, 引号包裹 — `*`/`?` 为 YAML 保留字符)
- `sem[]`: 该类型典型可测物理量 (如 `G` galaxy 含 redshift/stellar_mass/distance/metallicity/extinction/luminosity/apparent_magnitude/radial_velocity/flux_density)

### 8.2 3 层推断链 (`infer_entity_type`)

优先级从高到低 (配置缺失 → 返回 `default_entity_type`="galaxy"):

| 优先级 | 层级 | 规则 | 配置内容 (实测) |
|--------|------|------|----------------|
| 1 | `catalog_inference` | `vizier_table_id` 前缀匹配 (目录本身定义对象性质) | III/135A→star (HD), II/125→galaxy (IRAS PSC), VII/237→galaxy (HYPERLEDA), VII/26D→galaxy (UGC), VII/233→galaxy (2MASS XSC) — 5 条 |
| 2 | `field_inference` | 字段名精确匹配 | distance/metallicity/stellar_mass/mass/extinction/radial_velocity/redshift→galaxy; sp_t/spectral_type→star — 9 条 |
| 3 | `field_class_inference` | 字段语义类型 (复用 `tools.assessment.semantic_type.infer_semantic_type`) → 实体 | parallax/proper_motion_ra/proper_motion_dec/effective_temperature/surface_gravity/stellar_radius/rotational_velocity→star — 7 条 |
| 4 | 默认 | — | `default_entity_type` = galaxy |

### 8.3 4 个消费函数

| 函数 | 行为 |
|------|------|
| `normalize_entity_type(entity_type, field_name, source, domain)` | "Unknown"/空/none/n/a → `infer_entity_type`; 已知值 → 规范名原样 (小写); `kws` 别名 → 规范名; 未识别 → 小写原样返回 (兼容 FRB 等非 Simbad 类型, KB 双向子串匹配不受影响) |
| `infer_entity_type(field_name, source, domain)` | 见 8.2 三级推断链; 配置缺失 → "galaxy" |
| `entity_ancestors(entity_type, domain)` | `[自身]` + 按 `parent` code 链上溯全部祖先规范名; 层级 ≤4, 上溯 guard < 8 (安全上限); 如 quasar → [quasar, agn, galaxy]; 未知类型 → `[自身小写]` |
| `get_typical_range(entity_type, field_name, domain)` | 兜底: `typical_ranges[实体][语义键]` → `"{lo}~{hi} {unit}"`; unit 取 `semantic_types_astrophysics[语义键].units[0]` (如 dispersion_measure → "cm^-3 pc"); 大数科学计数法 `%.2e` (≥1e6 或 <1e-3); 无匹配 → None |

`build_entity_type_reference(field_summaries, domain)`: 构建 prompt 的 `{entity_type_reference}`
内容 — 对数据中出现的实体类型去重排序, 每类一行 `"  {name} ({code}){ , parent: X}{; typical k1 1.0e+00~..., k2...(前3键)}"`;
配置缺失/无实体 → 返回空串 (**绝不残留占位符**, V4 fix)。

### 8.4 typical_ranges (实体级 sanity check, 实测 18 个实体)

`star`, `main_sequence_star`, `supergiant`, `red_supergiant`, `white_dwarf`,
`neutron_star`, `brown_dwarf`, `t_tauri_star`, `red_giant_star`, `galaxy`,
`agn`, `quasar`, `supernova_remnant`, `cluster_of_stars`, `exoplanet`,
`hii_region`, `starburst_galaxy`, `pulsar`。

示例: `star.stellar_mass: [0.1, 100]` (Msun), `galaxy.stellar_mass: [1e6, 1e13]` (Msun),
`pulsar.dispersion_measure: [1, 3000]` (cm^-3 pc), `quasar.redshift: [0.1, 8]`。

### 8.5 配置缺失降级

`_load(domain)` 失败/缺段 → 空 dict → `normalize` 返回小写原样、`infer` 返回 "galaxy"、
`ancestors` 返回 `[自身]`、`get_typical_range` 返回 None、`build_entity_type_reference` 返回
空串 — **全程不抛异常**。按 domain 缓存 (`_CFG` dict, 镜像 semantic_type.py 模式)。

---

## 9. State 读写

### 9.1 读取的 State

| State 路径 | 读取者 | 用途 |
|-----------|--------|------|
| `data_state.current_data.records` | Node 1, 2, 3 | 记录聚合 (entity_type/entity_name/field_name/field_value/field_unit/extraction_confidence/context_snippet/measurement_method/condition_tags/provenance.raw_column) |
| `data_state.current_data.sources` | Node 1, 3 | 来源元数据 (source_type/title/abstract/research_content/research_methodology/waveband/vizier_table_id...) |
| `context_state.research_domain` | 全部 | 领域 (默认 "astrophysics") |
| `report_state.quality.quality_scoring` | Node 1, 3 | overall_score/quality_level/calibrated_confidence |
| `report_state.quality.multi_source_variance` | Node 1, 3 | anomaly_count / variance_count |
| `report_state.quality.route_counts` | Node 1 | 路由统计 |
| `report_state.quality.sources[*].completeness` | Node 3 | `missing_expected_fields` → coverage_gaps |
| `report_state.conflict.resolution_report` | Node 1 | status / route_decision (质量上下文) |
| `report_state.normalization.modifications` | Node 1 | total (质量上下文) |
| `report_state.insights.*` | Node 2, 3, 4 | 上游节点累积结果 (field_insights/relationships/recommendations) |
| `workflow_state.llm_call_count` | 全部 | 累计 LLM 调用计数 |
| `workflow_state.tool_call_count` / `loop_round` | Node 1 | 质量上下文 |
| `workflow_state.run_id` | Node 4 | 输出目录 `run_id[:8]` |
| `output_state.output_dir` | Node 4 | 输出目录复用 (V3.5) |

### 9.2 写入的 State

| State 路径 | 写入者 | 内容 |
|-----------|--------|------|
| `report_state.insights.field_insights` | Node 1 | List[dict] 字段洞察 (每字段一条) |
| `report_state.insights.relationships` | Node 2 | List[dict] 跨字段关系 |
| `report_state.insights.recommendations` | Node 3 | dict (overall_grade/use_cases/limitations/caveats/low_confidence_records/coverage_gaps) |
| `output_state.insights` | Node 4 | 完整 DataInsightsReport (Pydantic 校验后 dump) |
| `output_state.exported_files` | Node 4 | 追加 `insights_{ts}.json` (reducer 覆盖, 与 export 文件共存) |
| `workflow_state.current_node` | 全部 | field_insight / relationship / recommendation / synthesis |
| `workflow_state.execution_status` | 全部 | "Success" |
| `workflow_state.llm_call_count` | 全部 | 累加 (每节点成功 +1) |
| `workflow_state.workflow_history` | 全部 | 追加 WorkflowRecord (agent/stage/status/timestamp/duration/reason) |
| `workflow_state.phase` | Node 4 | "done" |
| `workflow_state.route_decision` | Node 4 | "" (空 — Insights 为终节点) |

磁盘副作用: `output/{run_id[:8]}/insights_{YYYYMMDD_HHMMSS}.json` + 最新 `manifest_*.json`
更新 (`files` 追加 + `insights_written=true`)。

### 9.3 Pydantic 输出模型 (`models/insights.py`)

| 模型 | 说明 |
|------|------|
| `EvidenceSource` | type: `Literal["data", "knowledge_base"]`; ref (如 "context_snippet" / "kb:NE2001_model") |
| `FieldInsight` | entity_type/entity_name/field_name/source_type/observation/interpretation/cause_hypotheses/typical_range/confidence (0-1)/evidence_sources/kb_references |
| `CrossFieldRelationship` | field_a/field_b/`relationship_type: Literal["physical_law","correlation","conditional","no_relationship"]`/description/`data_evidence` (默认 "insufficient_data")/confidence/kb_references |
| `DataUsageRecommendation` | overall_grade (默认 "unknown")/suitable_use_cases/limitations/recommended_caveats/low_confidence_records/coverage_gaps |
| `DataInsightsReport` | research_domain/generated_at/field_insights/cross_field_relationships/usage_recommendations/overall_narrative/insufficient_context_fields |

---

## 10. 异常处理

| 层级 | 异常 | 策略 |
|------|------|------|
| Node 1 | LLM 失败 / JSON 解析失败 | 模板 fallback: `_merge_with_deterministic` 确定性 observation 补全, interpretation="LLM 不可用 — 仅提供确定性观测事实", confidence=0.0 |
| Node 1 | `build_entity_type_reference` 异常 (V4) | `try/except` → `et_ref=""` (prompt 占位符替换为空, 不残留) |
| Node 1 | 无字段 | 快速返回 (reason="no_fields") |
| Node 2 | 字段数 < 2 | 跳过 LLM, 仅 `_kb_preset_relationships` (data_evidence="insufficient_data", confidence=0.0) |
| Node 2 | LLM 失败 | 同上 kb preset 兜底 |
| Node 2 | `schema_mapping.yaml` 缺失/解析失败 | `_build_standard_name_map` 返回空映射 → 字段名原样 (标准名=原列名) |
| Node 3 | LLM 失败 | `rec={}` + 确定性合并 (overall_grade 取 quality_level) |
| Node 4 | LLM 失败 / 响应非 str (V3.5: MagicMock 防护) | 模板叙述: "Analyzed N fields across {domain}. Overall grade: X. Found Y cross-field relationships." |
| Node 4 | Pydantic 校验失败 | 保留原始 dict (不阻塞) |
| Node 4 | 文件写入失败 | 跳过落盘, 继续返回 output_state (warning) |
| Node 4 | manifest 缺失/更新失败 | 跳过 manifest, 不阻塞 |
| 知识库 | 目录不存在 / yaml 解析失败 | 跳过该文件 (warning) 不崩溃; 空库 → search() 返回 [] → "(none available)" 注入 → 纯 LLM 模式 |
| 实体类型 | 配置缺失 (V4) | 全部安全降级: normalize 原样小写 / infer "galaxy" / ancestors [自身] / typical_range None / reference 空串, 不抛异常 |
| 通用 | LLM JSON 提取 | `re.search(r'\{.*\}', text, DOTALL)` 提取首个 JSON 对象 (所有 4 节点一致) |

**Graph 层**: 4 节点恒连边、无条件分支, 无 Retry/Loop/Failed 概念; 各节点
`workflow_state.execution_status` 恒为 "Success" (LLM 失败已被模板兜底吸收)。

---

## 11. 文件清单

```
Data_Insights_agentV1/
├── insights_graph.py                    # 63 行, 纯编排 (4 节点线性, V3.4)
├── __init__.py
└── agents/
    ├── field_insight_agent.py           # Node 1: RAG + LLM 解读 + 确定性 observation 合并
    ├── relationship_agent.py            # Node 2: 同实体字段对 + 物理关系识别
    ├── recommendation_agent.py          # Node 3: 使用建议 + 确定性 low_conf/coverage
    └── synthesis_agent.py               # Node 4: 综合叙述 + 落盘 + output_state

tools/insight/
├── __init__.py
├── context_builder.py                   # 字段/来源/质量上下文构建 + 语义聚合 + 确定性组件
├── knowledge_store.py                   # 知识库加载 + 关键词评分检索 + 领域缓存
├── entity_types.py                      # Simbad 类型消费层 (normalize/infer/ancestors/typical_range)
└── embedder.py                          # V2 向量检索接口占位 (未启用, 抛 NotImplementedError)

configs/
├── domain_config.py                     # Astronomy Domain Adapter (V3.5): 全部领域常量
├── insight_prompts.yaml                 # 4 节点 prompt 模板 + entity_type_reference 占位符
└── quality_rules.yaml                   # entity_types_astrophysics 段 (153 类型/8 大类/typical_ranges 18 实体)

data/insight_knowledge/astrophysics/
├── reference_ranges.yaml                # 20 条
├── measurement_theory.yaml              # 16 条
├── astrophysical_models.yaml            # 16 条
├── physical_laws.yaml                   # 13 条 (含 version/last_updated 等扩展键)
└── methodology.yaml                     # 13 条
   （合计 78 条）

共享:
├── quality_state.py                     # report_state.insights (L124) / output_state.insights (L195)
├── models/insights.py                   # DataInsightsReport 等 5 个 Pydantic 模型
├── utils/llm.py                         # get_llm / set_agent_context / track_raw_llm_call
└── graph.py                             # 主图: NODE_INSIGHTS, Export → Insights → END (V3.4)
```

**主图接线** (`graph.py`, V3.4): `NODE_INSIGHTS = "insights_graph"` → `graph.add_node(NODE_INSIGHTS, build_insights_graph().compile())` → `graph.add_edge(NODE_EXPORT, NODE_INSIGHTS)` → `graph.add_edge(NODE_INSIGHTS, END)`。
