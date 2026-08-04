# SubGraph 4: 数据清洗与质检子图 (V4.3)

> 科学文献数据管道 — 数据清洗与质检子图 (V4.3)  
> AI-Scientist 2026 挑战杯项目 | 后半部分模块

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)](https://langchain.com/langgraph)
[![Pydantic](https://img.shields.io/badge/pydantic-v2-red)](https://docs.pydantic.dev/)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%20v4--flash-orange)](https://deepseek.com)

## 项目概述

本模块是整个 LangGraph 多智能体科学数据处理管道的 **第 4 个子图 (SubGraph 4)**，负责对上游提取子图产出的 grounded_data 进行 **质量评估 → 规范化清洗 → 冲突/方差分析 → 结构化导出 → 数据洞察** 的完整闭环。

### 管道位置

```
START → 意图澄清(SubGraph1) → 文献检索(SubGraph2)
     → 文字提取(SubGraph3) → ★ 数据清洗与质检(SubGraph4) → END
```

### 六个子模块

| 模块 | 版本 | 职责 | 修改数据 |
|------|------|------|---------|
| **Assessment** | V3.1 / V4.2 | 质量评估 (4 Stage) + per-source 路由决策 | ❌ |
| **Normalization** | V2.3 / V4.3 | 规范化清洗 (5 Stage) — **唯一有权修改数据** | ✅ |
| **Variance Analysis** (原 Conflict) | V3.0 | 多源方差特征化 + 异常检测 + 全量保留标注 | ❌ |
| **Export** | V1.0 | 结构化输出 (6 Stage) — 多格式 + 溯源 + 元数据 | ❌ |
| **Insights** | V3.4 | 科学数据洞察 (4 Node) — 知识库 RAG + Simbad 类型体系 | ❌ |
| **HumanReview** | V1.0 | 命令行人工审核 (E→A/B 双向路由) | ❌ |

## 架构

```
Main Graph (graph.py + routers.py, 198 行)
│
├── Assessment → gate_assessment → Dispatch → 按 per_source_routes 分发
│     ├── 有 Normalization → Normalization (先清洗)
│     ├── 有 Conflict (无 Norm) → Variance
│     ├── 全 Export → Export
│     └── 纯 HumanReview → HumanReview
│
├── Normalization ⇄ Variance 循环 (gate → LoopController, 最多 3 次)
│     └── pre_normalization 簿记 (iteration_counter + pending_sources)
│
├── Export (三路汇聚 A→D / B→D / C→D)
│
└── Insights (Export → Insights → END, V3.4)
```

**Gate 层 (V4 fix)**：不覆写业务路由；Failed→HumanReview 经 human_target 簿记（Assessment→Dispatch、Norm/Conflict→Loop）。

### 配置体系 (V4.3)

| 配置文件 | 内容 |
|---------|------|
| `quality_rules.yaml` | 语义类型 **32 键**（keywords/units/feasible_ranges/unit_category）、Simbad 对象类型 **153 个/8 大类**、typical_ranges 18 实体、领域权重、期刊分级、loop_control |
| `schema_mapping.yaml` | target_schema_astrophysics **28 字段 / 1178 别名**（含 database_catalog_properties 919，覆盖 23 个 VizieR 目录 1072 列）、unit_conversions_astrophysics **34 组 257 条** |
| `insight_prompts.yaml` | Insights 4 节点 prompt 模板（含 entity_type_reference 注入） |
| `domain_config.py` | 领域常量（KB_TOP_K / ENTITY_TYPE_PARENT_SCORE 等） |
| `llm_config.yaml` / `value_parser_rules.yaml` | LLM 配置 / 数值解析规则 |

**数据源**（项目根）：`vizier_catalogs_schema.json`（23 个 VizieR 目录列定义）+ `query_results_progress_final.json`（25 天体多目录查询）→ 生成脚本 `scripts/gen_catalog_schema.py`（行级合并/幂等/备份回滚）。

**生成脚本**：`gen_entity_types.py`（153 类型）/ `gen_astro_units.py`（单位组）/ `gen_catalog_schema.py`（目录别名+单位）/ `append_knowledge.py`（知识库）。

## 目录结构

```
V1\子图4部分代码\
├── graph.py                      # Main Graph 编排 (198 行)
├── routers.py                    # 控制层: Retry + Gate + Router + Loop
├── quality_state.py              # State 定义 + Reducer + 工厂函数
│
├── Data_Assessment_agentV1/      # Assessment SubGraph (4 Stage)
│   ├── assessment_graph.py       # 87 行
│   ├── ASSESSMENT_DESIGN_REPORT.md
│   └── agents/                   # profiling / quality_assessment / quality_scoring / decision_reasoning
│
├── Data_Normalization_agentV1/   # Normalization SubGraph (5 Stage)
│   ├── normalization_graph.py    # 138 行
│   ├── NORMALIZATION_DESIGN_REPORT.md
│   ├── README.md
│   └── agents/                   # source_router / planning / normalization / validation / report
│
├── Data_Conflict_agentV1/        # Variance Analysis SubGraph (5 Stage)
│   ├── conflict_graph.py         # 151 行
│   ├── CONFLICT_DESIGN_REPORT.md
│   ├── agents/                   # 5 个 Agent (逻辑内联, 0 Tools)
│   └── legacy/                   # resolution_reasoning_agent.py (已废弃)
│
├── Data_Export_agentV1/          # Export SubGraph (6 Stage)
│   ├── export_graph.py           # 109 行
│   ├── EXPORT_DESIGN_REPORT.md
│   └── agents/                   # 6 个 Agent
│
├── Data_Insights_agentV1/        # Insights SubGraph (4 Node)
│   ├── insights_graph.py         # 63 行
│   ├── INSIGHTS_DESIGN_REPORT.md
│   └── agents/                   # field_insight / relationship / recommendation / synthesis
│
├── Data_HumanReview_agentV1/     # Human Review
│   ├── HUMAN_REVIEW_DESIGN_REPORT.md
│   └── human_review_agent.py     # 命令行交互
│
├── configs/                      # 配置文件体系 (8 文件, 见上)
├── models/                       # Pydantic v2 (grounded_data / source / record / insights)
├── tools/                        # 工具层 (assessment 16 / normalization 6 / conflict 8 / export 6 / insight 6)
├── data/insight_knowledge/       # 知识库 (astrophysics 78 条, 5 yaml)
├── scripts/                      # 配置生成脚本 (4 个, 幂等)
├── utils/                        # llm / logger / retry
├── schemas/                      # LLM 输出 Schema
└── test/                         # 测试 (见下方"测试")
```

## 快速开始

### 环境要求

```bash
python >= 3.10
pip install langgraph langchain-openai pydantic pyyaml
```

### 配置 LLM

编辑 `configs/llm_config.yaml`:

```yaml
model: "deepseek-v4-flash"        # 或 gpt-4o / deepseek-v4-pro
api_key: "sk-your-key-here"
base_url: "https://api.deepseek.com"  # OpenAI 可留空
temperature: 0.0
timeout: 120                      # 请求超时秒数
max_retries: 3
structured_output_method: "function_calling"  # DeepSeek 建议 prompt_parsing
```

### 运行测试

```bash
cd 子图4部分代码

# 单元回归 (V4 修复 + 单位 + 实体类型, 无 LLM)
python -m unittest test.test_fix_regression        # 23 用例

# Insights 测试 (知识库 + Simbad 类型, 无 LLM)
python -m unittest test.test_insights_graph        # 12 用例

# 主图路由测试 (无 LLM)
python -m unittest test.test_main_graph_routing    # 9 用例

# 零 LLM 全链路验证 (真实数据 + mock LLM, ~10s)
python test/test_real_data_e2e_mock.py             # 10 条抽样
python test/test_real_data_e2e_mock.py --data result_9e76f974-....json   # 全量 219 条

# 真实 LLM 端到端 (10 条抽样, ~10min, 需 API 余额)
python test/test_real_data_e2e.py --data test_data_sample10.json

# Assessment / Normalization 流程测试
python test/test_assessment_flow.py
python test/test_normalization_flow.py
```

## 数据输入格式

输入 `grounded_data` JSON (上游提取子图产出, schema_version 2.0.0):

```json
{
  "schema_version": "2.0.0",
  "sources": [
    {
      "source_id": "SRC_DB_IRAS",
      "source_type": "database",
      "title": "IRAS Point Sources",
      "vizier_table_id": "II/125/iraspsc",
      "research_content": "IRAS 12/25/60/100um photometry",
      "research_methodology": "Space-based infrared survey",
      "waveband": "IR 12-100um"
    },
    {
      "source_id": "2001AJ....121.2557D",
      "source_type": "paper",
      "doi": "10.1086/319976",
      "title": "M31 distances from Cepheids",
      "year": 2001
    }
  ],
  "records": [
    {
      "record_id": "r1",
      "source_id": "SRC_DB_IRAS",
      "field_name": "Fnu_60",
      "field_value": 7.65,
      "field_unit": "Jy",
      "extraction_method": "database_query",
      "provenance": {"db_table": "II/125/iraspsc", "key_column": "IRAS", "key_value": "00398+4039", "raw_column": "Fnu_60"}
    },
    {
      "record_id": "r2",
      "source_id": "2001AJ....121.2557D",
      "field_name": "distance",
      "field_value": "24.47 ± 0.12 (= 783 ± 43 kpc)",
      "field_unit": "mag / kpc",
      "extraction_method": "vlm_text",
      "trace_id": "doc1_p3_tb2_r1",
      "provenance": {"page": 3, "bbox": [120, 340, 280, 355]}
    }
  ]
}
```

## 输出

### 路由决策 (Assessment Stage 4, 0 LLM 规则引擎)

```python
report_state.quality = {
    "profile": {...},                  # Stage 1: 8 维度画像 (semantic_types 32 键)
    "sources": {...},                  # Stage 2: per-source 评估 + conflict_risk (Cohen's d)
    "multi_source_variance": {...},    # 全局方差特征化 + 异常检测
    "quality_scoring": {...},          # Stage 3: 加权评分 + 校准
    "per_source_routes": {...},        # Stage 4: 每 source 路由
    "conditional_routes": [...],       # 条件路由 {condition, route, reason}
    "route_counts": {...}              # 路由分布统计 (Dispatch 依据)
}
```

路由类型: `Export` / `Normalization` / `Conflict` / `HumanReview`

### 最终输出 (Export → Insights)

```python
output_state = {
    "structured_data": {...},          # JSON (长表/宽表) + CSV (15 列)
    "metadata": {...},                 # 字段定义 + 来源汇总 + 处理记录
    "traceability": {...},             # 数据世系 + 逐条溯源 + Agent 决策链 (含 duration_s)
    "quality_summary": {...},          # 综合评分 + 风险指标
    "insights": {...},                 # DataInsightsReport (V3.4)
    "schema_version": "2.0.0",
    "exported_files": [...],           # 输出 output/{run_id[:8]}/
}
```

## 设计文档

- [总架构设计方案.md](总架构设计方案.md) — 总架构 (V4.3): Main Graph / State / 路由 / 配置体系
- [ASSESSMENT_DESIGN_REPORT.md](Data_Assessment_agentV1/ASSESSMENT_DESIGN_REPORT.md) — Assessment (V3.1/V4.2)
- [NORMALIZATION_DESIGN_REPORT.md](Data_Normalization_agentV1/NORMALIZATION_DESIGN_REPORT.md) — Normalization (V2.3/V4.3)
- [CONFLICT_DESIGN_REPORT.md](Data_Conflict_agentV1/CONFLICT_DESIGN_REPORT.md) — Variance Analysis (V3.0)
- [EXPORT_DESIGN_REPORT.md](Data_Export_agentV1/EXPORT_DESIGN_REPORT.md) — Export (V1.0)
- [INSIGHTS_DESIGN_REPORT.md](Data_Insights_agentV1/INSIGHTS_DESIGN_REPORT.md) — Insights (V3.4/V4.2)
- [HUMAN_REVIEW_DESIGN_REPORT.md](Data_HumanReview_agentV1/HUMAN_REVIEW_DESIGN_REPORT.md) — HumanReview (V1.0)

## License

MIT
