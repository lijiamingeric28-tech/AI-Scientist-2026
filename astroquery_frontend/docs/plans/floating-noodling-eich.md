# 前端修复计划（P0 已交付 + P1/P2 样式统一）

## Context

真实任务验收暴露 5 类问题（表格 0/非实时/下钻缺失/对齐/样式不统一）。P0（数据正确性）已完成交付。P1/P2（样式统一）经 4 轮 AskUserQuestion 逐项确认用户偏好后实施。

## ✅ 第一批 P0（已完成）

- P0-1 后端完成时序根治（task_completed 落库后发）+ 测试更新
- P0-2 前端时序兜底（App 轮询 / DetailPanel taskDone 重拉 / ResultTabs status 重拉 / 洞察 hydrate 重试）
- P0-3 记录表格对齐（stage-indent）
- P0-4 agent.reason 透传（后端 workflow_history 提取 + 前端透传）
- P0-5 log 归属改进（lastStage/recentAgent 两级回退）
- P0-6 质量 Tab 补渲染（评估摘要/决策矩阵/条件路由/多源方差/冲突标注）+ 轨迹字段级明细 + L3 空态文案
- 追加修复：SourcesList `s.type`→`s.source_type`；StageCard `stage.flow`→`stage.flows`；AgentTree 明细增强

## ✅ 设计决策（4 轮选项卡确认）

| 主题 | 决策 |
|---|---|
| 步骤连接线 | **全部圆点不连线**（去卡 1/3 竖线） |
| 节点形态 | 纯圆点（状态色），统一尺寸 7px |
| Agent 明细交互 | **统一侧抽屉下钻**（对话卡点 Agent → 右侧滑出 StageDetailPanel L3） |
| 卡片本体 | 保留"标题头+展开内容"结构 · 对齐工作流 token（状态色边框/胶囊徽标/hover 阴影/统一圆角） |
| 流转轮次 | 时间线行（圆点 + FLOW_LABELS 名 + 第 N 轮 + 状态 pill） |
| 主区布局 | 保留现状（38px 缩进） |
| 日志 | 胶囊化结构化行（级别胶囊 INFO蓝/DEBUG灰/WARN黄/ERROR红 + 节点浅色胶囊 + 常规字体换行） |
| RA/Dec | 时角/度分秒制：`RA 05:55:10.29 · Dec +07:24:25.4` |
| 大文本/JSON | 结构化+Markdown（JSON→键值对；pre-wrap→Markdown；超长折叠+展开） |
| 右侧面板 | 对齐 token 不动结构 |
| 数值格式化 | 只格式化展示数值（分数/耗时/坐标）；ID/来源编号 mono 原样 |
| 动画/空态 | 沿用工作流基元（pulse-dot/tab-in/fade-in）+ empty-state 统一 |

## 📋 第二批 P1/P2 实施清单

### P1-1 步骤表达统一（去连线）
- `StageCard.jsx` Substeps：删除竖线（只留圆点列）
- 卡 2 GroupSteps 已无竖线，保持；StatusDot 统一 7px

### P1-2 Agent 侧抽屉下钻
- `StageCard.jsx` AgentTree：`<details>` 折叠 → 可点击行（onClick 回调）
- `StageCard.jsx` 加 `onOpenAgent(stage, agent)` prop；`ChatView.jsx` 管理抽屉状态（stage+agentKey）→ 渲染 `StageDetailPanel`
- `StageDetailPanel.jsx` 加 `initialAgentKey` prop（进入即 L3）

### P1-3 卡片本体 token 对齐
- `StageCard.jsx` 容器：状态色边框（running/error 已有）、圆角 `var(--radius-lg)`、hover 阴影（.card 风格）、卡头状态胶囊化

### P1-4 流转轮次时间线行
- `StageCard.jsx` FlowNodes：box 列表 → 圆点 + 名称 + 第 N 轮 + 状态 pill 行

### P1-5 日志胶囊化
- 新建 `frontend/src/components/log/LogLine.jsx`（时间 + 级别胶囊 + 节点胶囊 + 正文换行）
- `LogDrawer.jsx` 日志区 + `StageDetailPanel.jsx` LogBox 共用

### P1-6 数值/坐标格式化
- 新建 `frontend/src/lib/format.js`：`fmtRaDec(ra, dec)`、`fmtNum`、`fmtPair`
- `StageCard.jsx` UnderstandOutput 坐标行用 fmtRaDec；Traces 用 fmtPair

### P1-7 大文本/JSON 结构化
- `DetailPanel.jsx` JSON.stringify → 键值对列表
- `ClarificationCard.jsx` pre-wrap → 分段段落 + 引用块
- `StageCard.jsx` overall_narrative → Markdown
- `markdown.jsx` 加 components 样式覆盖（标题/列表/表格/code/引用/链接，走 CSS 变量）

### P1-8 DetailPanel token 对齐
- KPI 卡圆角/阴影、Tab 胶囊化、row-item 统一（小幅）

### P1-9 动画/空态
- 检查各处空态统一 empty-state；沿用现有动画基元

## 关键文件

`frontend/src/components/chat/StageCard.jsx`、`frontend/src/components/chat/ChatView.jsx`、`frontend/src/components/chat/ClarificationCard.jsx`、`frontend/src/components/workflow/StageDetailPanel.jsx`、`frontend/src/components/log/LogDrawer.jsx`、`frontend/src/components/layout/DetailPanel.jsx`、`frontend/src/components/results/RecordDetail.jsx`、`frontend/src/lib/markdown.jsx`、`frontend/src/lib/format.js`（新建）、`frontend/src/components/log/LogLine.jsx`（新建）

## 验证

1. `npm run build`
2. 历史任务回看：对话卡步骤无竖线、Agent 点击弹抽屉、流转轮次时间线行、日志胶囊化、RA/Dec 格式化
3. 回放模式跑一次验证新任务（agent.reason 可见）
