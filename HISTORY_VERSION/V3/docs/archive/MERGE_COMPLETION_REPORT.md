# 合并完成报告

**日期**：2026-08-05
**范围**：上游 `astroquery_ai` + RAG 性质库（`train/rag_properties`）+ 下游 `子图4部分代码`（质量管线）合并为单一端到端系统。

---

## 一、最终架构

```
run.py (combine/run.py)
  │
  ├─ P0 clarification      ← Node1 澄清（不再翻译性质，保留用户原文）
  ├─ P1 property_std       ← 【新增】SIMBAD 解析 + RAG 选性质 → PropertySpec（系统中枢）
  ├─ P2 retrieval          ← 数据库（27 星表）+ ADS 论文 + 补充材料
  │     └─ 数据库列名经 LLM 归一到 PropertySpec（按表+指纹缓存）
  │     └─ 补充材料列名同样归一（与数据库共用 column_mapper）
  ├─ P3 extraction         ← VLM 提取（prompt 注入 PropertySpec 白名单 + 强约束）
  ├─ P4 aggregation        ← final_output（补 research_domain / simbad_info / error_log）
  ├─ P5 quality            ← 【新增】接缝适配器 → quality_pipeline 完整质量管线
  └─ END
```

**PropertySpec**（`property_id + name_cn + unit + category + ucd + description`）贯穿全系统：
- 是字段名白名单（VLM/数据库/补充材料都必须归一到它）
- 是标准单位表（生成 target_schema 与 standard_units）
- 是子图4 的 context_state 来源

---

## 二、已完成的修复（12 项任务）

### 包迁移（C5/C6）
| # | 内容 | 状态 |
|---|------|------|
| C5 | `子图4部分代码` → `combine/quality_pipeline` 正式包；120 文件 / 91 改写 / 388 处导入改为包限定 + 相对导入；补 5 个 `__init__.py` | ✅ |
| C6 | 知识库路径改为基于 `__file__` 锚定（不再依赖 cwd） | ✅ |

### 性质标准化（P1 中枢，任务 6/7）
| # | 内容 | 状态 |
|---|------|------|
| 6 | 新增 `property_standardization.py`：SIMBAD（含 OTYPES 多码优先）→ RAG 选文件 → LLM 选性质 → PropertySpec + target_schema；主图挂接 `property_std` 节点 | ✅ |
| 7 | Node1 停止性质翻译（prompt 改为保留用户原话），翻译权移交 P1 | ✅ |

### 提取归一（任务 8/9）
| # | 内容 | 状态 |
|---|------|------|
| 8 | 数据库列名归一：新增 `column_mapper.py`（LLM 映射 + 按表+指纹缓存），`build_database_records` 只保留有映射的列，provenance 留痕 raw_column/raw_unit/row_index | ✅ |
| 9 | VLM prompt 注入 PropertySpec 白名单并强约束 field_name；补充材料共用 column_mapper，standard_unit 从 PropertySpec 反查 | ✅ |

### 聚合器（任务 11）
| # | 内容 | 状态 |
|---|------|------|
| 11 | `final_output` 补 `research_domain: "astrophysics"`、`query_metadata`、`simbad_info`、`error_log`；补充材料 records 的 source_id 与 source 对齐（修复孤儿 source） | ✅ |

### 模型对齐（任务 10）
| # | 内容 | 状态 |
|---|------|------|
| C1 | `record_id` 加入 `row_idx`（多行表不再重复） | ✅ |
| C2 | `extraction_method` Literal 补 `vlm_table`/`vlm_figure` | ✅ |
| N1 | bbox 统一 0-1000 归一化：下游描述改写 + `bbox_coord_system` 字段；上游 provenance 显式标注 | ✅ |
| N5 | `Provenance` 补补充材料溯源字段（source_kind/cds_table_id/parent_bibcode/row_index/matched_alias/raw_unit/standard_unit） | ✅ |

### 接缝适配器（任务 12）
| # | 内容 | 状态 |
|---|------|------|
| 12 | 新增 `quality_adapter.py`：PropertySpec → target_schema/standard_units → 注入 `make_initial_state` 的 context_state + `set_research_domain("astrophysics")` → 运行 `build_quality_graph`；主图 `aggregation → quality → END` | ✅ |

---

## 三、验证结果

### 编译与构建
- ✅ 上游 + 下游全部 .py 编译通过（仅 1 个预存在 SyntaxWarning，不影响运行）
- ✅ 主图（含 P1 + quality 节点）构建成功

### 端到端冒烟测试（模拟数据）
- ✅ 完整质量管线跑通：Assessment → Dispatch → Normalization → Loop → Export → Insights → END
- ✅ 知识库 78 条按 astrophysics 领域正确加载
- ✅ 质量评分 0.74 (fair)，正确路由到 Normalization
- ✅ Export 产出 7 个文件（JSON/CSV 长表/CSV 宽表/质量摘要/元数据/溯源/manifest）
- ✅ LLM 缺 key 时全部优雅降级（模板/知识库兜底，不中断）

### P1 集成测试
- ✅ SIMBAD 查询（M31 → QSO|AGN|GiC… 多 otype）
- ✅ RAG 按 OTYPES 首个命中（QSO.json，36 性质）
- ✅ LLM 选性质 → PropertySpec（含 unit）
- ⚠️ 曾出现一次瞬时"LLM 未返回"（重跑即通过），属外部 API 抖动

---

## 四、已知遗留事项（非阻塞）

| 事项 | 说明 | 建议 |
|------|------|------|
| 子图4 的 LLM key | 未配置（`configs/llm_config.yaml` 的 api_key 为空），Insights/Metadata 走模板降级 | 部署时填 key（可用 DEEPSEEK 或现有阿里云 key） |
| `planning_agent.py` SyntaxWarning | `"\d"` 非法转义（预存在） | 顺手改 `r"^-?\d..."` |
| 星表数量 | config 中 `total_catalogs: 22` 过期，实际 27 | 更新 config + 文档 |
| QSO 库无 distance/metallicity | RAG 按 otype 选性质，QSO 类只有红移/黑洞质量等 | 属产品预期；若需补充可扩展 RAG 库 |
| `run.py` 的 CLI 交互 | Node1 仍为 `input()` 交互模式 | 后续按"分步 API"改造（前端化） |
| 删减清单 | 未调用工具 / legacy / 材料科学配置段 | 按计划"先跑通再删"，已跑通，可择机清理 |

---

## 五、关键文件清单

**新增**
- `combine/astroquery_ai/property_standardization.py` — P1 性质标准化
- `combine/astroquery_ai/quality_adapter.py` — 接缝适配器
- `combine/astroquery_ai/subgraph2/utils/column_mapper.py` — 列名 LLM 映射
- `combine/quality_pipeline/` — 迁移后的完整质量管线包（原目录保留作基线）

**修改**
- `combine/astroquery_ai/main_graph.py` — 挂接 P1 + quality 节点
- `combine/astroquery_ai/adapters.py` — 传 property_spec/simbad_info 到子图 2/3
- `combine/astroquery_ai/aggregator.py` — 补 research_domain 等
- `combine/astroquery_ai/subgraph1/utils/llm_utils.py` — 停止性质翻译
- `combine/astroquery_ai/subgraph2/nodes/database_query.py` — 列名映射接入
- `combine/astroquery_ai/subgraph2/utils/database_utils.py` — record_id + 列名归一
- `combine/astroquery_ai/subgraph2/nodes/supplementary_query.py` — 列名归一 + source_id 对齐
- `combine/astroquery_ai/subgraph3/utils/vlm_client.py` — 白名单注入
- `combine/astroquery_ai/subgraph3/nodes/vlm_extractor.py` — 传递 property_spec
- `combine/astroquery_ai/subgraph3/nodes/result_builder.py` — bbox 坐标系标注
- `combine/quality_pipeline/models/record.py` — extraction_method / bbox / Provenance 扩展
- `combine/quality_pipeline/configs/domain_config.py` — 知识库路径锚定
