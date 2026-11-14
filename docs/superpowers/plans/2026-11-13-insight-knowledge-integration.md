# 新版洞察与任务知识快照实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 保留新版资料总结，恢复性质级综合洞察，展示可追溯知识依据，使科研追问共享准确任务知识快照。

**Architecture:** 新确认任务固定 `TaskKnowledgeContext/1`，新策略 `research-workbench/2` 在科学封存后分别生成两层报告，以 `InsightBundle/1` 统一收尾。历史单模式及导出保持兼容；资料详情和报告页展示当时依据。

**Tech Stack:** 现有 Python/FastAPI/SQLite 与 React/Vite，复用科学知识绑定、M11 生成校验、抽屉、主题变量及系统五色，无新依赖。

**Spec:** docs/superpowers/specs/2026-11-13-insight-knowledge-integration-design.md（用户已明确批准实施）。

## Global Constraints

- 不改科学规则、原报值、误差、来源、单位与转换许可；洞察不自行改采用状态或导出记录。
- 新策略仅用于新确认任务；旧任务固定策略、科学快照、报告和导出原字节可读，不自动升级或补写。
- 同一任务的正式知识、选中的用户/理论背景按准确版本与内容哈希固定；历史显示和追问不被当前库修改影响。
- 保持总预算、模型资格和许可，不用资料总结的 report-only 许可替代性质洞察正常资格。
- 模型失败、无匹配、知识不可读、条件未知、预算不足分别记录状态，保留已完成部分。
- 前端全部复用现有语义变量/配色及覆盖式抽屉；不硬编码独立色板。
- 复用已接受的普通隔离暂存工作流；保存源树与数据库恢复快照，回写逐文件哈希防覆盖。不提交、推送、重置或清理用户未提交内容。

## Shared Interfaces

- 新策略常量 `MODE='research-workbench/2'`；`task_knowledge.enabled(spec)` 与 bundle mode 同值。
- `science/task_knowledge.py`: `capture(app,spec)->dict`、`pin(app,conn,tid,spec)->reference`（设置 spec.knowledge_context_ref）、`load(repo,conn,tid,spec)->dict|None`、`blocks(context,property_id=None)->list`、`frozen_user_store(context)`、`frozen_theory_store(context)`；返回值必须独立副本，校验哈希，旧任务无 ref 返回 None 不创建快照。
- `TaskKnowledgeContext/1` 至少有 context_id/content_sha256、knowledge_release_ref、library_version、entries（兼容既有 knowledge_block，claim.claim_id/text、entry_id/title/sources/conditions/property_ids/origin）、properties（property_id/name/state/entry_ids/reason）。FrozenStore 提供现有 search/get_entry/to_knowledge_block/resolve_cached_block/get_preferred_ids；理论视图只返回有明确依据的已捕获关系，不做名称近似推断。
- `InsightBundle/1` 至少有 report_id/delivery_id/snapshot_ref/status、material_report（原 MaterialSummaryReport/1）、property_report（原 InsightReport/4）、knowledge_context_ref、components 两部分状态。完成报告与上下文引用单独保存，最终报告可包含轻量子报告正文以兼容现有读取。
- 新 bundle 生成函数支持子生成器只返回报告、保存自身检查点，不 finish_job、finish_insights 或改主交付修订；父任务在两部分结束后统一完成一次。
- 新 `knowledge_context` 交付资源返回 `{delivery_id,delivery_revision,snapshot_ref,context,origin}`；对历史任务按已保存报告/summary.basis 聚合只读依据，标记 origin=historical_saved_basis，不写入或现时检索替代。沿用准确修订/at_seq/sealed/replay 边界。
- insights 新模式返回兼容现有分页 envelope，item 为 Bundle；旧模式保持原 schema。科研追问读取相同 context，当前补充知识不混为任务依据。

## Review Focus

- 两个子任务任意先结束、部分失败、取消恢复时，不提前封存、发布两次、重复调用或使对方因修订变更失效。
- 用户知识更新/隐藏/删除和默认发布变化之后，新模式已固定任务的总结、解释、追问保持相同依据。
- 历史资源及回放不能越过可见时点或捕获边界；GET 不产生模型调用或权威对象。
- 大批量测量完整覆盖、条件分组明确；综合洞察的发现不会自动修改科学采用状态和导出。
- 无知识/条件未知、资格不足、磁盘/模型失败、预算用尽有真实状态，不显示成功或补造依据。

## Tasks

### Task 1 任务知识快照及科研追问

Files: 新增 science/task_knowledge.py；修改 query/drafts.py、agent_harness/data_loader.py、controller.py、tools.py；新增 tests/rebuild/test_task_knowledge_context.py。

- [ ] 先编写并观察失败：确认时固定正式及相关用户背景，修改当前库后 load/blocks/追问仍相同；无 ref 历史不写入；哈希损坏拒绝；无关与不相容知识不选中。
- [ ] 实现共享接口；仅捕获与确认性质相符的条目/正式绑定，版本化内容与适用状态一起固定。FrozenStore 不回读当前用户库，返回副本。
- [ ] 在查询确认、spec_hash 生成前 pin；Bundle 的 property_report/cards 与 context 接入 TaskDataBundle 和 DomainTools。
- [ ] 运行目标测试、既有追问和知识相关回归，输出报告和准确接口说明；独立审查修复后冻结。

### Task 2 两层生成与发布屏障

Files: 新增 science/insight_bundle.py；修改 runtime/run_policy.py、science/workflow/insight_service.py、material_summaries.py、property_insight_generation.py、property_insights.py、results/publication.py；必要修改 task_score/exporting/format validation 的新 schema 适配；新增 tests/rebuild/test_insight_bundle.py。

- [ ] 先失败测试：两个完成顺序、任一失败、重复运行/恢复、预算/许可缺失、跨修订拒绝，旧两模式不变。
- [ ] 新策略采用两层生成；资料知识来自 Task1 快照，性质解释的 claims 与 theory/user store 使用同一快照。复用分批覆盖和引用校验，不自动执行排除测量的 owner_rechecks。
- [ ] 两个生成器增加兼容默认参数 `publish=True`；新模式 publish=False，仅返回并保存自身结果。父任务统一 finish_job/finish_insights，全部结束前主交付修订不变。
- [ ] 扩展 final publication 为新 Bundle，科学内容和原导出值/顺序不变；子报告失败保留另一部分。新评分区分两部分状态且不把仅有背景当已生成洞察。
- [ ] 运行旧 property/material/publication/export 与新目标测试，独立审查后冻结。

### Task 3 前端统一阅读及知识依据

Files: 修改 frontend/components/results/DataView.jsx、MaterialWorkbench.jsx、RuntimeInsights/PropertyInsightCards（必要时）；新增 TaskInsights.jsx/TaskKnowledgeBasis.jsx 及主题变量样式、对应 Node/挂载测试；修改 services/api.js 支持新资源；必要扩展现有知识详情抽屉的归档只读呈现。

- [ ] 写失败测试或挂载 harness：Bundle 三分区、旧模式可读、资料背景入口、依据点击/测量定位、无匹配和失败状态、主题变量/历史只读。
- [ ] “总结与洞察”默认资料总结，增加性质洞察和知识依据；复用现有性质卡片，按需加载。历史 material 报告显示未生成性质卡片，并显示真实已保存背景。
- [ ] 资料详情展现原文依据与输入知识背景，以现有覆盖抽屉打开；当时版本与当前库跳转分开，不补造逐句引用。仅绘制显式依据关系。
- [ ] Node 全量、生产构建、真实挂载交互验证通过，独立审查后冻结。

### Task 4 API 与整体集成验证

Files: application/insight_views.py（新增）、api/routes/results.py、必要 agent 读取适配；集成测试和验证报告。Root 负责。

- [ ] 新 knowledge_context 资源准确版本/历史边界与只读聚合测试 RED→GREEN；Bundle 分区读取与前端合同一致；避免历史读时动态理论替代封存依据。
- [ ] 合并三任务接口，测试真实最新样例已有67条总结与知识背景可展示、旧六份卡片不变；新策略用隔离数据和受控模型回执验证完整生成、幂等与导出，不默认消费真实付费模型。
- [ ] 新演示能力提供基于真实样例准确快照的可审查验证；如发布新演示需真实模型运行则先完成构建与校验工件，再按已授权范围维护发布，不把测试输出标成真实科学结论。
- [ ] 独立最终评审、前端全量/构建、后端离线全量与7份样例科学/导出指纹对照；验证失败和历史兼容。
- [ ] 按源文件哈希回写并重启前后端，保留 HMR；检查权威数据/用户知识未被测试改写，保存 UI 验证与最终报告。
