# P18 实际对照、消融与方案优势 — 执行计划（2026-08-28 上午）

## Context

申报技术报告 `docs/申报技术报告.md` P1–P17 已填真实数据（M45 代表案例：175 条记录/30 来源/质量分 0.8298/84 图证/271 分钟），P18 空白，提示框要求"只填团队真实完成的比较，不编数字"。模板允许与人工整理、单一来源、通用检索、去掉关键模块后的版本比较。

用户上午可运行真实查询（Qwen 百炼）。经核实 `output/m45_real_run/traceability_*.json` 只有 `data_lineage` 计数、**没有逐条 data_trace.before**，无法从产物重构"管线输入视图"——所以对照 2/3 必须真实消融运行，不能靠拆分旧产物。

**素材**：`output/m45_real_run/`（权威：grounded_data_20260824_195658.json / quality_summary_20260824_195658.json，字段已核实：issues_summary = {assessment_issues:121, normalization_modifications:141, conflicts_resolved:11, remaining_issues:0}；processing_statistics = {total_llm_calls:64, total_tool_calls:213, total_elapsed_seconds:358.48, b_c_loop_iterations:2}）。

## 对照矩阵（P18 表格 4 行，数据需求恒同：M45 的 age/distance/dist_modulus/parallax/fe_h）

| # | 对照对象 | 评价方法 | 本作品结果（用 m45_real_run） | 对照结果（实验产生） |
|---|---|---|---|---|
| 1 | 人工整理 | 耗时/摘录条数/与系统命中率/可回溯性 | 175 条/27 分钟/逐条 bbox 溯源 | 实测摘录 12-16 条 + 耗时 + 命中 N-M 条；页码级 |
| 2 | 无质量闭环（消融：只关质量管线） | 记录数/单位混杂/错误值数/冲突处理数/耗时 | 121 评估/141 规范化/11 冲突/0 剩余 | 消融运行：原始提取单位混杂、冲突 0 处理 |
| 3 | 仅数据库单源（消融：禁论文链+白名单 mwsc） | 记录数/性质覆盖/收敛证据 | 175 条/5 性质全覆盖/收敛区间（Gaia 135.15、HST 134.6±3.1、VLBI 136.2） | 4 条/缺 parallax/log(yr)、log(Sun) 原样/单值无收敛 |
| 4 | 通用检索（裸 qwen3.7-plus 一次回答） | 数值条数/出处可验证/单位规范 | 175 条结构化+bbox | 1 段文字、无出处、单位不统一 |

## 代码改动（4 文件，全部可逆、默认行为不变）

1. **`astroquery_ai/config.py`**（`llm_max_retries` 后，pydantic-settings 风格，env 自动大写映射）：加 `quality_pipeline_enabled: bool = True`、`paper_chain_enabled: bool = True`、`catalog_whitelist: str = ""`。
2. **`astroquery_ai/quality_adapter.py`** `quality_node` 空数据检查（85-87 行）后加早退：`if not get_settings().quality_pipeline_enabled: return {"quality_report": {"skipped": True, "reason": "ablation_disabled"}}`。`quality_finalize_node` 已有把 skipped 标记并入 final_output 的兜底逻辑（223-230 行），无需改。
3. **`subgraphs/subgraph2/graph.py`**（53-64 行）：`paper_chain_enabled` 为假时不装配 build_ads_query 链，START 直接连 `result_aggregator`（`result_aggregator` 全程 `state.get()` 默认值，安全；主图 route_after_retrieval 见下载为空→skip_extraction）。注意：不要用"空返回 build_ads_query"，ads_search 有仅天体名回退查询，会实际查 ADS。
4. **`subgraphs/subgraph2/nodes/database_query.py`**（`load_catalog_config` 后）：`catalog_whitelist` 非空时按逗号分隔 key 过滤 `catalog_config`。顶部加 `from astroquery_ai.config import get_settings`。

## 脚本（3 个，新增到 `scripts/`）

1. **`scripts/p18_metrics.py`** — 输入：消融 final_output JSON + m45 三件产物 + `--out output/p18_ablation/p18_metrics.json`。输出 7 组：①记录/来源数（source_type 在 sources 上）②age 单位混杂清单（按 (source_id, field_name) 统计 field_unit；值模式分类：值内嵌单位 `100_myr`、区间 `70-100`、下划线 `5.33_+/-_0.06`、log(yr)/log(Sun)、± 不确定度）③质量 issue 数字（读 quality_summary 已核实字段）④错误/越界值候选（age∉[0,1e13]、distance∉[1,5000] pc、dist_modulus∉[0,30] mag、parallax∉[0.1,30] mas、fe_h∉[-1.5,1.5] dex 扫描，人工复核后引用——0.1054 消光值属 V1 时代，V2 消融 raw 中不存在，**不要引用**）⑤耗时/LLM 调用 ⑥bbox 覆盖率（m45: vector 123/full_table 41/fallback 7/None 4=97.7%）⑦字段完整率（age 30/distance 56/dist_modulus 49/fe_h 27/parallax 13）。
2. **`scripts/p18_generic_llm.py`** — 裸调用 qwen3.7-plus（无系统提示、无工具），问"昴星团(M45)的年龄、距离和金属丰度"，响应存 `output/p18_ablation/generic_llm_response.txt`。
3. **`scripts/p18_manual_compare.py`** — 输入人工 CSV + m45 grounded_data，按 field_name+source_id 对齐（数值相对误差 <1%），产出命中数/漏检数/回溯性对照/单位格式差异。

## 人工整理任务单（用户执行，对照组 1）

- 计时：开工 `date` 记录，逐条 `seconds_spent`，结束记总时长（预估 30-45 分钟）。
- 材料（PDF 在 `subgraphs/data/papers/be5dd304-bf9e-4633-9da3-1b6c3f54f7ed/`，无则从 ADS 重下；溯源页图备份 `output/m45_real_run/source_pages/`）：
  - 1999ApJ p13 正文 + p1 摘要：distance 130.7 pc；dist_modulus 5.58±0.18
  - 2006A&A p9 Table 6 + p2：age 70-100 Myr、dist_modulus 5.60-5.70、fe_h 0.0668；p2 有 fe_h −0.14~+0.13、dist_modulus 5.33±0.06、distance 116.3±3.2
  - 2003AJ p6 + p26 Table 3：dist_modulus 5.53；fe_h 0.003
  - 2005AJ p1 + p8：distance 133.5±1.2 / 134.6±3.1、parallax 7.49±0.07 / 7.43±0.17
  - 2019A&A p5 Table 1：distance 135.15±0.43、parallax 7.34
  - VizieR `J/A+A/558/A53/catalog`（MWSC）：Pleiades 行 logt/d/MOD/[Fe/H]
- 摘录表 `output/p18_ablation/manual_extraction.csv` 列：`seq, property, value, unit, source, page, quote, seconds_spent, note`。原样抄写不换算不改单位；不偷看系统值。完成后跑 `p18_manual_compare.py`。

## 执行顺序（约 2.5-3 小时）

1. **改 4 文件 + 冒烟**：`python -c "import astroquery_ai.cli, subgraphs.subgraph2.graph"`；stub 单测 quality_node 早退。
2. **后台启动消融运行 #1**（~22-27 分钟，真实计费约几元）：
   `PYTHONUTF8=1 QUALITY_PIPELINE_ENABLED=false printf '年龄、距离和金属丰度\ny\n' | python -m astroquery_ai "昴星团(M45)的年龄、距离和金属丰度" -o output/p18_ablation/quality_off_final_output.json -v > output/p18_ablation/quality_off_run.log 2>&1`
3. 并行：通用 LLM 裸调用；写 p18_metrics/p18_manual_compare 并 dry-run（用 m45 产物）；**用户同步做人工摘录**。
4. #1 完成后启动单源消融 #2（~4-6 分钟）：
   `PYTHONUTF8=1 CATALOG_WHITELIST=mwsc PAPER_CHAIN_ENABLED=false printf '年龄、距离和金属丰度\ny\n' | python -m astroquery_ai "昴星团(M45)的年龄、距离和金属丰度" -o output/p18_ablation/single_source_final_output.json -v > output/p18_ablation/single_source_run.log 2>&1`
   （#2 质量管线保持默认开，只削数据源。）
5. 跑 3 个脚本，人工复核越界值候选清单。
6. 填 P18：4 行表格 + 结果说明 4 条（科研数据适用性/数据处理方法/结果质量和复用/没有改善的部分（跨源单位差异保留策略；范围写法 1-2 条保留；+358s +64 次 LLM 调用；端到端 ~25 分钟 + API 费）与成本）。所有数字来自实验产物，零编造。

## 验证

- `git status` 仅 4 个文件改动；消融运行新 query_id，不触碰 `subgraphs/data/papers/be5dd304-*`。
- #1 输出 `quality_report == {skipped: true, reason: ablation_disabled}`；log grep 到"[Quality Adapter] P18 消融"；CLI 退出码 0；#1 的 query_id 目录**无** quality_summary/traceability 导出。
- #2 sources 恰为 `[SRC_DB_MWSC]`、records 4 条，值与 m45 的 MWSC 4 条一致（age 8.15 log(yr)/dist_modulus 5.576/distance 130/fe_h -0.036 log(Sun)）；figure_evidence 空。
- 提取端一致性：比 #1 records 与 m45 重叠 source_id 的 record_id 集合，差异如实记录（ADS 检索当日漂移可能，P18 注明）。
- 消融运行全部走 CLI（web 对 skipped 有优雅回退，无需改 web）。

## 降级预案

- #1 因网络/ADS 漂移与 m45 差异过大（论文集漂移 >20%）：以 m45 quality_summary 的"输入侧问题计数"为对照口径并如实注明"两次运行检索结果存在漂移"。
- 单源消融 #2 失败：退化为 m45 grounded_data 按 SRC_DB_MWSC 拆分（Plan agent 核实该拆分可得同样 4 条），标注"自同一次运行按源拆分"。
