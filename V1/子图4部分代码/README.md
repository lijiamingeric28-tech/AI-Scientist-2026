# SubGraph 4: Data Quality Assessment Pipeline

> 科学文献数据管道 — 数据清洗与质检子图 (V2.0)  
> AI-Scientist 2026 挑战杯项目 | 后半部分模块

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)](https://langchain.com/langgraph)
[![Pydantic](https://img.shields.io/badge/pydantic-v2-red)](https://docs.pydantic.dev/)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%20v4--pro-orange)](https://deepseek.com)

## 项目概述

本模块是整个 LangGraph 多智能体科学数据处理管道的 **第 4 个子图 (SubGraph 4)**，负责对上游提取子图产出的结构化科学数据进行 **质量评估、评分、路由决策**。

核心思路：**每篇论文独立评估 → per-source 分流 → 下游模块按需处理**。

### 管道位置

```
START → 意图澄清(SubGraph1) → 文献检索(SubGraph2)
     → 文字提取(SubGraph3) → ★ 数据质量评估(SubGraph4) → 结构化输出 → END
```

## 架构

```
Main Graph (graph.py + routers.py)
│
├── AssessmentGraph (Data_Assessment_agentV1/)
│   ├── Stage 1: ProfilingAgent        — 8 Tools, 0 LLM
│   ├── Stage 2: QualityAssessmentAgent — 5 Tools × N, LLM 完整性分析
│   ├── Stage 3: QualityScoringAgent    — 领域权重 + 惩罚 + 校准
│   └── Stage 4: DecisionReasoningAgent — LLM 决策 + 条件路由
│
├── NormalizationGraph (stub)
├── ConflictGraph (stub)
└── ExportGraph (stub)
```

### 12 项 V2.0 优化

| Phase | Tool | 功能 |
|-------|------|------|
| P1 | DistributionProfiler | skewness/kurtosis/quantiles/IQR 分布分析 |
| P2 | OutlierDetector | IQR + Modified Z-Score 双策略异常检测 |
| P3 | SemanticTypeInferrer | 10 种物理量类型推断 + 物理可行性验证 |
| A1 | AdaptiveThresholdEngine | 三维度动态阈值 (关键性 × 样本量 × 领域) |
| A2 | Statistical Conflict Detector | Cohen's d 效应量 + 置信区间 |
| A3 | LLM Completeness Analyzer | LLM 分类缺失字段 (expected/optional/irrelevant) |
| S1 | Domain-Adaptive Weights | 材料科学/天体物理/默认 三套权重 |
| S2 | Nonlinear Penalties | 系统性失败 ×0.7 + 稀疏性对数惩罚 |
| S3 | Confidence Calibration | 数据量 × 一致性 × 稀疏性 三因子校准 |
| D1 | LLM Decision | LLM 结构化 per-source 路由决策 |
| D2 | Decision Matrix | Quality × Repair Cost 二维矩阵 |
| D3 | Conditional Routes | {condition, route, reason} 条件路由 |

## 目录结构

```
├── graph.py                     # Main Graph (编排 + 路由)
├── routers.py                   # Retry/Loop/Router 控制器
├── quality_state.py             # LangGraph State 定义
├── normalization_graph.py       # Normalization SubGraph (stub)
├── conflict_graph.py            # Conflict SubGraph (stub)
├── export_graph.py              # Export SubGraph (stub)
│
├── models/                      # Pydantic v2 数据模型
│   ├── source.py                # Source (源文献)
│   ├── record.py                # Record + Provenance (提取记录)
│   └── grounded_data.py         # GroundedData (顶层容器)
│
├── schemas/                     # JSON Schema + 结构化输出模型
│   ├── grounded_data_v1.json    # 接口契约 JSON Schema
│   └── __init__.py              # Pydantic LLM Schema (AssessmentDecision 等)
│
├── configs/                     # 配置
│   ├── llm_config.yaml          # LLM API 配置
│   ├── quality_rules.yaml       # 质量规则 (阈值/权重/领域)
│   └── schema_mapping.yaml      # Schema 字段映射
│
├── utils/                       # 基础设施
│   ├── llm.py                   # LLM 工厂 (3 策略自动回退 + 统计)
│   ├── logger.py                # 日志
│   └── retry.py                 # 重试装饰器
│
├── tools/assessment/            # 14 个评估工具
│   ├── profiling.py             # 基础统计
│   ├── completeness.py          # 完整性评估
│   ├── consistency.py           # 一致性评估
│   ├── format_checker.py        # 格式检查
│   ├── source_checker.py        # 来源可信度
│   ├── quality_scoring.py       # 加权评分
│   ├── conflict_detector.py     # 传统冲突检测
│   ├── distribution.py          # P1: 分布分析
│   ├── outlier.py               # P2: 异常值检测
│   ├── semantic_type.py         # P3: 语义推断
│   ├── adaptive_threshold.py    # A1: 自适应阈值
│   ├── statistical_conflict.py  # A2: Cohen's d 冲突检测
│   └── llm_completeness.py      # A3: LLM 完整性分析
│
├── Data_Assessment_agentV1/     # ★ Assessment 模块
│   ├── assessment_graph.py      # Assessment SubGraph
│   ├── ASSESSMENT_DESIGN_REPORT.md
│   ├── OPTIMIZATION_ROADMAP.md
│   └── agents/
│       ├── profiling_agent.py           # Stage 1: 数据画像
│       ├── quality_assessment_agent.py  # Stage 2: 质量评估
│       ├── quality_scoring_agent.py     # Stage 3: 综合评分
│       └── decision_reasoning_agent.py  # Stage 4: 路由决策
│
└── test/                        # 入口 + 测试
    ├── app_quality.py           # CLI 入口
    ├── mock_data.py             # Mock 数据
    ├── generate_test_data.py    # 测试数据生成器
    ├── test_full_pipeline.py    # 完整流程测试
    ├── test_assessment_flow.py  # Assessment 流程测试
    └── test_pipeline.py         # 单元测试套件
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
model: "deepseek-v4-pro"       # 或 gpt-4o / deepseek-v4-flash
api_key: "sk-your-key-here"
base_url: "https://api.deepseek.com"  # OpenAI 可留空
temperature: 0.0
structured_output_method: "prompt_parsing"  # DeepSeek 推荐
```

### 运行

```bash
cd 子图4部分代码

# 运行完整测试 (3篇论文, 模拟数据)
python test/test_full_pipeline.py

# 运行 Assessment 流程测试 (8组数据)
python test/test_assessment_flow.py

# 运行单元测试
python test/test_pipeline.py

# CLI 入口
python test/app_quality.py
```

## 数据输入格式

输入 `grounded_data` JSON (上游提取子图产出):

```json
{
  "schema_version": "1.0.0",
  "sources": [
    {
      "source_id": "10.1016/j.msea.2023.001",
      "source_type": "paper",
      "doi": "10.1016/j.msea.2023.001",
      "title": "High-temperature tensile properties of Al-7075 alloy",
      "authors": ["Zhang, W.", "Li, H."],
      "year": 2023,
      "journal": "Materials Science and Engineering: A",
      "access_path": "/cache/msea_2023_001.pdf",
      "retrieval_priority": 0.95
    }
  ],
  "records": [
    {
      "record_id": "p1_yield_1",
      "source_id": "10.1016/j.msea.2023.001",
      "field_name": "yield_strength",
      "field_value": 450,
      "field_unit": "MPa",
      "trace_id": "doc1_p3_tb2_r1",
      "provenance": {"page": 3, "bbox": [120, 340, 280, 355]},
      "extraction_method": "llm_table"
    }
  ]
}
```

## 输出

### Quality Report

每篇论文独立评估，输出结构化报告:

```python
report_state.quality = {
    "profile": {...},           # Stage 1: 8 维度画像
    "sources": {                # Stage 2: per-source
        "doi_A": {
            "completeness": {"score": 0.97},
            "consistency":  {"score": 1.00},
            "conflict_risk": {"method": "cohens_d", "conflict_count": 0},
            "llm_completeness": {"summary": "..."}
        }
    },
    "quality_scoring": {        # Stage 3
        "overall_score": 0.9733,
        "quality_level": "excellent",
        "calibrated_confidence": 0.86
    },
    "route_decision": "Export", # Stage 4: 全局路由
    "per_source_routes": {...}, # 每篇论文路由
    "conditional_routes": [...],# 条件路由
    "decision_matrix": {...}    # 决策矩阵
}
```

### 路由分流

```
workflow_state.route_decision
  "Export"         → 数据可直接使用
  "Normalization"  → 需字段映射/单位转换/缺失值处理
  "Conflict"       → 存在跨来源数据冲突
  "HumanReview"    → 需人工介入
```

## 下游模块接口

| 下游模块 | 读取的 State | 用途 |
|---------|-------------|------|
| NormalizationGraph | `sources[sid].issues`, `profile.semantic_types` | 知道修复什么 |
| ConflictGraph | `sources[sid].conflict_risk.conflicts[*]` | Cohen's d 效应量指导解决 |
| ExportGraph | `profile`, `quality_scoring`, `per_source_routes` | 生成报告 + 分流导出 |

详见 `Data_Assessment_agentV1/ASSESSMENT_DESIGN_REPORT.md` 第 6 节。

## 测试

```bash
# 单元测试 (18 tests, 含 Schema 校验 + Agent + 端到端)
python test/test_pipeline.py

# 完整 V2.0 流程测试 (3 papers, 含 LLM, ~2min)
python test/test_full_pipeline.py
```

## 设计文档

- [ASSESSMENT_DESIGN_REPORT.md](Data_Assessment_agentV1/ASSESSMENT_DESIGN_REPORT.md) — V2.0 详细设计报告
- [OPTIMIZATION_ROADMAP.md](Data_Assessment_agentV1/OPTIMIZATION_ROADMAP.md) — 优化路线图 (12 项全部实施)

## License

MIT
