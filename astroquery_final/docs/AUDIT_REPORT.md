# 代码审计报告（AUDIT_REPORT）

> 审查日期：2026-08-10 ｜ 审查对象：`astroquery_final/`（9 子图 + `astroquery_ai/` + `quality_pipeline/`，约 2.6 万行 Python）
> 审查方法：13 单元独立初审 + 13 个对抗验证 agent（默认推翻制），仅 confirmed 入报告

## 1. 审查概览

### 1.1 范围与方法

- **13 个审查单元**：U01 主图装配 ｜ U02 意图澄清 ｜ U03 检索（网络）｜ U04 VLM 提取（网络）｜ U05 质量评估 ｜ U06 评估工具 ｜ U07 归一化（沙箱）｜ U08 冲突+人工复核 ｜ U09 导出 ｜ U10 洞察 ｜ U11 编排核心 ｜ U12 配置+脚本 ｜ U13 跨模块契约追踪（T1–T12）
- **两阶段**：每单元独立初审（只读、离线、禁 pytest/LLM/网络）→ 对抗验证（逐条重读代码尝试推翻，行号可修正）
- 验证手段：静态阅读 + 纯标准库 `python -c` 复现；关键机制（LangGraph 通道过滤/reducer 语义）对照已安装 langgraph 1.2.7 源码

### 1.2 统计摘要

| 单元 | 上报 | confirmed | refuted | uncertain | 单元 | 上报 | confirmed | refuted | uncertain |
|------|------|-----------|---------|-----------|------|------|-----------|---------|-----------|
| U01 | 6 | 6 | 0 | 0 | U08 | 7 | 7 | 0 | 0 |
| U02 | 6 | 6 | 0 | 0 | U09 | 7 | 7 | 0 | 0 |
| U03 | 8 | 8 | 0 | 0 | U10 | 7 | 6 | 1 | 0 |
| U04 | 6 | 5 | 1 | 0 | U11 | 6 | 4 | 2 | 0 |
| U05 | 6 | 6 | 0 | 0 | U12 | 5 | 5 | 0 | 0 |
| U06 | 8 | 8 | 0 | 0 | U13 | 6 | 6 | 0 | 0 |
| U07 | 12 | 11 | 1 | 0 | **合计** | **90** | **85** | **5** | **0** |

**confirmed 严重度分布**（去重合并后 80 条）：critical **1** ｜ high **17** ｜ medium **37** ｜ low **25**

**confirmed 类别分布**：data_correctness 26 ｜ error_handling 10 ｜ state_contract 10 ｜ llm_parsing 9 ｜ config_drift 7 ｜ logic_bug 8 ｜ interface_mismatch 6 ｜ dead_code 5 ｜ security 2 ｜ resource_leak 2 ｜ performance 1 ｜ other 2

> 去重说明：U08[0] 与 U13[0]（人工裁决整源覆盖）同根因合并为 C-01；U01[0] 与 U13[3]（figure_evidence 通道）合并为 H-01；U05[1] 与 U06[0]（DB record_id 正则）合并为 H-02；U07[0]/U08[2]/U13[2]（normalize_unit 重贴单位）合并为 H-03；U08[5] 与 U13[1]（cross_id 人工裁决丢弃）合并为 H-04。

## 2. 审查方法与流程

1. **初审（13 agents 并行）**：按单元类型执行维度清单 —— 图装配 G1-G8（节点接线/通道声明/reducer 语义/checkpointer/HITL/状态机/死代码）、LLM agent L1-L8（JSON 解析/类型校验/重试/契约读写/注入面/写盘/性能）、确定性工具 D1-D6（数值公式/天文格式/边界/资源/缓存/配置漂移）、配置脚本 C1-C5（yaml 对齐/产物键名/幂等/env/破坏性覆盖）。
2. **对抗验证（13 agents 并行）**：逐条重读 `file:line` ±30 行，沿失败场景独立推演（允许 python -c 复现），**默认 refute**；仅能独立证毕才判 confirmed；行号有误但问题成立 → confirmed + corrected_line；需运行环境/网络/LLM 才能判定 → uncertain。
3. **合成**：同根因去重 → 分级 → 写本报告。**0 条 uncertain**（所有候选均在静态约束下证毕或证伪）。

**严重度定义**：critical = 主路径静默错误数据/必然崩溃/安全/契约断裂；high = 边缘路径错误或 LLM 输出未校验或重试缺陷或资源泄漏；medium = 死代码/配置漂移/性能/统计不准；low = 影响极小。

**基准契约**：已知正确且经本轮验证的契约（quality.sources[sid] 字段、report_state 四报告、workflow_state 状态机、_merge_dict 三态 reducer、routers.py 单一路由权威、HITL dunder 键）未破坏者不重复上报；本轮共发现 **3 处已知修复的回归**（M9 typo 只改 writer、A7 透传链被 scoring 打断、R1-B8 透传被 insights 前序节点打断）。

## 3. 总体结论

### 3.1 子系统健康度

| 子系统 | 评价 | 关键问题数 |
|--------|------|-----------|
| 检索/提取子图（U02-U04） | **中等**。网络路径（URL 编码/文件名安全/资源释放）审查充分、多数正确；短板在 LLM 输出防御（2 处整链路崩溃风险）与缓存/资源生命周期 | C0/H4/M8/L5 |
| 质量评估（U05-U06） | **中等**。数值算法（Cohen's d/Bootstrap/CI）验证正确；但存在 2 个系统性误判（DB record_id 全量误路由 Normalization、域紧度乘子方向反）与 1 个 A7 状态透传回归 | C0/H2/M7/L4 |
| 归一化（U07） | **高风险**。沙箱逃逸防护（C1）完整，但**沙箱无超时**（LLM 死循环代码可挂死管线）、冲突动作 `normalize_unit` 重贴单位损坏数值（跨 3 单元证据）、3 处工具日志/统计断链 | C0/H2/M6/L3 |
| 冲突+人工复核（U08） | **最高风险**。**1 条 critical**：A→E 人工裁决因空作用域整源覆盖全部记录；另有 C→E 两处决策静默丢弃、critical 异常绕过人工直接导出 | C1/H3/M1/L1 |
| 导出（U09） | 中等。CSV 注入、写盘无异常降级、宽表折叠与注释不符；**M9 修复回归**（normalization_status typo 只改 writer） | C0/H1/M5/L1 |
| 洞察（U10） | 中等。**R1-B8 回归**（Failed 被覆写为 Success）+ LLM 逐项校验缺口可致整管线 skipped；KB 检索层验证正确 | C0/H2/M2/L2 |
| 编排核心（U11/U13） | **良好**。T1-T12 契约追踪绝大多数一致；3 处状态边界缺陷（retry_by_node 重置被 reducer 吞掉、Assessment Failed→dispatch 信号丢失、语义去重漏单位键） | C0/H0/M3/L2 |
| 配置/脚本（U12） | 中等。13+ 配置段零消费（改 yaml 无效）、metallicity/density 单位组错配、3 脚本硬编码个人机器路径 | C0/H0/M3/L2 |

### 3.2 关键风险 Top 10

| # | 风险 | 严重度 | 一句话影响 |
|---|------|--------|-----------|
| 1 | 人工裁决 human_replace 空作用域 → 整 source 全部记录被单值覆盖（`human_review_agent.py:228`） | **critical** | A→E 质量审核项用户采纳/自定义一个值 → 该源 RA/Dec/星等/通量全部字段被替换为同一值，静默导出 |
| 2 | 沙箱 exec 无超时（`normalization_agent.py:469`） | high | LLM 生成 `while True: pass` 通过 AST 校验 → 整条管线永久挂起，无兜底 |
| 3 | conflict `normalize_unit` 只改单位标签不换算数值（`normalization_agent.py:122`，3 单元证据） | high | 单位量纲不匹配时 3000 K → 3000 eV 式伪数据，且 unit_converter 随后跳过固化损坏 |
| 4 | 三处 execution_status 透传回归：scoring 硬编码 Success（`quality_scoring_agent.py:270`）、insights 前序节点覆写（`field_insight_agent.py:170`）、M9 typo 只改 writer（`metadata_generator.py:113`） | high×3 | 子图级重试/HumanReview 不可达、Export 失败被报告为 Success、元数据谎称清洗零遗留 |
| 5 | LLM 字符串型 confidence 无 float 强转（`confidence_evaluation_agent.py:42`） | high | TypeError 击穿冲突子图 → quality_adapter 吞掉 → **整条质量管线静默跳过**，未质检数据照常导出 |
| 6 | critical 异常（flag_for_review）C→E 后无待审项（`resolution_report_agent.py:141/225`） | high | 子图明确要求人工介入的数据被静默转 Export |
| 7 | cross_id 人工裁决 source_id 恒空（`human_review_agent.py:121`） | high | 用户对 C→E cross_id 项的裁决全部被 source_router 丢弃，数据原样导出 |
| 8 | bbox VLM 输出类型未校验（`bbox_annotator.py:60`） | high | 页码为字符串/浮点时节点崩溃 → 该查询全部论文提取记录静默丢失 |
| 9 | DB record_id 命中 paper 格式正则（`format_checker.py:88`） | high | 所有含 VizieR 记录的数据集系统性误路由 Normalization，A→D 直达 Export 对 DB 源不可达 |
| 10 | figure_evidence 通道未声明（`adapters.py:409` + `state.py`） | high | LangGraph 静默丢弃顶层键，final_output.figure_evidence 恒为空，VLM 图证据功能整体失效 |

## 4. 按严重度问题清单

### 4.1 Critical（1 条）

**C-01. A→E 人工裁决 human_replace 无字段/记录/实体作用域，整 source 全部记录被单值覆盖**
- **位置**：`subgraphs/data_human_review/human_review_agent.py:228-239`（生成侧）→ `subgraphs/data_normalization/agents/normalization_agent.py:95-108`（消费侧）（单元 U08/U13 同根因合并）
- **失败场景**：Assessment 因提取质量低把 source S 路由 HumanReview（QHR 审核项只含 `source_a={source_id}`，field_name/entity_name/record_ids 全空）→ 用户在 HITL 选"采用 Source A 的值"/自定义值并输入一个数（或直接回车得空串）→ `_decisions_to_actions` 生成 `human_replace{record_ids:[], field:"", entity_name:""}` → `_apply_conflict_ction` 三个过滤条件全空全部放行 → S 的**每一条记录、每一个字段**被 `rec["field_value"]=V` 覆盖（回车时空串覆盖）→ 经 E→B→Export 静默导出，`_human_replaced` 标记在 export 白名单中被剥离，损坏无痕。
- **证据**：`human_review_agent.py:340-357` QHR 项仅 `source_a={"source_id": sid}`；`:121` source_id 取值；`:228-239` 生成动作；`normalization_agent.py:98-108` 三个 `if X and ...: continue` 全空放行；M1 fix 只防了 `new_value is None`（`:91-93`），空串 `""` 放行（stdlib 验证 `float("")` 走 except → selected=""）。
- **修复建议**：① 对 QHR 质量类审核项禁用 adopt/custom 裁决（仅允许 skip/retain_both 或降级为 annotate）；② `_decisions_to_actions` 生成 human_replace 前强制校验 record_ids 与 field_name 非空，空则改生成 annotate/skip 并记 warning；③ `_get_user_choice` 空串输入视为无效回退重问；④ 消费端 `_apply_conflict_ction` 对三条件全空的 human_replace 直接拒绝并写 errors（防御性校验）。
- **验证**：confirmed（双 agent 独立证毕，含全链路路由/挂载/透传实证）。

### 4.2 High（17 条）

**H-01. figure_evidence 未在 MainGraphState 声明，LangGraph 静默丢弃，final_output.figure_evidence 恒为空**
- **位置**：`astroquery_ai/adapters.py:409` + `astroquery_ai/aggregator.py:66` + `astroquery_ai/state.py`（U01/U13 合并）
- **失败场景**：subgraph3 VLM 成功裁剪出 N 张相关图 → `extraction_node` 返回 `figure_evidence=[...]` → LangGraph 1.2.7 `pregel/_algo.py apply_writes` 对未声明通道写 `logger.warning("wrote to unknown channel ... ignoring it")` 并丢弃 → `aggregator` 恒读 `[]`。图证据功能整体失效且无错误提示。
- **修复建议**：`MainGraphState` 增加 `figure_evidence: NotRequired[List[Dict]]`（聚合通道即可，单生产者单消费者）；或并入已声明的 `paper_results` 嵌套结构。
- **验证**：confirmed（对照安装版 langgraph 源码 `_algo.py:308-313`，生产/消费两端及 state.py 全文核对）。

**H-02. record_id 正则 `^.+_.+_\d+$` 不匹配 DB 记录，所有 database source 系统性路由 Normalization**
- **位置**：`quality_pipeline/tools/assessment/format_checker.py:88`（U05/U06 合并）
- **失败场景**：subgraph2 的 DB record_id 形如 `REC_src1_III/130_5_2_flux_density`（末段为属性名）恒不匹配 → 每条 DB 记录计 1 条 record_id_issues → format.total_issues>0 → decision 追加 format_issues → **含 VizieR 记录的数据集永远路由 Normalization**（8 项检查全过也无法 Export），score 还损失 0.5×n_db/n_records。同单元 `extraction_quality.py:97` 却有"DB 记录跳过 paper 格式校验"分支，两工具自相矛盾。
- **修复建议**：record_id 校验前加 `if not is_database_record(rec):` 跳过分支（与 extraction_quality 对齐），或为 DB id 定义独立格式 `^REC_.+_\d+_[A-Za-z][A-Za-z0-9_]*$`；修复后回归 decision 路由测试。
- **验证**：confirmed（正则三组 DB id 实测不匹配、paper id 匹配；消费链 82→73-75→205-206 全链核对）。

**H-03. conflict normalize_unit 动作只改单位标签不换算数值，量纲不匹配时产出值/单位配对的伪数据**
- **位置**：`subgraphs/data_normalization/agents/normalization_agent.py:122-131`（U07/U08/U13 三单元证据合并）
- **失败场景**：unit_error（量纲不匹配，如 K vs eV、mag vs Jy）触发 C→B → `resolution_report_agent.py:98-110` 为每涉事 source 生成 `{action:normalize_unit, from_unit, to_unit}` → 消费端仅 `rec["field_unit"]=to_unit` 从不换算 field_value → 随后 base 工具 `unit_converter.py:146-147` 见 `unit==target` 直接 `continue` 跳过 → 损坏固化：3000 K → 3000 eV、0.5 Jy → 0.5 mag，无任何 unconverted 标记。
- **修复建议**：normalize_unit 动作应携带换算语义 —— executor 调用 unit_converter 按 from_unit→to_unit 因子换算数值；量纲不匹配/无规则时记入 errors（kind=unconverted_unit）而非重贴单位；或对量纲不匹配的 unit_error 一律路由 HumanReview。
- **验证**：confirmed（三 agent 独立证毕，stdlib 模拟复现 21.3/mag→21.3/mJy；执行顺序 conflict_ctions 先于 base tools 实证）。

**H-04. C→E cross_id 人工裁决 source_id 恒为空串，被 SourceRouterAgent 过滤，用户裁决全部静默丢弃**
- **位置**：`subgraphs/data_human_review/human_review_agent.py:121/265-281` → `subgraphs/data_normalization/agents/source_router_agent.py:63-66`（U08/U13 合并）
- **失败场景**：V3.0 resolution_report 从不产出 per_conflict 键（`resolution_report_agent.py:188-235` 无此键）→ `_extract_pending` 的 cross_id 项 `full={}` → `source_a={}` → 决策记录 source_id="" → human_replace/annotate 动作 source_id="" → `source_router_agent` `if source_id:` 判定为假丢弃 → sources_to_process 为空 → Normalization 直接 Export。用户对 cross_id 冲突的裁决（adopt/custom/retain）永不落地，异常数据原样导出。
- **修复建议**：cross_id 异常本身带 `source_ids`（`statistical_conflict.py:683`）—— resolution_report_agent 的 anomaly_flags/human_review_items 保留 source_ids；`_extract_pending` 以 source_ids 回填 source_a；SourceRouterAgent 对空 source_id 记 warning 入 errors 而非静默跳过。
- **验证**：confirmed（全链静态证毕，路由可达性 unit_error→Conflict→C→E 实证）。

**H-05. P1 LLM 输出的 requested_properties 条目未做形状校验，非 dict 条目直接 TypeError 使整阶段静默失败**
- **位置**：`astroquery_ai/property_standardization.py:588`（`select_properties_with_llm` :428 无校验）
- **失败场景**：LLM 返回 `{"requested_properties": ["fe_h", "distance"]}`（字符串列表）→ `[item['property_id'] for item in selected]` 抛 TypeError（stdlib 复现）→ adapter 捕获仅返回 error_log → P1 的 simbad_info/property_spec/target_schema 全部静默丢失 → retrieval/quality 在无字段白名单、空 target_schema 下盲跑。
- **修复建议**：select_properties_with_llm 返回前过滤非 dict/缺 property_id 条目（记 warning）；全部非法返回 (None, err) 走既有错误路径。
- **验证**：confirmed（python 复现 TypeError/KeyError，588 行无 try，adapters.py:173-179 吞错，main_graph.py:163 无条件边续跑全链核对）。

**H-06. subgraph1 LLM 调用失败直接 raise，零重试零回退，单次瞬时故障静默丢弃整次查询**
- **位置**：`subgraphs/subgraph1/utils/llm_utils.py:126-128/225-227` + `initial_parse.py:75-78`
- **失败场景**：DashScope 瞬时 429/超时 → classify/extract raise → 适配层 `adapters.py:132-141` 降级 `clarification_status="failed"`、target_entity=None → 主图 aggregation 输出空 records，用户拿到空结果且仅 error_log 有痕迹。对比共享设施 `quality_pipeline/utils/llm.py` 有 max_retries=3 + 3 策略回退。
- **修复建议**：子图内指数退避重试（2 次 0.5s/1s）；classify 失败回退 astronomical 走 ask_entity 追问路径而非整图失败；extract 失败返回空 dict 转追问。
- **验证**：confirmed（重读证毕，graph.py 无重试回环、全仓 retry_by_node 仅 quality_pipeline 使用）。

**H-07. extract_entity_and_properties JSON 解析无回退：greedy 正则 + json.loads 失败即 raise**
- **位置**：`subgraphs/subgraph1/utils/llm_utils.py:212-227`
- **失败场景**：LLM 响应尾部含花括号解释文本（如 `...[]}\n（M31 即{梅西耶编号}）`）→ greedy `\{.*\}` 吞到最后一个 } → JSONDecodeError → raise → 适配层降级 failed → 空 records。尾逗号同样失败（均已 python 实测）。
- **修复建议**：多层解析：剥 fence/前后空白 → json.loads → 失败用 `json.JSONDecoder().raw_decode` 定位首个完整对象 → 仍失败重试一次 LLM（prompt 强调严格 JSON）→ 再失败才抛错。
- **验证**：confirmed（python 复现 JSONDecodeError；BOM 子断言略夸大但核心场景成立）。

**H-08. table_meta_cache 缓存键仅 table_id 缺 target_entity，且 LLM 失败兜底被永久缓存**
- **位置**：`subgraphs/subgraph2/nodes/supplementary_query.py:275-286/428`（兜底 :167-169）
- **失败场景**：`_llm_judge_table` 判断结果强依赖 prompt 中的目标天体，但缓存键只含 table_id 且为包级持久文件（跨 query_id 共享）。查询 A 判 whole_entity+entity_column=null 的表 → 查询 B（不同天体）命中缓存走 `kept_rows=list(table)` 整表模式，把 A 天体的数据行写成 entity_name=目标 B 的记录；反向：LLM 超时兜底 irrelevant 被缓存 → 之后所有查询永远跳过该表。对比 `column_mapper.py:156-163` 有"空映射不缓存"约定，本文件违反。
- **修复建议**：缓存键并入 target_entity 指纹（`f"{table_id}#{target_entity}"`）；LLM 失败/解析失败兜底不得写缓存；命中缓存时校验 judgment 结构（dict + table_class 四枚举）。
- **验证**：confirmed（行号 275-276/286/428/167-169/342 全部与代码一致）。

**H-09. bbox VLM 输出类型未校验：page 为字符串/浮点或 extractions 为对象时整个 bbox 节点崩溃**
- **位置**：`subgraphs/subgraph3/nodes/bbox_annotator.py:60/64`（46-72 行无 try）
- **失败场景**：VLM 返回 `{"page": "4"}`（字符串）→ `page < 1` 抛 TypeError；page 为 float（JSON 4.0）→ `image_paths[page-1]` 抛 TypeError；extractions 为 dict → `extraction.get("page")` 抛 AttributeError（均已沙箱复现）。vlm_extractor 出口（:282）零校验即 return success。异常击穿节点 → adapters.py:392-403 兜底返回 `paper_records=[]` → **该查询全部 35 篇论文已提取的记录从最终输出静默消失**。
- **修复建议**：① vlm_extractor 出口逐条归一化（page 用 int() 转换失败丢弃该条、extractions 非 list 判论文失败）；② bbox 任务构建循环逐条 try/except，坏记录写入 bbox_annotation_failed 并 continue。
- **验证**：confirmed（三种异常输入均沙箱复现；上游零校验与下游兜底全链静态可证）。

**H-10. image_cache.cleanup() 零调用点，%TEMP%/graph3_image_cache 跨查询无限累积**
- **位置**：`subgraphs/subgraph3/utils/image_cache.py:91`（全仓库 grep 无调用点）
- **失败场景**：pdf_batch_converter 每篇论文全页面 150DPI PNG 落盘（35 篇 × ~20 页 ≈ 数百 MB/查询），无 TTL 无容量上限无删除路径 → 连续 K 次查询后系统盘耗尽 → 后续查询 pdf_to_images 写盘失败 → 提取链路完全瘫痪。docs/CODE_ANALYSIS.md:79 亦自认为已知问题。
- **修复建议**：result_builder 后或 extraction_node 返回前调用 `image_cache.cleanup()`（按 query_id 清本次临时页图）；或增加 TTL/容量上限淘汰。
- **验证**：confirmed（grep 仅命中定义与 docs 提及；pdf_converter.py:55 只写不删）。

**H-11. Scoring 节点硬编码 execution_status="Success"，打断 A7 透传链 —— 子图级重试机制失效（回归）**
- **位置**：`subgraphs/data_assessment/agents/quality_scoring_agent.py:270`
- **失败场景**：profiling 工具异常置 Retry/Failed（profiling_agent.py:179-185）→ quality_assessment 透传（:337-344）→ **scoring 无条件覆写 Success**（`_merge_dict` 标量覆盖，quality_state.py:72）→ decision 读到 Success 透传 → gate 永不重入 assessment 或转 HumanReview → 子图级重试形同虚设，失败被静默掩盖（如 semantic_types={} → out_of_range_count 恒 0）。
- **修复建议**：scoring 与 assessment/decision 同款透传：`exec_status = prev if prev in ("Failed","Retry") else "Success"`；补子图级测试：profiling 工具异常后断言 gate 读到非 Success。
- **验证**：confirmed（透传链逐节点验证，含 _merge_dict 覆盖语义复现；注：OPTIMIZATION_STATUS 中 A7 标记为"—"未验证）。

**H-12. 沙箱 exec 无超时/资源上限：LLM 生成的 while True 死循环永久挂起整条管线**
- **位置**：`subgraphs/data_normalization/agents/normalization_agent.py:469-470` + `planning_agent.py:614`
- **失败场景**：AST 白名单允许 ast.While/ast.For，`while True: pass` 通过全部校验（python 复现校验 PASSES）→ exec 无限循环 → `future.result()` 无 timeout → `with ThreadPoolExecutor` 退出 join 全部线程 → 整节点永不返回，管线挂死，无任何兜底。
- **修复建议**：沙箱代码在独立进程/线程执行并设硬超时（5-10s）+ 输出大小上限，超时判生成失败回退 Base Tools；或 AST 校验限制 While/For 迭代次数。
- **验证**：confirmed（复刻校验逻辑验证 while True 放行；exec/result()/join 全链无超时机制）。

**H-13. critical 级 flag_for_review 异常路由 C→E 后，人工审核无待审项而静默转 Export**
- **位置**：`subgraphs/data_conflict/agents/resolution_report_agent.py:141-143/225`
- **失败场景**：extraction_error（confidence<0.3）生成 action="flag_for_review"（:118-126）→ has_critical 路由 HumanReview（:141-143）→ 但 resolution_plan.human_review_items 只收录 action=="human_review" 的 cross_id 项（:225）→ human_review_agent._extract_pending 四路皆空（human_review_items/anomaly_flags/per_conflict 恒空/per_source_routes 无 HumanReview）→ `_no_conflicts_result` 写 route_decision="Export" → **critical 数据未审核直接导出**。
- **修复建议**：resolution_report_agent 将 severity=critical 的 flag_for_review 项也写入 human_review_items（或单独 critical_review_items 键）；human_review_agent 增加对 critical anomaly_flags 的兜底提取。
- **验证**：confirmed（全链静态证毕，含 per_conflict 键 V3.0 不产出、A→C 来源 per_source_routes="Conflict" 不匹配）。

**H-14. LLM 返回字符串型 confidence 未经 float 强转，置信度评估节点 TypeError 崩溃，整个质量管线被静默跳过**
- **位置**：`subgraphs/data_conflict/agents/confidence_evaluation_agent.py:40-42`（写入端 `conflict_classification_agent.py:183`）
- **失败场景**：prompt_parsing 模式下 LLM 写 `"confidence": "0.8"` → `conf < 0.55` 抛 TypeError（stdlib 复现）→ 节点异常 → conflict 子图 invoke 抛出 → `quality_adapter.py:190-200` except 捕获返回 `quality_report={skipped:true}` → **数据未经任何质检照常导出**。
- **修复建议**：classification agent 写入前 `try: float()` 失败回退 0.5；confidence agent 对 conf 做 isinstance 数值校验，非法按 0 处理记 warning。
- **验证**：confirmed（全链静态证毕+stdlib 复现；llm.py:78 structured_output_method="prompt_parsing" 使字符串置信度现实可达）。

**H-15. M9 typo 修复只改了 writer 未改 reader：normalization_status vs normalization_tatus（回归）**
- **位置**：`quality_pipeline/tools/export/metadata_generator.py:113`（writer `report_agent.py:26` 已改）
- **失败场景**：M9 前两端拼写一致（均 typo）可工作；修复后 writer 改 `normalization_status` 而 reader 仍读 `normalization_tatus` → 恒命中默认值 "Completed" → Normalization 以 "Completed_With_Issues" 结束时导出元数据仍输出 "Completed"，与 quality_summary 的 remaining_issues>0 直接矛盾。
- **修复建议**：reader 改为 `normalization.get("normalization_status", "Completed")`；全仓 grep 已确认无其他读取点。
- **验证**：confirmed（全仓 grep 仅两处；OPTIMIZATION_STATUS 将 M9 标为完成但实际只改单端）。

**H-16. field_insight 无条件覆写 execution_status="Success"，R1-B8 Failed 透传被前序节点击穿（回归）**
- **位置**：`subgraphs/data_insights/agents/field_insight_agent.py:170`（relationship :127 / recommendation :119 同）
- **失败场景**：主图 `graph.py:190` 无条件 Export→Insights（Export 失败也执行）。Export 校验失败写 Failed（export_generation_agent.py:40）→ field_insight 先写 Success（标量覆盖）→ synthesis_agent.py:142-143 读到的 upstream_status 恒为 "Success" → R1-B8 透传成为死代码 → **管线最终状态在 Export 失败时被静默报告为 Success**。
- **修复建议**：三个前序节点 _return 读入参 state 的 execution_status，仅当不为 "Failed" 才写 "Success"（与 A7 透传模式一致）；或在 insights_graph END 前加透传节点。
- **验证**：confirmed（独立证毕，含 _merge_dict 标量覆盖语义）。

**H-17. field_insight LLM 输出逐项校验缺口：confidence=None/非数值或非 dict 条目在 _merge_with_deterministic 崩溃，H5 修复不完整**
- **位置**：`subgraphs/data_insights/agents/field_insight_agent.py:263`（:226/:155 同）
- **失败场景**：H5 只校验 batch_insights 是 list。条目非 dict → `ins.get` AttributeError；confidence=null → `float(None)` TypeError；"0.9x" → ValueError（均 python 实测）。调用在批次 try/except 之外（:155）→ 节点崩溃 → quality_adapter 顶层 except 丢弃整条质量管线结果（`pipeline_failed`），已完成的 Assessment/Normalization/Conflict/Export 全部作废。
- **修复建议**：_merge_with_deterministic 内逐条防御：非 dict 跳过记 warning；confidence try/except 包裹 float 并夹 [0,1]；cause_hypotheses/typical_range/kb_references isinstance 校验；或将 :155 整体包入 try/except 回退纯确定性模板。
- **验证**：confirmed（三种异常输入 python 实测；155 行位于 try 之外确认）。

### 4.3 Medium（37 条）

**状态/契约类**

- **M-01. retrieval_node 异常路径用 `_empty_retrieval()` 的 simbad_info 空壳整体覆盖 P1 已解析结果** — `astroquery_ai/adapters.py:218`（U01）。subgraph2 抛异常时返回 `{status:failed, main_id:None}` 空壳 → 覆盖 P1 的 main_id/otype/ra/dec → final_output.simbad_info 丢失、extraction entity_type 落 "Unknown"、quality 的 entity_type_overrides 不注入。与成功路径 B3 fix（:297-306 合并保留）直接矛盾。修复：异常路径不写 simbad_info 键或同样合并 `{**p1_simbad, "status":"failed"}`。✅
- **M-02. `_merge_dict` 对空 dict 递归合并使 dispatch 的 retry_by_node={} 重置静默失效** — `quality_pipeline/routers.py:277`（U11）。复现：merge({retry_by_node:{assessment_graph:3}}, {retry_by_node:{}}) → 旧值残留。E→B 后 normalization 失败（已重试 3 次）→ gate 判 retries≥MAX_RETRIES 立即 HumanReview，形成 HR⇄B 交互循环。修复：置 None（走覆盖分支）或配置覆盖型 reducer；补 E→A/E→B 边界测试。✅
- **M-03. Assessment Failed/重试耗尽的 HumanReview 决策在 dispatch 边界丢失** — `quality_pipeline/routers.py:141`（U11）。gate Failed 分支写 route_decision="HumanReview"，但 graph.py:98 human_target=NODE_DISPATCH，route_after_dispatch 只读 pending_sources 不读 route_decision → profiling 部分失败时 per_source_routes 可能全为 Export → 未完整评估的数据直接导出。修复：dispatch 检查 route_decision=="HumanReview"/execution_status=="Failed" 时强制返回 NODE_HUMAN_REVIEW。✅
- **M-04. Profiling 读 input_data 而 quality_assessment/decision 读 current_data，E→A 重入时 profile 基于过期数据** — `subgraphs/data_assessment/agents/profiling_agent.py:147`（U05）。normalization 修改 current_data 后经 E→A 重入，profiling 的 semantic_types/out_of_range_count 全部基于原始数据 → decision 用旧计数与当前记录数算 oor_ratio 可能冲突误路由。修复：统一读 current_data（仅首次回退 input_data）。✅
- **M-05. conditional_routes 的 alias_fields 条件缺少 A5 fix-③ 的 expected 空守卫** — `subgraphs/data_assessment/agents/decision_reasoning_agent.py:285`（U05）。target_schema 为空时凡被路由 Normalization 的 source 都被附加 alias_fields 全字段条件 → planning 为全部字段生成 identity schema_mapping，规划与病因不符。修复：`if src_aliases and src_expected:` 与 :64 同款守卫。✅
- **M-06. verification 对 state 共享的 classified_variances 列表原地 append，重试轮次重复组标注翻倍** — `subgraphs/data_conflict/agents/evidence_collection_agent.py:168`（U08）。_merge_dict 按引用存值无拷贝；`_after_confidence` 重入 verification 第二轮再次 append → resolution_report 中同一重复组出现 2 份，且 classification 报告被混入 duplicate_observation 条目；重试（确定性 verification 不重分类）纯空转。修复：append 前 `list(...)` 拷贝或写入独立键；重试边应回退 classification 或去掉。✅

**LLM 输出防御类**

- **M-07. classify_query_type 输出无白名单校验：content=None 崩溃、任何非 yes 响应一律判 invalid 误拒** — `subgraphs/subgraph1/utils/llm_utils.py:116`（U02）。content 为 None 时 `.strip()` AttributeError → 整图降级；"不确定"/空串/截断输出一律映射 invalid → polite_reject 礼貌拒绝。修复：content 判空后 None/空串回退保守路径（astronomical 走 ask_entity 追问）；判定改为正则/显式枚举合法值。✅
- **M-08. requested_properties/target_entity 无类型校验：字符串/数值进入下游导致乱码性质或崩溃** — `subgraphs/subgraph1/utils/llm_utils.py:220`（U02）。LLM 返回字符串时 `", ".join('distance')` 逐字符拼接出乱码性质喂给 P1 筛选 LLM；返回数值时 join 抛 TypeError 整图降级。修复：返回前校验 requested_properties 必须 list 且元素为 str、target_entity 必须 str，不符置默认值记 warning。✅
- **M-09. final_confirm else 分支把空回车/所有非 y/m 输入一律当取消** — `subgraphs/subgraph1/nodes/final_confirm.py:113`（U02）。白名单仅 "y/yes/确认/是" 与 "m/modify/修改"；空回车与 "是的"/"对" 落入 else 置 cancelled → 主图 aggregation 空结果，用户以为已确认。修复：空输入/未识别输入重发 interrupt 追问（限定 y/m/n），仅显式 "n/取消" 才置 cancelled。✅

**数值/数据正确性类**

- **M-10. CSV 注入：_csv_escape 不转义 =,+,-,@ 前缀** — `quality_pipeline/tools/export/format_exporter.py:157`（U09）。field_value/context_snippet 来自论文正文提取（外部不可信），`=HYPERLINK(...)` 原样输出 → Excel 打开触发公式执行（OWASP CSV Injection）。field_standardizer 前缀正则不含 '='。修复：前缀 = + - @ /tab 强制加双引号包裹或前置单引号。✅
- **M-11. _write_export_iles 无任何异常处理：单个文件写失败致整条质量管线输出全丢** — `subgraphs/data_export/agents/export_generation_agent.py:47`（U09）。7 个输出文件 open()/json.dump 均无 try；磁盘满/权限 → OSError 冒泡 → quality_adapter 捕获返回 skipped → 已组装好的 quality_summary/structured_data 全部丢失，违反"单工具失败→跳过/模板替代"降级承诺。修复：逐文件独立 try/except 记 manifest failed_files 并继续。✅
- **M-12. json_wide 重建时 extra 字段的 _unit 单位列被静默丢弃** — `quality_pipeline/tools/export/schema_formatter.py:80`（U09）。重排循环 `not fn.endswith("_unit")` 条件对 extra 字段只追加 fn 列；csv_wide 保留单位列而 json_wide 丢失，同一输出两种宽表不一致（stdlib 模拟验证）。修复：extra 追加时同步 `ordered_wide[fn+"_unit"] = json_wide.get(fn+"_unit", [])`。✅
- **M-13. 宽表折叠注释与实现不符：CSV 宽表是首值非 LWW，json_wide "零丢失" 承诺不成立** — `quality_pipeline/tools/export/format_exporter.py:98`（U09）。折叠分支从不更新 existing["value"]（首值固定），且按首值去重追加：[5,6,5]→csv=5、json_wide=[5,6]（丢 1 条）；[5,5,6]→[5,6] 第二个 5 静默丢失且不计入 collapsed_records。修复：同步更新 existing["value"] 实现真 LWW；all_values 无条件追加。✅
- **M-14. 长表 CSV 对 None 值输出字面量 "None"** — `quality_pipeline/tools/export/format_exporter.py:60`（U09）。`str(r.get("field_value",""))` 在值为 None 时输出 "None"；宽表输出空串、JSON 输出 null，三格式不一致。触发路径确定性可达：planning_agent.py:337 选 fill_default → missing_value_handler 写 None。修复：`str(r.get("field_value") or "")`。✅
- **M-15. executor 日志键提取漏掉 marked_issues/format_log：3 个工具的修改不进 modifications 也不进 data_trace** — `subgraphs/data_normalization/agents/normalization_agent.py:218`（U07）。提取链只认 log/mapping_log/modification_log/conversion_log 四键，而 missing_value_handler 返回 marked_issues、format_standardizer 返回 format_log、duplicate_handler 返回 duplicate_ids → 填值/去重删除/格式改写全部无痕：data_trace 只剩 "tools executed" 汇总条目，modifications.total 低估。修复：统一各工具返回 'log' 键或扩展提取表。✅
- **M-16. LLM 生成工具 confidence 全链路无消费方：confidence<0.7 需人工审核契约未实现** — `subgraphs/data_normalization/agents/planning_agent.py:638`（U07）。CLAUDE.md Layer 3 契约要求低置信工具标记人工审核，但全仓 grep 无任何节点读该字段 → confidence=0.3 的工具照常全量修改真实数据。修复：执行前检查 confidence<0.7 跳过并写 modifications.errors，或限制仅 dry-run。✅
- **M-17. _execute_base 异常被吞：工具级失败不记入 modifications.errors** — `subgraphs/data_normalization/agents/normalization_agent.py:439`（U07）。except 仅 logger.error 后 return None，调用侧 `if r:` 才处理 → 工具异常静默跳过，errors 列表为空，报告显示 0 错误，数据以未清洗状态进入下一环节。修复：返回 None 时调用侧追加 {source_id, tool, error}。✅
- **M-18. fill_default 策略永远以 None 填充：无调用方传 fill_value，缺失值原样保留却记录 filled_value** — `quality_pipeline/tools/normalization/missing_value_handler.py:28`（U07）。planning_agent.py:337-341 选 fill_default 时只传 {'strategy': strategy}，全仓无任何 fill_value 实参 → `rec["field_value"]=None` 对已缺失记录无实质修复，却计 200 条 filled_value 虚报修复量。修复：提供领域默认填充值或改显式 mark+待补清单；至少统计口径不把 None 填充计为已修复。✅
- **M-19. 全量执行缺 dry-run 的记录数稳定性校验** — `subgraphs/data_normalization/agents/normalization_agent.py:475`（U07）。planning dry-run 用 3 条样本校验 len 一致才放行，但 `_execute_generated` 全量执行 `return fn(records)` 后无任何 count/结构校验 → `if len(records)>3: records.append(...)` 型代码 dry-run 不触发、全量触发，伪造记录注入 current_data 无 trace。修复：全量执行复现 dry-run 校验（len + 字段键集合），不满足丢弃结果记错误。✅
- **M-20. offset 因子只支持源单位侧：目标单位为 offset 单位时走单步换算，25°C 静默转成 25 K** — `quality_pipeline/tools/normalization/unit_converter.py:225`（U07）。`isinstance(tf, str)` 触发单步路径只应用源因子，目标侧 offset_273.15 被丢弃；research_domain 缺失回退材料段（°C 基单位）而 target_schema 天体物理 standard_unit='K' 时 25°C→25K（python 复现）。修复：两段式同时处理两侧 offset，或规则加载时校验基单位一致。✅
- **M-21. 语义去重 key 不含 field_unit，同值不同单位记录被静默删除** — `quality_pipeline/tools/normalization/duplicate_handler.py:27`（U13）。key=(source_id, entity_type, entity_name, field_name, str(field_value)) 无单位；单位转换失败（unconverted）时 '5' pc vs '5' kpc 判重复，后一条被删。C→B 全量规范化必执行该工具（planning_agent.py:163）。修复：key 纳入 canonical_unit 归一化后的 field_unit，不一致则跳过删除记 warning。✅
- **M-22. format(float(val),'g') 把数据库浮点值截断到 6 位有效数字** — `subgraphs/subgraph2/utils/database_utils.py:179`（U03）。实测 format(1234.56789,'g')=='1234.57'；与 M8 大整数修复的精度意图相悖；两来源 1234.5678 vs 1234.5734 截断后同值还会掩盖真实差异。修复：`str(val)` 或 `format(float(val), '.17g')`。✅
- **M-23. _is_retryable 不识别 HTTP 5xx，镜像 fallback 在文档化的高负载场景失效** — `subgraphs/subgraph2/utils/vizier_client.py:47`（U03）。文件头注释的"CDS/VizieR 间歇性高负载"场景最典型表现是 502/503/504 快速返回，但 astroquery 经 raise_for_status 抛 requests.HTTPError 不命中 timeout/connection/econn 规则 → 立即 raise，其余 3 镜像不尝试。修复：HTTPError 且 status>=500（或 429）判可重试。✅
- **M-24. Unpaywall API URL 中 DOI/email 未做百分号编码** — `subgraphs/subgraph2/nodes/unpaywall_query.py:29`（U03）。DOI 含括号/分号/加号原样发送；含 '?'/'&' 确定性破坏 query 结构；email 含 '+' 按 form 解码变空格。失败被 :61-66 静默吞掉返回 urls=[]。修复：`quote(doi, safe='')` + DOI 校验（10. 前缀/长度上限）。✅
- **M-25. max_size_mb 仅靠 Content-Length 头执行，缺失时流式写盘无界** — `subgraphs/subgraph2/nodes/pdf_download.py:56`（U03）。chunked/无头服务器直接 `for chunk in iter_content: f.write(chunk)` 无累计检查，超大体无界写盘至 60s 超时；except 分支也不删 .part 残留。修复：写循环内累计字节数超限中断删 .part；except 补 os.remove。✅
- **M-26. bbox 解析路径无 markdown 围栏剥离与 json_repair 回退** — `subgraphs/subgraph3/utils/bbox_vlm_client.py:170`（U04）。_coerce_to_dict 只裸 json.loads，```json 围栏 JSON 在 char 0 抛错返回 None（沙箱复现）→ bbox_2d=None → result_builder 丢弃整条记录——而 field_value 数据本身有效。对比 vlm_extractor.py:256 有 repair_json 回退，两路径不对称。修复：失败分支先 repair_json 再解析；解析失败返回 error 信息而非仅 None。✅
- **M-27. field_name 缺失时 str(None) 产出 "None" 脏字段记录流入下游** — `subgraphs/subgraph3/nodes/result_builder.py:195`（U04）。str(None).strip()=='None'，record_id 变 `{bibcode}_{entity}_None_{idx}`；同函数 :197 对 field_unit 有 None 防护而不一致；通过三道检查进入 paper_records → 质量管线把 "None" 当真字段统计。修复：与 field_value 处理对齐，field_name 空则丢弃该条。✅
- **M-28. 类型一致性检查 numeric+text 混合被判定为 consistent（核心检测失效）** — `quality_pipeline/tools/assessment/consistency.py:88`（U06）。`normalized = shapes - {"uncertainty","numeric"}` 把 numeric 减掉 → {'numeric','text'} → len=1 → consistent=True；只有 {'text','null'} 类才能检出。实测两族判定 False/True 与初审一致。修复：显式两族判定 `shapes <= {'numeric','uncertainty'} or shapes <= {'text','null'} or len(shapes)<=1`。✅
- **M-29. parse_numeric 接受 'NaN'/'inf' 字符串 → 组均值 NaN/Inf 污染方差分析** — `quality_pipeline/tools/assessment/statistical_conflict.py:340`（U06）。_parse_float 用 float()，nan/inf 均非 None 拦不住；nan 组 mean=nan → cohens_d=nan → CAUSE_UNKNOWN 且报告写 nan；'inf' 则恒满足 d>=2.0 生成假 statistical_outlier。上游 supplementary_query 仅精确过滤小写 'nan'，'NaN' 变体与 'inf' 可穿过。修复：`math.isfinite` 判空。✅
- **M-30. 统计异常检测被组级多数原因门控，单对 d>2.0 异常在 ≥3 源时被抑制** — `quality_pipeline/tools/assessment/statistical_conflict.py:570`（U06）。`if primary_cause == ANOMALY_STATISTICAL` 门控由组内 pairwise 多数决定；构造 S1/S2 d=7.07 真实离群 + 两组小差异 → primary=measurement_uncertainty → 0 条 anomaly（stdlib 复现）。设计文档声明逐 pair 判定。修复：去掉组级门控，直接遍历 pairwise_causes 中 ANOMALY_STATISTICAL 的 pair。✅
- **M-31. domain_tightness 乘子方向与代码/配置注释相反** — `quality_pipeline/tools/assessment/adaptive_threshold.py:86`（U06）。yaml 注释"探索性科学, 阈值更宽松"，但 astrophysics='exploratory'→1.30（更严格）、materials='precise'→0.80（更宽松），n<10 时天体物理阈值 0.99 vs 材料 0.61，相差 37.8 个百分点，探索性天体数据被要求更高覆盖度。修复：乘子方向对调或改 threshold = base × sample_factor × (1/domain_factor)。✅
- **M-32. 天文不对称误差格式 '12.3+1.4-2.1' 与 sexagesimal 解析失败 → 合法数值被标记为垃圾串** — `quality_pipeline/tools/assessment/format_checker.py:133`（U06）。parse_numeric 对 '+1.4-2.1' 系/空格系/':' 系全部 None（实测），format_checker 对数值型字段中这类串产 format_issue → 路由 Normalization；statistical_conflict 中这些记录不参与方差分析。修复：新增 AsymmetricErrorParser + sexagesimal 解析器，或标记 text 豁免。✅
- **M-33. build_quality_context 键名拼写错误 conflict_tatus/conflict_oute，recommendation 的 conflict 检索词分支永远不触发** — `quality_pipeline/tools/insight/context_builder.py:313`（U10）。写 conflict_tatus/conflict_oute，而 recommendation_agent.py:165 读 conflict_status → 恒 None → kws += ["conflict"] 死代码，存在冲突时 KB 检索不带冲突关键词。OPTIMIZATION_PLAN.md:160-162 已计划未实施。修复：改键名 conflict_status/conflict_outcome 并 grep 确认无其他消费方。✅
- **M-34. field_pairs 为空（各字段记录数<MIN_RECORDS_FOR_RELATION）时仍调 LLM，产出关系被标记 data_evidence="sufficient_data"** — `subgraphs/data_insights/agents/relationship_agent.py:111`（U10）。守卫只查 distinct_fields≥2（:60），但 _build_field_pairs 会因 record_count<2 排除全部字段 → field_pairs=[] 时 LLM 仍被调，setdefault("data_evidence","sufficient_data") 与事实相反。修复：`if not field_pairs:` 走 kb preset + insufficient_data。✅

**配置/漂移类**

- **M-35. 语义类型 metallicity/density 的 units 与转换组错配，'Sun'/'pc**-2' 等永远无法转换** — `quality_pipeline/configs/quality_rules.yaml:368`（U12）。metallicity.units 声明 ["dex","","Sun","log(Sun)"] 但转换组只有 dex；density.units 含 pc**-2/mas**-2 但组只有 g/cm³ 系；无任何语义类型指向 abundance/surface_density 组。unit_converter 以 (inferred_cat, unit) 查表必然 miss，且因 inferred_cat 非空跳过全组 fallback → 记录以非标准单位静默导出。修复：把 'Sun'/'log(Sun)' 并入 metallicity 组（或改 unit_category 为 abundance）、为 surface_density 注册语义类型或从 density.units 移除。✅
- **M-36. 13+ 个配置段无任何代码消费（missing_value/duplicate/outlier_detection/nonlinear_penalties/journal_tiers 等）** — `quality_pipeline/configs/quality_rules.yaml:6`（U12）。全仓 grep 确认这些段键名仅出现在注释/字符串；quality_scoring_agent.py:195 硬编码 `overall_score *= 0.7` 而 yaml nonlinear_penalties.multiplier=0.7 无读者——**改 yaml 调参零效果且无告警**，与 A11 "单点定义"承诺相悖。修复：删除死段或真正下沉 loader；至少注明 quality_scoring.weights 仅作兜底。✅
- **M-37. catalog_units.json 中 5 列不在别名生成源内，逃逸 database_catalog_properties 兜底** — `quality_pipeline/scripts/gen_catalog_schema.py:138`（U12）。3c 的 S159MHz/e_S159MHz、ucac 的 f.mag、fermi 的 AV(HK)/AV(JH) 不在 vizier_catalogs_schema.json（1072 列）与 query_results_progress_final.json 的 used 集中 → 永远进不了 target_schema aliases → 运行时 map_to_target_schema 返回 None，记录保留原始列名与单位绕过兜底。修复：列源并入 catalog_units.json 键集并重跑 --apply。✅

### 4.4 Low（25 条）

- **L-01. `_timed`/`_stage_times` 定义后从未调用；entity_type_hint/user_confirmed/conversation_history 通道只写不读** — `astroquery_ai/adapters.py:75`（U01）。死代码 + 3 个死通道白占 checkpoint 序列化体积。修复：删除或并入 final_output.query_metadata。
- **L-02. state.target_schema 通道只写不读，generate_target_schema 双实现且已漂移** — `astroquery_ai/property_standardization.py:604`（U01）。全仓消费者均读 context_state.target_schema（quality_adapter 从 property_spec 重新生成）；P1 实现缺 "criticality": "important"（quality_adapter 有），未来改接会静默丢失字段关键性。修复：二选一（删除 P1 版本或补齐 criticality 复用）。
- **L-03. HITL 循环 input() 的 EOFError 未捕获，stdin 关闭时整条流水线 traceback 崩溃** — `astroquery_ai/main_graph.py:196`（U01）。`astroquery-ai "..." < /dev/null` 触发 ask_entity interrupt → EOFError 直达顶层（cli.py:129 只捕 KeyboardInterrupt）→ traceback 退出码 1，违反"永远出 JSON"承诺。修复：捕获 EOFError 视为取消返回当前 state 或转 GraphInterrupt；cli 补 EOFError 分支。
- **L-04. 寒暄规则 len<15 门限把含问候语的真实天文查询确定性误判为 greeting** — `subgraphs/subgraph1/utils/llm_utils.py:73`（U02）。实测 "你好 M31 的距离是多少"（13 字符）命中 → 实体解析被跳过，用户被迫重输；greeting→initial_parse 回环反复误判无自动边界。修复：门限改为"问候后无其余内容"判定或交 LLM 二次确认。
- **L-05. simbad_resolver 节点死代码仍被 nodes/__init__.py 导出，且 state.py 注释断言其仍为图入口（与 graph.py 矛盾）** — `subgraphs/subgraph2/state.py:40`（U03）。graph.py 已移除该节点（B2 收敛），但 `from .simbad_resolver import simbad_resolver` 连带 import astroquery.simbad —— 依赖缺失时 nodes 包导入即崩；注释误导维护者重新接线会复现 B2 已修复的双查询。修复：删除导出与 __all__ 条目，修正注释。
- **L-06. A&A 字母文章页码的 J/ 表号推导错误** — `subgraphs/subgraph2/nodes/supplementary_query.py:73`（U03）。'2018A&A...616A...1G' 正则分组 ('2018','A&A','616A','1G') → 卷尾字母被剥 → 推导 J/A+A/616/1（不存在），正常靠 find_catalogs 兜底，网络失败则 A&A 补充表静默缺失。修复：A&A 特例保留文章字母拼 J/A+A/616/A1。
- **L-07. calculate_retrieval_priority 硬编码 current_year=2026，跨年后时间衰减因子失真** — `subgraphs/subgraph2/utils/paper_utils.py:69`（U03）。2027 年论文 age=-1 → time_factor=1.0526 反超上限并 min 截断并列满分。修复：datetime.now().year + age<0 钳制 0。
- **L-08. 死配置：pdf.dpi=100 与 vlm.timeout=600 从未被消费，bbox max_tokens 硬编码与配置重复** — `subgraphs/subgraph3/config/settings.py:50`（U04）。pdf_to_images 恒用默认 150 DPI、MultiModalConversation 恒用 SDK 默认超时、bbox_vlm_client.py:128 硬编码 500 —— 运维按配置调整静默无效。修复：显式透传或删除死配置字段。
- **L-09. decision_matrix 的 repair_cost 用 sr['issue_count']（含 info 级条目）而真实路由用 len(issues_found)，矩阵报告与路由可矛盾** — `subgraphs/data_assessment/agents/decision_reasoning_agent.py:256`（U05）。5 个正常方差组 → issues_found=0 路由 Export，但矩阵因 issue_count=5 报 medium/Normalization。目前无下游消费，影响限于报告。修复：两处同源（存 issues_found 复用）。
- **L-10. records_with_units 将空串单位计为'有单位'，与 completeness 的 V4 语义（'空串=缺失'）矛盾** — `quality_pipeline/tools/assessment/profiling.py:103`（U06）。result_builder 对无单位字段统一产出空串 → profiling 报 100% 单位覆盖而 completeness 报 N 条缺失，同数据两报告对撞（records_with_units 无下游消费方，影响限于报告）。修复：统一 `if rec.get("field_unit"):` 判定。
- **L-11. per-entity bbox 缺失计数 e_mb 恒为 0（切片与 not 使判断恒 False）** — `quality_pipeline/tools/assessment/extraction_quality.py:184`（U06）。`not (...)[0:4]` 无论 bbox 缺失/非 4 元/合法恒 False → per-entity 分数从不因缺 bbox 扣分，与主循环 :86 正确写法矛盾。修复：改 isinstance+len==4 判定。
- **L-12. 科学记数法+括号不确定度（如 "1.2e-5(3)"）小数位计算错误，不确定度偏差 100 倍** — `quality_pipeline/tools/_parse_utils.py:315`（U11）。base_str.split('.')[1]='2e-5' 长度 4 → uncertainty=3e-4（应为 3e-6）；"1200(5)e3" 因正则要求括号结尾完全不匹配 → 数值整体丢失。正常格式 '776.2(5)' 仍正确。修复：mantissa 计算小数位再叠指数修正；补两单测锚点。
- **L-13. 重试上限漂移：MAX_NORM_RETRIES=1 使子图条件边 retry_count<2 与注释'最多 2 次'不可达** — `subgraphs/data_normalization/agents/validation_agent.py:75`（U07）。三处常量/图边/注释不一致，至少两处是死代码或错误注释。修复：统一为 1 或 2。
- **L-14. per-entity 修改计数 O(L×R) 二次复杂度** — `subgraphs/data_normalization/agents/normalization_agent.py:266`（U07）。每条 log 线性扫描全部 srecs：20000 记录 × 8000 日志 = 1.6 亿次比较，每个并行 source 重复。修复：预建 {record_id: (entity_type, entity_name)} 索引。
- **L-15. critical_expected 计算后从未使用（死代码）** — `subgraphs/data_normalization/agents/validation_agent.py:23`（U07）。V3.0 重构残留，误导维护者以为 schema 完整性检查仍在生效。修复：删除或纳入 remaining 输出。
- **L-16. 混合 int/str 的 years 集合使 sorted() 抛 TypeError，整批 LLM 分类被静默禁用** — `subgraphs/data_conflict/agents/conflict_classification_agent.py:150`（U08）。sorted({2015,"2016"}) 抛 TypeError（stdlib 复现）→ 外层整段 try 吞掉 → 全部项回退 unknown/0.2 → 触发两次无效重试。修复：years 统一 str() 后 sorted；细化 try 粒度。
- **L-17. metadata 读 resolution_report.metadata.total_conflicts，writer 从不写该键 → 恒 0** — `quality_pipeline/tools/export/metadata_generator.py:124`（U09）。resolution_report_agent 的 metadata 键清单无 total_conflicts，全仓无 writer；与 M3 已补写的 auto_resolved 形成对照。修复：writer 补写或 reader 改用 total_anomalies 口径。
- **L-18. llm_call_count 在 JSON 解析失败时未递增，LLM 实际已调用但计数漏记** — `subgraphs/data_insights/agents/recommendation_agent.py:89`（U10；relationship :98 / field_insight :140 同模式）。json.loads 抛异常跳 except 回退时递增在解析之后未执行 → quality_summary.total_llm_calls 低估。修复：递增移到 invoke 成功后、解析前。
- **L-19. Pydantic 强校验失败时回退写原始未校验 dict，与注释意图相反** — `subgraphs/data_insights/agents/synthesis_agent.py:109`（U10）。注释称"防止非法结构写入正式结果"，但 except 保留原始 dict 后仍 json.dump 落盘 insights_{ts}.json；LLM 返回 dict 型 typical_range（models 声明 str|None）必触发 ValidationError → 非法结构落盘。修复：校验失败时字段级净化（非法→None/[]）后再落盘。
- **L-20. check_retry 定义后全仓库无调用（被 _make_stage_gate 取代后的残留）** — `quality_pipeline/routers.py:83`（U11）。grep 仅命中定义处；与 gate 逻辑重复，将来调整重试口径两处易不同步。修复：删除或改共享实现。
- **L-21. out_of_range 比率用字段数除以记录数，量纲不一致使越界过半判定失真** — `subgraphs/data_assessment/agents/decision_reasoning_agent.py:187`（U05）。out_of_range_count 是 (entity,field) 组合 key 数，分母是记录总数：800/1000 条单字段全部越界只计 1 → 0.1% 不触发；3 字段各 1 条越界共 4 条记录 → 75% 触发 HumanReview，语义颠倒。修复：改记录级计数或字段占比口径。
- **L-22. 三个脚本硬编码作者机器绝对路径，换机器必然 FileNotFoundError** — `quality_pipeline/scripts/append_methodology_entries.py:8`（U12；backfill_hq.py:10 / extend_galaxy_catalogs.py:6 同）。对照 append_knowledge.py:12 用 `Path(__file__)` 相对定位。修复：统一基于 __file__。
- **L-23. 幂等去重仅靠 assert，python -O 运行会重复追加条目** — `quality_pipeline/scripts/append_methodology_entries.py:265`（U12；extend_galaxy_catalogs.py:191 同）。-O 下 assert 被剥离 → 重复执行产生重复 id；对照 append_knowledge.py:550 真实列表过滤。修复：改真实过滤。
- **L-24. Assessment 并行 LLM 完整性分析未递增 llm_call_count** — `subgraphs/data_assessment/agents/quality_assessment_agent.py:292`（U13）。_llm_task 实际调用 analyze_missing_fields（真实 LLM 调用）但返回体仅 tool_call_count → export_generation_agent.py:103 的 total_llm_calls 恒低估 K 次。修复：as_completed 循环按成功 sid 数累加写入 llm_call_count。
- **L-25. per_conflict 键恒空导致 cross_id 项 source_a 为空（提取侧证据）** — `subgraphs/data_human_review/human_review_agent.py:265-281`（U08）。V3.0 报告无 per_conflict 键 → cross_id 项 source_a={}；cross_id 异常本身含 source_ids 但 anomaly_flags/human_review_items 构造时丢弃（`resolution_report_agent.py:111-117/217-226`）。与 H-04 同根因，本条保留提取侧修复点：anomaly_flags/human_review_items 保留 field_name 与 source_ids。修复：随 H-04 一并落地。

## 5. 待确认项

**无 uncertain 项** —— 全部 90 条候选均在静态约束下证毕或证伪。

### 5.1 被推翻的条目（5 条，仅列摘要与推翻理由）

| 单元 | 初审主张 | 推翻理由 |
|------|---------|---------|
| U04[5] | `pdf_utils.py:49` 异常路径不 close fitz Document → 句柄滞留 | CPython 引用计数使局部 doc 在异常传播出帧时立即析构，PyMuPDF 自带 `__del__` 调 close()；traceback 引用链在 except 套件结束时释放。线性累积前提不成立 |
| U07[9] | `_find_unresolved` 读 missing_expected_fields/conflicts 两键"任何来源不会产出" | 基线契约已过时：`completeness.py:196` 确实产出 missing_expected_fields、`quality_assessment_agent.py:99` 产出 conflicts —— 两维度均有真实数据源 |
| U10[4] | typical_ranges 光度上限 1e53 erg/s 物理不可能，star 注释与存储差 1000 倍 | 误数字面量位数：quasar 上限实测 1e48 erg/s（物理合理区间），star 存储值 4e37 与注释一致。场景反转（1e50 会正常触发越界判定） |
| U11[2] | loop_controller from_conflict 分支丢弃 gate 写入的 HumanReview 决策 | 前置条件不可达：normalization 子图终态必经 report_agent 无条件写 Success，gate 的 Retry/Failed/HumanReview 分支对该子图永不可触发 |
| U11[5] | compile_quality_graph 无 checkpointer，外部调用触发 HR 会抛异常崩溃 | 安装版 langgraph 1.2.7 的 interrupt() 无 checkpointer 检查，实际行为是返回含 `__interrupt__` 的结果而非崩溃（仍建议清理该入口，理由改为"中断结果易被误当正常输出"） |

## 6. 局限与未覆盖

- **未运行任何 pytest/集成测试**（只读约束）；网络 client 行为（ADS/VizieR/CDS/Unpaywall 真实响应、5xx 异常形态、'Redirection error' 页面判据）仅静态推断，需网络环境实测确认。
- **未调用真实 LLM**：所有 LLM 输出类 finding 均以"代码对 LLM 输出的处理缺陷"判定（输入前提 LLM 可达性经代码路径证明），非对 LLM 行为的断言。
- **LangGraph 运行时细节**：interrupt() 双中断恢复序列、checkpointer 跨层恢复、嵌套 reducer 运行期行为依赖 langgraph 1.2.7 源码与既有 60 测试全绿基线，未实跑验证。
- **tests/ 与 conftest.py 未审**（测试质量本身不在本次范围）；`rag_properties/` JSON 仅做键名漂移核对（T11），未逐文件审数据内容；知识库 yaml 属数据非代码。
- **U13 各 T 项结论**：T1 仅 figure_evidence 一例（嵌套键经 _merge_dict 通道保留，已对照 _algo.py 源码）；T2 无问题；T3 quality.sources[sid] 全链一致（conflict_risk 无 per-source cohens_d/ci_95 但无任何消费者读取，不构成破坏）；T4 路由权威单一（无 gate 越权）；T5 除 M-02/M-03 外生命周期对称；T6 entity_index 无生产消费者（死数据非活 bug）；T7 target_schema 由 quality_adapter 注入两端一致（standalone 恒空但 standard_units 有 V4 回填）；T8 无问题；T9 全链 .get 默认值无缺键崩溃；T10 两端 source_id 均为字符串一致；T11 键名一致；T12 retry_on_failure 零调用（死代码未上报）、logger 无敏感信息落盘。

## 7. 后续建议

### 7.1 修复路线图

**即时（critical）**：C-01 人工裁决作用域护栏（human_review_agent + normalization_agent 双端防御）。

**短期（high，按影响面排序）**：
1. H-03 normalize_unit 数值换算（连带 H-04 一并修复 human_review→normalization 动作链）
2. H-12 沙箱硬超时（线程 + timeout，超时回退 Base Tools）
3. H-11/H-15/H-16 三处 execution_status 透传回归（scoring/insights 前序节点/M9 reader），恢复"失败可见"
4. H-14 confidence float 强转 + 全 LLM 数值字段防御（同类风险：classification/insights/relationship 的数值字段统一 try/float）
5. H-13 flag_for_review 写入 human_review_items（critical 异常必须人工介入）
6. H-02 DB record_id 格式分支（修复后补 decision 路由回归测试：纯 DB 源可达 Export）
7. H-09 bbox 类型归一化（vlm_extractor 出口 + bbox 循环逐条 try）
8. H-05/H-17 LLM 输出形状校验（P1 与 field_insight 对齐 M6/H5 的既有防御模式）
9. H-06/H-07 subgraph1 重试与 JSON 多层解析
10. H-08 缓存键并入 target_entity + 失败兜底不缓存
11. H-01 figure_evidence 通道声明
12. H-10 image_cache.cleanup() 接线

**中期（medium）**：M-02/M-03 状态边界（retry_by_node 置 None 重置 + dispatch Failed 信号）；M-22/M-28/M-29/M-30/M-31/M-32/M-20/M-32 数值/统计口径修正（各需单测锚点）；M-10 CSV 注入防护；M-11 写盘降级；M-35/M-36/M-37 配置清理；M-15/M-16/M-17/M-18 归一化统计/契约对齐。

**低优先级（low）**：死代码清理（L-01/L-02/L-05/L-15/L-20）、脚本可移植性（L-22/L-23）、统计口径（L-09/L-10/L-18/L-21/L-24）、L-12 解析器补丁。

### 7.2 回归测试建议（新增锚点）

| 修复 | 建议测试 |
|------|---------|
| C-01 | 构造 QHR 审核项 + adopt 决策 → 断言不产生全空作用域 human_replace / _apply_conflict_ction 拒绝执行 |
| H-02 | DB 记录集 8 项检查全过 → 断言路由 Export（当前必 Fail，先写红测） |
| H-03 | unit_error → C→B → 断言导出值=换算后数值（au→pc 锚点） |
| H-11 | profiling 工具异常 → 断言 gate 读到非 Success（重入或 HumanReview） |
| H-14 | LLM 返回字符串 confidence → 断言不崩溃且回退 0.5 |
| H-16 | Export Failed → Insights 执行后 → 断言最终 execution_status="Failed" |
| M-02 | E→A 重置后 → 断言 gate 重试预算归零 |
| M-30 | 3 源 + 少数派 d>2.0 → 断言 anomaly 生成（当前必 Fail） |
| M-20 | °C→K 跨域配置 → 断言 25→298.15 |
| L-12 | "1.2e-5(3)"/"1200(5)e3" 解析锚点 |

### 7.3 下一轮审计建议

- 对网络路径（U03/U04）做一次带真实 API 的专项验证（5xx/429/超时/畸形响应）；
- 对 HITL 全流程（A→E→B、C→E→B、E→A）做 3 条端到端 HITL 集成测试（含 interrupt/resume 恢复）；
- 修复落地后复跑本 13 单元两阶段审查，验证无回归并收敛 uncertain（当前为 0）。

## 附录

### A. 单元审查覆盖表

| 单元 | 已核查维度 |
|------|-----------|
| U01 | G1-G8, L2/L6/L8, T1/T7 |
| U02 | L1-L8, G1/G2/G6 |
| U03 | L1-L8, D4/D6, 网络专项 |
| U04 | L1-L8, D4/D5, 安全 |
| U05 | L1-L8, G1-G7, T3 写入侧 |
| U06 | D1-D6 |
| U07 | L1-L8, D1-D6, 沙箱专项, G 装配 |
| U08 | L1-L8, G1/G5/HITL 专项, T4 冲突报告契约 |
| U09 | L1-L8, D1-D6, G1-G7 |
| U10 | L1-L8, D5, KB 一致性, G1-G7 |
| U11 | G1-G8, T1/T2/T4/T5, reducer 专项 |
| U12 | C1-C5, D4/D6 |
| U13 | T1-T12 全量 |

### B. T1-T12 追踪结论

| 追踪项 | 结论 | 备注 |
|--------|------|------|
| T1 通道声明 vs 返回键 | ⚠️ 1 处不一致 | figure_evidence 顶层键未声明被丢弃（H-01）；嵌套键经 _merge_dict 保留 |
| T2 _merge_dict 语义 | ⚠️ 1 处 | dispatch retry_by_node={} 重置被递归合并吞掉（M-02） |
| T3 quality.sources[sid] 全链 | ✅ 一致 | 生产/消费字段逐字核对；conflict_risk 无 per-source cohens_d 但无消费者 |
| T4 report_state 契约/路由权威 | ✅ 一致 | 仅业务节点写 route_decision，无 gate 越权 |
| T5 workflow_state 生命周期 | ⚠️ 2 处 | dispatch Failed 信号丢失（M-03）、retry_by_node 重置失效（M-02）；其余对称 |
| T6 current_data 记录形状 | ✅ 一致 | entity_index 无生产消费者（死数据非活 bug） |
| T7 property_spec→target_schema | ✅ 一致 | quality_adapter 注入两端字段映射一致；standalone 恒空但 standard_units V4 回填 |
| T8 supplementary_records | ✅ 一致 | source_kind=supplement 专门分支处理 |
| T9 输出组装 | ✅ 一致 | 全链 .get 默认值，无缺键崩溃 |
| T10 entity_type_overrides | ✅ 一致 | 两端 source_id 均为字符串，码→规范名映射存在 |
| T11 rag_properties 键名 | ✅ 一致 | 两消费端键名逐字对齐 |
| T12 横切（retry/llm/logger） | ✅ 一致 | retry_on_failure 死代码未上报；logger 无敏感信息 |

### C. 同根因扩散索引

| 根因 | 实例位置 |
|------|---------|
| 人工裁决空作用域覆盖 | human_review_agent.py:228/231（C-01，双实例合并） |
| figure_evidence 通道缺失 | adapters.py:409 + aggregator.py:66 + state.py（H-01） |
| DB record_id 正则误判 | format_checker.py:88（H-02，U05/U06 双单元） |
| normalize_unit 重贴单位 | normalization_agent.py:122-131（H-03，U07/U08/U13 三单元证据） |
| cross_id 裁决丢弃 | human_review_agent.py:121/265-281 + source_router_agent.py:63-66（H-04 + L-25） |
| execution_status 覆写 Success | quality_scoring_agent.py:270 / field_insight_agent.py:170 / relationship_agent.py:127 / recommendation_agent.py:119（H-11/H-16） |
| normalization_tatus typo | report_agent.py:26 vs metadata_generator.py:113（H-15） |
| llm_call_count 漏记 | recommendation_agent.py:89 / relationship_agent.py:98 / field_insight_agent.py:140 / quality_assessment_agent.py:292（L-18/L-24） |
| 脚本硬编码路径 | append_methodology_entries.py:8 / backfill_hq.py:10 / extend_galaxy_catalogs.py:6（L-22） |
| assert 幂等去重 | append_methodology_entries.py:265 / extend_galaxy_catalogs.py:191（L-23） |
