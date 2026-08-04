# Data Normalization Agent (V2.3)

> SubGraph 4-B: 数据规范化处理模块  
> AI-Scientist 2026 挑战杯 | 负责修改数据，不负责判断质量或解决冲突

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green)](https://langchain.com/langgraph)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%20v4--pro-orange)](https://deepseek.com)

## 概述

本模块是整个 LangGraph 多智能体科学数据处理管道的 **Normalization 子图**，负责对 Assessment 标记为 "Normalization" 的数据执行规范化处理。

**核心创新 (V2.0)**: LLM 动态 Tool 生成 — 不再依赖固定的 6 个工具函数。LLM 可以根据数据的具体问题自动生成/适配规范化工具。

> 文档版本: V2.3（2026-08-03 更新 V4.2: 单位转换配置体系完整化 — 27 组 231 条转换规则, 详见 [NORMALIZATION_DESIGN_REPORT.md](NORMALIZATION_DESIGN_REPORT.md)）

### 管道位置

```
AssessmentGraph → Router → ★ NormalizationGraph → LoopController → Router
                              ↑                        ↓
                              └── ConflictGraph ←──────┘ (B⇄C 循环)
```

### 职责边界

| 能做 | 不能做 |
|------|--------|
| ✅ 修改数据 (唯一有权修改的 Agent) | ❌ 判断数据质量 (Assessment 做) |
| ✅ Schema Mapping / Field Std / Unit Conv | ❌ 解决复杂冲突 (Conflict 做) |
| ✅ Missing Value / Duplicate Handling | ❌ 决定路由 (Validation 做) |
| ✅ LLM 动态生成/适配工具函数 | ❌ 修改 State 结构 |

## 架构

```
NormalizationGraph (5 Stage Nodes)
│
├── Stage 1: SourceRouterAgent     — 筛选 Normalization sources
├── Stage 2: ToolPlanningAgent     — LLM 规划工具链 (3层)
├── Stage 3: ToolExecutorAgent     — 执行工具 (Base/Adapted/Generated)
├── Stage 4: ValidationAgent       — 校验 + 内部 Retry
└── Stage 5: ReportAgent           — 生成 Normalization Report
```

### 三层工具架构

```
Layer 3: LLM-Generated      (V2.0)   — LLM 动态编写 Python 函数 (sandbox + dry-run)
Layer 2: Rule-Adapted       (V2.1)   — 确定性规则注入自定义参数 (非 LLM)
Layer 1: Base Tools         (6 个固定) — 确定性工具函数
```

### 条件→工具映射

| 问题类型 | 工具 |
|---------|------|
| `alias_fields` / `extra_fields` | schema_mapping |
| `format_issues` | field_standardizer |
| `unit_inconsistency` | unit_converter |
| `missing_units` / `missing_provenance` / `completeness_low` | missing_value_handler |
| `duplicate_records` | duplicate_handler |
| `general` | format_standardizer |

## 目录结构

```
Data_Normalization_agentV1/
├── README.md                          # 本文件
├── NORMALIZATION_DESIGN_REPORT.md     # V2.3 详细设计报告 (2026-08-03 更新 V4.2)
├── normalization_graph.py             # SubGraph (5 Stage + finalize, 138 行)
└── agents/
    ├── source_router_agent.py         # Stage 1: 来源分流
    ├── planning_agent.py              # Stage 2: LLM 工具规划
    ├── normalization_agent.py         # Stage 3: 三层工具执行
    ├── validation_agent.py            # Stage 4: 校验 + Retry
    └── report_agent.py                # Stage 5: 报告生成
```

### 配套工具

```
tools/normalization/
├── schema_mapping.py         # T1: 字段名映射到标准 Schema
├── field_standardizer.py     # T2: 数值/字符串值标准化
├── unit_converter.py         # T3: 单位统一转换
├── missing_value_handler.py  # T4: 缺失值处理 (mark/drop/fill)
├── duplicate_handler.py      # T5: 重复记录去重 + rejected 过滤
└── format_standardizer.py    # T6: 数值/日期/字符串格式标准化
```

## 输入输出

### 输入 (来自 Assessment)

```python
report_state.quality.per_source_routes   # {"doi_A": "Normalization", ...}
report_state.quality.conditional_routes  # [{source_id, conditions: [...]}]
report_state.quality.sources[sid]        # per-source completeness/consistency/...
report_state.quality.profile             # semantic_types, schema_summary
report_state.quality.quality_scoring.per_entity_scores  # V2: per-entity breakdown
report_state.conflict.resolution_report  # C→B 路径: actions_to_normalize (V3.5: 保留 record_ids/from_unit/to_unit)
data_state.current_data                   # 待处理数据
context_state.target_schema              # 目标 Schema (standard_unit 查询, V4: 领域配置兜底)
context_state.standard_units             # V4: 从领域 target_schema 回填的目标单位
```

### 输出 (Normalization Report)

```python
report_state.normalization = {
    "source_plan": {...},           # 来源分流 (V3.5: 含 conflict_actions)
    "tool_registry": {...},         # 工具注册表 (base+adapted+generated+by_source)
    "planning_method": "llm_enhanced" | "full_normalization" | "rule_engine",
    "modifications": {              # 修改详情
        "total": 10,
        "by_layer": {"base": 8, "adapted": 0, "generated": 2},
        "per_source": {...},
        "per_entity_modifications": {...},  # V2: per-entity 修改次数
        "errors": [...],            # V4: 含 unconverted 单位 (missing_unit/no_target_unit/no_conversion_rule)
    },
    "validation": {...},            # 校验结果 (conflict_check 完整数组; V4: needs_conflict → "Conflict")
    "normalization_status": "Completed" | "Completed_With_Issues" | "Skipped_No_Sources",
    "route_decision": "Conflict" | "Export",
}
workflow_state.route_decision      # "Conflict" or "Export" (V4 fix: 复检冲突, 不再恒 Export)
data_state.data_trace              # V3.2: 逐记录 TraceEvent (record_id/field/before/after/tool/reason)
```

## 运行

```bash
cd 子图4部分代码

# 端到端测试 (Assessment → Normalization)
python test/test_e2e_pipeline.py

# 单独 Normalization 流程测试
python test/test_normalization_flow.py
```

## 相关文档

- [NORMALIZATION_DESIGN_REPORT.md](NORMALIZATION_DESIGN_REPORT.md) — V2.3 完整设计报告（2026-08-03 更新 V4.2: 单位转换配置体系）
- [../Data_Assessment_agentV1/ASSESSMENT_DESIGN_REPORT.md](../Data_Assessment_agentV1/ASSESSMENT_DESIGN_REPORT.md) — Assessment 模块 (上游)
- [../README.md](../README.md) — 项目总览
