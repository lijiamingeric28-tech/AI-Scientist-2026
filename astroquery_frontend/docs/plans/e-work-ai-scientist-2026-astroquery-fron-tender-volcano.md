# 分批填写 docs/muban.md（2026 揭榜挂帅·阿里云榜题·方向1A）计划

## Context（背景与目标）

`docs/muban.md` 是 2026 年度中国青年科技创新"揭榜挂帅"擂台赛·阿里云榜题·**方向 1A 科学数据查找解析与整合（题目 XH-202619）**的官方技术报告模板，共 P1–P20 二十个章节。本计划目标：**分批分次**把本项目（AstroQuery AI 天文数据智能检索 Web 应用）的真实实现填入该模板，形成可提交的技术报告正文。

**已确认的用户决策：**
1. **交付形式**：本次只填 `docs/muban.md`（Markdown），PPT/PDF 之后另做。
2. **Qwen 合规**：质量管线当前用 `deepseek-v4-flash`，比赛要求基座必须 Qwen 系列并经阿里云百炼调用 → **先切全 Qwen 再进入填充**（阶段 0a）。
3. **P18 对照消融**：**先不填**（留空并标注"待补消融实验"），不编造对照数据。
4. 真实模式已跑过；提交材料（报名名称/团队/视频链接等）部分已有。
5. **实测与报告案例合一**：Qwen 切换后由**用户本人前端实测**；实测样例与报告代表案例用**同一个避开距离的查询——"M13 的积分V星等与金属丰度"**，一次真实运行同时产出实测验证、报告素材（P13-P17）与重录 cassette。旧 "M13 的距离、年龄和金属丰度" 快照**降为次要参考**（距离含 pc/kpc/距离模数mag/视差mas 四种冲突表征，是历史易错点）。
6. **执行门禁**：阶段 0b 用户实测**通过后**才开始批次填充；P18 按决策留空。

**探索结论（三路 Explore 完成）**：项目能力覆盖模板全部要求——NL 查询→HITL 澄清→P1 性质标准化（SIMBAD+RAG 库+LLM）→27 个 VizieR 星表 + ADS 论文 + Unpaywall + CDS 补充表并行检索→PDF 多模态提取（Qwen-VLM/bbox/图证）→质量管线（评估/规范化/冲突/导出/洞察）→结构化导出（JSON/CSV 长宽表/溯源/洞察），前端 7 卡实时可视化。真实运行产物、测试记录、审计文档均可作报告证据。

---

## 素材基线（Evidence baseline）——报告可引用的真实数据

填写全程以"**代码为准 + 真实运行产物为准 + 最新日期文档**"三条原则取数，**不编造、不照抄旧文档中已被推翻的数字**。

> ⚠️ **报告代表案例已按用户决策更换**：P13-P17 等案例章节以**阶段 0 新真实运行产物（`output/m13_real_run/`，查询 "M13 的积分V星等与金属丰度"）**为准。下表"M13 旧距离快照"仅作数量级与性质参考，**不得作为案例正文字据**。

| 素材 | 位置 | 关键数字 |
|---|---|---|
| 新代表案例真实运行（阶段 0 产出，权威） | `output/m13_real_run/`（grounded_data / 长宽CSV / quality_summary / traceability / insights / 截图） | 查询 **"M13 的积分V星等与金属丰度"**；预期 target_entity=M13；字段 `integrated_v_mag`（mag，文献 Vt≈**5.83**）与 `metallicity`（dex，≈**-1.39~-1.57**）；来源数/记录数/质量分**以实际运行值为准** |
| M13 旧距离快照（次要参考，非案例） | `frontend/UsersYOGA.qoderworkcnworkspacemrr92yto4di477rlstate_snap.json`（`/state/final_output`） | target_entity=M13；SIMBAD GlC（M 13 / NGC 6205）；22 来源 / 61 条记录 / 48 图证 / 源质量分 0.74–0.94；9 字段洞察 / 6 跨字段关系——仅数量级参考 |
| 大角星真实运行（质量管线实绩） | `output/6459b52c/quality_summary_*.json` + manifest | overall_score **0.8954 / fair**，calibrated_confidence 0.8484；**24 次 LLM 调用 / 121 次工具调用 / 257.5s / B⇄C 循环 2 轮**；评估问题 54 / 规范化修改 20 / 冲突解决 4 / 剩余 0；**49 行**，18 来源，7 个导出文件；规范化 1 base/0 adapted/19 LLM 生成 |
| M13 回放 E2E 验收 | `docs/FIX_LOG.md` §最终验收 P15（行 ~326） | **12/12 PASS**，SSE 960 事件严格递增，figures 3/3 可达，8 个导出文件 |
| 真实冒烟 M31 | `docs/OPTIMIZATION_STATUS.md` §零-2 | sources=**27**，records=**49**（真实模式 ~20min） |
| 离线测试 | `pytest tests/ -m "not network"` | **270–271 passed**（mock，零费用） |
| 审计修复证据 | `docs/AUDIT_REPORT.md`、`docs/WEB_AUDIT_REPORT.md` | 后端 80/80、Web 60/60 问题全修复（含 1+3 条 critical） |
| 运行历史 | `web/data/tasks.db`（只读查询） | 19 任务：9 完成 / 9 取消 / 1 错误；M13、大角星、毕宿五三组真实查询 |

**数据资产（P4/P10/P11 引用）**：27 个 VizieR 星表（`subgraphs/subgraph2/catalog/catalog_config.json` 全表）；RAG 性质库 100 文件/3,293 性质/74 个 OTYPE→4 父类映射（`rag_properties/`）；28 字段 target_schema / 1,178 别名 / 34 单位组 / 257 换算规则（`quality_pipeline/tools/normalization/schema_mapping.yaml`）；洞察知识库 294 条 / 7 文件（`quality_pipeline/data/insight_knowledge/astrophysics/`）。

**Qwen 分工现状**（阶段 0 之后将变为全 Qwen）：qwen3.7-flash（澄清/ADS 检索串/列映射/bbox/图检/卡7总结）、qwen3.7-plus（PDF VLM 提取）、qwen3.8-max（P1 性质选择）、质量管线 deepseek-v4-flash（**待切换**）。全部经 DashScope compatible-mode HTTP 调用（OpenAI 兼容协议）。

---

## 阶段 0｜Qwen 全合规迁移 + 用户实测门禁 + 证据固化（先做；0a/0c/0d 由我执行，0b 由用户执行）

**目标**：基座全 Qwen 合规成立，并经**用户本人前端实测**验证；同时产出报告代表案例（新查询）的证据与 cassette。

**0a. 切全 Qwen + 同步测试（我改代码）**
- 改 `quality_pipeline/utils/llm.py` 的 `get_llm`（或统一 `Settings`）：质量管线 LLM 从 `base_url=https://api.deepseek.com` + `OPENAI_MODEL=deepseek-v4-flash` 切到 **DashScope 百炼 compatible-mode base_url + `qwen3.7-flash`**（与 `astroquery_ai/config.py` 现有 DashScope 配置一致）。
- 同步 `scripts/add_units.py` 与 `web/main.py` 启动自检的 model 引用；跑 `tests/test_web_offline.py` 确认绿。
- **同步更新 `tests/test_e2e_recorded.py`**：用例查询改为 **"M13 的积分V星等与金属丰度"**，澄清答案 `["积分V星等、金属丰度", "y"]`，`assert_m13_contract` 期望性质改为 积分V星等/金属丰度。

**0b. 用户前端实测（门禁，用户执行）**
- 真实模式启动 `python -m uvicorn web.main:app --port 8000`（无 LLM_CASSETTE），前端 5173 提交 **"M13 的积分V星等与金属丰度"**。
- 用户验证：7 卡完整、右侧栏数据合理、summary 正常、数值与文献一致（integrated_v_mag≈5.83 mag，metallicity≈-1.39~-1.57 dex）、质量管线调用日志为 qwen3.7-flash/DashScope。
- **此为硬门禁：用户确认通过后才进入 0c。**

**0c. 证据固化（我执行）**：把本次真实运行的 `grounded_data_*.json` / 长宽 CSV / quality_summary / traceability / insights / 截图复制到 `output/m13_real_run/`，作为 P13-P17 与 P3/P4 的权威素材。

**0d. 重录 cassette（我执行）**：`python -m pytest tests/test_e2e_recorded.py -m network`（record_mode=once，按新查询覆盖 `tests/cassettes/m13_query.yaml`）；回放模式再跑一次确认新契约通过；跑 `test_cassette_contains_no_secrets` 确认无密钥。

**验收**：0b 用户确认通过 + 0c 产物齐全 + 0d 回放绿。`output/m13_real_run/` 即报告案例素材。

---

## 批次 1｜作品总览：P1 + P2 + P3（1 次工作会）

| 章节 | 要填的字段 | 素材来源 | 需用户提供 |
|---|---|---|---|
| **P1-1 团队信息** | 成员/盖章报名表截图 | — | **报名表第一、二页截图（盖章版）** |
| **P1-2 作品基本信息** | 报名名称/最终名称/简介(≤300字)/Qwen说明(≤300字)/视频链接 | 简介与 Qwen 说明由我们起草（引用阶段 0 的分工） | **挑战杯报名时作品名称、最终作品名称、宣传视频链接（夸克盘）** |
| **P2-1 核心主张** | 数据需求/核心方法/结果1(新 M13 V星等+金属丰度案例)/结果2(大角星 0.8954)/局限 | 阶段 0 产物 `output/m13_real_run/` + `output/6459b52c/`；局限引 CLAUDE.md §5（VCR 错位、并发1、前端快照渲染未完整） | — |
| **P2-2 解决的问题** | 一段话：现有天文数据获取靠人手工查星表+读论文的痛点 | CODE_ANALYSIS §1 + 真实痛点 | — |
| **P2-3 完成的工作** | 一段话：需求理解/来源发现/多类型解析/对齐/多源整合/来源保留/质量反馈 | 项目全貌（三路探索结论） | — |
| **P2-4 完整闭环** | 成果/范围/与通用检索差异 | PropertySpec 中央契约 + 质量管线 B⇄C 循环 | — |
| **P3-1 数据需求表** | 5 行问题（用什么/示例：M13 积分V星等+金属丰度） | 阶段 0 产物 `output/m13_real_run/` | — |
| **P3-2 能/不能范围** | 4 问 | 子图2/3 + 质量管线能力边界 | — |

**验收**：P1 表中用户未提供的项以 `【待补：…】` 标注（不编造）；其余全字段可溯源到真实代码/产物。

---

## 批次 2｜来源与架构：P4 + P6（1 次工作会）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P4-1 来源清单表** | ≥3 行来源：①VizieR 27 星表（按阶段 0 案例命中的 MWSC 等 + 全量 27）②ADS 论文（命中数以阶段 0 产物为准）③SIMBAD ④Unpaywall/arXiv PDF ⑤CDS 补充表（guess_j_tables）——每行填"实际获取内容/理由/覆盖与局限/来源保留" | `catalog_config.json`、`catalog_metadata.json`、阶段 0 产物 sources、`ads_search.py`、`supplementary_query.py` |
| **P4-2 来源使用说明** | 4 问：实际用了哪些/覆盖重复冲突/如何判断可用/不可核实数据如何处理 | 多源方差分析（statistical_conflict Cohen's d）、assessment `source_reliability`、`decision_reasoning_agent` 路由到 HumanReview |
| **P6-1 架构模块表** | 5 行模块（需求理解/发现筛选/内容解析/对齐整合/质量修正）逐行填 输入/核心处理/输出/与下一模块关系 | `CODE_ANALYSIS.md` §1–2 + `main_graph.py` 7 节点拓扑 |
| **P6-2 数据闭环设计** | 一段话：为什么不是一次性检索；质量如何回流（Normalization↔Conflict 循环≤3、gate 失败→HumanReview、`_merge_dict` 状态机） | `quality_pipeline/routers.py`、`graph.py`、FIX_LOG B⇄C 循环 2 轮实绩 |

**验收**：P6 五模块与真实 7 节点一一对应；P4 每行来源有 M13 实际数据支撑。

---

## 批次 3｜Qwen 与上下文工程：P7（1 次工作会，**在阶段 0 完成后填**）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P7-1 Qwen 作用表** | 5 行：模型与调用方式（qwen3.7-flash/plus/3.8-max + DashScope compatible-mode）/承担任务（表）/上下文组成（Prompt 结构）/结构化输出约束（`response_format=json_object`、`StructuredLLM` 三级、JSON Schema）/与检索解析协作（子图 1/2/3 + 质量管线 Agent 工具调用） | 阶段 0 后 `config.py` 全 Qwen 模型表 + `web/summary.py` + `vlm_client.py` + `quality_pipeline/utils/llm.py` |
| **P7-2 上下文组织与约束** | 防幻觉措施（性质白名单 PropertySpec、VLM 页码映射防页码幻觉、`min_confidence 0.7` 丢弃、bbox 校验丢弃、`_is_usable_summary` 防错位透传、LLM 生成代码沙箱低置信不执行）/上下文更新逻辑（每源检索结果回填、错误反馈重试）/效果数据（质量问题 54→20 修改→4 冲突→0 剩余；M13 源质量分区间） | `property_standardization.py`、`vlm_extractor.py`、`result_builder.py`、`summary.py`、`quality_pipeline/sandbox/` |

**验收**：P7 表格内每个模型名在阶段 0 后的真实配置中存在；效果数据与 Arcturus/M13 真实产物一致。

---

## 批次 4｜查找与解析方法：P8 + P9 + P10（1–2 次工作会，量最大）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P8-1 查找过程表** | 5 行：需求→检索表达（ADS 查询串构建/星表列映射）/候选发现（27 星表匹配 + ADS rows=20 + 补充表 guess）/相关性判断（`retrieval_priority` 属性命中数+ADS score）/缺失补充（VLM 提取失败重试、Unpaywall 多级下载） | `subgraphs/subgraph2/nodes/*`、`database_utils.py`、`paper_utils.py` |
| **P8-2 真实查找示例** | M13 Case：原始需求→检索方式→候选来源（以阶段 0 产物为准）→保留/排除理由（如报道 Vt 或 [Fe/H] 的论文被采用；与性质无关/无开放 PDF 的排除） | 阶段 0 产物 sources + 各自理由 |
| **P9-1 解析类型表** | 4 行：PDF 正文（PyMuPDF 100dpi→Qwen3.7-Plus VLM 整实体提取）/复杂表格补充材料（列映射+SIMBAD 别名过滤）/科研图表（figure_extractor 裁剪图证）/数据库 API（astroquery VizieR 4 镜像回退）——每行填 方法/提取内容/质量检查/无法解析处理 | `subgraphs/subgraph3/nodes/*`、`vizier_client.py` |
| **P9-2 复杂解析示例** | M13 一篇论文跨页表格/图：原始→提取（如表格中 [Fe/H]=-1.39 或 Vt 值）→校验（bbox 0–1000 坐标校验、min_confidence） | 阶段 0 产物 + cassette VLM 响应片段 |
| **P10-1 统一过程表** | 5 行：字段名（PropertySpec 白名单+column_mapper 列映射）/对象标识（SIMBAD 别名正则）/编码格式（schema_mapping 28 字段/1178 别名）/单位规则（34 组/257 条换算，K↔℃、dex↔log(Sun)）/缺失（missing_value_handler、min_confidence 丢弃） | `property_standardization.py`、`column_mapper.py`、`unit_converter.py` |
| **P10-2 真实统一示例** | M13 金属丰度多源写法（星表 -1.445 log(Sun) vs 论文 -1.39/-1.51/-1.57±0.07 dex）→统一为 dex 的过程与原始保留 | 阶段 0 产物 + `data_trace` |

**验收**：每个表格行都有具体代码路径或真实记录佐证；单位统一示例展示"原始写法→规则→结果"三步。

---

## 批次 5｜质量与整合：P5 + P11 + P12（1 次工作会）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P5-1 评价方案表** | ≥3 行：字段正确性（outlier/可行性范围/LLM 完整性）/来源可回溯性（trace_id+provenance）/冲突处理质量（Cohen's d 方差卡/分类/置信标注）——每行 方法/对象样本/对后续影响 | `quality_pipeline/subgraphs/data_assessment/*`、`data_conflict/*` |
| **P5-2 评价口径** | 4 问：重点与原因/抽样（阶段 0 案例记录数、per-source 并行 8 worker）/正确错误缺失冲突无法判断定义/修正前后口径是否一致 | `decision_reasoning_agent.py` 规则表 + `quality_scoring_agent.py` |
| **P11-1 整合方法表** | 5 行：同对象多记录（按 entity+field 聚合）/重复近似（duplicate_handler）/数值冲突（方差保留全部 + 分类注释，preserve_all）/字段缺失（标注+missing_value_handler）/无法确认同对象（HumanReview） | `data_normalization/*`、`data_conflict/*`、`quality_pipeline/models/record.py` |
| **P11-2 来源保留** | 4 问：溯源元数据（provenance：db_table/key_column/key_value/raw_unit；paper page/bbox；supplement cds_table_id/row_index）/多来源同字段表示（EAV + trace_id）/模型补充 vs 规则换算 vs 原始区分（source_kind + extraction_method）/未合并冲突及原因 | `aggregator.py`、`record.py`、`source.py` |
| **P12-1 质量问题表** | 3 真实问题：①bbox 解析失败（历史 M13 运行 error_log 5 条 `无法解析为 dict: '[]'`，新运行以实际为准）②单位/量表冲突（metallicity dex vs log(Sun)）③VCR 回放数据错位——每行 发现方式/原因/修改环节/结果 | 阶段 0 产物 error_log（+历史运行佐证）+ FIX_LOG + CLAUDE.md §5 |
| **P12-2 反馈机制** | 4 问：触发重查（VLM 失败重试/检索优先级低）/触发重解析重对齐（Normalization↔Conflict 循环）/必须人工（HumanReview E→A/E→B、gate 失败）/版本保留（`data_trace` record_id/field/before/after/tool/reason + 源文件 CSV） | `routers.py`、`data_trace` 结构、quality_summary issues_summary |

**验收**：P12 三个问题均为真实发生过并有修复记录；P11 来源保留字段与 `record.py`/`source.py` 模型一致。

---

## 批次 6｜代表案例（一）：P13 + P14 + P15（1 次工作会）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P13-1 案例选择** | 场景（球状星团 M13 的积分V星等+金属丰度两性质）/理由（覆盖数据库+论文+图证多源、属典型天体物理检索、避开距离多重表征易错点）/覆盖能力（27 星表+ADS+VLM 表/文/图）/边界声明（不覆盖光谱原始数据、不覆盖非天文领域） | 阶段 0 产物 + README 示例 |
| **P13-2 案例数据需求表** | 5 行：对象与目标（M13，汇总星团物理参数）/范围与条件/字段与单位（**积分V星等 mag、金属丰度 dex**）/期望输出（JSON+CSV）/质量方法 | 阶段 0 产物 + `GlC.json` 性质库（integrated_v_mag/metallicity 定义） |
| **P14-1 候选来源表** | 4–6 行代表来源（MWSC 数据库采用；2–3 篇论文采用；1 篇排除并给理由）：类型/找到内容/是否采用/理由 | 阶段 0 产物 sources（选代表） |
| **P14-2 查找过程** | 4 问：需求→检索条件（ADS title/abs 查询串 + SIMBAD 别名匹配星表）/首查不足（部分论文无开放 PDF）→Unpaywall/arXiv 补充下载/最终覆盖 | `ads_search.py`、`pdf_download.py` 多级回退 |
| **P15-1 解析内容表** | 3–4 行：MWSC 数据库记录（table 查询）/论文表格（VLM table 提取）/论文正文（VLM text）/图证（figure_extractor）——原始形式/方法/字段/校验 | 阶段 0 产物记录 + extraction_method |
| **P15-2 原始→结构化对照** | 3–4 行：如论文原文 "[Fe/H]=-1.39（Carretta & Gratton 标度）" → metallicity -1.39 dex（状态：正确）；多论文 metallicity 多值（-1.51 / -1.57±0.07，状态：冲突已保留标注）；MWSC 星表 Vt → integrated_v_mag（状态：正确） | 阶段 0 产物 + data_trace |

**验收**：P14 每行来源能在阶段 0 产物中找到对应 source_id；P15 对照表能从"原始文本"定位到"提取字段"。

---

## 批次 7｜代表案例（二）：P16 + P17（1 次工作会；P18 按用户决策留空）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P16-1 V1 输出表** | 4–6 行初始记录（V1=质量管线规范化前）：如 MWSC 星表 Vt（mag）/metallicity 原始写法（-1.445 log(Sun) 或 [Fe/H]=-1.39 dex）——含 单位/来源/核对状态 | 阶段 0 产物记录（raw_field 保留原始写法 = V1） |
| **P16-2 V1 质量检查** | 完整性/准确性 + 冲突两行：检查对象与判断/结果/主要问题（单位未统一、metallicity 多量表、bbox 部分失败） | `quality_summary` issues_summary + assessment 54 项 → 阶段 0 产物对应项 |
| **P16-2 附问** | V1 能否直接用（否，依据：多量表冲突+缺失单位）；V2 需改什么 | 同上 |
| **P17-1 V1→V2 变化表** | 5 行（查找范围/内容解析/字段单位统一/重复缺失冲突/结构化输出）：V1→发现问题→修改方法（unit_converter、field_standardizer、duplicate_handler、LLM 生成工具、preserve_all 冲突注释）→V2 | `data_trace`（record_id/field/before/after/tool）+ Arcturus 实绩（20 修改/4 冲突/0 剩余） |
| **P17-2 第二版结果** | 改善（0 剩余问题、单位统一、可回溯）/未解与新代价（token 开销、部分论文仍无 PDF）/支持的分析（星团物理参数汇总、多论文对比）/是否达标（依据：quality_level fair 0.89 + 0 剩余问题） | quality_summary + manifest |

**P18 处理**：整章保留模板占位，顶部加一行 `> 待补：计划补做 ①人工整理 vs 系统 ②去质量管线单轮提取 两组对照后填写（用户已确认本轮暂不填）`。**不编造对照数字。**

**验收**：V1/V2 差异全部来自 `data_trace`/quality_summary 真实记录，无推测值。

---

## 批次 8｜总体结果与交付：P19 + P20（1 次工作会）

| 章节 | 要填的字段 | 素材来源 |
|---|---|---|
| **P19-1 总体表现表** | 2 行任务范围：M13 案例（来源/记录/质量分以阶段 0 产物为准）/大角星（18 源/49 行/0.8954）——记录量/质量结果/能否回溯到原始出处/遗留问题 | 阶段 0 产物 + `output/6459b52c/` |
| **P19-2 失败与边界** | 3–4 行：bbox 解析失败（历史 M13 运行 5 条，新运行以实际为准）/VCR 回放数据错位（防透传已降级）/并发 1 排队/单次 token 成本（大角星 24 LLM 调用 257s 参考） | CLAUDE.md §5 + 阶段 0 产物 error_log + `output/6459b52c/` |
| **P19-3 应用与成本** | 4 问：结构化数据如何下载使用（export 下载+CSV/JSON 供科研脚本）/成本对比（一次任务 LLM 调用数 vs 人工查星表读论文）/人工兜底（HumanReview、无法确认保留原文）/不能支持的来源学科（非天文、需付费/受限源） | export 文件 + 运行统计 |
| **P20-1 交付内容表** | 6 行：源代码+运行方法（GitHub 路径 + 一键运行）/Qwen 凭证截图/案例输入与修正记录/M13 结构化输出+Schema/测试 API+前端（FastAPI + 5173）/可选视频 | 项目根 + `docs/` | **需用户提供：GitHub 仓库地址、阿里云百炼控制台/计费截图、演示视频链接（如做）** |
| **P20-2 自检清单** | 逐项勾选 5 条（≤20 页为 PPT 阶段项，标注"PPT 生成时核对"） | — |

**验收**：P20 交付表无 `【待补】` 残留（用户材料到位后）；自检清单 5 条全勾或明确标注归属阶段。

---

## 风险与注意

1. **Qwen 切换影响面**：只改质量管线 `llm.py`/配置 + `add_units.py` + 启动自检引用；先跑 `test_web_offline.py` 再真实重跑，避免污染 cassette。若 qwen3.7-flash 结构化输出偶发不稳，`StructuredLLM` 三级 fallback 已兜底。
2. **文档数字矛盾**：`CODE_ANALYSIS`/`README`/`OPTIMIZATION_STATUS` 中 KB 条目数（78 vs 294）、星表数（22 vs 27）不一致 → 一律以**代码当前值 + 最近日期真实产物**为准；报告引用前先核对。
3. **P18 留空**：按用户决策不填，占位标注即可，不编造对照结果。
4. **P16/P17 V1 重构**：系统不存"未经质量管线的独立 V1 输出"，V1 由 `raw_field`/`data_trace.before` 重构，需在报告中如实说明"V1 为规范化前原始提取视图"。
5. **P1/P20 需用户材料**：批次 1/8 结束时汇总缺项成清单（报名名称、团队截图、视频链接、GitHub 地址、百炼凭证截图），一次性向用户索取，避免反复打断。
6. **案例更换连带更新**：报告案例改为无距离查询后，`tests/test_e2e_recorded.py` 的查询/澄清答案/`assert_m13_contract` 期望性质须同步改为"积分V星等/金属丰度"再重录 cassette（0a 改代码时一并改，0d 重录）；旧 M13 距离快照仅作次要参考，案例章节不得引用其数字。

## 全局验收（对应模板 P20 自检）

- 全部 20 章中仅 **P18** 按决策留占位，其余无空字段（用户材料项以 `【待补】` 显式标注而非留白）。
- 每个数值（来源数/记录数/分数/修改数）可溯源到本计划"素材基线"表中的具体文件，**零编造**。
- 溯源三区分（原始来源 / 规则换算 / 模型补充）在 P11/P15 明确呈现。
- 阶段 0 完成后质量管线全 Qwen；P20 附百炼凭证截图与调用日志。
- **P13-P17 案例数字全部来自阶段 0 的 `output/m13_real_run/`（"M13 的积分V星等与金属丰度"），不引用旧距离快照数字。**
