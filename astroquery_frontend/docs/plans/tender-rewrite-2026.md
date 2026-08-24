# docs/template.md 从零填写工作方案（2026 揭榜挂帅·方向 1A）

> 前提：旧填稿（muban.md）已作废删除，本方案**从零重写**，不参考旧稿内容。
> 代表案例：**昴星团 M45**（2026-08-24 用户手动真实运行，task_id 待跑后固化）。
> 已就绪的代码改动：质量管线 qwen3.7-flash（`astroquery_ai/config.py`）、年龄
> log(yr)/yr/Myr 三态单位确定性统一（unit_converter V2.3 + normalization_agent
> Layer 0 预统一）、bbox 溯源页图落盘 + 前端画框（result_builder / web /records /
> RecordDetail）。

---

## 0. 写作总原则（怎么设计、怎么写）

1. **零编造**：每个数字必须能溯源到代码或运行产物（文件 + 字段名），写不进证据链的内容删掉而不是编。
2. **单一事实来源**：先固化 `output/m45_real_run/RUN_NOTES.md`（查询文本、task_id、关键指标、每字段值域、冲突清单），全部章节引用它；写完后用脚本对一遍数字。
3. **真实优先**：评审看"是否真实做过"，失败与边界如实写（比堆砌成功叙事可信）。素材：牛郎星两轮实体错位、M31 星表占位值、3C 273 多波段混装。
4. **三层区分**：原始来源 / 规则换算 / 模型补充，在 P11/P15 处处显式标注（模板明确要求"严格区分"）。
5. **案例按时间线叙事**：需求 → 检索 → 解析 → V1 → 质检 → V2，不按模块罗列（P13–P17 的骨架）。

## 1. 阶段 0：素材固化（用户跑完 M45 后立即做）

- 验证产物：`output/<task_id[:8]>/` 的 grounded_data / quality_summary / traceability / figures；检查 age 字段是否单一单位 Gyr、`figures/<task_id>/source_pages/` 是否有页图。
- 固化到 `output/m45_real_run/`（拷贝全部导出文件 + 关键图证 + 截图），写 RUN_NOTES.md。
- 重录 cassette：`tests/test_e2e_recorded.py` 查询与契约换成 M45（同步 `assert_m13_contract` 类断言），`-m network` 重录 + 回放验证 + 密钥检查。

## 2. 数字口径清单（从产物提取，每项注明出处）

| 数字 | 出处 |
|---|---|
| 来源数/记录数/按类型分布 | grounded_data.json sources/records |
| 质量分、B⇄C 循环轮数、LLM/工具调用数、耗时 | traceability.json data_lineage |
| 评估问题数/规范化修改数/冲突解决数/剩余数 | quality_summary.json |
| 每字段值域 + 与文献对照表 | grounded_data records（写表时逐字段列） |
| bbox 覆盖率、图证数 | records.provenance + figure_evidence |
| 真实失败清单 | traceability error_log + RUN_NOTES 实测记录 |

口径基准：**25 个 VizieR 星表**（`subgraphs/subgraph2/catalog/catalog_config.json` 实测 25 张表）；RAG 性质库条目数、schema 别名/单位规则数以代码实测为准（写前跑一遍，不抄旧文档）。

## 3. 按章写作指引（每章：写什么 + 证据在哪 + 注意）

| 章 | 内容要点 | 证据 |
|---|---|---|
| P1 | 简介 300 字：系统做什么 + M45 案例数字（来源/记录/多源互证）；Qwen 说明 300 字：**分工表要写质量管线=qwen3.7-flash**（VLM=qwen3.7-plus、P1=qwen3.8-max、其余 flash）、百炼 compatible-mode、JSON Schema + 三级回退 | RUN_NOTES + config.py |
| P2 | 核心主张/方法链条；结果1=M45 多源互证案例；结果2=质量管线闭环数字；**局限照实写**：双星实体消歧（牛郎星两轮错位实据）、多波段星等拆分、VCR 回放风险 | RUN_NOTES + 旧运行 error 记录 |
| P3 | 5 行数据需求表用 M45 实例填 | RUN_NOTES |
| P4 | 来源清单 ≥3 行：VizieR 25 星表 / ADS 论文 / SIMBAD / Unpaywall+arXiv PDF / CDS 补充表；每行"实际获取内容/理由/局限/来源保留" | catalog_config + grounded sources |
| P5 | 评价方案 3 行（字段正确性/来源可回溯/冲突处理）+ 口径定义（正确/错误/缺失/冲突/无法判断） | assessment 规则 + quality_rules.yaml |
| P6 | 5 模块 ↔ 真实 7 节点一一对应；闭环：Normalization↔Conflict 循环 ≤3 + HumanReview 兜底 | main_graph 拓扑 + routers.py |
| P7 | Qwen 分工表 + 上下文工程：PropertySpec 白名单、页码防幻觉、min_confidence、bbox 硬校验、白名单强制丢弃（V2.5）；效果数据用 M45 真实修改数 | config + vlm_client + result_builder |
| P8 | 查找 5 环节 + **M45 真实查找示例**（需求→ADS 检索式→候选→保留/排除理由） | RUN_NOTES sources |
| P9 | 解析 4 类型表（PDF 正文 VLM/表格/图表/数据库 API）+ **M45 复杂解析示例**：**用 bbox 溯源图做原始→提取对照**（本次新功能直接服务此章） | record provenance + source_pages 图 |
| P10 | 字段/单位统一规则 + **年龄三态单位统一为真实案例**：`8.15 log(yr) → 0.141 Gyr`（10^x×1e-9 换算，data_trace 留痕）——今天修的这个 bug 就是 P10 的现成素材 | unit_converter V2.3 + data_trace |
| P11 | 整合/冲突/来源保留：EAV + provenance（页码+bbox / db_table+row_index）、冲突保留并标注、模型补充 vs 规则换算 vs 原始区分 | record.py + aggregator |
| P12 | 质量问题表 3 条真实问题：① 年龄三态单位（已修，给出前后对比）② 牛郎星实体错位（两轮跑成天狼星/比邻星，质量分 0.84–0.88 照样 good → 说明质量管线不校验实体级正确性，这是真实边界）③ 星表占位值混入（HD 50 mag、TIC 4352 pc）；反馈机制 4 问 | 旧运行记录 + FIX_LOG + 本轮修复 |
| P13–P17 | M45 代表案例全链路；V1 由 raw_field/data_trace.before 重构并如实说明"V1=规范化前原始提取视图"；V2 展示统一后的单一单位/冲突标注 | RUN_NOTES + data_trace |
| P18 | **留空标注"待补"**（或补做两组真实对照：人工整理 vs 系统；无质量闭环单轮提取 vs 系统——需真实执行，不许编数字） | — |
| P19 | 总体表现 2 行（M45 案例 + 一次旧恒星查询）；失败边界表：牛郎星实体错位 / 多波段星等 / VCR 风险；成本：LLM 调用数 vs 人工 | RUN_NOTES + 旧运行 |
| P20 | 交付 6 行 + 自检 5 条逐项勾选；**页数口径以官网为准**（模板 30 页 vs 自检 20 页，写前核对官网） | 项目根 + docs/ |

## 4. 需要用户提供的材料（一次性索取）

1. 挑战杯报名作品名称、最终作品名称
2. 盖章版报名表第一、二页截图
3. 宣传视频链接（夸克网盘）
4. GitHub 仓库地址（公开）
5. 阿里云百炼控制台调用日志/计费凭证截图

## 5. 附属交付物

- 技术方案 PPT/PDF（≤ 官网页数上限；可后于文档做）
- 10 分钟演示视频脚本：M45 查询全流程 → 7 卡界面 → **点开一条记录看 bbox 溯源图** → 导出 CSV/JSON → 质量报告；录屏即可
- 测试 API 示例请求 + 前端入口核验（服务已在 8000/5174 跑）
- 复现说明：README 一键运行 + cassette 回放

## 6. 执行顺序

1. 用户手动跑 M45（现在，8000 后端 / 5174 前端）
2. 我：验证产物 + 固化 m45_real_run + 重录 cassette（阶段 0）
3. 我：按 P1→P4→P6→P7→P8–P10→P5/P11/P12→P13–P17→P19→P20 顺序分 4–5 批填写 template.md，每批完成后向用户汇报数字依据
4. 用户：补 P1/P20 用户材料；决定 P18 是否补对照
5. PPT/视频在文档定稿后制作（复用文档素材与 bbox 溯源图）
