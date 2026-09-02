# Normalization Layer 3（LLM 动态生成工具）优化方案

> 2026-08-10 ｜ 根因双 agent 验证 + 离线实验复现 + 开源沙箱调研 + 独立安全验证（V1）
> 目标：Layer 3 有效成功率 **~29% → ≥85%**，让任何流到第三层的数据都能被处理。

## 1. 执行摘要

**现状**：`subgraphs/data_normalization` 的 ToolPlanningAgent 三层方案中，Layer 3（LLM 动态编写 Python 变换函数，沙箱执行）经常执行失败。离线实验（17 个真实 LLM 风格代码片段过真实生产管线）实测漏斗：

```
AST 白名单通过 82% → dry-run 通过 41% → 执行接受 41%（其中 2/7 静默 no-op）
→ 真实有效率 ~29%
```

**结论**：失败不是单点 bug，而是 **"自由 Python 生成"模式的系统性问题** —— 8 个根因中 6 个（dry-run/执行不对称、AST 误杀、正则消毒、builtins 过窄、confidence 静默丢弃、缩进缺陷）是换任何执行容器都不会消失的流程缺陷；只有把"LLM 写自由代码"改为"LLM 输出结构化操作规格"才能在源头消除。

**方案（三明治架构）**：
- **层 A（主默认路径，新增）**：模板驱动变换 —— LLM 输出结构化 ops 规格（`{op, field, params}`），确定性审计执行器 `op_executor.py` 运行。消除 8 根因中 7 个，成功率可达确定性 95%+（文献：Anka 多步变换 100% vs 自由 Python 60%）
- **层 B（核心防御纵深，保留并加固）**：in-process AST 白名单 + 受限 exec 沙箱，承载自由 Python fallback（复杂条件逻辑场景），按 8 根因逐项修复
- **层 C（P4 可选，feature-flagged）**：multiprocessing + Windows Job Object 硬杀超时进程（修复现状 daemon 线程超时后死循环仍占 CPU 的缺陷）

**实施前置（V1 独立验证发现，必修）**：现役沙箱存在 **operator.attrgetter 字符串 dunder 路径的完整任意代码执行漏洞**（实测已通过 Popen 类对象生成子进程）——既是既有基线漏洞，也必须在实施前将 operator 移出模块白名单并补 PoC 测试。

## 2. 根因与证据（8 条，file:line 锚点经 V1 逐行复核）

| # | 根因 | 代码锚点 | 失败模式 |
|---|------|---------|---------|
| 1 | **dry-run/执行不对称**（headline） | dry-run 校验 planning_agent.py:626-647（无键集合检查）；执行端 M-19 normalization_agent.py:610-615（有）；itertools/statistics 仅 dry-run 注入 planning_agent.py:608-613 vs _make_sandbox normalization_agent.py:231-236；执行数据已被 L1/L2 改造（schema_mapping.py:43 加 `_raw_field`、field_value→float） | 工具 dry-run 通过 → 注册 → 执行必败（NameError/键集合变）；"注册后执行必败"静默路径 |
| 2 | **AST 白名单误杀** | normalization_agent.py:28-46 无 NamedExpr/Match/TryStar；686-691 while 无 break 一刀切拒；681-684 Name 黑名单不限 ctx（Store 撞名也拒） | walrus/match/有界 while/黑名单撞名变量 —— 合法代码被拒 |
| 3 | **正则消毒破坏代码** | planning_agent.py:537-540 整行删除 import/return/def/class | 嵌套 helper def 被删 → NameError；`import numpy` 被删 → np NameError |
| 4 | **builtins 过窄** | normalization_agent.py:219-230 仅 34 键（实测） | reversed/next/type/repr/hasattr/callable/format/frozenset/bytes/complex + 异常类全 NameError |
| 5 | **Prompt 无 schema** | planning_agent.py:488-520 只送 3 条截断样本（剔除 provenance） | LLM 猜错键名 → 注册成功但静默 no-op（实验 2/7） |
| 6 | **confidence 静默丢弃** | planning_agent.py:653 `get("confidence", 0.5)`；normalization_agent.py:340-347 硬编码 0.7 | LLM 漏填 → 默认 0.5 → 执行端静默跳过（成本已付、工具无效、无重试） |
| 7 | **无反馈闭环** | validation_agent.py:61-65 排除 gen_errors 重试、75-82 判 Success；planning_agent.py:246-253 仅 logger.warning；metadata_generator.py:118 只导出 len(errors) | 失败不可见、不重试、不进导出；用户看到"规范化完成"实则未修复 |
| 8 | **缩进归一化缺陷** | planning_agent.py:541-556 min_indent≥8 → indent_delta 为负 → 行保留 8 空格注入函数体 | IndentationError；tab 混用同样崩 |

**实验数据**（17 片段过真实管线，双 agent 交叉验证）：AST 拒 3 类（无界 while/辅助函数被删/无界 for）、dry-run 拒 6 类（记录数变/超时/类型错/NameError/日志爆）、执行拒 1 类（键集合变）、静默 no-op 2 例（猜错字段/幻觉字段守卫）。

## 3. 开源沙箱方案对比（7 方案 × 8 轴）与决策

| 方案 | 安全模型 | 资源控制 | Win11 | 搭建成本 | 启动延迟 | 适配 | 结论 |
|------|---------|---------|-------|---------|---------|------|------|
| **① RestrictedPython** (Zope) | 字节码级受限编译；CVE 史：2023-37271/2023-41039/2024-47532/**2025-22153 (CVSS 7.9)** 逃逸 | 无，需外层超时 | ✅ | 低（pip） | <10ms | partial | 视审计要求可选；≥8.0 且承担 CVE 跟踪；手写白名单修复后无必要 |
| **② sandboxed-python** (seccomp/Finite Python) | seccomp 仅 Linux；PyPI 实际包 = Finite Python（禁循环、需 Py3.12） | 仅迭代限制 | ❌ | 中-高 | 慢数倍 | no | **拒绝**：平台+语言特性双重不兼容 |
| **③ 子进程 + Job Object** | 进程级隔离、崩溃隔离、真终止 | **强**：JobMemoryLimit/CPU 速率/Kill-on-close（ctypes 零依赖） | ✅ | 低（~150 行） | spawn 100-300ms（常驻池可 1-10ms） | partial | **推荐为可选加固层（层 C）**：修复线程超时无法真终止缺陷 |
| **④ Docker** (WSL2) | 最强（VM 内 namespace/cgroup） | 强 | ✅但重依赖 | 高（Docker Desktop） | 冷启动 2.7-8s+ **撞 8s 约束** | no | **拒绝**：延迟与依赖超约束 |
| **⑤ WASM (Pyodide)** | 强（无 syscall 面） | 无内置配额 | ✅ | 中高（Node/wasmtime） | 300ms-4.5s + 慢 3-5 倍 | no | **拒绝**：无增益叠加新运行时 |
| **⑥ 商业** (OpenAI CI/E2B/Modal) | 最强（microVM/gVisor） | 平台托管 | ✅客户端 | 云账号+付费 | 200-500ms RTT | no | **拒绝**：违反"离线、数据不出机器"硬约束；仅作基准 |
| **⑦ 约束 DSL/模板驱动** | **本质最优**：不执行 LLM 自由代码，无逃逸面 | 确定性 bounded | ✅ | 中（200-400 行零依赖） | 亚毫秒 | **fit** | **推荐为主默认路径（层 A）**：源头消除 7/8 根因 |

**决策**：① 主路径 = ⑦ DSL（Anka 证据 +40pp；本项目 Layer 2 adapted tools 已是现成迷你 DSL）；② 核心纵深 = 加固版 in-process AST+exec（层 B，C1 审计要求保留）；③ 可选 = ③ Job Object（层 C）。拒绝 ②④⑤⑥ 理由如上。

## 4. LLM 代码生成可靠性最佳实践（9 条，映射本库）

| # | 实践 | 关键证据 | 映射 |
|---|------|---------|------|
| 1 | **Schema-in-prompt**（注入字段 schema/类型/约束替代原始样本） | Anka：约束化语法多步变换 60%→100%；read-frog #1019 | planning_agent `_llm_generate_tool`：新增 `_build_schema_block`（见 §6.d） |
| 2 | **生成代码自检**（LLM 输出 before/after 断言，程序化验证） | IEEE TSE 2024：纯 introspection 不可靠，可执行断言有效 | 契约必填 `self_check`；`_verify_self_check` dry-run+执行双端 |
| 3 | **结构化修复循环**（错误 kind+行号+消息回喂，≤2 轮） | 文献：零样本 30-40% → 修复循环 70-96%；收益集中前 2-3 轮 | `_llm_generate_tool` 外包循环 + retry_context（见 §6.g） |
| 4 | **Few-shot 示例**（3-5 条领域内精选） | PERC/CodeExemplar-Free：选取策略优于数量，+5.7pp | `tool_examples.yaml` 15+ 条 + issue 关键词匹配选取 |
| 5 | **严格输出契约**（JSON Schema 必填，缺字段=失败≠默认值） | AWS Bedrock/OpenAI Structured Outputs 实践 | Pydantic `ToolGenResponse`（tool_name/tool_code/**confidence 必填**/self_check） |
| 6 | **锚定式代码块提取**（marker 分割/fence 剥离/平衡括号扫描） | n8n PR #23726、llm-repair | 替换 planning_agent.py:526 裸正则 `\{.*\}` |
| 7 | **模板补全 vs 自由生成**（fill-in-the-blank 优于全量生成） | ICML 2026：占位完成编辑成本降 19-50% | 保留 `_TOOL_CODE_TEMPLATE`；废除行正则消毒、修复缩进 |
| 8 | **评估装置**（golden corpus + pass@1 + 有效成功率） | HumanEval/BigCode 范式 | `tests/test_layer3_golden.py` + 三层漏斗指标 |
| 9 | **DSL/模板驱动变换**（结构化 op 规格） | Anka +40pp、Query4Regex +6.74pp；自由 Python 三大系统性失败（变量遮蔽 42%/操作排序 31%/链式困惑 27%） | `op_executor.py` + ops 优先路径（层 A） |

## 5. 推荐架构（三明治：层 A 主路径 / 层 B 纵深 / 层 C 可选）

```
                     ┌─ Layer 3 规划 (planning_agent._llm_generate_tool)
                     │   输入: unresolved issues + field profile + target_schema
                     ▼
              LLM 输出 (strict JSON 契约 / schema-in-prompt / temperature=0)
                     │
        ┌────────────┴───────────── 分流点 (规格能否表达当前问题?)
        │ ops 可表达 (默认主路径)            │ 规格表达不了 (复杂条件/多字段联动)
        ▼                                    ▼
┌───────────────────────┐        ┌──────────────────────────────────────┐
│ 层 A 模板驱动 (op_executor) │        │ 层 B 自由 Python fallback (防御纵深)   │
│ 1. Pydantic 校验 ops       │        │ 1. 模板注入 (_TOOL_CODE_TEMPLATE)      │
│ 2. 确定性纯函数逐 op 执行    │        │ 2. AST 白名单 (补 NamedExpr/Match/      │
│ 3. 无沙箱/无逃逸面/无死循环面  │        │    TryStar; Name 黑名单仅 Load)        │
└───────────┬───────────┘        │ 3. 受限 exec (builtins ~55 名 + 异常类      │
            │                    │    + _ALLOWED_MODULES 自动注入, operator 除外)│
            │   per-source 执行单元 (深拷贝副本) │
            │   8s 硬超时 ◄── 层 C (P4 可选): spawn 子进程 + Job Object 硬杀 │
            ▼                                   ▼
     ┌─────────────────────────────────────────────────────┐
     │ 统一不变量门 (两路共用): 记录数不变 | 键集合不变 | log ≤ 上限 │
     │  + self_check 断言验证 (捕获静默 no-op)                  │
     └───────────────────────┬─────────────────────────────┘
                             │ 通过 → 采纳 + modifications 入账
                             │ 失败 → 结构化失败 {kind, line, message, code}
                             ▼
             结构化修复循环 (≤2 轮, 每 source 独立计时)
                             │ 预算耗尽
                             ▼
             回退 Base Tools + errors 入库 → 转人工审核 (confidence<0.7)
```

**层 A 执行器 op 枚举**（op_executor.py，全部复用 `_parse_utils`/`unit_converter`）：`strip_prefix / numeric_convert / trim / unit_normalize / drop_suffix / replace_substring / mark_missing_unit`（可扩展 to_number/regex_extract/enum_map/missing_fill/date_parse/numeric_round/numeric_clip），每 op 自带记录数/键集合不变校验，LLM 输出 `{ops: [...], confidence}`（Pydantic OpSpecResponse 校验）。ops 路径 confidence 不设 <0.7 门槛（确定性执行器无低置信风险）。

## 6. 优化方案（逐根因修复规格，V1 验证后修正版）

### (a) AST 白名单修复（normalization_agent.py:28-46/652-712）
- 补节点：`NamedExpr`（walrus）、`Match` 系（MatchValue/MatchSingleton/MatchSequence/MatchMapping/MatchClass/MatchStar/MatchAs/MatchOr）、`TryStar`（**hasattr 守卫**——ast.TryStar 仅 3.11+，3.10 直接写入会 import 期 AttributeError）
- **while 三档判定** `_check_while_bounded`：(i) 常量假条件放行；(ii) 有界计数器（Compare+单一 Constant+同名字段 AugAssign 方向匹配）放行；(iii) 否则拒绝 + **带行号与条件摘要的具体错误消息**供修复循环；8s 超时作运行时兜底
- **Name 黑名单仅 Load 上下文**（Store 撞名放行；`_imp = __import__` 的 Load 检查保留）
- **type 放行**（dunder 属性块 696-699 已挡 type.__subclasses__/__mro__；3-arg type 动态建类无逃逸链——方法体只见沙箱 namespace）
- 错误结构化：`{allowed, kind: "ast_blocked", line, message}`

### (b) builtins/模块扩充（normalization_agent.py:219-236/49-52）
- safe builtins 追加：`reversed next iter type repr format issubclass callable id hash frozenset bytes bytearray complex divmod pow ord chr` + 异常类 `StopIteration RuntimeError ZeroDivisionError OverflowError ArithmeticError LookupError`
- **`_ALLOWED_MODULES` 单一常量自动生成 globals**（`_MODULE_GLOBALS = {name: __import__(name) for name in sorted(_ALLOWED_MODULES)}`）——AST 检查 / `_safe_import` / globals 注入三处零漂移；planning dry-run 手写沙箱整体删除改用 `_make_sandbox()`
- **`operator` 移出白名单**（V1 实测：`operator.attrgetter("__class__.__bases__")` 字符串 dunder 路径实现完整任意代码执行——见 §9 风险）；**`logging` 移出**（FileHandler 可写任意文件，违反无 IO 声明）；numpy 不入（C 扩展属性面大）
- 每个新增模块静态审计表写入 sandbox_common.py docstring

### (c) dry-run/执行对称化（SSOT）
- 新建 `quality_pipeline/sandbox/sandbox_common.py`：收纳 `_ALLOWED_AST_NODES/_ALLOWED_MODULES/_FORBIDDEN_FUNCTIONS/_SANDBOX_TIMEOUT_SEC/_SANDBOX_MAX_LOG_ENTRIES/_safe_import/_make_sandbox/_validate_code_ast/_validate_generated_result/_check_while_bounded/_detect_noop`；normalization_agent 保留 re-export 兼容既有 import 路径（tests/test_sandbox_security.py 不破）
- **共享不变量门** `_validate_generated_result(records_before, result, max_logs)`：invalid_format / record_count_changed / key_set_changed / log_too_large 四类 kind，dry-run 与执行共用同一门
- **dry-run 输入 = L1/L2 处理后的样本形态**（用 NormalizationAgent 按 plan 的 base+adapted 顺序处理 3 条样本后再 dry-run）——执行端真实输入

### (d) Schema 感知 Prompt（S3 全文模板见附录 A）
- `_build_schema_block`：字段 key/推断类型/缺失率/样例值/单位范围/是否 schema 必需/standard_unit/criticality/aliases 合并 JSON（替代 3 条截断样本作为主要信息源）
- **记录形态契约**明文声明：执行时键集合（含 `_raw_field`、provenance 只读）、field_value 已数值化、空串单位=缺单位
- 3-5 条 golden few-shot（`quality_pipeline/configs/tool_examples.yaml`，按 issue 关键词匹配选取）
- 执行端硬性校验清单明示（记录数/键集合/log/self_check/no-op/confidence）
- **契约块**：`tool_name/tool_code/confidence(必填 0-1)/self_check{assertions, sample_predictions}/reasoning`；`assert` 字段名用 `assert_` + `Field(alias='assert')`（**V1 修正**：Python keyword 不可作字段名）

### (e) 后处理管线修复（planning_agent.py:526-556）
- **锚定 JSON 提取**（替换 526 裸正则）：fence 剥离 → `first_brace` 平衡扫描/`raw_decode` → 尾随文本自然丢弃；失败返回 kind=parse_error
- **marker 分割**：LLM_GENERATED_LOGIC_START/END 之间取逻辑（容忍侧，与 prompt 契约共用同一分割函数）
- **AST 手术替代行正则**：`expandtabs(4)` → `ast.parse` → 仅删模块级 `ast.Return`（嵌套 FunctionDef 的 return 保留）→ `ast.unparse`（自动 4 空格归一）；不再做任何 import 删除（非白名单 import 由 _validate_code_ast 统一拒绝）
- 缩进降级路径 `textwrap.dedent`（消除负 delta）

### (f) Confidence 契约（S3）
- 缺失/非数值/越界 → Pydantic 校验失败 → **kind=confidence_invalid 进修复轮**（删除 653 行默认 0.5）
- 共享常量 `_CONFIDENCE_EXEC_THRESHOLD = 0.7`（planning/exec 同源，identity 测试防漂移）
- **effective_confidence = llm_confidence × (self_check 通过 ? 1.0 : 0.3)**；exec 只消费 effective
- M-16 契约保持：合法但 <0.7 → 注册但执行跳过 + kind=low_confidence 转人工审核；**low_confidence 不可重试**（V1 修正：与 g3 的 kind 表统一）
- prompt 明示"confidence 是自评信号不是考试分数，不要因修复调高"

### (g) 反馈闭环（V1 修正后）
- 结构化错误对象 `{source_id, tool, kind, error, line?}`；kind 枚举 16 种（9 核心 + parse_error/confidence_invalid/self_check_failed/self_check_invalid/log_too_large/invalid_format/unsupported_assert）
- planning 侧失败写新键 `norm["layer3"] = {"attempts": [...], "repair_left": {sid}, "succeeded": {sid}}`（**不能写 modifications.errors**——normalization.run 同轮会用全新 mods dict 覆盖）；跨轮 prev_failures = mods.errors ∪ layer3.attempts
- **修复循环 ≤2 轮**（每 source 最多 3 次 LLM）：可修复 kind 重试；noop/键集合/记录数/log 类重试一次即止；修复段携带上一版完整 code + 按 kind 修复指引表
- **validation 三态重试门**：gen_errors 含可修复 kind 且 repair_left>0 且 retry_count<2 → status=Retry；预算耗尽 → 现状 Success+note
- **错误导出细化**：metadata_generator `errors_count` + `errors: [{source, tool, kind, error}][:50]`

### (h) no-op 检测
- `_detect_noop(records_before, result)`：深度相等判定（NaN 特判/None≡缺失/数值跨型）
- dry-run：先 **unverifiable 预检**（样本无目标问题 → 放行防误拒）；非 unverifiable 且 noop → kind=noop 拒
- 执行端：全量 0 修改 → kind=noop（无 unverifiable 概念——目标问题必存在否则不会规划 Layer 3）→ 重试一次即止或回退
- log 空但数据变 → 采纳 + kind=missing_log 非阻断错误（数据已改但缺审计轨迹需人工可见）

### (i) 测试套件（§8 详述）

## 7. 分阶段实施路线图

| 阶段 | 内容 | 依赖 | 验收锚点 |
|------|------|------|---------|
| **P0**（1-2 天） | (b) builtins 扩充 + `_ALLOWED_MODULES` 自动注入 + **operator/logging 移出**； (c) sandbox_common SSOT 落地 + 共享不变量门 + dry-run 用 L1/L2 后形态； (e) 锚定提取 + marker 分割 + AST 手术 + 缩进修复 | 无 | 现有 271 测试全绿 + operator 逃逸 PoC 拦截 + 沙箱同一性测试 |
| **P1**（2-3 天） | (a) AST 节点补全 + while 三档 + Name Load 限定 + type 放行（**同步更新 2 处既有测试**）； (f) confidence 契约； (d) schema prompt + few-shot | P0 | corpus 漏斗指标（dry-run/exec 通过率） |
| **P2**（1-2 天） | (g) 反馈闭环 + 修复循环 + validation 门 + errors 导出； (h) no-op 检测双端 | P1 | 集成测试 + 有效成功率 ≥85%（pass@3） |
| **P3**（持续） | 层 A：op_executor + ops 优先路径（纯增量、零安全面） | 独立 | ops 路径确定性 95%+；两路配比按 t4 实测 |
| **P4**（可选 ~1 周） | 层 C：multiprocessing spawn worker + psutil 轮询 + Job Object（ctypes 零依赖，feature-flagged 默认关） | 独立 | 死循环 8s 内被杀且管线恢复；未启用时 pytest.skip |

**实施顺序依赖**：P0 先行（b→c→e）→ P1（a→f→d）→ P2（g→h）→ 测试随步增量。

## 8. 测试套件

**新增**：`tests/test_layer3_golden.py`（corpus + 指标装置）、`tests/test_layer3_sandbox_fix.py`（单元）、`tests/test_layer3_integration.py`（mock LLM 端到端）；扩展 `tests/test_sandbox_security.py`。全部离线。

- **Golden corpus**：17 实验片段（按期望 stage_expected 归档）+ ≥12 回归片段：walrus/match/try-except*（3.10 期望 syntax_error 路径）/有界 while/无界 while（拒+行号消息）/tab 缩进/8 空格缩进/嵌套 helper+顶层 return/itertools 使用/黑名单撞名 Store（放行）/dunder（拒）/`__import__` 别名（拒）/缺 confidence/no-op/键集合变/记录数变/log 爆/运行时死循环（slow 组）
- **单元**：AST 接受/拒绝矩阵（含结构化 kind/line）、while 三档、沙箱名字可用性（逐名）、两处沙箱同一性、`_validate_generated_result` 11 kind 矩阵、`_detect_noop` 深度比较、缩进边界、**operator/logging 逃逸 PoC 拦截**
- **集成**（mock LLM）：成功路径数据真被修改（杜绝静默 no-op）；no-op 不注册 + errors kind=noop；错误逐条进 export；修复循环（第 1 次错第 2 次对 → attempts 2 条）；预算耗尽回退；validation Retry 门
- **指标装置**：三层漏斗 + **有效成功率**（通过且真实修改数据且 log 非空）+ pass@1/pass@3；断言全 corpus 有效成功率 ≥85%（阈值参数化）

**既有测试同步（V1 验证，必修）**：
1. `tests/test_audit_fixes_pipeline.py:112` 的"无 break while 必拒"断言 → 翻转为"有界 while 放行"（111 行 while True:pass 与 114-115 行有 break 用例保留）
2. `tests/test_sandbox_security.py::test_runtime_type_removed` → 替换为 `type_subclasses_after_allow`/`type_mro` PoC（a4 type 放行后原断言必失败）

## 9. 风险与回滚

### 9.1 现役沙箱安全漏洞（V1 实测复现，实施前必修）
- **漏洞**：`import operator; b=operator.attrgetter("__class__.__bases__")(())[0]; ...` 字符串 dunder 路径绕过现有三层检查（AST dunder 检查/Name 黑名单/Call 黑名单），实现 `object.__subclasses__()` → `subprocess.Popen` → **任意代码执行**。当前即存在（C1 基线漏洞），实测已生成子进程回读 stdout
- **修复**：operator（及 methodcaller/itemgetter）移出 `_ALLOWED_MODULES`；`_ESCAPE_POCS` 增补 attrgetter PoC；logging 同步移出（FileHandler 文件 IO）
- **威胁模型说明**：本项目威胁源是 LLM 偶然生成代码（非对抗性），但该路径是"偶然可被触发"级别（LLM 输出含 attrgetter 的概率低但非零），且修复成本极低（一行移出白名单）

### 9.2 逐阶段回滚
- 每阶段独立可回退（P0 纯增量；P1 白名单放宽可整体还原；P2 反馈闭环可拆解）；P4 在 feature flag 后
- 白名单/builtins 扩充携带 **C1 复审计清单**：10 条 _ESCAPE_POCS 全拦截 + 新增 6 PoC + 13 模块静态审计表 + 三层冗余矩阵复核 + 271 测试基线

### 9.3 成本与约束
- 修复循环预算封顶：每 source ≤3 次 LLM 调用（1+2）+ graph Retry ≤2 次 = 有限终止
- prompt 增长有界：schema 紧凑 + 3 样本 + 3-5 few-shot（约 +2-3k token/调用）
- Windows 11 兼容：方案全为纯 Python/标准库/ctypes；无 seccomp/Docker/WASM 依赖
- 全量改动保持 271 测试离线全绿基线

## 10. 附录

### A. 新版 Prompt 模板关键段（S3 设计，实施时全文落盘）
- System：模板结构明示 + 可用环境清单（模块/builtins/异常类/helper）+ 8 条硬性约束（记录数不变/键集合不变/禁 import-return/禁危险调用/while 有界/逐条 log/_summary/4 空格缩进）+ 修改范式（`_safe_get` 读、`new_val != val` 才写回才 log）+ 数据驱动规则 + 输出契约
- User：source_id + 待解决问题 + 【字段 Schema】JSON + 【记录形态契约】 + 3 条分层样本 + 【Golden 示例】 + 【执行端硬性校验清单】 + 【输出格式】JSON 契约（含 self_check 断言类型枚举与 sample_predictions before 一致性要求）
- 修复轮段：失败对象渲染（kind/line/message/上一版 code）+ 按 kind 修复指引表 + "confidence 保持真实自评不因修复调整" + "样本已达标可输出空 tool_code 不视为失败"
- ops 路径段：op 目录 + 规则 + "无法表达时输出自由代码路径"

### B. V1 独立验证清单（11 项）
- ✅ 8 根因锚点全复核（仅 metadata_generator 115→118 行 3 行偏移）
- ✅ S1/S2/S3 放宽项（type/while 三档/walrus/Match/Name Store）实弹验证无新逃逸面
- ❌→修正 operator 逃逸路径（§9.1）
- ❌→修正 2 处既有测试冲突（§8）
- ⚠️→修正 S3 Pydantic `assert` 字段名 → `assert_`+alias；⚠️→修正 low_confidence 重试矛盾（统一不可重试）；⚠️→修正 t1-18 示例（静态三档判定应为 ast_blocked 而非 exec_timeout）
- ✅ confidence 契约与 M-16 不冲突；✅ e3 AST 手术可达性实测确认

### C. 实验数据（17 片段漏斗）
```
AST 通过 14/17 (82%) → dry-run 通过 7/17 (41%) → 执行接受 7/17 (41%)
其中 2/7 静默 no-op（猜错字段名/幻觉字段守卫）→ 真实有效率 5/17 (~29%)
```

### D. 关键引用
- Anka: ar5iv.labs.arxiv.org/html/2512.23214（DSL +40pp）
- RestrictedPython CVE: CVE-2023-37271 / 2023-41039 / 2024-47532 / 2025-22153
- IEEE TSE 2024 "Fight Fire With Fire"（自检不可靠，可执行断言有效）
- Structured Feedback / self-debugging / ExeCRE（修复循环）
- ICML 2026 "From Guessing to Placeholding"（模板补全）
- EvalPlus / BigCode Evaluation Harness（评估范式）
- docker/for-win#14304（WSL2 冷启动延迟）、psutil issue #1149（Windows 仅监控不可设限）
