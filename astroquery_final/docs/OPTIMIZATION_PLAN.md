# quality_pipeline 调研与优化方案报告

> 由 7-agent workflow 产出（4 路调研 + 3 路方案设计），2026-08-10
> 三部分：① Assessment 评价算法优化（含开源方案调研）② Insights 模块优化 ③ 整体代码逻辑审查修复计划

---

## 一、Assessment 评价算法优化方案

### 目标

在不引入重依赖、保持 0 LLM（除既有 LLM completeness 一次调用）、不破坏现有 state 契约（report_state.quality.* / per_source_routes / conditional_routes）的前提下，以公式/权重/阈值/流程结构级修复 Assessment 模块 V3.x 的 12 类缺陷：修复 Cohen's d 三个边界漏报、接入被静默丢弃的 extraction_quality 权重、把自适应阈值死代码接线为第 9 项检查、补 records_missing_source/out_of_range_count/target_schema 空三个路由漏洞、消除 LLM 完整性双重计分、恢复子图级重试状态透传，并借鉴调研中的开源方案（F-UJI 层级聚合、RAND bootstrap SE、GE bootstrap KS 分布检验、Wang&Strong 维度分类、CDS/VizieR 单位同质化）增强评分聚合与不确定性输出。

### 优化项（12 项，按优先级）

#### [高/小] 修复 Cohen's d 三个边界缺陷 + 清理无效循环（statistical_conflict.py:310-321, 327-334, 465-469）

**依据**: ① n<2 分支用相对差异 (a−b)/max(a,b,0.001)∈[0,1)，永远达不到 D_LARGE=2.0 → 单记录 source 的极端离群 100% 漏报；② 双组组内方差都为 0 时 pooled_std=0 → d 恒为 0，均值差 1e6 也判 uncertainty 而非 anomaly；③ CI 恒用 1.96 而非 t 分布（小样本 CI 过窄）；④ :465-469 的 for 循环只含 continue 是死代码，unit_error 实为组级一次。对应调研中'稳健离群检测组合（IQR/修正 Z-score）'与 GE 分位数/z-score 检验的尺度思想。

**实现**: 引入字段级稳健尺度 σ_robust = IQR(该 (entity_name, field_name) 组全部数值)/1.349（MAD 兜底），ε = max(σ_robust, 最大|值|×1e-6)。① n<2 分支改为 d = |mean_a−mean_b| / max(σ_robust, ε)，删除 :312 相对差异；② pooled_std≤0 时分母取 max(pooled_std, ε)（:319-321），保证 d 有界；③ CI 用 t_{0.975, na+nb−2}（纯 math 实现 t 近似表，df≥30 用 1.96；不新增 scipy）；④ 重写 :465-469 为按 source 收集 dimensions 一次 append（含 per-source dim 明细）。

#### [高/小] extraction_quality 权重接入 + 全领域 6 维权重重归一化（quality_scoring_agent.py:72-82 + quality_rules.yaml domain_weights + quality_scoring.py:17-23 _DEFAULT_WEIGHTS）

**依据**: metrics 传 6 维但所有 weights 只有 5 维 → compute_quality_score 按 weights 迭代（quality_scoring.py:66），extraction_quality 被静默丢弃，overall_score 从不含提取质量；extr_score=0 的 source 可被其他高分完全掩盖，仅剩 Decision 0.3 阈值一处作用。按 Wang&Strong 15 维框架，提取溯源/可追溯性属 Intrinsic(believability) 维度，在天文多源场景是可信度核心，应入权重。

**实现**: ① quality_rules.yaml 每领域补 extraction_quality 并重归一化（建议值，和=1）：astrophysics 0.12/0.15/0.10/0.25/0.23/0.15（completeness/consistency/format/source_reliability/conflict_risk/extraction_quality），materials 0.26/0.26/0.05/0.13/0.18/0.12，chemistry 0.22/0.22/0.13/0.13/0.18/0.12，biology 0.18/0.22/0.13/0.18/0.17/0.12，default 0.20/0.24/0.10/0.15/0.19/0.12；② _DEFAULT_WEIGHTS 同步；③ quality_scoring_agent.py 加双保险：`weights.setdefault('extraction_quality', 0.12)` 后按 Σw 归一化（compute_quality_score 已按 total_weight 归一化，加 key 即生效）；④ 在 yaml 每个权重后补来源/依据注释（F-UJI 的权重透明性要求）。

#### [高/小] conflict_risk 分数改为 severity 加权（quality_scoring_agent.py:78-80）

**依据**: 现公式 conflict_score = 1−min(1, count×0.1) 只数个数：1 个 critical unit_error 只扣 0.1，10 个 statistical_outlier 才扣满 1 分；严重度不对等（unit_error/cross_id 是数据语义错误，应远重于同方法同条件的统计离群）。

**实现**: 改为 conflict_score = max(0, 1 − min(1, Σ_anomaly sev(a)/3.0))，sev 映射：critical=1.0（unit_error/cross_id_error）、high=0.7（extraction_error/statistical_outlier）、medium=0.4、low=0.2；遍历 sr['conflict_risk']['conflicts'] 的 severity 字段（anomaly dict 已带 severity）。权重表与归一常数 3.0 下沉 yaml（与第 11 项合并）。

#### [高/中] 自适应阈值引擎接线为第 9 项检查（quality_assessment_agent.py:113-115 + decision_reasoning_agent.py）

**依据**: below_adaptive_threshold 全库 0 消费者（已 grep 验证），get_conflict_hreshold 无调用方，adaptive_threshold.py:72-73 代码默认 small_mult=1.3 与 yaml 0.85 矛盾；comp_field 取 present_fields 首个字段代表全 source 有偏差。E1 引擎投入已存在，接线成本最低且直接堵住'完整度低但无其他问题→Export'的洞。

**实现**: ① quality_assessment_agent.py：阈值按 (entity, field) 逐字段计算——遍历 completeness['field_completeness']，critical_fields 用 base 0.95、important 0.90、aux 0.70 × sample_factor × domain_factor；任一 critical/important 字段 coverage < 阈值 → below_adaptive_threshold=True 并记录违规字段列表 `adaptive_issues`（替换 :113 首个字段逻辑）；② decision_reasoning_agent.py 加检查：`sr_completeness.get('below_adaptive_threshold') → issues_found.append('below_adaptive_threshold: {fields}')` → 路由 Normalization；③ 统一 adaptive_threshold.py 默认值与 yaml（删 1.3 默认或注释澄清'小样本放宽=multiplier<1'，yaml 0.85 为现行值）；④ get_conflict_hreshold 保留为 Conflict 模块预留接口并标注 unused。

#### [高/小] 补三个路由漏洞（decision_reasoning_agent.py）

**依据**: ① records_missing_source（外键断裂）只在 completeness issues 里，Decision 8 项检查无对应项 → 外键全断可无异常直达 Export；② profile.out_of_range_count 只在 Normalization validation_agent.py:120 事后消费，Assessment 内部不路由（物理不可行值不拦截）；③ target_schema={} 时 expected_fields=[] → 全部字段算 alias → 全量误路由 Normalization（quality_state.py:349 默认空 dict 依赖上游填充）；④ cross_id_error 把同实体全部 source 一并 HumanReview 包括无辜者（:161-163）。

**实现**: ① 加检查：`sr_completeness.get('records_missing_source',0) > 0 → issues_found.append('missing_source: N records')` → Normalization；② 加检查：`oor = profile.get('out_of_range_count',0)`，oor_ratio = oor/max(总记录数,1)，>0.5 → HumanReview，否则 → Normalization；③ target_schema 为空（schema_fields 为空）时跳过 alias/missing_expected 检查，reason 写 'target_schema missing — alias check skipped (上游未提供)'，不再全量 Normalization（以 assessment_summary 显式警告兜底）；④ cross_id 判定前用 src_records 过滤：仅当 sid 的记录的 entity_name ∈ cross_id 异常的 entity_name 时才判 HumanReview。

#### [高/中] LLM 完整性调整改可加性单次计分 + 上下文增强（llm_completeness.py:82 + quality_scoring_agent.py:64-66）

**依据**: adjusted = 1−(...)×0.5 再乘 raw_score（已含 0.4×外键+0.3×单位+0.3×溯源惩罚）→ 双重扣分；LLM 只凭标题分类（:59-64）无 schema 语义易幻觉；失败回退 1.0 使 LLM 可用性直接决定扣分与否。另一面：missing_expected_fields 当前完全不进 score（completeness.py:139 公式无字段项），字段全缺也可 score=1.0——LLM 调整恰好应补这个洞。

**实现**: ① llm_completeness.py：新增输出字段 `field_penalty = 0.5 × (expected + 0.3×optional) / max(len(expected_fields),1)`（保留 adjusted_completeness 向后兼容）；prompt 注入 target_schema 字段语义描述（从 schema_mapping.yaml 字段定义读）与 research_domain，降低幻觉；失败回退 field_penalty=0（不扣分、写 warning 到 summary）；② quality_scoring_agent.py：`score = clip(raw_score − field_penalty, 0, 1)`（:65-66 从乘法改减法），raw 内部三项不变 → 各扣分只计一次；expected/optional 阈值系数 0.5/0.3 下沉 yaml（第 11 项）。

#### [高/小] execution_status 透传修复（quality_assessment_agent.py:328）

**依据**: profiling 的 errors≥3→Failed/Retry 被 quality_assessment 无条件覆写 'Success'（:328），finalize 读到的永远是 decision 的 Success → 子图级重试机制形同虚设。

**实现**: quality_assessment_agent.py 返回前读入参 `prev = state.get('workflow_state',{}).get('execution_status')`：`final = 'Failed' if prev=='Failed' or 任一 source 降级失败 else ('Retry' if prev=='Retry' else 'Success')`（:328 改）；decision_reasoning_agent.py:278 同样透传而非硬编码 Success；单 source 降级报告（:255-265）计入失败计数。

#### [中/中] overall_score 改记录数加权 + Bootstrap CI（quality_scoring_agent.py:124 + :149-170）

**依据**: overall_score 对 source 等权算术平均，1 条记录的小 source 与 1000 条记录的大 source 权重相同；评分无不确定性输出。对应调研 RAND QA Tools '加权通过率 + bootstrap SE'（传统 SE 公式在资格/通过相关性下难算，bootstrap 直接估计）与 PRIDIT/gsm.studykri 的百分位 CI。

**实现**: ① `overall = Σ(score_i × n_i)/Σ(n_i)`（n_i=record_count，全 0 时回退等权；:124）；② S3 用纯 numpy 实现 bootstrap（B=1000，按 source 索引重抽样，无 scipy 依赖）：overall 分布取 2.5/97.5 百分位 → 输出 `overall_score_ci`；agreement_factor 改用 CI 宽度：`agreement = max(0.3, 1 − (ci_hi−ci_lo))`；③ CI 与 per_source_scores 一并写入 quality_scoring 报告（不改路由，供 HumanReview/Export 摘要使用，契约只加字段）。

#### [中/小] consistency 连续化评分（consistency.py:155-164）

**依据**: score=通过项/3 只有 {0, 1/3, 2/3, 1} 四档，1 个字段单位不一致即整维失败（二分），对下游加权评分与决策矩阵过于钝感；代码内已有 per_entity_*_consistency 细粒度数据（:121-141）却没用进总分。

**实现**: 改为连续公式：`score = 0.4×schema_ok + 0.3×type_ok_ratio + 0.3×unit_ok_ratio`，其中 type_ok_ratio/unit_ok_ratio = 按字段记录数加权的通过比例（复用 :67-107 的 field_shape_map/unit_map，加权分母=字段覆盖记录数）；全通过时=1.0 与现值一致，单个字段不一致只按比例扣分。系数 0.4/0.3/0.3 下沉 yaml。

#### [中/小] canonical_unit 统一单位归一化（decision_reasoning_agent.py:98-99 + consistency.py:91-107）

**依据**: _norm_unit 只做 °/℃→C 字符串级替换，'K' vs 'Kelvin'、'yr' vs 'year' 会误报 unit_mismatch → 误路由 Normalization；consistency 的 unit_consistency 也是字符串比较，两处各自实现。对应 CDS/VizieR 发布前 DQ 清单'列单位必须同质'与 schema_mapping.yaml 单位规则。

**实现**: 在 source_utils.py 新增共享 `canonical_unit(u)`：清理空白/括号 + °/℃→C + 大小写/别名映射（K≡Kelvin、yr≡year、m/s≡m s^-1 等，映射表从 schema_mapping.yaml 的 units 规则加载，加载失败回退纯字符串清理）；decision_reasoning_agent 的 unit_mismatch 与 consistency 的 unit_consistency 统一调用；不影响现有输出字段名。

#### [中/中] 配置收敛：硬编码值全部下沉 yaml + 代码-配置一致性测试

**依据**: volume 0.3/0.7/0.9、agreement std×2、repair_cost 3/10、extraction 0.3、anomaly 0.1（quality_scoring_agent.py:79, 151-170；decision_reasoning_agent.py:146-150, 158）、_LEVELS 0.40 死分支（quality_scoring.py:26-31）、domain_weights 双处定义（yaml :137 与 :585、_DEFAULT_WEIGHTS）全部硬编码/重复，改一处另一处失同步。

**实现**: quality_rules.yaml 新增 `quality_scoring:` 段：volume_thresholds {10:0.3, 100:0.7, else:0.9}、agreement_std_coef 2.0、repair_cost {anomaly: [1,3], issues: [3,10]}、extraction_human_threshold 0.3、conflict_severity {critical:1.0, high:0.7, medium:0.4, low:0.2}、level_thresholds {excellent:0.90, good:0.75, fair:0.60}（删 poor:0.40 死分支）；各 agent 读配置并带 fallback；新增测试 `test_config_code_sync`（见 verification）。

#### [低/大] 跨来源分布一致性检验（bootstrap KS，纯 numpy）（statistical_conflict.py 扩展）

**依据**: 现跨来源比较只用 per-source 均值算 Cohen's d，均值相同但分布不同的来源差异完全不可见（如 5 条值 {100,100,100,100,900} vs {180×5}，均值同、分布异）。对应调研 GE bootstrapped_ks_test / distributional expectations（z-score/分位数/KL/KS）。

**实现**: 对 (entity_type, entity_name, field_name) 组内任两 source 且双方 n≥15 的 pair：对原始值（非均值）做 bootstrap KS（numpy 重抽样计算 max|经验 CDF 差|，B=1000，p<0.01 判分布不一致）；结果并入 variance_entry：`distributional_ks_p` 字段，且当 d<0.5 但 KS p<0.01 时 inferred_cause 优先标 `distributional_variance`（新 cause 常量，不阻塞 Export，仅标注）；n 过小时跳过。可选 scipy.stats.ks_2samp 加速（非必需，不新增依赖）。

#### [低/小] Decision 死代码清理与语义明确化（decision_reasoning_agent.py）

**依据**: _DECISION_SYSTEM LLM prompt 定义但从不调用（:20-27）造成文档-实现漂移；llm_count 读取但从不回写（:43）；_ROUTE_SEVERITY 定义两次（:18, :184）；决策矩阵构造两份（:175-180, :216-219）；matrix 只单向升级的语义未文档化（fair×high→Conflict 在 base 已被 Normalization 覆盖时行为依赖 severity 比较，读者无法判断意图）。

**实现**: ① 默认删除 _DECISION_SYSTEM 与 llm_count 读取（保持 0 LLM 原则），在 docstring 注明'V3.x 为纯规则决策，LLM 增强已移除'；② 合并单份模块级 `_ROUTE_SEVERITY` 与 `_build_decision_matrix()` 函数；③ :185-186 改为显式注释的 escalate_only 语义：`route = matrix_route if severity(matrix_route) > severity(base_route) else base_route`，并把两路结果都写入 decision_matrix 输出（已部分实现）；④ 若后续要双向决策，可加 config 开关 `matrix_direction: escalate_only|matrix_priority`（默认 escalate_only 不动行为）。

#### [低/中] 测试锚点补齐（tests/test_quality_pipeline.py 扩展，test_fix_regression 模式）

**依据**: 现有测试仅 3 个契约测试（test_make_initial_state_contract/empty_data/test_quality_graph_compiles），本方案所有公式改动无回归护栏，V4 系列逐 bug 修复的熵增会继续；CLAUDE.md 的 test_fix_regression 模式（先写失败测试再修复）正好可用。

**实现**: 新增：test_cohens_d_single_record_boundary（n=1 vs n=1，值 500 vs 5 → d≥2 检出 anomaly）、test_zero_variance_pair（双组各 2 条同值，均值差 1e6 → 检出而非 uncertainty）、test_target_schema_empty_no_global_reroute（target_schema={} → 不全部 Normalization）、test_cross_id_innocent_source（同实体无辜 source 不 HumanReview）、test_extraction_weight_in_overall（extr_score=0 时 overall 至少降 0.12）、test_adaptive_threshold_wired（低完整度无其他问题 → Normalization）、test_consistency_continuous（1 字段单位不一致 → score<1 但 >2/3）、test_severity_weighted_conflict（1 critical > 10 low）、test_config_code_sync（yaml 值与代码 fallback 一致）、test_overall_record_weighted（1 条 vs 999 条 source 加权）。

### 预期影响

1) Cohen's d 边界修复后：单记录 source 极端离群（此前 d∈[0,1) 永远 <2.0，100% 漏报）与双零方差组（d 恒 0 漏报）均可检出，anomaly 检出率由公式保证可测；CI 换 t 分布后小样本 CI 宽度正确（不再过窄假阳性）。2) extraction_quality 权重 0.12-0.15 接入：extr_score=0 的 source overall_score 降幅从 0 变为 ≥0.12，'0 分提取维度被高分完全掩盖'消除；severity 加权后 1 个 critical unit_error 扣分从 0.1 → 0.33。3) 自适应阈值由 0 消费者变为第 9 项检查，低完整度无其他问题的 source 不再直达 Export（此类数据占比取决于数据集，每 source 多 1 次检查、0 额外 LLM 成本）。4) 路由漏洞补漏：外键全断不再直达 Export；物理不可行值（out_of_range_count>0）在 Assessment 阶段拦截（此前只有 Normalization 事后知道）；target_schema={} 不再全量误路由 Normalization（消歧目标：schema 缺失时 alias 误报 100%→0）。5) LLM 完整性双重扣分消除（乘法→可加性惩罚），且 missing_expected_fields 首次进入评分链，'字段全缺也 score=1.0' 漏洞闭合。6) overall 记录数加权：1 条记录 source 的聚合权重从 1/N 降至 n_i/N（2 sources 1 条 vs 999 条时从 50% → 0.1%），整体分不再被小 source 主导；bootstrap CI 使评分带不确定性输出。7) consistency 从 4 档二分变 [0,1] 连续，1 个字段单位不一致的惩罚从整维归零变为按记录占比扣分。8) execution_status 透传后子图级重试恢复生效。全链路 LLM 成本不变（仍是每 source 至多 1 次 LLM completeness 调用），运行时长增加 <10%（逐字段阈值计算与 bootstrap 均为 O(n log n)/O(B×N) 纯 numpy）。

### 风险

- 权重调整（extraction_quality 入权 + 重归一化）会改变既有评分与决策矩阵结果，依赖旧 golden 值的测试断言需同步更新，否则回归测试误报
- Cohen's d 用 σ_robust 后小样本组更容易触发 statistical_outlier → 路由向 Conflict/HumanReview 偏移，可能增加人工介入量（预期内，但需在验收时监控路由分布变化）
- LLM 完整性改为可加性惩罚后，字段缺失严重的 source 分数下降 → 更多 Normalization 路由（符合'不完美即清洗'哲学，但会改变下游工作量）
- target_schema 为空时跳过 alias 检查可能放过真别名（权衡：以 assessment_summary 显式警告兜底，避免静默漏检）
- bootstrap CI（B=1000）在超大规模数据上增加少量运行时间（毫秒级，numpy 向量化），若数据 >10 万记录可降 B=500
- canonical_unit 引入新单位别名映射可能改变 unit_mismatch 判定结果（如 K/Kelvin 从误报变正常），需回归比对确认无反向误判
- 逐字段自适应阈值可能因 critical_fields 列表不全（yaml 只列 6 个材料字段）产生阈值选择偏差，需保证 astronomy 领域 critical_fields 补充到位

### 验证方式

1) 单元测试（tests/test_quality_pipeline.py 扩展，按 CLAUDE.md 的 test_fix_regression 模式：先写断言'修复前行为'的失败测试，再修复）：为第 1/2/3/4/5/6/7/8/9/10 项各建一条边界用例（详见第 14 项清单），覆盖 n=1 vs n=1、双零方差组、target_schema={}、外键全断、extr_score=0、低完整度、1 字段单位不一致、1 critical vs 10 low、1 条 vs 999 条 source、K vs Kelvin。2) 回归：运行 `D:/miniconda/envs/py3.10/python.exe -m pytest tests/test_quality_pipeline.py tests/test_main_graph.py tests/test_full_loop_mock.py`（Python 3.10），确认既有契约测试（make_initial_state_contract/graph_compiles）与 mock 全流程不破坏；state 契约只增字段（overall_score_ci、field_penalty、adaptive_issues、distributional_ks_p），不改删既有键。3) 端到端：用合成 grounded_data 构造上述边界场景跑 test_full_loop_mock 类流程，断言 per_source_routes 结果：双零方差组→Conflict、外键全断→Normalization、out_of_range 50%+→HumanReview、target_schema={}→不再全量 Normalization 且 summary 带警告。4) 配置一致性：新增 test_config_code_sync 断言代码 fallback 默认值与 quality_rules.yaml 现值一致，防双处定义失同步。5) 效果量化：对同一测试数据集在改动前后各跑一次，记录 anomaly_count（应上升：边界漏报转检出）、Normalization 路由数（应上升）、overall_score 变化（extr 弱 source 应下降 ≥0.12），输出对比表作为优化验收证据。

---

## 二、Insights 模块优化方案

### 目标

对 Insights 洞察模块 (subgraphs/data_insights + quality_pipeline/tools/insight) 做"0 LLM 成本优先"的可执行优化: (1) 统一三套互相漂移的典型范围配置为单源并加启动校验; (2) 将 KB 检索从"仅 tags/applies_to/category 子串匹配"升级为 content/hypothetical_queries 参与、带词边界阈值、纯 Python TF-IDF hybrid 的检索, 并接上评测基准; (3) 打通 RAG 性质库 (3293 条/2101 property_id) 与 PropertySpec(target_schema) 到 insight 上下文的断链 — 注入标准单位/逐星表描述/实体类型; (4) 修复字段摘要统计抗噪、分批覆盖、引用闭环、拼写等正确性问题。目标是让每字段洞察覆盖率、检索 recall、DB 列解读质量可量化提升, 且全程不新增 LLM 调用、不引入重依赖。

### 优化项

#### [P0/M (0.5-1 天)] P0-1: 典型范围单源化 + 启动一致性校验 (消除三源数值漂移)

**依据**: 已实测漂移: entity_types_astrophysics.typical_ranges star.effective_temperature=[2000,100000] K 与 reference_ranges.yaml 自由文本('O 型~40000 K'/'全域 2000-100000 K')不一致; star.luminosity 兜底 [3e29,4e39] erg/s≈1e-4~1e5 Lsun 与 reference_ranges '1e-4~1e6 Lsun' 矛盾, 红色超巨星会被判越界; main_sequence_star[2400,50000] 与 star[2000,100000] 同实体链也漂移。三套范围 (feasible/typical/reference) 语义相近但无同步机制, LLM 与确定性兜底拿到互相矛盾的'事实'。

**实现**: a) quality_rules.yaml 的 entity_types_astrophysics.typical_ranges 定为唯一权威兜底源 (确定性路径不改代码); b) insight_knowledge/astrophysics/reference_ranges.yaml 每条目增加可选结构化段 range: {lo, hi, unit} (与 content 自由文本并存), 由 field_insight_agent 的 _format_knowledge_block 渲染时优先用结构化数值; c) 新增 scripts/check_range_consistency.py (纯 yaml 读取, 0 依赖): 对 (entity_type, semantic_key) 三源比对 lo/hi/unit, 容忍度内一致则通过, 漂移输出 warning 并给出建议值; 先以 warning 模式上线, 修正全部现存漂移后加 --strict 进 CI; d) 修正现有漂移值: star.luminosity 改 [3e29,4e37] erg/s 并备注 Lsun 换算关系 (与 reference_ranges '1e-4~1e6 Lsun' 对齐), star.effective_temperature 全域改 [2000,100000] 与 star_teff_luminosity_span 一致, 各恒星子类 (main_sequence/supergiant/red_supergiant) 保持子集关系并加注释。

#### [P0/S (0.5 天内)] P0-2: KB 检索字段扩展 — content 与 hypothetical_queries 参与匹配 + 词边界/最小长度阈值

**依据**: knowledge_store.py:108-152 检索只扫 tags/applies_to/category, entry.content 与 hypothetical_queries 从不参与 (grep 确认全仓零消费), 仅存在于 content 里的概念 ('Macquart relation'、'Chandrasekhar 极限') 检索不到; physical_laws.yaml 已备好 hypothetical_queries 设计字段 (如 DM_redshift_relation) 白白浪费。子串双向匹配 (fn in ef or ef in fn) 还会被短名误命中 (如 'i' 命中 filter)。

**实现**: quality_pipeline/tools/insight/knowledge_store.py search() 内: a) 增加 _CONTENT_SCORE=1.5: 关键词/字段名在 entry.content 中命中 +1.5 (低于 tags 的 +3); b) 增加 _QUERY_SCORE=2: 关键词与 entry.hypothetical_queries 任一命中 +2; c) 词边界与长度守卫: 长度 <3 的查询词禁用子串匹配 (仅允许精确匹配), ≥3 的词先查全词 (regex \b), 未命中再降级子串; d) 复用同一评分管道, 不改 search 签名, 零调用方改动。

#### [P0/S-M (0.5-1 天)] P0-3: 字段摘要稳健统计 — value_range 改 [P5,P95]+median, values_sample 按来源分层, 加离群计数

**依据**: context_builder.py:94-125: value_range=[min,max] 与 values_sample=前 5 条记录, 单条错误值直接扭曲 LLM 看到的'观测事实'; 对跨来源差异洞察尤其不利 (5 条可能全来自一个 source)。这是 0 成本确定性增强, 直接改善 Node 1 prompt 输入质量。

**实现**: quality_pipeline/tools/insight/context_builder.py build_field_summaries: a) numeric 排序后计算 [P5, P95]+median (纯 statistics/numpy, numpy 缺失时手写分位, 不引入依赖); b) 保留 min/max 为独立字段 extreme_values 供 LLM 判断是否物理异常; c) values_sample 改为按 source_id 分层抽样 (每来源最多 3 条, 均匀铺开); d) 复用 tools/assessment/outlier.py 的 IQR 逻辑计算字段内 outlier_count (definite/suspected 计数) 加入摘要 — LLM 无需自己数。

#### [P0/M (1 天)] P0-4: 启用 INSIGHT_BATCH_SIZE 分批 + 诚实覆盖文案 (消除截断误标)

**依据**: domain_config.py:21 INSIGHT_BATCH_SIZE=6 定义后从未使用; MAX_FIELD_SUMMARIES_CHARS=12000 硬截断, 字段多时 LLM 漏覆盖, 漏掉的字段在 field_insight_agent.py:173 被 _merge_with_deterministic 标成 'LLM 不可用 — 仅提供确定性观测事实', 文案误导 (LLM 可用, 只是字段被截掉)。

**实现**: subgraphs/data_insights/agents/field_insight_agent.py: a) 将 field_summaries 按 INSIGHT_BATCH_SIZE=6 切块, 每块一次 LLM 调用 (temperature=0, prompt 相同), 结果合并后统一 _merge_with_deterministic; b) 加硬上限 MAX_INSIGHT_BATCHES=3 (domain_config.py 新增), 超过部分直接确定性输出 — 有界成本, 最多 18 字段进 LLM; c) 合并逻辑区分 llm_covered=True/False: 未被任何 batch 覆盖的字段 interpretation 改诚实文案 'LLM 未覆盖该字段 (超出分批上限), 仅确定性观测' , confidence=0; d) llm_call_count 按实际批次累加。

#### [P0/S (2-3 小时)] P0-5: kb_references 引用闭环校验 (幻觉 ID 剔除)

**依据**: knowledge_store.get_entry (knowledge_store.py:154-159) 已实现但四个 agent 从不调用; LLM 幻觉的 kb:ID 原样进 evidence_sources/kb_references, 污染证据可信度。纯确定性过滤, 0 成本。

**实现**: 在 field_insight_agent.py 与 relationship_agent.py 的 LLM 输出后处理各加一步 _validate_kb_refs: 对每条 kb_references 提取 kb:ID → get_entry 验证; 不存在的拆出到 invalid_kb_references 字段 (保留供审计), 有效引用回填该条目的 title/source 便于下游展示; _kb_preset_relationships 生成的引用天然有效, 无需处理。

#### [P0/S (半天)] P0-6: 拼写修复 + relationship 配对缺陷修复 (record_count 双计/无优先级截断)

**依据**: 已实测: context_builder.py:255-256 'conflict_tatus'/'conflict_oute' 泄漏进 LLM prompt; synthesis_agent.py:131 manifest['insights_ritten'] 拼错; relationship_agent.py:182 record_count=a+b 把两字段记录数相加 (同实体两字段本应取 min 作为有效配对样本); MAX_FIELD_PAIRS=30 直接截断, 无优先级, 物理定律候选对被随机丢弃。

**实现**: a) context_builder.py:255-256 改 conflict_status/conflict_outcome; b) synthesis_agent.py:131 改 insights_written; c) relationship_agent.py:182 record_count 改 min(a,b); d) _build_field_pairs 截断前按优先级排序: 先按两字段在 KB applies_to.fields 中是否共现 (物理定律候选, 如 dispersion_measure+redshift 同时出现在 DM_redshift_relation 的 fields), 再按 min(record_count) 降序, 取前 30。

#### [P1/M (1-1.5 天)] P1-1: RAG 性质库接入 — rag_property_matcher 工具 + 字段摘要注入逐星表描述

**依据**: rag_properties/ 100 文件/3293 条/2101 property_id, name_cn+description 含逐星表口径细节 (如 G.json 'HYPERLEDA 精度优于2″、RC3/2MASS XSC/GZ1 各口径') — 与 insight KB 同命名空间 (27 个 KB 字段中 19 个与 RAG id 重叠) 但内容互补 (RAG=目录/单位/描述, KB=物理/范围), 运行时零关联。DB 原始列 (database_catalog_properties) 解读本可直接受益。0 LLM, 纯查找。

**实现**: a) 新增 quality_pipeline/tools/insight/rag_property_matcher.py: 按 otype 文件名懒加载 json (进程级缓存 _cache: {otype: {property_id: entry}}), 提供 lookup(otype_hint, field_name) → {name_cn, description, unit, category}; otype 用 entity_type 规范名映射到文件名 (galaxy→G.json, 已有 100 个文件覆盖 154 个 Simbad 类型, 未命中返回 None); b) context_builder.py build_field_summaries 增加字段: rag_description (取 description 前 150 字) + rag_unit (RAG unit 仅在记录无 unit 时作为候选注入), 仅对 source_type=database 的组生效; c) field_insight_agent 的 _format_knowledge_block 后追加 'CATALOG PROPERTY NOTES:' 段 (每字段一行 [prop:{property_id}] {name_cn}: {description 摘要}), 只注入当前数据出现的字段; d) 命名空间去重策略: 对 19 个重叠 id 在文档与校验脚本中声明 'KB=物理解释, RAG=目录口径', 运行时以 KB 为主、RAG 描述为辅, 不做合并。

#### [P1/M (1 天)] P1-2: PropertySpec 权威单轨 — relationship 标准名改读 context_state.target_schema + 标准单位注入

**依据**: relationship_agent.py:129-143 用静态 schema_mapping.yaml 建标准名映射, 与 RAG P1 生成的 PropertySpec (property_id 命名空间, quality_adapter.py:30-53 注入 context_state.target_schema) 双轨并存 — PropertySpec 变更时映射静默失效; 且 target_schema.standard_unit 从未流入字段摘要, 记录缺单位时 LLM 无从知道标准单位。

**实现**: a) relationship_agent._build_standard_name_map 优先读 ctx.get('target_schema', {}).get('fields', []) 的 name (property_id), 其次 schema_mapping.yaml (回退链), 记录每条映射来源 (mapping_source: target_schema|schema_mapping) 供审计; b) context_builder.build_field_summaries 增加 standard_unit 字段: 字段名 (含语义聚合后的名) 命中 target_schema field name 时注入 standard_unit + semantic_type (RAG category 粗粒度); c) field_insight_agent prompt 注入 'STANDARD UNITS' 段: 每字段一行 field → standard_unit, 指令 LLM 据此解读无单位记录并指出单位异常 (替换现有 quality_rules 里 units 混淆)。

#### [P1/S (半天)] P1-3: recommendation 检索修复 — keywords=[domain] 改确定性质量主题词

**依据**: recommendation_agent.py:57 keywords=[domain]='astrophysics' 在全部 78 条 tag 中无命中 (grep 确认), 检索实际只靠 entity_types+category 硬分类, methodology/best_practice 条目 (如 frb_statistical_guidelines) 基本进不了 prompt, 检索价值趋零。

**实现**: recommendation_agent.py: 由 build_quality_context 输出确定性派生检索词: 实体名 + 字段名 + 按质量状态映射的主题词表 (anomalies>0 → ['anomaly','outlier']; variance_groups>0 → ['cross-source','comparison']; conflict_status 非空 → ['conflict']; coverage_gaps 非空 → ['missing','coverage']; low_conf 非空 → ['confidence','uncertainty']; 至少保留 ['methodology','best_practice'] 兜底); keywords 传入 kb.search 并注入 prompt 的 knowledge_block。

#### [P1/M (1 天)] P1-4: hybrid 检索最小接线 — 纯 Python TF-IDF 语义层替代 embedder 占位 (决策: 不引入模型依赖)

**依据**: embedder.py 是 NotImplementedError 占位; 但领域 KB 仅 78 条、词汇高度领域化, 关键词子串在补齐 content/hypothetical_queries 匹配后已够用; 上 sentence-transformer 是重依赖且领域微调收益不明。最小可行升级: 用零依赖 TF-IDF 余弦给 KB 条目建内容索引, 与规则分加权融合, 既消灭 embedder 占位, 又不引入模型。

**实现**: a) embedder.py 实现 LexicalEmbedder: 启动时对 78 条目构建 TF-IDF 向量 (token = 小写 + 简单拆分 [a-z0-9]+ 与单位符号), 纯标准库/collections 实现, 条目级缓存; b) knowledge_store.search 尾部融合: final_score = rule_score + 0.5 * tfidf_cosine(查询词并集, entry); 查询词 = field_names + keywords + entity_types; c) 保留规则分主导 (领域先验), 向量分仅提 recall; d) domain_config.py 增加 KB_SEMANTIC_WEIGHT=0.5 可调; e) embedder 的 NotImplementedError 路径仅剩为未来模型接口留档, 注明当前启用 lexic。

#### [P1/M (1 天)] P1-5: 检索评测基准 + KB 覆盖率报告脚本 (量化验证基础)

**依据**: 当前无任何检索质量度量, 优化无法验证、KB 覆盖缺口不可见 (reference_ranges 仅 3 条星系专属, 星系形态/SFR/气体含量/星表特有知识缺失无据可查)。

**实现**: a) 新增 tests/test_kb_retrieval.py: 每 category 建 golden query 集 (如 ('dispersion_measure','redshift') → 期望命中 DM_redshift_relation; ('effective_temperature','O-type') → star_teff_luminosity_span), 断言 recall@5≥0.8 (物理定律/测量理论类)、precision@5≥0.6, 作为所有检索改动的回归门槛; b) 新增 scripts/kb_coverage_report.py: 输入一次运行的真实 field_summaries (或直接读 insights_{ts}.json + sources), 输出三级覆盖率: 字段级 (语义聚合字段 vs KB applies_to.fields)、实体级 (entity_type vs KB applies_to.entities vs RAG 文件)、目录级 (vizier_table_id → RAG property 覆盖), 产出 gap 清单指导补条目; c) 两个脚本进 CI 或测试入口。

#### [P2/S-M (0.5-1 天, 不含上游改动则 M)] P2-1: 实体类型推断增强 — catalog_inference 前缀扩展 + context_state.entity_type_overrides 接口

**依据**: catalog_inference 仅 5 个 vizier 前缀 (III/135A, II/125, VII/237, VII/26D, VII/233), 未知星表一律落 default 'galaxy' → KB 实体匹配与典型范围兜底同时降级; 上游 P1 已查到的 SIMBAD otype (simbad_info) 未传入 quality_pipeline, 是 5 前缀推断的根本替代, 但改动上游 (astroquery_ai P1) 需最小接口。

**实现**: a) quality_rules.yaml catalog_inference 按实际消费目录扩展: 2MASS (II/246, II/281) → star/galaxy, IRAS (II/125 已有) 保持, HYPERLEDA (VII/237 已有), POSS (I/.., III/..) → star, GSC (I/305) → star — 以 SubGraph 3 实际查询的 vizier 目录清单为准补全; b) 最小上游接口: quality_adapter 或 graph.py 初始化时若上游 state 含 simbad_info (source_id → otype), 写入 context_state.entity_type_overrides: {source_id: otype}; context_builder.normalize_entity_type 调用前先查 overrides (优先级最高), 无则走现有推断链 — 上游未传时零影响, 纯增量; c) overrides 命中时在 field summary 标注 entity_type_source: 'simbad_override'|'catalog'|'field'|'default', 供覆盖率报告统计推断质量。

#### [P2/M (1-2 天, 内容工作量)] P2-2: 知识库覆盖扩展 — 按实际消费目录补条目 (内容工程)

**依据**: 78 条重度偏向 FRB/DM 与恒星 (reference_ranges 星系专属仅 3 条), 星系形态/SFR/气体含量/星系团/X 射线缺失; 而 G.json 等 RAG 文件显示实际消费目录是 IRAS/2MASS/HYPERLEDA 星系数据 — KB 与真实数据错位。

**实现**: a) 按 kb_coverage_report.py 产出的 gap 清单优先补: galaxy 条目 (galaxy_morphology: Hubble 型 T 序列范围; sfr: SFR 密度典型 1e-2~10 Msun/yr, Hα 光度换算; gas_content: HI 质量 1e8~1e11 Msun), cluster_of_galaxies (velocity_dispersion 100~1500 km/s, richness), X 射线波段条目 (luminosity 1e42~1e45 erg/s), per-catalog 条目 (IRAS flux_density 的 Jy 量级与 12/25/60/100um 波段含义; 2MASS 测光与银河消光注记; HYPERLEDA 口径差异说明 — 与 RAG G.json 描述呼应); b) 新条目一律带 structured range {lo,hi,unit} (配合 P0-1) + source/version/last_updated; c) 每条 target 领域标注 applies_to.entities 与 applies_to.fields, 不新增 category (复用现有 20 类, 防分类膨胀)。

#### [P3/M (1 天)] P3-1: insights 扩展到 A→E/C→E 路径 — HumanReview 数据也产出洞察

**依据**: insights 只在 Export 路径运行 (graph.py:190-191 Export→Insights→END), 人工评审的数据不产生洞察, 洞察价值被局限在完美/已解决数据。

**实现**: a) graph.py: HumanReview 出口 (route_after_human_review) 增加条件边: 若 workflow_state.human_review_exit 状态为'数据可洞察'(E→A/B 返回重评前), 经 insights 节点再进 Assessment/Normalization — 需与 routers.py 协调, 最小改动是加一条 'hr_insights' 边并复用 build_insights_graph().compile(); b) 若担心主图复杂度, 降级方案: insights 结果 (field_insights/relationships/recommendations) 在 HumanReview 出口注入 output_state.human_review_support, 供未来 UI 展示, 不强制跑完整 4 节点 (可只跑 Node1+Node3 确定性组件)。

#### [P1/S (半天)] P1-6: FieldInsight prompt 结构优化 (0 额外 LLM 成本, 随 P1-1/P1-2 注入落地)

**依据**: 当前 prompt (insight_prompts.yaml) 把 field_summaries/source_summaries/quality_context/knowledge_block 平铺注入, 无逐字段元数据提示、无越界判定指令、无输出 schema 约束 — LLM 解读无单位记录时靠猜, 输出 JSON 靠正则 {.*} 碰运气。

**实现**: quality_pipeline/configs/insight_prompts.yaml 与 field_insight_agent.py: a) user prompt 增加 '{standard_units}' 与 '{catalog_notes}' 两占位 (P1-1/P1-2 的产物), replace 注入 (沿用 V3.4 replace 机制防裸花括号); b) system prompt 增加指令: '若观测值超出该实体类型的 typical range, 必须显式标注 value_outside_typical_range=true 并给可能原因; 只能引用 knowledge_block 中出现的 [kb:ID], 不得虚构引用'; c) 输出格式改为明确 schema 说明 (insights[] 每项必含 entity_type/entity_name/field_name/observation/interpretation/typical_range/confidence/kb_references), 正则提取后 JSON schema 校验失败仅丢弃该批次走确定性 (现有容错路径); d) relationship prompt 同样注入 '{standard_units}'。

### 预期影响

预期可量化收益 (均以现有 M31/HYPERLEDA 与 FRB 样例实测为基线): (1) 字段洞察覆盖率: 截断导致的 'LLM 未覆盖' 从当前随机截断 (30+ 字段时约半数) 降至受控上限 (≤18 字段进 LLM, 其余诚实标注), 全字段输出对齐字段数; (2) 检索 recall: content+hypothetical_queries 匹配 + TF-IDF hybrid 后, golden set recall@5 预计从现有子串匹配的 ~60-70% 升至 ≥80% ('Macquart relation'、'Chandrasekhar 极限' 等仅存在于 content 的概念可命中); (3) DB 列解读质量: 标准单位 + 逐星表描述 (RAG) + 实体类型 overrides 三路注入后, M31 星系样例的 stellar_mass/distance 洞察将带正确单位与口径说明, 典型范围兜底不再出现 Lsun/erg/s 量级错误; (4) 证据可信度: 幻觉 kb:ID 被剔除, evidence_sources 100% 可解析; (5) 观测事实抗噪: P5/P95+分层抽样使单条错误值不再主导 LLM 解读, 跨来源差异洞察显著更稳; (6) 维护成本: 三源范围漂移被启动校验拦截, 配置变更可回归; (7) 全程 0 新增 LLM 调用 (分批上限封顶) 或减少无效上下文 (12k 截断废除后每批上下文更小), 不引入重依赖 (纯标准库 TF-IDF)。

### 风险

- 分批使 FieldInsight LLM 调用次数增多 (每 6 字段一次): 用 MAX_INSIGHT_BATCHES=3 硬上限封顶, 超限字段走确定性路径, 成本有界
- content/hypothetical_queries 参与匹配可能引入误命中 (content 长文本子串噪音): 权重压低 (1.5/2 vs tags 3)、词边界守卫、golden set recall/precision 回归门槛把关
- value_range 改 P5/P95 会掩盖真实极值: 保留 min/max 与 outlier_count 独立字段, LLM 仍能看到极值信号且知道它是否统计离群
- target_schema (property_id) 与 schema_mapping.yaml 双命名空间并存: 采用'target_schema 优先 + 回退 + mapping_source 审计'策略, 不改动 schema_mapping 既有语义
- RAG 逐星表描述带口径偏差 (如 HYPERLEDA 2″ vs RC3): 仅注入 source_type=database 且实体类型命中的组, 描述附 catalog 出处, 不并入确定性 typical_range
- 一致性校验修正数值可能改变 Assessment 离群判定边界: 校验脚本默认只报不修 (warning 模式), 数值修正走配置评审并跑 outlier 测试回归
- TF-IDF 对 78 条小语料区分度有限: 向量分权重仅 0.5 且规则分主导, 若 golden set 显示 recall 无提升可整体回退为纯规则 (权重可配)
- P2-1 的 entity_type_overrides 依赖上游 P1 传 simbad_info: 上游未改时接口空转零影响, 但需在 quality_adapter 留可选项并写单测覆盖两态

---

## 三、整体代码逻辑审查 — 修复计划

### 目标

基于全代码逻辑审查（22 项发现 + 已知问题清单复验）输出分优先级修复计划：critical（沙箱逃逸，立即修）→ high（5 项：HITL 断链、C→E→B 陈旧路由循环、B→C 桥接判据、单位维度误判、insights 类型崩溃）→ medium（9 项）→ low（4 项 + 已知风险归档/排期）。每项给出改动文件/行、改动方式、影响面（测试与契约），并按依赖关系排序（先修安全与阻断性问题，typo 契约清理最后统一扫）。

### 修复项（按严重性排序）

#### [critical/M（0.5 天）：两文件同步 + 逃逸 PoC 回归测试] C1 [critical] 沙箱逃逸：safe_builtins 暴露 __import__，AST 黑名单可被别名绕过（normalization_agent.py:129-148 + _validate_code_ast 474-519；planning_agent.py:584-600）

**依据**: 已确认 `"__import__": __import__` 在 normalization_agent.py:133 与 planning_agent.py:584 的 safe_builtins 中；_validate_code_ast 只对 ast.Call 的 func 名查 _FORBIDDEN_FUNCTIONS，`_imp = __import__`（Name Load，白名单允许）→ `_imp('os').system(...)` 即可任意代码执行；`type.__subclasses__` 亦可经别名链逃逸。注释宣称的『AST 白名单』防护实际无效，且代码在用户本机进程内运行，是最高危问题。

**实现**: 文件 A：subgraphs/data_normalization/agents/normalization_agent.py ① 133 行删除 `"__import__": __import__` 与 139 行 `"type": type`；② 新增受限包装 `def _safe_import(name, *args, **kw): base=name.split('.')[0]; if base not in _ALLOWED_MODULES: raise ImportError(...); return __import__(name, *args, **kw)`，以 `"__import__": _safe_import` 暴露（注意：exec 的 import 语句经 IMPORT_NAME 从 __builtins__ dict 取 __import__，直接删除会让 `import re` 报错，必须用包装器而非裸删除；math/re/datetime/collections/itertools/statistics 已预注入 globals，大部分模板代码不依赖 import 语句）；③ _validate_code_ast 增强：(a) 黑名单检查从『仅 Call 的 func』扩展到**所有 ast.Name 节点**（任意 Load 出现 _FORBIDDEN_FUNCTIONS 内名字即拒绝，杀死别名赋值）；(b) 所有 ast.Attribute 节点若 attr 以 `__` 开头（__class__/__bases__/__subclasses__/__getattribute__ 等）即拒绝（允许白名单例外如 __name__）；(c) 保留现 Import/ImportFrom 模块白名单。文件 B：planning_agent.py:584-600 同步同样改动。长期（后续里程碑）：换 RestrictedPython 替代手工黑名单。

#### [high/M（0.5-1 天）：风险最高的改动，需端到端验证] H1 [high] HumanReview HITL 断链：quality_node 无 checkpointer 注入，嵌套 graph 的 interrupt() 抛 GraphInterrupt 被 except 吞掉 → 整条质量管线静默跳过（astroquery_ai/quality_adapter.py:136-151；main_graph.py:243-246 的 __interrupt__ 循环只覆盖主图）

**依据**: 已确认 quality_adapter.py:138 `quality_graph.invoke(initial_state)` 无 config；human_review_agent.py:127 用 interrupt()（langgraph 1.2.7 无 checkpointer 必抛）；main_graph.py 顶层 while 循环覆盖不到嵌套 invoke。后果：任何 A→E/C→E 路由导致质量报告缺失、导出未清洗数据，人工审核永远不发生。

**实现**: ① quality_node 签名改为 `def quality_node(state, config=None)`（LangGraph 节点带 config 参数时自动注入，不破坏直接调用单元测试）；② 按 subgraph1/2/3 适配器既有 `_shared_checkpointer(config)` 模式构造嵌套 config，`quality_graph.invoke(initial_state, config=qconfig)`；③ quality_node 内单独 `except GraphInterrupt`：返回 `{"quality_report": {...}, "__interrupt__": [...]}` 透传（或由主图 run_pipeline 检查 result 中的 quality 层 interrupt payload，_prompt_for_interrupt 渲染后 `Command(resume=answer)` 以同一 thread_id 重进 main graph 恢复，LangGraph 嵌套中断经共享 checkpointer 在 resume 时回到 human_review 节点之后）；④ main_graph.py:243-246 循环改为同时处理顶层与 quality 层两处 `__interrupt__`。

#### [high/M（0.5 天）] H2 [high] C→E→B 陈旧路由循环：resolution_report.route_decision='HumanReview' 残留，loop_controller else 分支优先读它 → 反复重进 HR（quality_pipeline/routers.py:372-397；subgraphs/data_human_review/human_review_agent.py:52 `_from_conflict` typo 键被 schema 静默丢弃）

**依据**: 已确认 routers.py:374 `route = report.get("route_decision", wf.get(...))` 读陈旧 resolution_report（优先级高于 Normalization 新写的 wf.route_decision）；human_review_agent.py:52 写 `_from_conflict`（缺 a）而 routers.py:317 读 `from_conflict` → from_conflict 保持 True 走 C→B 分支；组合效果：C→E 流程要么浪费轮次强制导出、要么第 3 次 HR 走交互 interrupt → GraphInterrupt → 整个质量管线 pipeline_failed。

**实现**: ① 路由新写优先：loop_controller else 分支改为『本迭代 Normalization/Validation 已产出新 route_decision 时（可用 wf.phase/current_node 或 normalization.report 存在性判断）优先 wf.route_decision，否则才读 resolution_report』；② E→B 进入时清空陈旧结果：before_normalization_node（routers.py:283-292）或 E→B 路由处对 report_state.conflict.resolution_report 置空/tombstone；③ human_review_agent.py:52 改为正确的 `"from_conflict": False`，且 Step-4b 两个出口（E→A/E→B）都写正确键；④ 与 H3 的 conflict_check 无冲突→C→D 直出配合后，C→E→B→C→D 可在 MAX_LOOP 内干净收敛。

#### [high/S（2-3 小时）] H3 [high] B→C 断链桥接判据缺陷：仅当复检发现冲突时才用 conflict_check，复检无冲突时回落 Assessment 的过期 multi_source_variance（subgraphs/data_conflict/agents/conflict_identification_agent.py:31-46）

**依据**: 已确认 33-34 行 `is_b_to_c = needs_conflict_analysis or needs_variance_analysis`，39-42 行仅在 variance/anomaly count>0 时替换 msv。归一化已修复的单位/异常在下一轮 Conflict 被重新检出 → 无谓 C→B 轮次，修复成果被掩盖，路由失真。

**实现**: 只要 is_b_to_c 成立（Normalization 运行过且产生 validation），一律以 norm_validation.conflict_check 作为 msv 数据源（其『无冲突』结论由 variance_count=0 表达），彻底不回落 Assessment 的 multi_source_variance；保留 42 行字段结构兼容（variances/anomalies/counts）。配套新增回归测试：Normalization 复检无冲突 → Conflict 走 _no_variance_result 快速出口（C→D），不再制造轮次。

#### [high/S（半天）] H4 [high] 单位维度误判 + unit_error 生成块空操作（quality_pipeline/tools/assessment/statistical_conflict.py:95-107 与 464-480）

**依据**: 已确认：`_get_unit_dimension` 子串回退把 'mag'（含 m 米）判为 length、'dex'（含 d 天）判为 time；466-469 行 `for sid, ss in ...: continue` 循环体无任何效果（append 在循环外、if 内无条件执行），『空单位跳过』意图从未生效 → fe_h 等字段制造 severity=critical 假 unit_error → 无谓 Conflict 路由 + C→B 修复轮次 + quality_summary 失真。

**实现**: ① _get_unit_dimension：先把单位串按空白/分隔符/幂符号切分为 token，仅做整 token 精确匹配；短单位（m/d/s/K/G/T/J）只精确匹配绝不子串匹配；其余回退返回 `unknown:u`（unknown 不参与维度冲突判定）；② 464-480 行重写：收集 `dims = {_get_unit_dimension(ss["unit"]) for sid, ss in source_stats.items() if ss.get("unit")}`，仅当非 dimensionless 维度数量 > 1 才 append unit_error（空单位/未知单位不参与判定）。

#### [high/S（2-3 小时）] H5 [high] insights 三节点 LLM 输出零运行时类型校验，字符串当列表迭代在 try 外抛 AttributeError 拖垮整条质量管线（subgraphs/data_insights/agents/field_insight_agent.py:96-104、relationship_agent.py:90/98、recommendation_agent.py:84/92）

**依据**: 已确认：field_insight_agent.py:96 `insights = data.get("insights", [])` 未校验类型，104 行 `_merge_with_deterministic(...)` 在 try(71-101) 之外，146-147 行 `for ins in llm_insights: ins.get(...)` 对字符串逐字符迭代 → AttributeError 冒出 insights 子图 → 质量图 invoke 失败 → quality_adapter 捕获 → quality_report=skipped(pipeline_failed)。relationship/recommendation 的 setdefault 同样在 try 外。LLM 一次非预期返回即全管线静默跳过且难排查。

**实现**: 三文件统一模式：解析后立即 `if not isinstance(insights, list): insights = []`（同理 data 非 dict 时置 {}）；把 merge/setdefault 后处理整体纳入 try（或加 isinstance 断言后置 []）；recommendation 对 LLM 返回非 list 同样置 []。

#### [medium/S（2-3 小时）] M1 [medium] 人工裁决 adopt_source_a 在 value=None 时被静默丢弃（subgraphs/data_human_review/human_review_agent.py:195-224 与 404-407；subgraphs/data_normalization/agents/normalization_agent.py:99-102）

**依据**: 已确认：QHR/异常类审核项 source_a 无 value（仅 source_id），adopt 分支 selected_value=None → _decisions_to_actions 生成 new_value=None 的 human_replace → normalization_agent.py:99 `if action_type == "human_replace" and new_value is not None` 直接跳过，用户『采用 Source A』的决策静默丢失无日志。

**实现**: ① _get_user_choice 的 adopt 分支：校验 value 非 None，否则降级为提示『该源无具体值，请输入自定义值』走 custom_value 流程；② _apply_conflict_ction 对 new_value=None 的 human_replace 记 logger.warning（含 action 元信息）而非静默跳过，便于排查。

#### [medium/S（半天）] M2 [medium] 循环上限口径错位：MAX_ITERATIONS=3 对每次 loop_controller 访问计数（含首次 A→B），B⇄C 实际只能 1 轮，MAX_LOOP 保护不可达（quality_pipeline/routers.py:295-417，337 行）

**依据**: 已确认 337 行 `next_iteration >= MAX_ITERATIONS`（默认 3）对每次访问计数：A→B(1)→C(2)→B(3) 即 force_export，『回 Conflict 重新验证』第 4 次访问永远到不了；363/378/386 行 MAX_LOOP 分支形同虚设。另 from_conflict 分支（361-369）无条件回 Conflict，无视复检已无冲突（与 H3 同源）。

**实现**: ① 计数口径改为仅 C↔B 轮次：以 loop_round（before_normalization_node 已递增）为准判断，MAX_ITERATIONS 提升为纯兜底（如 2*MAX_LOOP+2=8）；② from_conflict 分支（C→B 复检完成）：读 normalization.validation.needs_conflict_analysis，False 时直接 next_route=Export（与 H3 配合，C→B→D 干净收敛）；③ 更新 loop_controller docstring 与实际行为一致。

#### [medium/S（半天）] M3 [medium] quality_summary 状态契约错位：恒报『存在未解决冲突』、人工审核/已解决统计恒 0（subgraphs/data_export/agents/export_generation_agent.py:112-129；subgraphs/data_conflict/agents/resolution_report_agent.py:189-199）

**依据**: 已确认：121 行 has_unresolved_conflicts 排除集为 (All_Resolved/No_Conflicts/None)，而 V3.0 实际状态是 Annotated/No_Variance/Needs_Unit_Fix/Unresolved_Anomalies → 恒 True；123/113 行读 metadata.auto_resolved/human_required 但 resolution_report_agent 从不写这两个键 → 恒 0/False。导出的 quality_summary.json 风险指标系统性错误，误导下游。

**实现**: ① has_unresolved_conflicts 改为 `status in ("Needs_Unit_Fix", "Unresolved_Anomalies")`；② resolution_report_agent（189-199 行附近）metadata 补写 `auto_resolved` 与 `human_required` 计数（可从 resolution_plan 的 resolved/annotated/needs_human 统计）；③ 与 B8（synthesis_agent 无条件写 execution_status=Success）一并对齐，使 export 层状态真实。

#### [medium/S（2-3 小时）] M4 [medium] 补充材料整表单天体表（无 entity_column）触发整批导出隔离（quality_pipeline/tools/export/output_validator.py:49-71；tools/assessment/source_utils.py:41-44；subgraphs/subgraph2/.../supplementary_query.py:395-396）

**依据**: 已确认：supplementary_query 无 entity_column 时 key_column=""，provenance_is_complete 对 database_query 记录要求四要素非空 → 全表记录被判缺失 → output_validator data_integrity is_valid=False → consumable=false，单天体 CDS J/ 表（常见场景）使整批输出不可消费。

**实现**: ① source_utils.provenance_is_complete 增加按 source_kind 分支：source_kind=='supplement' 且 matched_alias=='whole_table'（或无 key_column）时 key_column 允许为空、仅要求 source_id/检索依据；② output_validator 的 provenance 检查同步该语义；③ 回归测试：整表补充记录导出 consumable=true。

#### [medium/S（2-3 小时）] M5 [medium] 冲突标注动作丢失：annotations_to_add 写 typo 键 conflict_nnotations 且仅对新 source 挂载（subgraphs/data_normalization/agents/source_router_agent.py:86-95）

**依据**: 已确认 93 行写 `sources_to_process[source_id]["conflict_nnotations"]`（typo），executor（normalization_agent.py:183-190）只读 conflict_ctions；且 88 行 `if ... not in sources_to_process` 条件使已存在 source 的标注直接丢弃 → retain_range/retain_both 等标注类裁决永远不落地。

**实现**: ① 改为并入 executor 已支持的 `conflict_ctions`（annotate 分支 normalization_agent.py:109-115），或写正确的 `conflict_annotations` 并同步 executor 读取；② 去掉『仅新 source 挂载』条件——对已存在于 sources_to_process 的 source 追加标注到其列表；③ 与 typo 键清理（见 L4 统一扫）一并处理。

#### [medium/S（1-2 小时）] M6 [medium] P1 对 LLM 输出缺防御：selected 项缺 property_id 或非 list → KeyError/TypeError 整节点失败（astroquery_ai/property_standardization.py:588）

**依据**: 已确认 588 行 `[item['property_id'] for item in selected]` 无 isinstance 与键校验，一次 LLM 结构偏差即 P1 全失败 → 检索/提取失去 property_spec 白名单，质量管线 target_schema 为空，下游整体降级。

**实现**: 588 行改为：`if not isinstance(selected, list): selected = []`；`selected_ids = [item["property_id"] for item in selected if isinstance(item, dict) and item.get("property_id")]`；缺失项跳过并 logger.warning。

#### [medium/S（1-2 小时）] M7 [medium] 子图1 路由顺序缺陷：greeting/invalid 特例排在 final_confirm 捷径之后，寒暄永不响应（subgraphs/subgraph1/routes/routing.py:37-39）

**依据**: 已确认 37-39 行 `target_entity and properties_asked and query_type != "exit"` 先于 greeting/invalid 判断，用户回复『你好』被当确认流程，可能误确认错误查询。

**实现**: 将 query_type 非 astronomical 的判断（greeting/invalid）移到 final_confirm 捷径之前；final_confirm 特例仅当 query_type=='astronomical'（或空）时生效；exit 判断保持优先。注意 test_subgraph1.py 若覆盖问候流程需同步断言。

#### [medium/S（1-2 小时）] M8 [medium] VizieR 数值列统一 str(float(val)) 大整数精度丢失 + 数值字符串不稳定（subgraphs/subgraph2/utils/database_utils.py:173-175）

**依据**: 已确认 174 行 `str(float(val))`：超 2^53 整数变 '5.854013331201521e+18'，浮点写 '123.0' 式，与上游文本表示不一致，下游回查失真。

**实现**: np.integer → `str(int(val))`（保留精度）；np.floating → `format(val, 'g')` 或按原始列 format 截断（避免 e 记数法与尾零噪声）；补 test_subgraph2 大整数 fixture 断言。

#### [medium/S（1-2 小时）] M9 [medium] report_agent per_entity_modifications 恒 {} + normalization_tatus typo 契约（subgraphs/data_normalization/agents/report_agent.py:26 与 47-53；quality_pipeline/tools/export/metadata_generator.py:113）

**依据**: 已确认 report_agent 从从不存在的 `mods.get("modification_log")` 计算（真实统计在 normalization_agent.py:379 写入的 mods["per_entity_modifications"]）→ 顶层 per_entity 统计恒空；normalization_tatus（缺 s）为脆弱契约但拼写一致可用（B6 同根）。

**实现**: ① report_agent.py:47-53 改为读 `mods.get("per_entity_modifications", {})`（或把 normalization_agent 写出的键名与读取端统一）；② 修正 `normalization_tatus` → `normalization_status`：writer（report_agent.py:26）与 reader（metadata_generator.py:113）同步改，全仓 grep 确认仅这两处（已确认）。

#### [low/S（0.5 小时）] L1 [low] validation_agent 残留死代码：missing_prov 强制 page 恒计入但不再参与判定（subgraphs/data_normalization/agents/validation_agent.py:33）

**依据**: 已确认 B7 行为已修复，33 行计算为误导性残留（DB 记录无 page 恒计入 missing_prov，但不进 remaining/is_valid）。

**实现**: 删除 33 行附近死计算，或改用 source_utils.provenance_is_complete（DB/paper 分流，与 M4 复用同一函数）。

#### [low/S（0.5 小时）] L2 [low] bbox_annotator 失败任务进度双计数（subgraphs/subgraph3/nodes/bbox_annotator.py:107 与 124）

**依据**: 已确认 107 行正常分支 completed+=1、124 行 except 内再 +=1 → 失败任务双计数（仅影响进度显示）。

**实现**: 删除 124 行 except 内的重复自增。

#### [low/S（0.5 小时）] L3 [low] result_builder 把 VLM 提取的 None 值写成字符串 "None"（subgraphs/subgraph3/nodes/result_builder.py:187）

**依据**: 已确认 187 行 `str(field_value).strip()` 在 field_value=None 时产出 "None" 字符串进入 paper_records，污染下游数值解析。

**实现**: field_value 为 None/空串时跳过该记录或写显式空标记（与低置信度/坏 bbox 过滤同处处理）。

#### [low/S（半天，含文档）] L4 [low] typo 契约统一清扫：from_conflict_fter（routers.py:369/397/405）、normalization_tatus（M9 已列）、human_review_tems（resolution_report_agent.py:210 / human_review_agent.py:237 两处对称）、conflict_nnotations（M5）、assessment_ssues/normalization_odifications（export_generation_agent.py:112-113）

**依据**: 已确认各 typo 键多为『自洽但脆弱』或『写读对称』的契约（human_review_tems 被 human_review_agent.py:237 正常读取，改名须两端同步）。

**实现**: 最后一个 commit 统一清扫：每键 grep 全仓（含 quality_pipeline/ 与 subgraphs/）确认全部读写点后同步改名；from_conflict_fter 与 M9 一起做；同步更新 CLAUDE.md / 设计文档中已过时的 V1 路径描述（文档描述的是旧结构 V1\子图4部分代码，实际代码已迁移到 subgraphs/）。

#### [low/L（合计 1-1.5 天，分 2 个批次）] R1 [known/backlog] 已知问题清单处置：B1/B6/B8/B9 部分/E5/E10 部分仍存在，需排期

**依据**: 审查结论：B7、B13/E13 已修复可归档；B1（llm_completeness 异常路径 adjusted=1.0——LLM 越不可用完整度越高）、B6（= M9 同根）、B8（synthesis_agent 无条件 Success，= M3 同源）、B9 部分（adaptive_thresholds_astrophysics 死配置）、E5（n<2 时相对差冒充 Cohen's d 可达 2.0+、MAD=0 用 1e-10 假分母）、E10 部分（exit_keywords 子串匹配、ADS 查询串无转义）仍存在。

**实现**: 排期：B1 → 异常路径返回 0.9 或『未知』标记而非 1.0（低优先级，与 E5 一起做统计健壮性批次）；B6/B8 → 随 M9/M3 修复一并收敛；B9 → AdaptiveThresholdEngine 增加领域段加载路径（读 adaptive_thresholds_astrophysics），并入跨领域配置批次；E5 → n<2 时跳过 anomaly 判定（不产出假冲突）+ MAD=0 时改用 IQR 或标记 inconclusive；E10 → exit_keywords 改整词匹配 + ADS 查询串转义（并入 L5 子图2 批次）。

#### [low/M（1 天）] R2 [known/backlog] 子图2 已知风险排期：ADS PUB_PDF 兜底无 Authorization 必 401、retrieval_priority 权重恒 0（score=citation_count 未取）、PDF 并发 min(5,3) 压制、supplementary key_value 恒取 kept_rows[0]、数据库路 27 表×4 镜像×10s 最坏时延（pdf_download.py:304-308、paper_utils.py:121、supplementary_query.py:370-377、ads_search.py:148-154）

**依据**: 审查证实风险点 3/4/5/6/7 仍存在：论文下载兜底必败、排序失真、检索吞吐受限、溯源不精确、最坏时延超设计目标。不阻塞主质量管线正确性，属性能/功能完整性问题。

**实现**: 排期批次：link_gateway 带 Bearer token（优先级最高，改一行）；ADS fl 增 'score' 字段并修正权重计算；并发取各自上限（PDF 取 5）；supplementary key_value 按行记录实际匹配值；数据库路改并发或加超时预算。

### 预期影响

修复后：(1) 安全：LLM 生成代码（或经提示注入引导生成的代码）无法再逃逸沙箱执行任意系统命令——safe_builtins 收紧 + AST 黑名单扩展到别名/属性链，逃逸 PoC 全部被拒；(2) HITL：A→E/C→E 路由时人工审核真正可发生（checkpointer 注入 + 嵌套 interrupt 处理），质量报告不再因 GraphInterrupt 被吞而静默丢失；(3) 路由状态机：C→E→B 在 MAX_LOOP 内干净收敛（不再浪费轮次或强制导出），B→C 复检无冲突时直接 C→D，B⇄C 循环获得设计中的多轮能力；(4) 数据正确性：mag/dex 等常见单位不再产生假 critical 冲突，归一化修复成果不再被过期方差数据掩盖，unit_error 生成逻辑真正生效；(5) 管线健壮性：LLM 输出类型异常只降级到确定性兜底，不再整线跳过；(6) 导出真实性：quality_summary 风险指标、人工裁决落地、冲突标注、per-entity 统计、补充表可消费性全部修正；(7) 已知问题：B1/B6/B8/B9/E5/E10 排期收敛，B7/B13 归档。整体上质量管线从『演示可用』提升到『逻辑闭环、输出可信』。

### 风险

- 沙箱收紧可能误伤合法生成工具：exec 代码中的 `import re/math` 依赖 __builtins__ 中的 __import__，直接删除会破坏（修复用 _safe_import 包装器解决，需回归 dry-run 5 条样本路径与 test_quality_pipeline 生成工具用例）
- H1 是风险最高的改动：嵌套图 interrupt 的 resume 语义（共享 checkpointer + thread_id）需端到端验证，处理不当可能从『静默跳过』变为『挂起』；必须保留无 checkpointer 时的降级路径（config 缺省时沿用现状）
- M2 循环计数口径变化会改变路由行为：依赖『3 次即强制导出』的测试（test_quality_pipeline / test_full_loop_mock）可能断言旧行为，需同步更新；iteration_counter 仍是兜底，无限循环风险由 MAX_ITERATIONS 提升后的值封顶
- H4 单位维度修复会减少 unit_error 产出：若测试断言了 mag/dex 类字段的 unit_error（断言了 buggy 行为），需更新；同时确认 conflict 相关 fixture 预期
- M3/M9/L4 涉及跨包契约键改名（normalization_tatus、human_review_tems、conflict_nnotations、from_conflict_fter 等）：必须一次 grep 全仓（subgraphs/ + quality_pipeline/ + astroquery_ai/）同步两端，拆多个 commit 会造成读写键不一致
- M4 放宽整表补充记录 provenance 校验可能掩盖真实溯源缺失——只对 matched_alias='whole_table' 的 supplement 记录放宽，普通记录校验不变
- M7 调整子图1 路由顺序可能影响既有交互测试（test_subgraph1.py）与前端对话流预期，需同步回归
- E5/B1 统计修正（n<2 跳过 anomaly）会减少冲突检出量，与 H4 叠加后需整体回归统计冲突测试，避免过度放松导致漏报真实冲突

---

## 四、开源科研数据质量评价方案调研

### 框架/维度体系

| 框架 | 核心原则 | 来源 |
|------|---------|------|
| FAIR Guiding Principles (Findable/Interoperable/Accessible/Reusable) + FAIRsFAIR Data Object Assessment Metrics | 把 4 条原则操作化为 16-17 条可测指标（F:5, A:3, I:3, R:5），每条指标含多级成熟度测试（test→sub-principle→principle→总分%），聚合出 FAIR level（incomplete/initial/moderate/advanced）。F-UJI 实现：'每条 metric 的成熟度 = 其通过测试中的最大成熟度'；多研究指出各工具结果不可直接比较（指标实现/权重/覆盖不同：F-UJI 缺 A1.1/A1.2/I2，FAIR Evaluator 缺 R1.2/R1.3），评分权重透明性很重要。 | https://www.fairsfair.eu/f-uji-automated-fair-data-assessment-tool |
| FAIR Maturity Indicators (FAIR Metrics Group, Gen2) | 15 个社区驱动的成熟度指标，每个是可用 smartAPI YAML 描述的 Web API 测试：POST 元数据 GUID 返回 JSON-LD，score 为 SIO:000300 'has_value'（二进制 0/1 或 0-1 浮点）；通过 Pull Request 提交给 FAIRsharing 注册（in development → ready）。全部可自动化，采用'指标库+社区自定义指标'的插件化架构。 | https://github.com/FAIRMetrics/Metrics |
| FAIRshake rubric 评估体系 | 支持人工/半自动/全自动三种评估模式，用 rubric（评分规则集）+ metric 组合评估数字资源；rubric 可混合手工指标与自动工具（如在同一个 rubric 内调用 F-UJI）得到总 FAIR 分。可借鉴其'rubric=手工规则+自动测试混合打分'的模式到我们的 8 项检查清单。 | https://github.com/MaayanLab/fairshake-assessments |
| Wang & Strong 1996 数据质量四类 15 维框架 | 从数据消费者视角定义 DQ='fitness for use'，基于 118 个消费者属性经因子分析得 15 维：Intrinsic（accuracy/objectivity/believability/reputation）、Contextual（value-added/relevancy/timeliness/completeness/appropriate amount of data）、Representational（interpretability/ease of understanding/representational consistency/concise representation）、Accessibility（accessibility/access security）。启示：质量维度需区分为内在（值本身）与情境（任务相关）两类——跨来源数值冲突属 Contextual 维度，格式/单位属 Representational。 | https://web.mit.edu/tdqm/www/tdqmpub/beyondaccuracy_files/beyondaccuracy.html |
| DAMA 数据质量维度 + DQAF (Data Quality Assessment Framework) | DAMA-DMBOK 6 核心维度：Accuracy/Completeness/Consistency/Timeliness/Uniqueness/Validity。DQAF（McGilvray 2013）给出测量类型：Completeness=已填充记录/总数（如 294/300=98%），Timeliness=事件发生到入库存的时差（continuous 测量），Validity=符合格式/类型/范围定义；强调 in-line 测量三目标：保证/探测变化/改进机会，并须按数据关键性定测量优先级。 | https://www.sciencedirect.com/science/chapter/monograph/pii/B9780123970336000389 |
| Batini et al. 2009 数据质量评估方法论综述（13 种方法论） | 系统比较 13 种方法论（TDQM 的 Define-Measure-Analyze-Improve 四相循环；QAFD 的 5 相评估=变量选择/分析/客观测量/主观专家测量/比较，维度含句法/语义准确性、内外一致性、完整性、时效性、唯一性，把客观指标与专家主观判断结合；AIMQ/DWQ/IQM 等），比较维度=阶段/技术/维度/数据类型/系统类型。结论：多数方法论是'客观指标+主观专家意见'混合，且测量值随任务上下文变化。 | https://www.semanticscholar.org/paper/Methodologies-for-data-quality-assessment-and-Batini-Cappiello/1a8f5de43ab7b266b9edd921c8f181221dada881 |
| ISO 8000 数据质量标准族（ISO 8000-62/63/66） | ISO 8000-62:2018 DQMM 成熟度模型：6 级（Immature→Innovating），9 个过程属性，过程属性评级用四档百分比量表 N(0-15%)/P(>15-50%)/L(>50-85%)/F(>85-100%)；ISO 8000-63 过程测量栈结构=goal→sub-goal→question→indicator→metric（可直接用于把我们的 8 项检查形式化为可审计的测量栈）；ISO 8000-8 定义通用定量指标：Accuracy=判定正确字段数/测试字段数，Completeness=完整元素/总元素，Consistency=语义规则违规率。 | https://www.boutique.afnor.org/en-gb/standard/iso-8000622018/data-quality-part-62-data-quality-management-organizational-process-maturit/xs131000/128980 |

### 可落地算法

| 算法 | 方法 | 适用性 | 来源 |
|------|------|--------|------|
| F-UJI 层级聚合评分（per-test → sub-principle → principle → overall %） | 每个 practical test 算局部分；metric 成熟度=通过测试的最大成熟度；按 metric 名正则分组聚合到 F/A/I/R 四类；最终总分百分比+FAIR level 映射（incomplete/initial/moderate/advanced）。权重显式声明（F-UJI）vs 等权（FAIR Evaluator）会给出不同结果。 | 高——可直接借鉴到我们的聚合评分：8 项检查(test)→维度(completeness/consistency/...)→总分→路由，且'成熟度取最大'思路可用于 decision 的 severity 聚合（我们目前用 _ROUTE_SEVERITY 取最严重，与之一致）。 | https://github.com/pangaea-data-publisher/fuji |
| Bootstrap 百分位置信区间（PRIDIT pridit_boot / gsm.studykri） | 对观测重抽样 B 次（PRIDIT 默认 B=500，gsm.studykri 默认 1000 次、95% CI），每次重拟合完整评分管线（含权重估计），对每个权重和每个观测评分取经验分布百分位 CI；PCA 符号任意性需在聚合前做符号对齐（相关系数为负则翻转）；重抽样必须镜像原始抽样结构（gsm.studykri 按 site 重抽样）。 | 高——为我们的加权评分（S1 权重）和 per-source score 提供不确定性区间，直接支撑 S3 置信度校准；可用 scipy.stats.bootstrap 实现。 | https://rdrr.io/cran/pridit/man/pridit_boot.html |
| 加权通过率评分 + Bootstrap SE（QA Tools, RAND） | score = Σ(w_i × passed_i) / Σ(w_i × eligible_i)；用 bootstrap 直接估计所有聚合分的标准误（传统 SE 公式在'资格事件、通过指标、二者相关性'存在时难以计算）；replicates 必须使用与原始分析相同的抽样权重与计分方法。 | 高——与我们 S1 加权评分公式同构，补上'评分的置信区间'这一缺失输出；适用于 per-source 维度加权分。 | http://www.nejm.org/doi/suppl/10.1056/NEJMsa064637/suppl_file/nejm_mangione-smith_1515sa1.pdf |
| Truth Discovery 迭代加权投票（CRH / 2-Estimates / Gaussian Truth Model / UTD-JMLE） | 两阶段迭代：①估计每个 source 的可靠性权重；②按权重投票/加权推断真值。连续值：normalized squared loss → 最优真值=加权平均；normalized absolute deviation loss → 加权中位数（抗离群）。CRH 通过最小化'真值与观测的加权偏差'统一处理混合类型（分类用软投票、连续用加权均值），实验中 CRH 错误率最低（0.0700 vs 0.0726）。UTD 证明 JMLE 一致性并含多数算法为特例。CIMTD 用置信区间估计处理小来源/冷对象。 | 高——正是 Conflict 模块需要的：跨来源数值冲突裁决=reliability 加权合并（可替代/补充我们基于 Cohen's d 的裁决），加权中位数可作 conflict 时的 robust 估计；权重=我们已有的 source_reliability 评分。 | https://www.semanticscholar.org/paper/Conflicts-to-Harmony%3A-A-Framework-for-Resolving-in-Li-Li/5f905e2994b17d72f721da72a5a8035bdf47f70d |
| 稳健离群检测组合（IQR 1.5× / 修正 Z-score(MAD, |z|>3.5) / Grubbs / 多元 Mahalanobis、Isolation Forest、one-class SVM） | 单变量：1.5×IQR 规则、|z|>3 阈值、MAD 修正 z>3.5（稳健）、Grubbs 检验；多元：Mahalanobis 距离、PCA、EllipticEnvelope、Isolation Forest。比较研究：one-class SVM 在毛刺误差检测（gross error detection）中 Accuracy/F1/Overall Power 最优，IQR 选择性（selectivity）最好。注意 TU Delft 对比研究结论：通用离群处理对下游模型无显著提升（IQR clipping 甚至显著降低分类性能），'价值必须被证明而非假设'。 | 中——用于 OutlierDetector 的候选方法库扩充（one-class SVM 可作共识判定的第三方），但需按我们的数据验证而不是默认采用；离群本身≠质量差，需结合领域物理可行性。 | https://zbmath.org/1410.62213 |
| Gaussian perturbation 测量误差传播（Shy et al. 2022, Astronomy & Computing） | 从高斯测量误差模型的贝叶斯后验预测分布生成多组扰动伪数据集，对每组重拟合分类器，用集成拟合的变化量化分类/结论不确定性（heteroscedastic 误差可处理）。案例：11,847 个 quasar 候选在计入测量误差后 26.6% 可能是误分类。 | 中高——把逐条记录的测量不确定度传播进冲突/质量判定；可作为我们冲突证据里'统计证据'的误差敏感度分析（Sensitivity analysis），输出'考虑误差后结论是否改变'。 | https://ar5iv.labs.arxiv.org/html/2112.06831 |
| 分布自由不确定性量化：CQR（conformalized quantile regression）与 RCPS（risk-controlling prediction sets） | 用校准集给出有限样本覆盖保证（coverage guarantee），与数据分布假设无关、适用于任意'黑盒'预测器；小校准集下 RCPS 保守（区间过大），CQR 避免该问题（Leterme et al. 2025, A&A 弱透镜质量图）。 | 中——为质量分数/阈值边界提供有覆盖保证的区间；对'评分刚好卡在阈值附近'的路由决策给出是否可判定的依据。 | https://www.aanda.org/articles/aa/abs/2025/02/aa51756-24/aa51756-24.html |
| 过量弥散指标（excess variability）：用观测弥散 vs 形式不确定度验证误差标定（ICRF astrometry, ApJS 274, 28） | 对每个源组合平均位置偏移、统计弥散、平滑趋势，量化'未被解释的过量方差'；发现过量方差呈赤纬依赖（未建模电离层延迟+北半球网络几何）。本质=形式误差标定是否可信的检验。 | 中高——用于校验来源自报测量误差的可信度：若某来源记录的误差明显小于其观测弥散，则该来源的 reliability/conflict 判定应降权——这正是 SourceReliabilityAnalyzer 缺的一维证据。 | http://dc.g-vo.org/rr/q/pmh/pubreg.xml?verb=GetRecord&metadataPrefix=oai_b2find&identifier=ivo://CDS.VizieR/J/ApJS/274/28 |
| Deequ 指标公式集（Completeness/Uniqueness/Distinctness/Compliance/PatternMatch/ApproxQuantile） | Completeness=列中非空比例；Uniqueness=唯一值比例；Distinctness=去重后比例；UniqueValueRatio=唯一值/总行数；Compliance=满足谓词的行比例；PatternMatch=匹配正则比例；Column Profiler 三遍策略（通用统计→数值统计→低基数直方图，基数阈值 120）；MetricsRepository 存储历史指标做随时间异常检测（drift）。 | 高——指标定义可直接作为我们 completeness/uniqueness/format 维度的标准度量；'约束建议'（Constraint Suggestion）与'历史指标异常检测'可移植为 config 自动生成与跨批次对比。 | https://deepwiki.com/awslabs/deequ/3.2-built-in-analyzers |
| 分布一致性统计检验（GE distributional expectations：z-score / quantile / KL divergence / bootstrap KS / chi-square） | expect_column_value_z_scores_to_be_less_than(threshold, double_sided, mostly) 检验 |z|>t 的比例；expect_column_quantile_values_to_be_between 用分位数区间验证分布形状（如 Q25/Q50/Q75 各设 min/max）；KL divergence（连续数据离散化后）、bootstrap 版 KS 检验（连续，可调 specificity）、chi-square（分类）。 | 高——跨来源数值分布的 consistency 检验可直接用 bootstrap KS 检验两来源同字段分布是否同分布（替代我们目前仅基于均值的相对差异/Cohen's d 视角），分位数区间可用于目标 schema 的物理合理范围约束。 | https://www.statology.org/how-to-z-score-based-statistical-validation-great-expectations/ |
| 贝叶斯分层模型证据综合（bivariate hierarchical / crossnma / 三层 HRQoL 模型） | 联合建模估计值与其方差的相关性（bivariate hierarchical, AoAS 2023）；crossnma 用 risk-of-bias 变量（low/high/unclear）对治疗效应做加性/乘性偏倚调整；三层随机效应模型跨仪器借力（borrowing strength），对证据最少的仪器不确定度降 ~80%。 | 低中——实现成本高，但'借力+偏倚调整'框架可作为 Conflict 裁决的理论支撑（每源估计值带误差 + 源质量先验→分层合并）；对当前 pipeline 用加权平均+Bootstrap CI 即可近似。 | https://ar5iv.labs.arxiv.org/html/2109.07560 |

### 开源库适配度

| 库 | 用途 | 适配度 |
|----|------|--------|
| pandera | 轻量 Python 原生 schema 校验：类型注解/类式 API 定义 DataFrame schema + 可组合 Check（Check.and_/greater_than 等），schema.validate(df) 内联校验；支持 pandas/Polars/pyspark；与 pytest 集成。 | 高 — 可直接用其编码 target_schema 的字段级规则（类型/范围/单位格式），与我们的 data_state（DataFrame 内存态）天然契合、零配置低依赖；缺点是无评分/无报告体系，只做通过/失败，需自行包一层评分。适合做 Validation 阶段或 Normalization 的 schema 强制层。 |
| DataProfiler (Capital One) | 单遍 O(n) 提取 schema/统计/实体：global_stats（row_has_null_ratio、unique_row_ratio、duplicate_row_count、correlation/chi2 矩阵）+ data_stats（nulls、min/max/mean/方差/分位数/直方图/偏度/峰度、精度统计）；profile 可合并/更新，diff 报告含 t-test 与 PSI（漂移检测）；输出 pretty/compact/serializable/flat 四格式。 | 高 — 对应我们 Stage 1 Profiling 的 8 个工具（DistributionProfiler/FieldProfiler）可直接替换或对标验证；PSI+t-test 的 profile 对比天然支持跨来源比较（SourceProfiler 升级）；无质量评分（不评好坏），正合 profiling '只观测不评价' 的定位。 |
| Great Expectations | 声明式 expectation 套件（expect_column_values_to_be_between / z_score / quantile / kl_divergence / bootstrapped_ks_test 等），Checkpoint 批量执行，结果 JSON + HTML Data Docs，审计报告；支持 pandas/Spark/SQL 后端。 | 中 — 统计型 expectation 库与我们的检验清单重合度高（z-score 离群、分位数范围、KS 分布一致性），Data Docs 适合审计；但框架重（DataContext/Checkpoint/YAML 布局），期望套件需每数据集重写，不支持自适应阈值（我们 E1 的三维动态阈值）与加权评分；适合在 Export 阶段做最终交付物的独立验收（第三方视角），不适合做主评估管线。 |
| pydqc | 自动 DQ 检查：infer_schema（key/str/date/numeric 四类，Excel 交互修正）+ data_summary（每列 NaN 率/唯一数/min/mean/median/max/分布图，数值自动 log10）+ data_compare（双表同名列统计对比）+ data_consist（按 key 合并检查一致性）。 | 中 — data_compare/data_consist 的双表对比思路可直接移植为'来源间同字段统计对比'（一致性维度）；但项目年久未维护、无数值质量评分、无冲突检测，key 类型推断需人工。可作为参考实现而非依赖。 |
| Deequ / PyDeequ (Amazon) | Spark 上的 DQ 框架：内置 analyzer（Size/Completeness/Uniqueness/Distinctness/Compliance/PatternMatch/ApproxQuantile/KLLSketch）、VerificationSuite（Check+严重度 Error/Warning/Info）、Constraint Suggestion、MetricsRepository 历史指标异常检测、增量 stateful 计算。 | 低 — 强依赖 Spark 集群，对我们单机 DataFrame 规模的数据过重；但其概念模型（约束建议、严重度分级、指标随时间异常检测）值得在设计中借鉴，指标公式可直接抄（见 algorithms）。 |
| F-UJI | REST 式自动化 FAIR 数据对象评估服务（Python/Flask+Connexion，MIT）：16-17 条 FAIRsFAIR core metrics（YAML 定义），harvester+评估器架构，聚合 F/A/I/R 分；输入 PID/着陆页 URL，约 1 分钟，输出 JSON+FAIR level。 | 低（字段级数值质量）/ 中（Export 包级元数据 QA）— 不评估数值字段本身；但对 Export 阶段产出的数据集包做 FAIR 自动评分（元数据完整性/许可证/版本/标准对齐）可复用其指标定义与层级评分模式；社区版 fuji4software 支持 FAIR4RS。 |
| FAIRshake | rubric+metric 的 FAIR 评估平台（Cell Systems 2019），支持人工/半自动/全自动评估数字资源，rubric 可混合手工问题与自动测试（含 F-UJI）产出总评分，fairshake.cloud 在线 + fairshake-assessments 社区指标仓库。 | 低 — 面向资源级 FAIRness 而非字段级数值质量；其'rubric=规则集+自动化测试'的插件化模式可启发我们把 8 项检查做成可配置 rubric（对应 configs/quality_rules.yaml 的扩展），但无直接可复用代码。 |

### 天文领域特有实践

- SIMBAD 双轨质量体系：VizieR 保存发表目录原值（'catalogue of catalogues'，异源可能矛盾），SIMBAD 提供专家挑选的 best-estimate 值，每个参数旁标注来源+可靠性字母（a letter which is an estimate of its reliability），另有 otype 分类标志（如 star/cluster/young stellar object 等数百类）；两处不一致（如 theta UMa F7V vs F6IV）源于'原发表值 vs 专家更新值'，跨来源冲突裁决时应把 SIMBAD 视为高权重专家源。
- CDS/VizieR 发布前 DQ 清单：表含天体对象必须有未改动名称+坐标（无坐标表不进 SIMBAD）；所有列必须有解释+单位；列必须同质（不混不同测量/误差限值/不同单位）；多表共享对象必须同名标识；FITS 头必须有 WCS 坐标/波长/观测日期/望远镜仪器；工作流文档化以支撑 CoreTrustSeal 认证——单位同质化与坐标标准化正是我们 Normalization 的领域规则来源。
- 巡天光度质量标志体系（引用时必须逐条检查 flags）：SDSS 质量等级 A(最好)-E(最差)；2MASS ph_qual 序 A>B>C>D>E>F>U>X，通常只保留 'A'；AllWISE 序 A>B>C>U>Z>X；Gaia：phot_bp_rp_excess_factor 的颜色无关修正 C*（|C*|>3σ 剔除 BP/RP）、RUME<1.4（astrometric 解质量）、IPDFracMultiPeak>7%（混叠/伴星）、BP/RP blended transits>20%、phot_variable_flag、flags_gspspec、flags_esphs(1-5)；可组合成复合标志（如 'GaiaBlend'=计数失败准则数，85% 标准星通过全部准则）——我们的 per-record quality flag 聚合可照此模式。
- Cross-match 质量规范（CDS xMatch）：位置统一为 FK5 J2000（有自行时归算到 epoch 2000），位置误差统一为弧秒圆/椭圆（半短轴/半长轴/位置角）；已知局限：USNO-B1.0 自行误差未纳入、Gaia DR2/SDSS DR7 位置角列是北偏东需 (90−errPosAng) 修正；1 角秒搜索半径典型匹配精度 ~0.3 角秒，匹配半径与误差椭圆必须纳入冲突判定的置信度。
- 跨巡天合并的统计一致性检验：预测星等与实测星等须 3σ 内一致（误差膨胀 0.01 mag 后），不匹配率约超统计预期 5 倍（多为 astrometric offset/blend）；变源筛选=phot_g_mean_flux_error×√phot_g_n_obs 取 95 分位；光谱双星筛选=RV 噪声 p≤0.001——这些是'来源间数值冲突'的具体天文判据。
- 过量弥散校验（ICRF3 天体测量）：用观测弥散 vs 形式不确定度之比识别误差标定不可信的来源（赤纬依赖的过量方差来自电离层延迟+北半球网络几何）——校验来源自报误差可信度的标准方法，可并入来源可靠性评分。
- 不确定性必须在管线每步估计并传播（SIRTF/Spitzer 管线设计原则）：从原始数据到科学产品逐级传播不确定度，作为定量 QA（验证需求达标）与下游产品（点源提取/镶嵌）的前提——对应我们数据里每条记录的 measurement uncertainty 必须全程保留。
- 数据包质量标志实践：ATLAS refcat2（VizieR）全局零点 ~0.005 mag、逐星误差 0.015-0.030 mag，但官方明确'必须逐条检查各 flags'（z 波段从远程通带导出'有些不可靠'）——即使权威目录也要 per-entry flag 检查，支撑我们'来源可靠性≠逐条质量'的区分。

### 参考来源

- https://www.fairsfair.eu/f-uji-automated-fair-data-assessment-tool
- https://github.com/pangaea-data-publisher/fuji
- https://github.com/FAIR-IMPACT/fuji4software
- https://github.com/FAIRMetrics/Metrics
- https://github.com/MaayanLab/fairshake-assessments
- https://fairshake.cloud/project/166/assessments/
- https://zenodo.org/records/14185638
- https://zenodo.org/records/14775217
- https://web.mit.edu/tdqm/www/tdqmpub/beyondaccuracy_files/beyondaccuracy.html
- https://www.ibm.com/docs/en/cloud-paks/cp-data/5.0.x?topic=quality-data-dimensions
- https://www.sciencedirect.com/science/chapter/monograph/pii/B9780123970336000389
- https://www.semanticscholar.org/paper/Methodologies-for-data-quality-assessment-and-Batini-Cappiello/1a8f5de43ab7b266b9edd921c8f181221dada881
- https://www.boutique.afnor.org/en-gb/standard/iso-8000622018/data-quality-part-62-data-quality-management-organizational-process-maturit/xs131000/128980
- https://www.boutique.afnor.org/en-gb/standard/iso-8000632019/data-quality-part-63-data-quality-management-process-measurement/xs131968/129706
- https://github.com/capitalone/DataProfiler
- https://capitalone.github.io/DataProfiler/
- https://github.com/unionai-oss/pandera/discussions/598
- https://github.com/great-expectations/great_expectations
- https://greatexpectations.io/expectations/
- https://legacy.docs.greatexpectations.io/en/0.13.20/autoapi/great_expectations/expectations/core/expect_column_value_z_scores_to_be_less_than/
- https://www.statology.org/how-to-z-score-based-statistical-validation-great-expectations/
- https://github.com/SauceCat/pydqc
- https://github.com/awslabs/deequ
- https://deepwiki.com/awslabs/deequ/3.2-built-in-analyzers
- https://rdrr.io/cran/pridit/man/pridit_boot.html
- https://github.com/IMPALA-Consortium/gsm.studykri
- http://www.nejm.org/doi/suppl/10.1056/NEJMsa064637/suppl_file/nejm_mangione-smith_1515sa1.pdf
- https://www.semanticscholar.org/paper/Conflicts-to-Harmony%3A-A-Framework-for-Resolving-in-Li-Li/5f905e2994b17d72f721da72a5a8035bdf47f70d
- https://dl.acm.org/doi/abs/10.1109/TKDE.2022.3173911
- https://zbmath.org/1410.62213
- https://ieeexplore.ieee.org/abstract/document/11219011
- https://ar5iv.labs.arxiv.org/html/2112.06831
- https://www.aanda.org/articles/aa/abs/2025/02/aa51756-24/aa51756-24.html
- http://dc.g-vo.org/rr/q/pmh/pubreg.xml?verb=GetRecord&metadataPrefix=oai_b2find&identifier=ivo://CDS.VizieR/J/ApJS/274/28
- https://ui.adsabs.harvard.edu/abs/2003ASPC..295..181M/abstract
- https://cds.unistra.fr/help/documentation/xmatch/
- https://madys.readthedocs.io/en/latest/photometric_quality.html
- https://www.semanticscholar.org/paper/Quality-flags-for-GSP-Phot-Gaia-DR3-astrophysical-Avdeeva-Kovaleva/33e440924c63ac479308ef140c0e37d05990486f
- https://ar5iv.labs.arxiv.org/html/2109.07560
- https://pubmed.ncbi.nlm.nih.gov/31583600/
- https://archive.aavso.org/index.php/atlas-refcat2-vizier
