# AstroQuery Final 系统设计文档

## 概述

AstroQuery 是一个**天文数据检索与提取 AI 流水线**。用户以自然语言提出天文查询（如"M31 的距离和金属丰度"），系统自动完成天体识别、性质标准化、多路数据检索、论文 VLM 提取、数据聚合、质量清洗与洞察生成。

核心设计理念：**PropertySpec 是系统中枢**——RAG 性质库提供的标准性质名 + 标准单位表是字段名唯一白名单和单位归一基准，三条提取路径（数据库 / 论文 VLM / 补充材料）全部归一到它，下游质量管线也只认它。

---

## 一、整体架构

```
run.py（入口 CLI）
  │
  ├─ 子图1 意图澄清（LangGraph 状态机、LLM 交互式追问）
  ├─ P1 性质标准化（SIMBAD 解析 + RAG 双库拼合 + LLM 选性质 → PropertySpec）
  ├─ 子图2 并行检索（database_query ∥ ads_search → unpaywall → pdf → supplementary）
  ├─ 子图3 多模态提取（PDF 转图 → VLM 提取 → bbox 标注 → result_builder）
  ├─ 聚合层（三路 sources/records 合并 → final_output）
  └─ quality_pipeline（Assessment → Normalization → Conflict → Export → Insights）
```

技术栈：Python + LangGraph（状态机编排）+ OpenAI 兼容 API（DashScope/DeepSeek）+ astroquery（天文数据访问）+ PyMuPDF + Pillow + dashscope SDK（VLM 多模态）。

外部依赖：SIMBAD（天体识别）、VizieR（27 个星表查询）、ADS（论文检索）、Unpaywall（开放获取 PDF 定位）、CDS 补充材料。

---

## 二、分层设计

### 2.1 入口层 `run.py`

**职责**：CLI 交互 + 结果输出。接收命令行参数或进入交互模式收集查询语句，调用 `run_pipeline()`，将 `final_output` 写入 JSON 文件并打印终端摘要。不参与业务逻辑。

**设计要点**：
- 交互模式收集 query 和可选 PDF 路径，其余追问由子图 1 在流水线内部完成
- 输出始终为 JSON（任何降级路径都出合法结构，records 可能为空）
- 错误日志随 final_output 一起输出

### 2.2 主图装配层 `main_graph.py` + `adapters.py`

**职责**：将三个子图包装成 LangGraph 主图的 7 个节点（clarification → property_std → retrieval → extraction/skip → aggregation → quality → END），管理节点间路由和状态流转。

**主图状态**：`MainGraphState`——统筹三个子图的"超集投影"，只声明跨子图流转的字段（如 `target_entity`、`property_spec`、`database_results`、`paper_records`），各子图内部工作字段保留在子图自己的 state 中。错误日志统一为 `Annotated[List, add]` 累加器。

**适配器设计（核心架构决策）**：
- 每个子图外覆一个"包装节点"（在 `adapters.py` 中），负责三件事：
  1. **输入投影**：从主图状态提取子图所需字段，按子图键名传入
  2. **输出映射**：把子图返回映射回主图的嵌套契约
  3. **失败隔离**：子图抛异常时记录 error_log 并返回降级状态，保证主图永远能走到 aggregation 出 JSON
- 设计理由：三个子图源码零改动，所有接口差异被适配层吸收

**路由决策**：
- `route_after_clarification`：非天文查询 / 取消 / 无实体 → aggregation（空结果）；正常 → property_std
- `route_after_retrieval`：有 PDF（自动下载或手动上传）→ extraction；无 → skip_extraction

### 2.3 子图 1：意图澄清

**职责**：将用户的自然语言输入澄清为结构化检索参数（`target_entity` + `requested_properties`）。

**内部拓扑**：`initial_parse` → 路由 →（寒暄 / 追问天体 / 追问性质 / 确认 / 拒绝 / 退出 / 失败）→ 循环或结束。Loops：`greeting_handler → initial_parse`、`ask_entity → initial_parse`、`ask_properties → initial_parse`、`modify → initial_parse`。

**设计要点**：
- `initial_parse`：两阶段 LLM 调用——先规则+LLM 分类查询类型（astronomical / greeting / exit / invalid），再 LLM 提取实体名和性质
- 追问上限 3 轮（由 `clarification_turns` 计数，仅 ask_entity 递增）
- `final_confirm`：展示确认卡片（天体 + 性质），y/m/n 三选一；m 时清空重置、n 时取消
- CLI 模式：5 处 `input()` 交互；Web 模式已设计好 Headless Protocol（`interaction_response` / `pending_interaction` 字段），前端搭建时激活

### 2.4 P1：性质标准化（系统中枢）

**职责**：将用户查询中的口语化天体名和性质转化为标准的 PropertySpec 和 target_schema。

**流程四步骤**：

1. **SIMBAD 解析**：优先 TAP/ADQL 接口（标准紧凑码），TAP 不可用时 astroquery Simbad 兜底。获取主 ID、紧凑码（otype）、坐标、别名列表（用于后续星表标识符提取）

2. **RAG 双库拼合**（核心设计）：
   - `OTYPE_PARENT` 字典：维护 SIMBAD 分类 1/2/4/5 的层级关系（如 AGN→G、dS\*→\*、BLL→G）
   - 查到子树映射后：加载父类基库（如 G.json 34 条大而全的星系性质）+ 子类特库（如 AGN.json 22 条 AGN 专属性质）
   - 按 property_id 去重合并（子类覆盖父类同名项）
   - 设计理由：解决"星系 AGN（如 M31）用 AGN.json 缺 distance"的覆盖率矛盾，同时避免 OTYPES 脏数据投票

3. **LLM 选性质**：将双库拼合后的性质列表（通常 50-80 条）按 category 分组后传给 LLM，LLM 根据用户需求选出最相关的 subset → PropertySpec。模型：qwen3.8-max（独立模型，不共享 DASHSCOPE_MODEL）

4. **生成 target_schema**：将 PropertySpec 的 property_id + 标准 unit + semantic_type 映射为下游 quality_pipeline 可消费的格式

### 2.5 子图 2：并行检索

**职责**：三路并行获取数据——数据库（27 星表 VizieR）、论文（ADS→Unpaywall→PDF）、补充材料（CDS J/ 表）。

**内部拓扑**：
```
START → [database_query ∥ build_ads_query → ads_search → unpaywall → pdf_download → supplementary] → result_aggregator → END
```

**B2 收敛设计**：取消 simbad_resolver 入口节点——simbad_* 字段在 adapters 层从 P1 的 simbad_info 直接映射，子图 2 不再做二次 SIMBAD 查询。START 直接进入两路并行。

**三路设计**：

1. **数据库路**：
   - 从 65 个别名中用 27 组正则提取 8-9 个星表的标识符（如 `Gaia DR3 5854...` → gaia_dr3 visier_table + key_column key_value）
   - 顺序查询 VizieR（带多镜像 fallback，单次 10s 超时，4 镜像轮询）
   - LLM 列名映射（column_mapper）：将 VizieR 原始列名映射到 PropertySpec 的 property_id，按（表 ID + PropertySpec 指纹）缓存
   - 空映射防毒：LLM 返回空的映射不写缓存，避免毒缓存使后续查询永不再试
   - EAV 模型归一：每行列拆为一条 record（含标准 property_id、原始值、原始单位、provenance 四要素），三态语义（无白名单→原始列名 / 有白名单无匹配→0条 / 有匹配→只输出映射列）

2. **论文路**：
   - `build_ads_query`：LLM 将 snake_case property_id 扩展为天文学自然表达式（同义词、单位、常见缩写），构造 ADS 查询串
   - `ads_search`：优先用 LLM 构造的查询串，失败回退到 property_id OR 拼接
   - `unpaywall_query`：10 并发查 DOI → 获取 OA PDF URL
   - `pdf_download`：瀑布式下载（arXiv 直链 > Unpaywall best > alternates > ADS PUB_PDF），5 并发
   - `supplementary_query`：从论文 bibcode 推导 CDS J/ 表号 → CDS 页面验证不存在 → LLM 判表分类（whole_entity 才保留）→ LLM 列名映射 → 行级别名过滤 → 构建 records

3. **数据库与补充材料 record 同构设计**：两者 provenance 均为 DB 四要素（db_table/key_column/key_value/raw_column），下游通过 `provenance.source_kind`（"database" vs "supplement"）区分来源，`is_database_record()` 依据 `extraction_method == "database_query"` 作类型判定——两条路完全同构、下游零适配。

### 2.6 子图 3：多模态提取

**职责**：从下载的 PDF 论文中提取物理数据并标注 bbox 定位。

**流程**：`pdf_batch_converter → vlm_batch_extractor → bbox_batch_annotator → result_builder`，全串行。

**设计要点**：
- PDF 转图：PyMuPDF 150dpi 渲染全部页面，图片落盘到 `%TEMP%\graph3_image_cache`
- VLM 提取：DashScope SDK `MultiModalConversation.call()`（qwen3.7-plus，15 并发），prompt 注入 PropertySpec 白名单约束 field_name，输出 JSON
- bbox 标注：DashScope SDK `MultiModalConversation.call()`（qwen3.7-flash，100 并发），百页图片 bbox 定位。提示词加固（7 条结构铁律 + 精确骨架模板）+ 递归归一化解析（`_coerce_to_dict` 处理 DashScope 多态返回）+ bbox 校验失败丢弃记录（几何+范围校验）
- result_builder：过滤 confidence < 0.7、构建 paper_records（含 trace_id / bbox / extraction_confidence）、合并三套失败列表到 error_log 上浮主图

### 2.7 聚合层 `aggregator.py`

**职责**：将三路 sources（数据库+论文+补充材料）和 records 合并为 `final_output`，永远产出合法 JSON。

**设计要点**：
- 不重写字段名——数据库/论文各自保持原始结构，下游按 source_id 关联
- 补全 research_domain、query_metadata、simbad_info、error_log
- 悬空 source_id 检查（records 引用了不存在的 source → 记入 error_log 但不阻断）

### 2.8 quality_pipeline（质量管线）

**职责**：对 final_output 进行 Assessment → Normalization → Conflict → Export → Insights 全链路质量处理。

**与主图的接缝**：`quality_adapter.py` 从 P1 的 PropertySpec 生成 target_schema + standard_units 注入 quality_pipeline 的 context_state。`unit_converter` 据此做原始单位 → 标准单位换算留痕。

**各阶段职责**：Assessment（质量评分+决策路由）、Normalization（字段标准化+清洗）、Conflict（多源冲突检测和解决）、Export（JSON+CSV 宽/长表导出）、Insights（LLM 驱动的数据洞察和推荐）。所有 LLM 调用均有 try/except → template fallback 优雅降级（无 key 时管线不阻塞）。

---

## 三、关键设计决策（Why）

### 3.1 PropertySpec 作系统中枢

**问题**：三条提取路径（数据库列名、VLM 从 PDF 提取的 field_name、补充材料）各自产出的字段名不一致（"Plx" vs "parallax" vs "视差"），下游无法统一处理。

**决策**：RAG 性质库的 `property_id` + `unit` 组合作为全系统唯一的字段名白名单和标准单位表。三条路径都通过 LLM 映射到这个标准名。quality_pipeline 也只认这个标准名。这样：数据库路通过 column_mapper 映射列名 → property_id；VLM 通过 prompt 强制 field_name 对齐；补充材料同理。

### 3.2 适配层外覆子图

**问题**：三个子图有各自的 state 键名（如子图 2 的 `downloaded_papers` vs 主图的 `download_paths`）、各自的异常处理策略、各自的嵌套结构。如果让子图直接做主图节点，耦合重且改一个子图破坏全局。

**决策**：adapters.py 把每个子图包装成一个函数——投影输入、映射输出、失败降级。子图源码零改动。三个子图可以独立测试、独立部署。LangGraph 的 `Annotated[List, add]` reducer 配合包装节点只返回增量 error_log 的设计，保证并行分支写入不互相覆盖。

### 3.3 双库拼合（父类基库 + 子类特库）

**问题**：SIMBAD otype 有时偏"窄"——M31 的 otype 是 AGN，但 AGN.json 只有 22 个 AGN 专属性质（黑洞质量、发射线），用户问"距离"时找不到。OTYPES 管线分隔码投票又太脏（M31 的 OTYPES 首码是 QSO）。

**决策**：维护轻量级 `OTYPE_PARENT` 字典，编码 SIMBAD 分类 1/2/4/5 的层级关系。查到这个 otype 是子树时，同时加载父类基库（如 G.json 34 条）和子类特库（如 AGN.json 22 条），去重合并后给 LLM 选。效果：M31 既保留了 AGN 的发射线/黑洞覆盖面，又有了 G 的 distance/stellar_mass 等通用性质。Token 量可控（通常 50-80 条）。

### 3.4 SIMBAD TAP + astroquery fallback

**问题**：SIMBAD TAP 服务间歇性高负载（完整 JOIN 查询 46s timeout），旧版 sim-id 接口返回不可预测的 verbose otype（`delSctV*` vs 紧凑码 `dS*`）。

**决策**：主路径用 TAP/ADQL（CSV 格式）直接查询，返回标准紧凑码。TAP 不可用时自动切换到 astroquery Simbad 兜底（astroquery 查询简易且稳定，曾全程正常）。两条路径的 otype 格式一致（紧凑码）、别名格式一致，对下游完全透明。

### 3.5 VizieR 多镜像 fallback

**问题**：CDS/VizieR 服务间歇性不可用，哈佛镜像 `vizier.cfa.harvard.edu` 超时率高（6/9 查询超时），导致 4.5 分钟死等。

**决策**：创建 `vizier_client.py` 共享模块，4 镜像轮询（哈佛 → 日本 → 剑桥 → 法国）。单次超时 10s（原 30s）。可重试异常（ReadTimeout/ConnectionError）→ 切镜像；不可重试异常直接抛。最坏单表耗时 40s（原 4.5 分钟）。

### 3.6 数据库与补充材料 record 同构

**问题**：两条路都是查 VizieR → 构建 records，但原代码各写各的——数据库路有 `build_database_records` 工厂函数，补充路内联 40 行且字段名不一致。

**决策**：统一 provenance 为 DB 四要素（db_table/key_column/key_value/raw_column）。`source_kind` 字段区分来源（"database" vs "supplement"）。下游 `is_database_record()` 依据 `extraction_method == "database_query"` 统一判类型——两条路处理方式相同、下游同一分支、零适配。

### 3.7 LLM 查询构造（ADS 论文检索）

**问题**：直接拼接 property_id 到 ADS 查询串（`"M31" AND (distance OR gas_phase_metallicity)`）命中率低——snake_case 词不会出现在论文全文里，ADS 的 Solr 全文检索匹配效果差。

**决策**：加一个轻量级 `build_ads_query` 节点（qwen3.7-flash，失败回退原逻辑）。LLM 负责将 snake_case property_id 扩展为天文学自然表达式（如同义词 distance modulus / metal abundance / O/H），每个性质最多 2 个 term，总 term 不超过 15 个。失败时回退到 property_id OR 拼接，不染流程。设计理由：LLM 失败路径不丢失原功能，成功路径显著提升召回率。

### 3.8 错误处理三原则

1. **永远产出 JSON**：任何降级路径都走到 aggregation，final_output 的顶层键集合恒定（sources/records 可能为空）
2. **错误上浮不中断**：所有子图异常被适配层捕获归入 error_log，管道继续
3. **优雅降级**：SIMBAD 挂了用 fallback → 还挂用 _star.json 兜底；LLM 挂了用规则/template；VizieR 挂了多镜像轮询 → 还挂跳过该表

---

## 四、状态流转

### 4.1 主图状态生命周期

```
run_pipeline()
  initial: {user_query, query_id, extra_pdfs, error_log}

│ → clarification_node: target_entity, requested_properties, clarification_status
│ → property_std: simbad_info, property_spec, target_schema
│ → retrieval_node: database_results, paper_results, supplementary_sources/records
│ → extraction_node: paper_records, processing_summary
│ → final_aggregator: final_output
└─► quality_node: quality_report
```

### 4.2 数据在各层之间的传递

```
用户: "M31 的距离"
  → 子图1: target_entity="M31", requested_properties=["距离"]
  → P1: simbad_info{main_id, otype=AGN, aliases}, property_spec[{property_id:"distance", unit:"Mpc"}]
  → 子图2: database_records[{field_name:"distance"}], paper_sources[{source_id=bibcode}]
  → 子图3: paper_records[{field_name:"distance", bbox:[...], provenance:{page, bbox}}]
  → 聚合: sources[db, paper, supp], records[db, paper, supp]
  → quality: target_schema → unit_converter(原始→标准) → 清洗 → insights
```

---

## 五、外部服务依赖与容错

| 服务 | 用途 | 主策略 | 兜底 / 容错 |
|---|---|---|---|
| SIMBAD | 天体识别 + 类型判定 | TAP/ADQL → CSV | astroquery Simbad fallback → _star.json 兜底 |
| VizieR | 27 星表数据 | `vizier.cfa.harvard.edu` 多镜像轮询 | 单表失败跳过，不影响论文路 |
| ADS | 论文检索 | API v1 → 论文元数据 | LLM 查询构造失败→property_id OR 回退 |
| Unpaywall | OA PDF 定位 | 10 并发查 DOI | DOI 为空或无 URL → 跳过该论文 |
| arXiv | PDF 直接下载 | arXiv 直链优先 | 如无 arXiv ID → 走 Unpaywall/ADS |
| DashScope | VLM 多模态 + LLM 文本 | Qwen SDK / OpenAI 兼容 | 超时重试 + json_repair 修复 |
| DeepSeek | quality_pipeline 洞察 | OpenAI 兼容 ChatOpenAI | template fallback（纯规则） |

---

## 六、配置集中管理

分为三类：

1. **环境变量**（`.env`）：API 密钥和模型/端点配置——DASHSCOPE_API_KEY / DASHSCOPE_BASE_URL（子图 1/P1/子图 3）、OPENAI_API_KEY / OPENAI_BASE_URL（quality_pipeline）、ADS_API_TOKEN / UNPAYWALL_EMAIL（子图 2）
2. **YAML 配置**（`config.yaml` / `llm_config.yaml`）：非密钥参数——星表配置、检索参数、LLM 温度/超时/模型名
3. **JSON 数据**（`catalog_config.json` 等）：星表正则 → VizieR 表映射、星表元数据、单位配置、RAG 性质库（100 文件、3293 条性质、50 个父类映射）

密钥管理：`.env` 单来源统一管理，subgraph1/2/3 各自通过 `load_dotenv` 两级回退链加载（包内 `.env` → 项目根 `.env` → 默认搜索）。config.yaml 中 api_key 字段清空，敏感字段优先从环境变量取值。

---

## 七、RAG 性质库体系

- **数据来源**：100 个 JSON 文件对应 100 个 SIMBAD 紧凑码（分类 1/2/4/5），手动编制 + LLM 批量补单位
- **每个条目**：`{property_id, name_cn, unit, category, ucd, description}`
- **category 统一**：8 类英文（astrometry/photometry/spectroscopy/physical/classification/variability/environment/identification），原本 220 条中文 category 已映射为英文
- **选库机制**：OTYPE 查 `OTYPE_PARENT` 字典 → 双库拼合（父类基库 + 子类特库）→ LLM 筛选
- **统计**：100 文件、3293 条性质、1 个孤儿文件（post_AGB_star.json）、9 条越界单位待人工确认
