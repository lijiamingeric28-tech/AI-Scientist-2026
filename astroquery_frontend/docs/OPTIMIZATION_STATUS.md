# 优化与修复完成状态报告

> 依据 docs/OPTIMIZATION_PLAN.md 执行，2026-08-10
> 验证基线：`pytest tests/ -m "not network"` → **60 passed**（含 16 沙箱安全 + 11 评估修复锚点 + 7 全链路/对抗）

## 零、2026-08-10 代码审计修复（AUDIT_REPORT，80/80 完成）

> 13 单元两阶段审查（90 findings → 85 confirmed / 5 refuted）→ 去重合并 80 条 → 12 组文件域并行修复。
> 验证基线：`pytest tests/ -m "not network"` → **271 passed**（原 79 + 12 个新 test_audit_fixes_g*.py ~190 锚点）+ 12 包导入 OK。

| 级别 | 数量 | 关键修复 |
|------|------|---------|
| critical | 1 | C-01 人工裁决作用域护栏（QHR 项禁用 adopt/custom + human_replace 空作用域降级 annotate + 消费端拒绝） |
| high | 17 | H-01 figure_evidence 通道声明 ｜ H-02 DB record_id 格式分支 ｜ H-03 normalize_unit 按 from_unit→to_unit 换算数值 ｜ H-04 cross_id source_ids 回填 ｜ H-05 P1 形状校验 ｜ H-06/H-07 subgraph1 重试+多层 JSON 解析 ｜ H-08 缓存键并入 target_entity ｜ H-09 bbox 类型归一化 ｜ H-10 image_cache 清理接线 ｜ H-11/H-16 两处 execution_status 透传回归（A7/R1-B8）｜ H-12 沙箱硬超时 _SANDBOX_TIMEOUT_SEC ｜ H-13 critical 异常入 human_review_items ｜ H-14 confidence float 强转 ｜ H-15 M9 typo reader ｜ H-17 LLM 逐项校验补全 |
| medium | 37 | 状态边界（retry_by_node 置 None 重置、dispatch Failed 信号、verification 拷贝隔离）＋ 数值口径（'g' 精度/NaN/逐 pair 异常/域紧度方向/offset 双向/不对称误差）＋ CSV 注入/写盘降级/宽表 LWW ＋ 工具日志键/低置信防护/fill_default/全量执行校验 ＋ 配置（metallicity 单位组/13 死段/5 列源）等 |
| low | 25 | 死代码清理（_timed/check_retry/simbad_resolver 导出/critical_expected）＋ 脚本相对路径/幂等真实过滤 ＋ 统计口径（oor 量纲/llm_call_count×2/e_mb/空串单位）＋ A&A 表号/年份动态/EOFError 等 |

> 同根因合并：figure_evidence（U01+U13）、DB record_id（U05+U06）、normalize_unit（U07+U08+U13）、cross_id 裁决（U08+U13）。
> 被推翻 5 条（详见 AUDIT_REPORT §5.1）：pdf 句柄滞留（CPython 引用计数）、_find_unresolved 键（基线契约过时）、typical_ranges（误数字面量）、from_conflict HR 分支（前置不可达）、compile_quality_graph（langgraph 1.2.7 行为不同）。
> 详细报告：docs/AUDIT_REPORT.md（含每条失败场景/证据/修复建议/验证结论）。


## 零-2、2026-08-10 真实 LLM 端到端验证（网络 smoke）

> 配置 .env 4 项 key 后跑通：`python -m pytest tests/test_smoke_network.py -m network` → **2 passed（20 分钟）**。
> M31 查询：sources=27, records=49（VizieR + VLM 提取 + 质量管线 Export 产物落盘）。

**过程中修复的真实链路问题**：
1. **循环导入**（真实入口暴露，离线 mock 未覆盖）：`property_standardization.py` 模块级导入 `subgraph1.config`、`adapters.py` 模块级导入三个子图工厂 → 均改延迟导入（与 quality_adapter 模式一致）
2. **GBK 控制台编码崩溃**（Windows 默认 GBK，emoji/上标打印即崩）：替换 5 文件 emoji 为 ASCII；**根治**——conftest.py 与 astroquery_ai/__init__.py 入口 `sys.stdout/stderr.reconfigure(utf-8, errors=replace)`
3. **HITL 循环**（真实数据被质量管线路由 HumanReview → interrupt 等待 stdin）：smoke 测试 mock 补上 `human_review_agent.interrupt → "3"`（取消）；测试运行加 `< /dev/null`
4. 测试 patch 目标随延迟导入更新（`adapters.create_*` → `subgraphs.*.graph`）

> 全量离线回归保持 **270 passed**。

## 一、已完成（✅ 代码实施 + 回归验证）

### 逻辑修复（C/H/M/L 全部完成）
| 编号 | 内容 | 关键文件 |
|------|------|---------|
| C1 | **沙箱逃逸**：safe_builtins 移除裸 `__import__`/`type`，`_safe_import` 白名单包装器；AST 校验扩展到所有 Name 节点 + dunder 属性链；**planning_agent dry-run 此前无校验**（比审计发现的更严重，一并修复） | normalization_agent.py / planning_agent.py / test_sandbox_security.py（16 用例） |
| H1 | HITL 断链：quality_node 注入共享 checkpointer + GraphInterrupt 上浮（无 checkpointer 降级报告） | quality_adapter.py |
| H2 | C→E→B 陈旧路由循环：gate 记录 loop_source，loop 按来源读"本轮"决策；`_from_conflict` typo 修复 | routers.py / human_review_agent.py |
| H3 | B→C 桥接：is_b_to_c 一律用复检 conflict_check，不回落过期方差 | conflict_identification_agent.py |
| H4 | 单位维度 token 化整词匹配（mag/dex 不再误判）+ unit_error 死循环重写 | statistical_conflict.py |
| H5 | insights 三节点 LLM 输出类型校验（字符串当列表迭代拖垮管线） | field_insight/relationship/recommendation |
| M1 | adopt_source_a/b 无值 → 降级自定义值流程 + human_replace 无值记 warning | human_review_agent.py / normalization_agent.py |
| M2 | 循环上限口径：max_iterations 3→8（纯兜底），from_conflict 复检无冲突直出 Export | routers.py / quality_rules.yaml |
| M3 | quality_summary 契约：has_unresolved_conflicts 匹配 V3.0 状态值；metadata 补写 auto_resolved/human_required | export_generation_agent.py / resolution_report_agent.py |
| M4 | 补充材料整表 provenance 放宽（source_kind=supplement/whole_table） | source_utils.py |
| M5 | conflict_nnotations typo → 并入 conflict_ctions + 去掉"仅新 source"条件 | source_router_agent.py |
| M6 | P1 LLM 输出防御（selected 非 list/缺键跳过） | property_standardization.py |
| M7 | 子图1 路由顺序：greeting/invalid 优先于 final_confirm 捷径 | routing.py |
| M8 | VizieR 大整数精度（str(int) 替代 str(float)） | database_utils.py |
| M9 | report_agent 读真实 per_entity_modifications + normalization_status typo | report_agent.py / metadata_generator.py |
| L1-L4 | 死代码删除 / bbox 双计数 / None→"None" 污染 / typo 契约统一清扫（from_conflict_flag/human_review_items/assessment_issues/normalization_modifications） | 多文件 |

### Assessment 算法优化（A1-A10 完成，A11 部分）
| 编号 | 内容 | 验证 |
|------|------|------|
| A1 | Cohen's d 三边界：σ_robust 稳健尺度（n<6 用量级 10%）、双零方差兜底、t 分布 CI（纯 math 表） | 4 场景验证：单记录离群检出、零方差检出、接近值不误报 |
| A2 | extraction_quality 权重接入（5 领域 6 维权重重归一，extr=0 降幅 0.12-0.15）+ 双保险 setdefault | 单测通过 |
| A3 | conflict severity 加权（critical=1.0/high=0.7/medium=0.4/low=0.2，Σ/3 封顶） | 2 critical ≈ 5 low |
| A4 | 自适应阈值接线为第 9 项检查（逐字段阈值 + adaptive_issues 违规清单） | decision 路由 Normalization |
| A5 | 三路由漏洞：records_missing_source / out_of_range（>50% HumanReview）/ target_schema 空不误路由 + cross_id 无辜过滤 | — |
| A6 | LLM 完整性改可加性惩罚（乘法双重扣分 → field_penalty 减法单次） | — |
| A7 | execution_status 透传（profiling Failed/Retry 不再被覆写） | — |
| A8 | overall 记录数加权 + Bootstrap CI（numpy B=1000）+ agreement 用 CI 宽度 | 1 条 vs 999 条验证 |
| A9 | consistency 连续化（0.4×schema + 0.3×type_ratio + 0.3×unit_ratio 记录数加权） | 单测通过 |
| A10 | canonical_unit 统一归一化（K≡Kelvin、yr≡year，decision+consistency 共用） | 单测通过 |
| A11 | domain_weights 补 extraction_quality + test_config_code_sync 一致性测试 | 单测通过 |
| A13 | Decision 死代码清理（_DECISION_SYSTEM 删除、单份 _ROUTE_SEVERITY、llm_count 移除） | — |
| A14 | 测试锚点 tests/test_assessment_fixes.py（11 用例守护全部公式改动） | 全绿 |

### Insights 基础优化（P0 完成）
| 编号 | 内容 |
|------|------|
| P0-1 | star.luminosity 范围漂移修正 [3e29,4e39]→[3e29,4e37]（与 reference_ranges 对齐）；校验脚本待建 |
| P0-2 | KB 检索扩展：content(+1.5)/hypothetical_queries(+2) 参与匹配 + 词边界守卫（<3 词只精确匹配） |
| P0-3 | 字段摘要稳健统计：[P5,P95]+median+extreme_values、按 source 分层抽样、IQR 离群计数 |
| P0-5 | kb_references 引用闭环校验（幻觉 ID 剔除，有效引用回填 title/source） |
| P0-6 | 拼写修复（conflict_status/conflict_outcome/insights_written）+ record_count 改 min(a,b) |

## 二、Backlog 完成状态（✅ 2026-08-10 第二次 workflow 全部实施）

| 编号 | 内容 | 状态 |
|------|------|------|
| A12 | 跨来源 bootstrap KS 分布检验（n≥15 pair，纯 numpy B=1000，distributional_ks_p + CAUSE_DISTRIBUTIONAL 标注） | ✅ |
| A11 余 | 硬编码值下沉 yaml（quality_scoring_runtime 段 + load_quality_scoring_runtime loader + _LEVELS poor 死分支删除） | ✅ |
| P0-4 | FieldInsight 分批（INSIGHT_BATCH_SIZE=6 切块 + MAX_INSIGHT_BATCHES=3 上限 + 诚实覆盖文案 + llm_call_count 按批累加） | ✅ |
| P0-1 余 | reference_ranges.yaml 结构化 ranges 段（star 条目）+ scripts/check_range_consistency.py（三源比对，--strict 模式） | ✅ |
| P1-1 | rag_property_matcher（懒加载 RAG 库 + 字段摘要注入 rag_description/rag_unit + CATALOG PROPERTY NOTES 段） | ✅ |
| P1-2 | PropertySpec 权威单轨（relationship 标准名优先 target_schema + standard_unit 注入字段摘要） | ✅ |
| P1-3 | recommendation 检索词派生（质量状态 → 主题词表，methodology/best_practice 兜底） | ✅ |
| P1-4 | LexicalEmbedder（纯标准库 TF-IDF）+ search 融合（rule + KB_SEMANTIC_WEIGHT×cosine） | ✅ |
| P1-5 | tests/test_kb_retrieval.py golden set（recall@5≥0.8/precision≥0.6）+ scripts/kb_coverage_report.py | ✅ |
| P1-6 | FieldInsight prompt 结构优化（standard_units 注入 + 越界标注指令 + 引用约束 + schema 说明） | ✅ |
| P2-1 | entity_type_overrides 接口（quality_adapter 注入 simbad otype + context_builder 最高优先级） | ✅ |
| R1 | B8（synthesis 透传 Failed）+ E10（exit 词整词匹配 + ADS 转义）+ E5 余（已随 A1 σ_robust 修复，验证确认） | ✅ |
| R2 | 四项：ADS PUB_PDF Bearer token / fl score 字段 / PDF 并发仅 arXiv 受限 / supplementary key_value 按行 | ✅ |
| P2-2 | 知识库覆盖扩展：+8 条目（星系形态/SFR/气体含量/星系团/X 射线/IRAS/2MASS/HYPERLEDA，含结构化 range）20→28 | ✅ |
| P2-3 | insights 扩展 A→E/C→E 路径（HumanReview 出口注入 human_review_support 确定性洞察，0 LLM） | ✅ |

> **全部 backlog 已实施完毕**（P1-6/P2-1/P2-2/P2-3 于 2026-08-10 第三轮完成）。
> 最终验证：79+ 测试全绿 + 12 包导入 OK + 覆盖率报告可运行（86 条知识）。

> **2026-08-10 补充（git restore 事件）**：实施期间工作区被外部 `git restore` 重置，抹掉了
> 会话起点 8 项未提交修复（A9/A10 consistency、M4、A6、H1、H2、L4、M2）——已全部重新恢复
> 并复验（79 测试全绿 + 12 包导入 OK）。

## 三、实施中发现的新问题（修复时顺手处理）

1. **planning_agent dry-run 无 AST 校验**（审计未发现）：dry-run 直接 exec 未校验代码 + 裸 `__import__` —— 与 C1 一并修复
2. **P0-3 首次实施引 TypeError**：`g["source_ids"]` 是 set 不可下标 → 排序轮转修正
3. **yaml 行内注释吞掉 `]`**：flow sequence 内 `[a, b  # comment]` 的 `]` 在注释后被吞 → 语法错误，已修正为 `[a, b]  # comment`
