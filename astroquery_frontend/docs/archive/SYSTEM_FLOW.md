# AstroQuery Final — 系统处理流程（2026-08-05 修订版）

## 环境变量统一管理

```
$DASHSCOPE_API_KEY    → subgraph1/P1/子图3 的 DashScope key
$DASHSCOPE_BASE_URL   → 同上（默认由 yaml 兜底）
$DASHSCOPE_MODEL      → 同上（默认 qwen3.7-flash）
$ADS_API_TOKEN        → 子图2 NASA ADS
$UNPAYWALL_EMAIL      → 子图2 Unpaywall
$OPENAI_API_KEY       → quality_pipeline（OpenAI 兼容）
$OPENAI_BASE_URL      → quality_pipeline
$DEEPSEEK_API_KEY     → scripts/add_units.py
```

`.env` 统一放在项目根目录。subgraph1/2/3 各自通过 `load_dotenv` 两级回退链加载（→ 根 .env）。

---

## 端到端处理流程

### 0. 入口 `run.py`

```
用户输入 "M31 的距离和金属丰度"
  → 交互模式: prompt_interactive() 收集 query 字符串
  → 命令行: python run.py "M31 的距离和金属丰度"
  → run_pipeline(user_query, extra_pdfs=[], query_id=uuid)

初始化:
  user_query = "M31 的距离和金属丰度"
  query_id = uuid
  extra_pdfs = []
  error_log = []
```

### 1. 意图澄清（子图1，`clarification_node`）

```
adapters.py:49-91
  sub_input = {original_query, query_id}
  → subgraph1.invoke(sub_input)

子图1 内部:
  initial_parse:
    获取最新用户输入（original_query 或 chat_history[-1]）
    → classify_query_type() → [astronomical | greeting | exit | invalid]
    → 若 astronomical: extract_entity_and_properties() → LLM
    → target_entity, requested_properties

  route_after_initial_parse:
    if target_entity && properties_asked && query_type != "exit"  ✅ B5 修复
      → final_confirm
    分支: polite_reject | greeting_handler | ask_entity | ask_properties | final_confirm | exit | handle_failure

  交互节点 (greeting_handler / ask_entity / ask_properties / final_confirm):
    input() 阻塞 → 用户输入 → 更新 chat_history → 回到 initial_parse
    循环上限: clarification_turns 最大 3 次

  终点:
    final_confirm: 用户选 y → clarification_status="confirmed"
                  用户选 m → clarification_status="modified"  ✅ B4 修复（契约已加入 "modified"）
                  用户选 n → clarification_status="cancelled"

adapters.py 映射:
  target_entity       = result["target_entity"]
  requested_properties = result["requested_properties"]
  clarification_status = result.get("clarification_status", "confirmed")  ✅ B4 默认值统一
  query_type           = result["query_type"]
  conversation_history = result["conversation_history"]
```

### 2. 路由决策 (`route_after_clarification`)

```
main_graph.py:69-99
  if clarification_status == "cancelled" → aggregation（空结果）
  if query_type in (greeting, exit, invalid) → aggregation
  if !target_entity → aggregation
  else → property_std ✅ B4 默认值 "confirmed" → property_std
```

### 3. P1 性质标准化（`property_standardization_node`）

```
property_standardization.py:370-476
  输入: target_entity, user_query, requested_properties

  Step 1 — SIMBAD 解析（HTTP VOTable XML）:
    sim-id?Ident=M31&output.params=main_id,otype,otypes,sp_type,coo(ICRS),ids
    ✅ ids 参数 → 解析 ALIASES 列表（| 分隔）
    → simbad_info = {MAIN_ID, OTYPE, OTYPES, SP_TYPE, RA_ICRS, DEC_ICRS, IDS, ALIASES}

  Step 2 — RAG 加载:
    按 OTYPES 紧凑码优先（| 分隔逐个查找），其次 OTYPE 详细名，最后的 _star.json 兜底
    → 加载 {otype}.json → 获取 properties 列表
    ✅ 全库 3293 条性质 category 已统一为英文 8 类

  Step 3 — LLM 选性质:
    build_selection_prompt() → 按 category 分组的性质清单
    → OpenAI client（model = DASHSCOPE_MODEL 或 yaml fallback）
    → 返回 selected_properties: [{property_id, reason}, ...]

  Step 4 — PropertySpec:
    build_property_spec(rag, selected_ids)
    → [{property_id, name_cn, unit, category, ucd, description}, ...]

  Step 5 — target_schema:
    generate_target_schema(property_spec)
    → {fields: [{name, standard_unit, semantic_type, ucd, description}, ...]}

  输出:
    simbad_info = {MAIN_ID, OTYPE, OTYPES, SP_TYPE, RA_ICRS, DEC_ICRS, ALIASES, ...}
    property_spec = [{property_id, name_cn, unit, ...}, ...]
    target_schema = {fields: [...]}
```

### 4. 并行检索（子图2，`retrieval_node`）

```
adapters.py:197-242
  ✅ B2 收敛：从 P1 的 simbad_info 直接构建子图2 所有 simbad_* 字段
    simbad_status = "success"
    simbad_aliases = simbad_info["ALIASES"]
    simbad_object_type = simbad_info["OTYPE"]
    simbad_coordinates = {ra, dec}
    → 不再需要 simbad_resolver 二次查询

subgraph2/graph.py ✅ B2 收敛：
  START → [database_query, ads_search] 直接并行
  无 simbad_resolver 节点，无前置路由

├─ database_query ✅ A1 修复：
│   aliases = state.get("simbad_aliases", [])
│   → extract_catalog_ids(aliases, catalog_config)
│   → 27 星表顺序查询 VizieR（row_limit=10, timeout=30）
│   → LLM 列名映射（column_mapper.py, model = s1_config.llm.model）✅ B15 修复
│   → build_database_records → EAV records
│   → 输出: database_sources, database_records
│
└─ ads_search → unpaywall_query → pdf_download → supplementary_query:
    ✅ E6 修复：论文路不再被 SIMBAD 失败牵连（整个路由已删除）
    ads_search: target_entity + property_spec → ADS 查询 → 论文元数据（50 篇）
    unpaywall_query: 按 DOI 并发 10 查 PDF URL
    pdf_download: 瀑布式并发下载
    supplementary_query: ✅ A2 修复 column_mapper 三级导入
      推导 J/ 表号 + Vizier.find_catalogs → CDS 页面验证 → LLM 判表分类
      → 列名映射（✅ 与 database 共用 column_mapper）
      → provenance: {source_kind:"supplement", db_table, key_column, key_value, raw_column}
      ✅ 对齐 DB 四要素
      ✅ record_id 含 bibcode 维度

→ result_aggregator:
  ✅ B12 修复：successful_catalogs / failed_catalogs 统一为 List[str]

adapters.py 映射:
  database_results = {total_catalogs_queried, successful_catalogs, failed_catalogs, sources, records}
  paper_results = {total_papers_found, downloaded_papers, download_paths, sources, search_metadata}
  simbad_info = {**p1_simbad, status, aliases, object_type, coordinates, resolved_at}
  ✅ B3 修复：合并而非覆盖，保留 OTYPES/SP_TYPE
```

### 5. 多模态提取（子图3，`extraction_node` / `skip_extraction_node`）

```
route_after_retrieval:
  有 PDF（下载或手动）→ extraction_node
  无 PDF → skip_extraction_node

extraction_node:
  _merge_extra_pdfs(download_paths, extra_pdfs) → 统一 PDF 列表
  子图3:
    pdf_batch_converter → vlm_batch_extractor → bbox_batch_annotator → result_builder

  result_builder:
    过滤 confidence < min_confidence → 构造 paper_records
    ✅ B10 修复：将 conversion_failed + extraction_failed + bbox_annotation_failed
    合并为标准 error_log 上浮

skip_extraction_node:
  返回 paper_records=[], processing_summary={skipped:True}
```

### 6. 聚合（`final_aggregator`）

```
aggregator.py:34-96
  合并:
    sources = db_sources + paper_sources + supplementary_sources
    records = db_records + paper_records + supplementary_records

  final_output = {
    schema_version: "2.0.0",
    research_domain: "astrophysics",
    query_metadata: {query_id, user_query, target_entity, requested_properties, retrieval_timestamp},
    simbad_info: {...},       ✅ B3 修复：包含 OTYPES/SP_TYPE
    sources: [...],
    records: [...],
    error_log: [...]          ✅ B10 修复：包含子图3 内部错误
  }

  悬空 source_id 检查（records 引用了不存在的 source → 记入 error_log）
```

### 7. 质量管线（`quality_node`）

```
quality_adapter.py:59-149
  generate_target_schema(property_spec) → target_schema fields
  generate_standard_units(property_spec) → field→unit 映射
  make_initial_state(final_output) → initial_state
  注入 context_state: target_schema, standard_units, research_domain

  quality_pipeline/graph.py:
    Assessment → gate → Dispatch → Normalization/Conflict/Export → Insights → END

    注：当前部署无 OPENAI_API_KEY 时，所有 Agent try/except → template fallback 优雅降级
    ⏸️ A5：配置项，.env 已预留 key
```

### 8. 输出

```
run.py:129-138
  final_output → JSON 文件（output/result_{query_id}.json）
  终端摘要: target_entity, sources 数量, records 数量, errors 列表
```

---

## 修复清单（已落实）

| 编号 | 问题 | 状态 |
|---|---|---|
| A1 | 数据库检索恒零（ALIASES 断线） | ✅ simbad_aliases 直读 |
| 新：毒缓存 | column_mapping_cache 空映射毒化 | ✅ 空映射不写缓存 + 清毒 |
| 新：D1 三态语义 | 空映射输出原始列名 | ✅ None/空/映射三态 |
| 新：P1 选库频率 | OTYPES 首码选错库 | ✅ 按频率降序（M31→G.json） |
| A2 | 补充材料恒零（四级导入） | ✅ column_mapper 三级导入 |
| A3 | 密钥明文 hardcode | ✅ 统一 .env, yaml 清除 |
| B2 | SIMBAD 双查 | ✅ P1 产 ALIASES, adapters 映射 |
| B3 | simbad_info 覆盖 | ✅ 合并保留 OTYPES/SP_TYPE |
| B4 | 契约枚举 "modified" | ✅ 4 处统一 |
| B5 | 退出词被吞 | ✅ routing + query_type != "exit" |
| B10 | 子图3 error_log 不上浮 | ✅ result_builder 合并上浮 |
| B12 | successful/failed 类型不对称 | ✅ 统一 List[str] |
| B14 | RAG 中文 category | ✅ 8 文件 220 条 → English |
| B15 | 模型名硬编码 qwen-plus | ✅ 读 s1_config.llm.model |
| E6 | SIMBAD 失败牵连论文 | ✅ resolver+路由已删除 |
| D12 | ALIASES 键名分裂 | ✅ 注释+读侧统一 |
| S14 | record_id 冲突 | ✅ 加 bibcode 维度 |
| C10 | 重复日志 | ✅ database_query 删重复块 |

### 搁置项

| 编号 | 问题 | 原因 |
|---|---|---|
| A4 | input() 阻塞 | CLI 阶段正确，Web 化方案已设计 |
| A5 | quality_pipeline LLM | 配置项，Agent 有 fallback |

---

## 数据流关键路径验证

```
用户 query "M31 的距离"
  → 子图1: target_entity="M31"
  → P1: SIMBAD → OTYPES="G|AGN" → RAG G.json(34 性质) → LLM 选 distance
  → PropertySpec: [{property_id:"distance", unit:"pc", category:"astrometry"}]

子图2 并行:
  → database_query: aliases[41 个] → extract_catalog_ids → 27 星表
    → column_mapper LLM: 列名 → "distance"
    → records: [{field_name:"distance", field_value:"0.77", field_unit:"Mpc", ...}]
  → ads_search: f'"M31" AND (distance OR 距离)'
    → papers → unpaywall → pdf_download → supplementary

子图3:
  → VLM 提取: prompt 注入 PropertySpec 白名单 → field_name 强制对齐 "distance"
  → records: [{field_name:"distance", bbox:[...], ...}]

aggregation:
  → sources: [SRC_DB_GAIA_DR3, SRC_PAPER_2020A&A..., SRC_SUPPL_J/ApJ/...]
  → records: [{field_name:"distance", source_id, provenance}, ...]
  → final_output

quality_pipeline:
  → target_schema: {name:"distance", standard_unit:"pc", semantic_type:"astrometry"}
  → unit_converter: 原始 Mpc → 标准 pc → 换算留痕
```

---

## 编译验证

全部改动文件通过 `py_compile`，无语法错误。
