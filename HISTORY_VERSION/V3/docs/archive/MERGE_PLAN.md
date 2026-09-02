# 合并修复方案 · 总览

**目标**：将上游 `astroquery_ai`（意图澄清 + 检索 + 提取）与下游 `子图4部分代码`（质量管线）合并为单一端到端系统，修复所有接缝不对齐问题。

**核心原则**：向上游对齐。上游握有权威源（SIMBAD 实体、RAG 性质库），下游子图 4 的推断机制从"核心逻辑"降级为"兜底"。

---

## 一、目标运行逻辑（合并后端到端流程）

### 阶段划分

| 阶段 | 职责 | 输入 | 输出 |
|-----|-----|-----|-----|
| **P0 意图澄清** | 理解用户需求，不做翻译 | `user_query` | `target_entity` + `raw_property_request`（用户原话） |
| **P1 性质标准化** | SIMBAD 解析 + RAG 选性质 | `target_entity` + `raw_property_request` | **PropertySpec**（中枢契约） |
| **P2 检索** | 数据库/论文检索 | PropertySpec | 表 + 论文列表 |
| **P3 提取** | VLM/数据库/补充材料提取 | PropertySpec（字段名白名单） | records（field_name 已标准化） |
| **P4 聚合** | 合并三路结果 | records + sources | **GroundedData** |
| **P5 质量管线** | 评估 → 冲突 → 标准化 → Insights | GroundedData + context_state | final_report |

### PropertySpec：系统中枢契约

**定义**：每次查询选中的标准性质列表，包含以下字段：

```json
[
  {
    "property_id": "fe_h",
    "name_cn": "[Fe/H] 铁丰度",
    "unit": "dex",
    "category": "physical",
    "ucd": "phys.abund.Fe",
    "description": "铁元素相对于太阳的丰度..."
  },
  ...
]
```

**作用**：
1. **字段名白名单**：数据库列名归一、VLM 输出约束、补充材料标准化的目标空间
2. **标准单位表**：每个 field_name 的 `unit` 已由 DeepSeek 生成并人工校验（3293/3293 已补齐）
3. **target_schema 源**：直接生成子图 4 的 `target_schema.fields`（`{name: property_id, standard_unit: unit}`）

**生成流程**（P1 节点）：
1. SIMBAD 解析 `target_entity` → `main_id / otype / otypes / coords`
2. 按 `otypes` → `otype` → `_star.json` 兜底，选中 RAG 文件（已有 100 个 otype JSON）
3. LLM 从该文件性质列表里挑出用户要的 → PropertySpec

---

## 二、必修项（CRITICAL：会导致运行时错误）

| # | 问题 | 根因 | 影响 | 修复 |
|---|------|-----|------|------|
| **C1** | 数据库 record_id 重复 | `build_database_records` 的 `record_id = f"REC_{source_id}_{id}_{col}"` 不含 `row_idx`，多行表产出重复 ID | `GroundedData.__init__` 唯一性校验直接抛 `ValueError` | 改 `result_builder.py:120`，加 `_{row_idx}` |
| **C2** | extraction_method 类型不兼容 | VLM 产出 `vlm_table` / `vlm_figure`，但下游 `Record.extraction_method` Literal 白名单只有 `vlm_pdf` / `vlm_text` | Pydantic 校验抛 `ValidationError` | 扩 `models/schemas.py` Literal 加这两个值 |
| **C3** | 三路提取字段名不统一 | 数据库用原始列名、VLM 自由翻译、补充材料 LLM 自拟 | 下游单位检查/换算/完整性全部查不到 schema → 每条都进 Normalization 误报 | 全部归一到 PropertySpec（见 M1/M2/M3） |
| **C4** | research_domain 缺失 | `final_output` 没有这个字段 | 子图 4 `make_initial_state` 用空串调 `set_research_domain` → 加载材料科学通用配置段（`yield_strength` / `hardness`…）→ 天体物理单位组/语义类型/实体类型全走错 | 聚合器写 `research_domain: "astrophysics"` |
| **C5** | 子图 4 顶层绝对导入 | 根目录无 `__init__.py`，内部 120 个文件全是 `from quality_state import ...` 顶层导入 | 从 `combine/` 启动时 `import 子图4部分代码.graph` 第一行就 ImportError | 迁移：`子图4部分代码` → `combine/quality_pipeline`，加 `__init__.py`，改写 388 处导入为包限定（`from quality_pipeline.quality_state import ...`） |
| **C6** | 相对路径 cwd 依赖 | `domain_config.py` 的 `KNOWLEDGE_BASE_DIR = "data/insight_knowledge"` 依赖 cwd 在子图 4 根目录 | 改成包后从 `combine/` 启动，知识库读不到 → `search()` 返回空 → Insights 静默退化 | 改基于 `__file__` 锚定：`Path(__file__).parent / "data/insight_knowledge"` |

---

## 三、主修项（MAJOR：功能打折或数据丢失）

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| **M1** | 数据库列名不归一 | VizieR 原始列名（`Plx` / `Gmag`）不在 target_schema → 单位检查失效 | 按 `(vizier_table, PropertySpec指纹)` 缓存，LLM 判列名→property_id，只保留有映射的列，`field_name` 写 property_id，`field_unit` 保留原始单位，provenance 留痕 |
| **M2** | VLM 字段名自由翻译 | 模型输出 `distance_modulus` 等非标准名 | prompt 注入 PropertySpec 白名单并强约束，后置校验丢弃越界项 |
| **M3** | 补充材料 standard_name 自拟 | LLM 自由命名，不在 PropertySpec 内 | `_llm_judge_table` 改为只能从 PropertySpec 选 |
| **M4** | error_log / processing_summary 被丢弃 | 聚合时只保留 `{sources, records}`，上游这些字段全删了 | 保留它们，供 Insights / quality_summary 使用 |
| **M5** | simbad_info 丢失 | 同上 | 保留，含 `main_id` / `otype` / `coords` / `aliases`，Insights 可用 |
| **M6** | 三类 source 字段不同构 | database source 有 `waveband` / `observation_facility`，paper source 有 `retrieval_priority`，supplementary 只有 5 字段 | 对齐到超集，缺字段填 None，让 `source_reliability` 评分统一 |
| **M7** | supplementary_sources 孤儿 | 这类 source 从未被任何 record 引用（records 的 source_id 指向父论文 bibcode） | 补充材料 records 的 source_id 指向其对应的 supplementary source，而非父论文 |

---

## 四、次要项（MINOR：不影响功能但需整改）

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| **N1** | bbox 坐标系语义冲突 | 上游 0–1000 归一化整数，下游描述"单位 pt" | 统一：上游保留 0–1000，改下游 `Provenance.bbox` 描述，provenance 显式写 `bbox_coord_system="normalized_1000"` |
| **N2** | otypes 优先未用 | `simbad_resolver` 只取单个 `otype`，而 `query_properties.load_rag` 用 `OTYPES` 逐个尝试命中率更高 | SIMBAD 解析同时取 `otype` / `otypes`，按 otypes → otype → _star 兜底 |
| **N3** | 星表数量常量过期 | 子图 2 config 写 22，文档写 23，实际 27 | 删除 `total_catalogs` 常量，文档统一写 27 |
| **N4** | Node1 性质翻译越权 | `initial_parse` prompt 要求把"金属丰度"译成 `metallicity`，但标准名要等拿到 otype、查 RAG 才能定 | Node1 只保留用户原话 `raw_property_request`，翻译权移交 P1 |
| **N5** | Provenance 额外字段丢失 | 补充材料写了 `source_kind` / `cds_table_id` / `parent_bibcode` / `row_index` / `matched_alias`，但下游 `Provenance` 模型没这些字段 | Pydantic 默认忽略额外键，会静默丢失。扩 `Provenance` 模型加这些字段（optional） |

---

