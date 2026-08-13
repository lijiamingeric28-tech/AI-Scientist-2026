# AstroQuery 系统代码分析报告

> 综合 6 个代码阅读器结构化报告（子图1意图澄清 / 子图2并行检索 / 子图3多模态提取 / quality_pipeline核对 / 配置与数据资产 / 入口·测试·文档）而成。
> 项目: `astroquery_final` — 天文数据检索与提取 AI 流水线（用户自然语言提问 → 澄清 → 性质标准化 → 并行检索 → 多模态提取 → 质量管线 → 洞察）。

---

## 1. 系统全景

### 1.1 架构分层

```
Layer 1 入口层      cli.py (astroquery-ai) / scripts/run_betelgeuse.py
Layer 2 编排层      main_graph.py (7 节点主图) + adapters.py (子图适配) + quality_adapter.py (接缝)
Layer 3 子图层      subgraph1 意图澄清 / P1 性质标准化 / subgraph2 并行检索 / subgraph3 多模态提取
                    + quality_pipeline (Assessment→Normalization→Variance→Export→Insights)
Layer 4 工具层      utils/ (vizier_client, column_mapper, vlm_client, image_cache...) + tools/
Layer 5 配置资产层  astroquery_ai/config.py (唯一配置源) + catalog/ + rag_properties/ + configs/*.yaml
```

**主图拓扑**（`main_graph.py`，7 节点）:

```
clarification(子图1) →[route_after_clarification]→ property_std(P1) → retrieval(子图2)
→[route_after_retrieval]→ extraction(子图3) / skip_extraction → aggregation → quality(quality_pipeline)
→ quality_finalize → END
```

**模型分工**：P1 用 `qwen3.8-max`；VLM 提取用 `qwen3.7-plus`；BBox/图检测/子图1 澄清/子图2 列映射与判表用 `qwen3.7-flash`；quality_pipeline 与脚本用 `deepseek-v4-flash`（OPENAI_API_KEY 契约）。所有敏感字段由 `astroquery_ai/config.py` pydantic-settings `Settings` 从根目录 `.env` 读取（env 优先 > 默认值，lru_cache 单例）。

### 1.2 完整数据流（含状态字段）

1. **输入**: `run_pipeline` 初始 state `{user_query, query_id, extra_pdfs, error_log}`；CLI 校验手动 PDF 存在性（不存在 → 退出码 2）。
2. **子图1 澄清**: `initial_parse`（规则+LLM 两阶段）产出 `target_entity` / `requested_properties`（空=查所有）/ `query_type`(astronomical/greeting/exit/invalid)；交互经 `interrupt()` HITL（ask_entity≤3 轮、ask_properties 1 次防重问、final_confirm y/m/n），最终 `user_confirmed` + `clarification_status`(confirmed/modified/failed/cancelled) + `conversation_history`。
3. **路由**: `route_after_clarification` — cancelled/greeting/exit/invalid/无实体 → 直接 aggregation 空结果（有意偏离设计文档 END，兑现"永远输出 JSON"）；否则进 P1。
4. **P1 性质标准化**: SIMBAD sim-id → otype/ALIASES → OTYPE_PARENT(74 映射→4 父类) → RAG 双库拼合（rag_properties/ 100 文件 3293 性质）→ LLM 选性质 → **PropertySpec 中枢契约** `[{property_id, name_cn, unit, category, ucd, description}]`；`simbad_info` 由 adapters 直接映射为 `simbad_*` 字段预填。
5. **子图2 并行检索**:
   - 数据库路: 27 条正则从别名提取星表 ID → VizieR 4 镜像轮询(10s 超时) → LLM 列名映射（三态语义）→ EAV `database_records`（provenance 四要素: db_table/key_column/key_value/raw_column）。
   - 论文路: LLM 构造 ADS 查询串 → ADS 检索(50 篇, 重试 3) → Unpaywall(10 并发) → PDF 瀑布式下载 → CDS J/ 补充表（LLM 判表+行级别名过滤）→ `supplementary_records`(source_kind='supplement')。
   - 失败全部进 `Annotated[list, add]` `error_log`，任何失败不中断主流程。
6. **路由**: `route_after_retrieval` — `paper_results.download_paths` 或 `extra_pdfs` 非空 → 子图3；否则 skip_extraction。
7. **子图3 提取**: PDF→150dpi PNG(磁盘缓存) → VLM 整篇提取(15 并发, `raw_extractions`) → bbox 标注(100 并发回填) → figure 证据通路 → `result_builder`(confidence≥0.7 + bbox 校验) → `paper_records[]` / `figure_evidence[]` / `error_log`（三套失败合并）。
8. **聚合**: `final_output = {schema_version:'2.0.0', research_domain, query_metadata, simbad_info, sources[], records[], error_log[], quality_report}`，顶层键恒定。
9. **quality_node 适配**: 空数据短路 `{skipped:true, reason:...}`；否则注入 `context_state{research_domain, target_schema(property_id+unit+semantic_type=category), standard_units, quality_rules}`，四层 try/except 降级（import_failed/initial_state_failed/context_inject_failed/pipeline_failed）。
10. **质量管线**: Assessment(10 项检查+决策矩阵 → `per_source_routes`) → Dispatch(HumanReview>Normalization>Conflict>Export) → Normalization(唯一改数据者，更新 `data_state.current_data`) → LoopController(B⇄C≤3, 超限 force_export) → Variance(全量保留+差异标注) → Export(输出 `output/{run_id[:8]}/` 7 文件) → Insights(RAG 洞察)。
11. **quality_finalize**: `quality_report` 并入 `final_output`（Phase 4 断链修复——历史 bug 是 quality 结果从不进最终 JSON）→ END → `output/result_<query_id>.json`。

---

## 2. 模块地图

### 2.1 入口层 + 主图装配（astroquery_ai/cli.py, main_graph.py, quality_adapter.py）
- **职责**: 标准入口（`astroquery-ai` / `python -m astroquery_ai`）、HITL 循环、子图装配、质量管线接缝。
- **核心逻辑**: `run_pipeline` 用 MemorySaver checkpointer（thread_id=query_id 隔离会话）+ `while` 循环处理 `__interrupt__`（payload 渲染 → `input()` → `Command(resume=answer)` 恢复）；`recursion_limit=50`；编译图缓存 `_compiled_graph`。`quality_node` 延迟 import quality_pipeline 避免循环依赖。
- **健壮性**: 退出码 0/2/130；`_force_utf8_stdio` 修复 Windows GBK 控制台 UnicodeEncodeError（澄清阶段实测炸过）。

### 2.2 子图1 意图澄清（subgraph1/）
- **职责**: 把自然语言查询澄清为结构化检索参数。
- **关键文件**: `graph.py`（7 节点+2 路由函数）、`state.py`（21 字段 6 组 IntentClarificationState）、`utils/llm_utils.py`、`config/__init__.py`。
- **核心逻辑**: `classify_query_type` 规则短路优先（exit_keywords 9 个 / greeting_keywords 6 个）→ LLM yes/no 兜底；`extract_entity_and_properties` 单次 LLM 提取（含 3 轮对话历史，中文俗名→英文官方标识符，JSON 正则截取+json.loads）；用户交互全走 `interrupt()` HITL（5 处），payload dict 契约供前端渲染；`final_confirm` modify 分支清空状态重来。
- **并发/缓存**: 无；子图不建 checkpointer，由主图注入共享实例。

### 2.3 P1 性质标准化（property_standardization.py）
- **职责**: 天体实体 → otype → 性质白名单（PropertySpec）的中枢。
- **核心逻辑**: SIMBAD sim-id HTTP VOTable（失败 → astroquery Simbad 兜底 → `_star.json` RAG 兜底）；OTYPE_PARENT 74 映射→4 父类（G/*/Cl*/ClG）；RAG 双库拼合（父类基库+子类特库，按 property_id 去重子覆盖父）；LLM 选性质。
- **注**: 设计文档称 SIMBAD 用 TAP/ADQL 主路径，代码实际用 sim-id HTTP（文档过期）。

### 2.4 子图2 并行检索（subgraph2/）
- **职责**: 双路并行——数据库路（27 个 VizieR 星表）+ 论文路（ADS→Unpaywall→PDF→CDS 补充表）。
- **关键文件**: `nodes/database_query.py`、`nodes/ads_search.py`、`nodes/unpaywall_query.py`、`nodes/pdf_download.py`、`nodes/supplementary_query.py`、`nodes/result_aggregator.py`、`utils/vizier_client.py`、`utils/column_mapper.py`、`utils/database_utils.py`、`catalog/catalog_config.json` 等。
- **核心逻辑**: 数据库路顺序查询（0.15s 限流防 VizieR 429），镜像轮询（ReadTimeout/ConnectionError 切镜像，非可重试错误直接 raise）；列名映射三态语义（None→原始列名兜底 / {}→0 条宁缺毋滥 / 非空→只输出映射列）；论文路 LLM 构造 ADS 自然表达查询（失败回退 property_id OR 拼接），ADS 429 直接 skipped，PDF 瀑布式（arXiv 直链→Unpaywall best+alternates→ADS PUB_PDF），CDS 补充表（bibcode 推导 J/{刊}/{卷}/{页} + CDS 页面验证"Redirection error"判存亡 + LLM 判表 + 行级别名双向包含匹配）。
- **并发/缓存**: Unpaywall 10 并发；PDF 有效并发 3（min(5, arxiv 3)，限幅对全部任务生效）；`config/column_mapping_cache.json`（键=`表#md5(sorted property_ids)[:12]`，空映射不写防毒，无淘汰机制）；`data/supplementary/table_meta_cache.json`（11 条）。
- **已知问题**: `simbad_resolver.py` 死代码（B2 收敛后图已移除但文件仍导出）；ADS PUB_PDF 兜底未带 Authorization 头疑似必败；retrieval_priority 被引量权重实际 0.8；`total_catalogs=22` 与实有 27 不符。

### 2.5 子图3 多模态提取（subgraph3/）
- **职责**: 从下载 PDF 中提取目标天体宏观性质（VLM）+ bbox 定位 + 图证据。
- **关键文件**: `nodes/pdf_converter.py`、`nodes/vlm_extractor.py`、`nodes/bbox_annotator.py`、`nodes/figure_extractor.py`、`nodes/result_builder.py`、`utils/pdf_utils.py`、`utils/image_cache.py`、`utils/vlm_client.py`、`utils/bbox_vlm_client.py`、`schemas/subgraph3_io.py`。
- **核心逻辑**: 5 节点全串行（figure_extractor 特意串行在 bbox 后避开 LangGraph 并行写 key 冲突，返回局部 dict `{"figure_evidence": [...]}` 依赖部分更新语义）；VLM prompt 铁律（PropertySpec 白名单+页码防幻觉+只提取宏观整体+condition_tags 必须含 scope:global/metric:xxx）；JSON 解析链 loads→内层 text→repair_json；bbox 两阶段定位 prompt+7 条结构铁律；result_builder 对 confidence<0.7 丢弃、bbox 校验失败整条丢弃（"不再用默认框伪造溯源"）。
- **并发/缓存**: VLM 15 并发、bbox 100 并发、figure 100 并发；`image_cache` 磁盘单例（%TEMP%/graph3_image_cache，`cleanup()` 零调用无清理）。
- **已知问题**: `settings.pdf.dpi=100` 死配置（恒用函数默认 150）；`vlm.timeout=600` 从未传给 SDK；超时重试与外层重试共用 attempt 计数语义混乱；`_coerce_to_dict` 双份复制。

### 2.6 聚合（aggregation_node）
- **职责**: 三路提取结果汇入 `final_output`，保证任何降级路径顶层键恒定（永远输出合法 JSON）。

### 2.7 quality_pipeline（子图4）
- **职责**: 数据清洗与质检——Assessment（评估）→ Normalization（清洗，唯一改数据者）→ Variance（差异标注，不裁决）→ Export（输出）→ Insights（洞察）。
- **关键文件**: `graph.py`（198 行纯编排）、`routers.py`（417 行控制层）、`quality_state.py`（5 层嵌套 TypedDict+递归合并 reducer+初始状态工厂）、各子图 agents/、`configs/quality_rules.yaml`（52KB 领域段）、`configs/schema_mapping.yaml`（1178 别名/257 单位转换）。
- **核心逻辑**: Assessment 4 Stage（Profiling 8 工具 0 LLM → QualityAssessment 5 工具+Cohen's d → Scoring 加权+非线性惩罚+置信度校准 → DecisionReasoning 10 项检查+决策矩阵+`_ROUTE_SEVERITY` 取最严重）；Normalization 5 Stage（LLM 3 层动态工具体系：Base 6 工具/LLM-Adapted 参数注入/LLM-Generated 沙箱动态代码，AST 白名单+dry-run 5 条样本，Stage4 4 维校验+冲突复检）；Variance 5 Stage（Stage1 B→C 断链桥接，Stage2 规则分类+LLM 补 undetermined，Stage4 置信度 0.55/0.50 驱动重试）；Export 6 Stage（三路汇聚 A→D/B→D/C→D，多格式，校验失败 quarantine）；Insights 4 节点全 LLM+RAG（样本<2 跳 LLM）。
- **并发/缓存**: Assessment Stage2 8 线程；Normalization Stage3 ThreadPoolExecutor 并行；LLM 调用 timeout 120s + max_retries 3。
- **控制层**: gate×3（Retry→重入 retry_by_node≤3，Failed/HumanReview→human_target 簿记 V4 fix，Success 不覆写业务 route_decision V4 fix）；loop_controller 状态机（MAX_ITERATIONS/MAX_LOOP=3，超限 force_export）；HumanReview interrupt() HITL（决策转 actions_to_normalize 供 SourceRouter 消费，无待审项清 pending 防死循环）。

---

## 3. LLM 调用点总清单

| # | 节点 | 模型 | 用途 | 失败行为 |
|---|------|------|------|----------|
| 1 | 子图1 classify_query_type | qwen3.7-flash (t=0.1, max_tokens=10) | 查询类型分类（规则短路优先） | 直接 raise（无回退/重试，整图失败） |
| 2 | 子图1 extract_entity_and_properties | qwen3.7-flash (t=0.1, max_tokens=500) | 提取天体+性质（含 3 轮历史） | JSON 解析失败 raise；无 json_repair |
| 3 | P1 性质选择 | qwen3.8-max | 从 RAG 候选选性质生成 PropertySpec | TAP→astroquery→_star.json 三级兜底 |
| 4 | 子图2 map_columns_to_properties | qwen3.7-flash (t=0, max_tokens=4096) | 表列→标准性质名映射 | 失败→{}→该表 0 条；空映射不写缓存防毒；无重试 |
| 5 | 子图2 build_ads_query | qwen3.7-flash (t=0, max_tokens=300) | 构造 ADS 自然表达查询串 | 校验失败→''→property_id OR 拼接回退 |
| 6 | 子图2 supplementary 判表 | qwen3.7-flash (t=0, max_tokens=1000) | 判定 CDS 表分类+列 | 失败→默认 irrelevant 跳过 |
| 7 | 子图3 VLM 整篇提取 | qwen3.7-plus (t=0, max_tokens=65536, json_object) | 从 PDF 图像提取宏观性质（15 并发） | 限流退避 5s×2^n(3)/超时 5×10s；repair_json；失败记 extraction_failed |
| 8 | 子图3 bbox 标注 | qwen3.7-flash (t=0, max_tokens=500) | 数据点级 bbox 定位（100 并发） | 退避 2s×2^n 重试 3；失败返回 error dict，记录被 result_builder 丢弃 |
| 9 | 子图3 figure 检测 | qwen3.7-flash (t=0, max_tokens=2000) | 页级图表检测+相关性筛选（100 并发） | 失败返回 None 该页跳过 |
| 10 | quality Assessment Stage2 E2 | deepseek-v4-flash | LLM 完整性分析（条件性） | 失败返回 adjusted=1.0 满分（**B1 bug 未修**） |
| 11 | quality Normalization Stage2 | deepseek-v4-flash | Layer3 动态生成清洗工具（per-source 并行） | 回退 Base Tool + unconverted 标记；dry-run 沙箱 |
| 12 | quality Variance Stage2+5 | deepseek-v4-flash | 补 undetermined 分类 / 摘要生成 | 兜底数值驱动重试 / 模板 fallback |
| 13 | quality Export Stage3 | deepseek-v4-flash | 字段描述生成 | 模板 fallback（interpretation=LLM 不可用） |
| 14 | quality Insights 4 节点 | deepseek-v4-flash (prompt_parsing) | RAG 知识库洞察 | 样本<2 跳 LLM；全模板 fallback |
| 15 | scripts/add_units.py | deepseek-v4-flash (异步 16 并发) | 批量补 rag_properties 单位 | 429/5xx 退避 4 次；非法/漏答不写入 |
| 16 | scripts/query_properties.py | qwen3.7-plus | SIMBAD→RAG→选性质参考实现 | 与 P1 重复实现 |

---

## 4. 容错设计总结

三原则：**任何失败只跳过不中断主流程** / **永远输出合法 JSON**（顶层键恒定契约）/ **LLM 失败逐级降级**（模板→规则→默认值兜底）。

具体机制：
1. **入口层**：CLI 退出码体系（0/2/130）；`quality_adapter` 四层 try/except 降级（import/initial_state/context_inject/pipeline_failed → skipped+error_log），主图不断链；子图适配层异常捕获降级状态。
2. **网络层**：VizieR 4 镜像轮询（10s 超时，可重试异常才切镜像，单表最坏 40s）；ADS 3 次指数退避且 429 直接 skipped 防雪上加霜；PDF 瀑布式下载（60s 超时/50MB 预拒绝/%PDF 魔数校验/.part+原子改名）；SIMBAD 三级兜底；CDS 页面"Redirection error"判存亡。
3. **LLM 层**：限流/超时独立退避计数；JSON 链式解析（loads→内层 text→repair_json）；列名映射空结果不写缓存（防毒，避免临时失败被永久缓存）；LLM 生成工具 AST 白名单（禁 os/sys/network）+dry-run 5 条样本验证。
4. **编排层**：gate 工厂（Retry 重入≤3、Failed/HumanReview 走 human_target 保证 pending 簿记 V4 fix）；loop_controller 状态机（MAX_ITERATIONS/MAX_LOOP=3 → force_export 保留完整日志）；Normalization Validation 回退 Planning（≤2）；Variance 重入验证（≤2）；dispatch 后空值 `or {}` 防御；HumanReview 无待审项清 pending 防死循环；子图1 3 轮追问上限 + failed 状态 → 主图聚合空结果。
5. **数据层**：`error_log` Annotated[list, add] 增量合并；EAV provenance 四要素全程溯源；configs 线程本地领域兜底（并行工作线程回退 `_global_domain`）；Settings extra='ignore'（未知 .env 变量不报错）。
6. **已知薄弱点**：子图1 LLM 零健壮性（无 timeout/retry，直接 raise）；子图2 列映射 LLM 失败静默丢整表数据；两个 JSON 缓存无锁无淘汰；image_cache 无清理。

---

## 5. 重要发现

### 5.1 关键设计决策
- **PropertySpec 中枢契约**：字段名白名单+标准单位表，三路提取（数据库/论文/补充）统一归一目标。
- **EAV 记录模型 + provenance 四要素**：全程可溯源，是审计与下游聚合的基础。
- **列名映射三态语义**（None/{}/非空）："有白名单则宁缺毋滥"（D1 fix）。
- **Cohen's d 效应量**替代传统相对差异法：组内方差小时（std=10），|450-500|/10=5.0 → LARGE 冲突正确检出，传统 10% 相对差会漏报。
- **质量管线**：Export 仅对完美数据开放（10 项检查+决策矩阵+severity 聚合）；Normalization 是唯一有权改数据的子图（职责边界清晰）。
- **B2 收敛**：simbad_resolver 移除，P1 的 simbad_info 由 adapters 直接映射——减少一次冗余 LLM/网络调用。
- **领域感知配置** `{section}_{domain}` 优先：新增天体物理/化学领域只需注册 yaml 不改代码。

### 5.2 审计报告要点（AUDIT_REPORT 2026-08-05，docs/archive/）
- **已修复**：A1/A2/A3 致命断线 + B2/B3/B4/B5/B10/B12/B14/B15/D1/D4/D12/E6/S14/C10 共 17 项；合并过程 12 项修复由 MERGE_COMPLETION_REPORT 逐项确认。
- **未修复（B 级数据失真）**：
  - B1: llm_completeness 失败返回 adjusted=1.0 满分 → LLM 越不可用完整度越高。
  - B6: report_agent 用恒空 {} 覆盖真实 per_entity_modifications 统计。
  - B7: validation_agent 对 DB 记录强制要求 page 字段 → 恒报 provenance 缺失假报警。
  - B8: Insights synthesis 无条件覆写 execution_status=Success，吞掉 Export 的 Failed。
  - B9: context_state.quality_rules 恒为空 → adaptive_thresholds yaml 配置从未生效。
- **E/F 级**：E5（Cohen's d n<2 用相对差冒充、MAD=0 假分母）；E10（退出词子串误判：NGC224 命中 NGC2244；ADS 查询串无转义）；E13（planning_agent 三引号模板非法转义，Python 3.14 -W error 会 import 失败）；F 级（1054/3293 条空 unit 占 32%、9 条越界单位、post_AGB_star.json 孤儿文件、vid/out.json 单位语义存疑）。

### 5.3 潜在问题/风险
1. **子图1 路由顺序缺陷**：`target_entity && properties_asked → final_confirm` 排在 greeting 判断前，用户在 ask_properties 回复"你好"会被直接送去 final_confirm（真实可触达边界 bug）。
2. **无 .env 时 LLM 必挂**：Settings 默认 base_url='' → OpenAI SDK 静默回退官方端点+空 key，认证失败隐蔽。
3. **ADS PUB_PDF 兜底疑似必败**：`link_gateway/{bibcode}/PUB_PDF` 请求未带 `Authorization: Bearer {ADS token}` → 401。
4. **retrieval_priority 双重计被引量**：fl 未请求 score 字段 → score=citation_count → 被引量实际权重 0.8，ADS 相关性分完全缺失。
5. **PDF 有效并发是 3 非 5**（min(max_workers=5, arxiv_max_workers=3)，非 arXiv 任务也被压到 3）。
6. **supplementary key_value 恒取第一行**：行级溯源不精确。
7. **子图2 最坏时延**：27 表×4 镜像×10s 理论数十分钟，背离 performance_targets.database_total=30s。
8. **变量命名 typo 已成跨文件契约**：`normalization_tatus`（缺 s）/`normalization_ctions`（缺 a）/`human_review_tems`（缺 i）——拼写一致所以能工作，但属脆弱契约。
9. **human_review 写旧字段 `_from_conflict` 被 langgraph 静默丢弃**：循环保护从未生效（D 级契约不对齐）。
10. **质量管线 LLM 输出零运行时校验**（E9：字符串当列表 join 逐字符拆）；bbox 进度双计数+默认全页框伪造溯源（E11，后者已由"不再用默认框"修复）。

### 5.4 死代码 / 待办
- `tools/conflict/` 8 文件 1148 行零引用（逻辑已内联 agents）；`legacy/resolution_reasoning_agent.py` 396 行仅测试引用；`tools/insight/embedder.py`（NotImplementedError，V2 向量检索占位未接线）；`simbad_resolver.py`；`_DECISION_SYSTEM` 常量未调用；utils/llm.py 消歧子系统未接线；双 VLM client 70% 重复。
- 死配置：`dpi=100`（恒用 150）、`vlm.timeout=600` 未生效、`common_properties` 10 项零引用、`exit_intent_detected` 死状态字段、`configs/llm_config.yaml` 已删除但设计文档仍引用、`astroquery_ai/.env.example` 残留。
- 未实现：子图1 Web Headless Protocol（interaction_response/pending_interaction，文档注明"前端搭建时执行"）；polite_reject/handle_failure 用 print() 输出，Web 化必改。
- 缓存治理：column_mapping_cache/table_meta_cache/image_cache 均无淘汰/清理/锁，缓存键不含模型版本。

### 5.5 测试与文档现状
- 顶层 tests/ 28 个（26 离线全 mock + 2 network smoke 默认跳过；README 声称 24 已过期）；覆盖图装配/4 路由纯函数/quality 空短路/HITL 全链路/P1 降级 e2e/ADS 429/figure 裁剪落盘。
- 未覆盖：真实网络全链路（2026-08-06 CDS 故障曾阻断实测）、supplementary 路径（A2 修复后无测试守护）、column_mapper、quality 真实 LLM 流程（无 key 全 template fallback）。
- 文档矛盾：MERGE_PLAN_IMPL.md 状态"待实施"已过期；DESIGN.md 的 SIMBAD TAP/ADQL 与代码实际 sim-id HTTP 不符；SYSTEM_FLOW 声称 B12 已修复但审计记录未列；docs 仍引用已删除的 run.py/config.yaml。

---

## 6. 文件地标（新加入者阅读优先级）

| 优先级 | 文件 | 理由 |
|--------|------|------|
| P0 | `astroquery_ai/main_graph.py` | 主图 7 节点装配+2 路由，系统骨架 |
| P0 | `astroquery_ai/adapters.py` + `quality_adapter.py` | 接缝适配器：子图 state 投影/重建、quality 注入与四层降级 |
| P0 | `astroquery_ai/config.py` + 根 `.env.example` | 唯一配置源，全部模型/密钥契约 |
| P0 | `astroquery_ai/cli.py` | 实际入口与退出码/HITL 交互 |
| P1 | `astroquery_ai/subgraph1/graph.py` + `agents/*` | 澄清子图拓扑与 HITL payload 契约 |
| P1 | `astroquery_ai/subgraph2/graph.py` + `nodes/database_query.py` + `utils/vizier_client.py` + `utils/column_mapper.py` | 检索核心：27 星表、镜像 fallback、列映射缓存 |
| P1 | `astroquery_ai/subgraph3/graph.py` + `nodes/vlm_extractor.py` + `utils/vlm_client.py` | VLM 提取与并发/重试模型 |
| P1 | `astroquery_ai/property_standardization.py` | P1 中枢：SIMBAD→RAG→PropertySpec |
| P1 | `quality_pipeline/graph.py` + `routers.py` + `quality_state.py` | 质量管线编排、Gate/Loop 控制、5 层状态 |
| P2 | `quality_pipeline/assessment/...` + `normalization/...` + `configs/quality_rules.yaml` | 各 Stage 细节与领域配置 |
| P2 | `tests/`（conftest.py + 6 个测试文件） | 既有测试模式（全 mock），改动的回归基准 |
| P2 | `docs/archive/AUDIT_REPORT.md` + `MERGE_COMPLETION_REPORT.md` + `SYSTEM_FLOW.md` | 审计结论与合并修复记录（注意部分已过期，以代码为准） |
| P2 | `astroquery_ai/subgraph2/catalog/catalog_config.json` + `rag_properties/` | 数据资产：27 星表正则/元数据/单位、3293 条性质库 |

---

## 附录：关键数字速查

- 主图 7 节点 / 子图1 7 节点+2 路由 / 子图2 7 节点 / 子图3 5 节点 / 质量管线 6 子图节点+4 控制节点（graph.py 198 行、routers.py 417 行、quality_state.py 415 行）
- 星表 27 个（catalog_config/catalog_metadata/catalog_units 各 27 条）；RAG 性质库 100 文件/3293 条/8 类 category；OTYPE_PARENT 74 映射→4 父类；target_schema 28 字段/1178 别名；单位转换 34 组/257 条；知识库 78 条
- 并发参数：VLM 15 / bbox 100 / figure 100 / unpaywall 10 / PDF 3 / Assessment 8 / add_units 16
- 重试上限：LLM 生成 2、Validation 2、Variance 重入 2、B⇄C 循环 3、gate retry 3、ADS 3、VLM 限流 3/超时 5、bbox 3
- 超时：VizieR 10s（4 镜像最坏 40s）、ADS 30s、Unpaywall 30s、PDF 60s、SIMBAD TAP 30s、quality LLM 120s
