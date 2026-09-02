# AstroQuery AI — 前端对接说明（Web 层全览）

> 本文档面向接手本项目的人：完整介绍 Web 前端的设计、架构、数据流与对接协议。
> 项目本体是 LangGraph 天文数据检索流水线（CLI 已跑通），本层将其 Web 化：
> **FastAPI 后端（`web/`）+ React 18 前端（`frontend/`）+ SSE 事件流 + HITL 澄清**。
> 配套文档：`docs/WEB_DESIGN.md`（UI 设计定案）、`docs/API_CONTRACT.md`（API 契约 10 轮定稿）、
> `docs/WEB_AUDIT_REPORT.md`（Web 层全面审计报告，60 条问题全部修复，逐条记录于 `docs/FIX_LOG.md`）。

---

## 1. 技术栈与架构总览

| 层 | 技术 | 位置 |
|---|---|---|
| 前端 | React 18 + Vite 6 + Tailwind（纯 CSS-in-JS 样式，无组件库） | `frontend/` |
| 后端 | Python 3.10+ / FastAPI + sse-starlette + LangGraph + sqlite | `web/`、`astroquery_ai/` |
| 通信 | **SSE 单向事件流（12+ 种事件）+ HTTP REST（重数据）**，无 WebSocket | — |
| 状态 | 前端本地 reducer（`usePipeline`），无 Redux/Zustand；服务端 sqlite 持久化 | — |
| 持久化 | `web/data/tasks.db`（任务 + 事件表，seq 自增）+ checkpoints.sqlite（LangGraph） | `web/data/`（已 gitignore） |

```
浏览器 (5173 dev / 8000 单进程 prod)
  │  POST /api/tasks {query, pdf_ids}
  │  GET  /api/tasks/{id}/events  ← SSE 事件流（12+ 种事件，seq 单调递增）
  │  POST /api/tasks/{id}/resume  {answer}   ← HITL 澄清回答
  ▼
FastAPI (web/main.py) ── executor 后台线程（并发=1 排队）
  └─ LangGraph 主图（astroquery_ai/main_graph.py）
       └─ 9 个子图节点 ── 埋点 emit（events.py）──► EventBus ──► sqlite + SSE 队列
```

**核心设计原则**：
- **轻量状态走 SSE、重度数据走 HTTP**：进度/事件实时推，records/sources/figures/exports 等数据一次性拉取
- **前端拼字段**：后端事件 `data` 只带原始数字，中文文案由前端 `usePipeline.js` 的 `formatStepDetail` 拼接（不要把 `data` 对象直接塞进渲染，会崩溃）
- **快照 + 续播**：打开任务先 `GET /state` 拿事件快照恢复历史，再开 SSE 从 `lastSeq` 续播（断线重连不重复）

---

## 2. 目录结构（前端相关）

```
frontend/
├── src/
│   ├── App.jsx                    # 三栏布局 + 任务列表（无限滚动/筛选/重试）
│   ├── services/api.js            # 全部端点封装 + SSE（EventSource + 断线重建）
│   ├── hooks/
│   │   └── usePipeline.js         # ★ 前端核心：SSE 事件消费 → stage reducer（含 log→stage/agent 归属）
│   ├── lib/
│   │   ├── stages.js              # 阶段定义/初始结构/澄清快捷按钮（真实数据源）
│   │   ├── markdown.jsx           # react-markdown 封装（AI 消息渲染）
│   │   └── utils.js               # cn() class 合并
│   ├── mock/pipeline.js           # 仅 useMockPipeline（演示钩子）引用，真实流程不依赖
│   ├── components/
│   │   ├── chat/                  # ChatView（时间线+输入区）、StageCard（7 卡）、ClarificationCard
│   │   ├── workflow/              # WorkflowView（KPI+时间线）、StageDetailPanel（阶段/Agent 三级下钻）
│   │   ├── results/               # ResultTabs（主区记录表格）、RecordDetail（单记录血缘弹窗）、OutputFiles
│   │   ├── layout/                # Sidebar（任务列表）、DetailPanel（右侧详情 8 Tab）
│   │   ├── log/                   # LogDrawer（实时日志，500 条上限 + 渲染 200 行截断）
│   │   ├── settings/              # SettingsDialog（配置页，GET/PUT /api/config）
│   │   └── ui/                    # button/scroll-area/toast（Radix + cva）
│   └── styles.css                 # 毛玻璃设计系统：seed token + glass-bg + 过渡动画
├── vite.config.js                 # proxy（/api /static → :8000）+ preview 同配 + VITE_BASE
└── package.json                   # dev/build/preview（无 test/lint，验证靠 build）
```

---

## 3. 三栏布局（WEB_DESIGN 块 1）

```
┌─ 侧边栏 240px（可折叠）─┬─ 主区 ──────────────────────┬─ 右侧详情面板（可折叠/拖拽调宽）─┐
│ 新建提取任务             │ 工具栏：任务标题+状态徽标      │ 概览 / 质量 / 运行 / 来源        │
│ 任务列表（无限滚动）      │   + 对话/工作流 视图切换       │ / 图证 / 轨迹 / 洞察 / 下载      │
│ 状态筛选 全部/运行中/…   │   + 取消任务（运行中可见）     │ （DetailPanel 按 [task_id,       │
│ 底部设置入口             │ 视图 A 对话时间线：           │  status] 重拉，8 Tab）           │
│                         │   AI 消息 · 7 阶段卡片 · 澄清卡 │                                │
│                         │ 视图 B 工作流：KPI 带+执行时间线 │                                │
│                         │ 输入区（自然语言+PDF 上传）     │                                │
└─────────────────────────┴───────────────────────────────┴────────────────────────────────┘
```

- 侧边栏任务条目：标题 + 相对时间 + 状态圆点（queued=灰"排队中"、running=蓝呼吸、completed=绿、error=红、cancelled=灰）
- 点"新建提取任务"清空主区（含 SSE 关闭与右侧面板重置）
- **主区视图切换**（`view` 状态）：`chat` 对话视图（默认）与 `workflow` 工作流视图共享同一份 `pipeline` 实时状态，切换带淡入过渡（见 §11A）
- **取消任务**：选中任务处于 queued/running/pending 时工具栏显示"取消任务"按钮 → `POST /api/tasks/{id}/cancel`

---

## 4. 数据流（提交查询 → 7 卡渲染）

```
用户输入 → ChatView.handleSubmit
  → usePipeline.submitQuery(query, files)
      ├─ api.uploadFiles(files)   POST /api/upload → {pdf_ids, rejected}
      ├─ api.createTask(query)    POST /api/tasks → {task_id}
      └─ openTask(task_id)
          ├─ api.getState()       GET /state → 快照事件全部 applyEvent（replay 模式）
          └─ api.openEventStream(afterSeq=lastSeq)   SSE 实时续播
事件到达 → usePipeline.applyEvent(ev)   ← 唯一 reducer 入口（seq 幂等去重 + taskId 归属校验）
  ├─ stage_started/completed   → 卡片状态 + 时间线弹卡（同步维护 activeStagesRef 运行集合）
  ├─ step_progress             → locateStep 定位子步骤 + formatStepDetail 拼中文
  ├─ agent_started/completed   → agent 动态追加（流式）+ 同步维护 activeAgentsRef 运行窗口
  ├─ flow_started/completed    → 卡 5 动态流转节点（规范化/冲突消解 × 轮次）
  ├─ clarification             → 挂起澄清卡（按 cl_type 渲染 + 快捷按钮）
  ├─ message / log / error     → 消息时间线 / 日志抽屉（500 截断）/ 错误行
  │                              log 另按运行窗口归属：stage.logs（200 截断）
  │                              + agent.logs（300 截断，工作流下钻"执行日志"）
  └─ task_completed/cancelled/failed/title_ready → 终态收尾 + 列表标题更新
渲染 → ChatView 时间线交错渲染：消息 + 7 卡 + 澄清卡 → 任务完成挂载 ResultTabs（记录表）
```

---

## 5. 7 阶段卡片设计（WEB_DESIGN 块 3-6）

| 卡 | 名称 | 内容 | 事件驱动 |
|---|---|---|---|
| 1 | 任务理解 | 垂直子步骤时间线：查询确认 → simbad 查询 → 研究方向确定；完成态展示目标天体/SIMBAD/标准性质（快照 state → `buildUnderstandOutput`） | `step_progress`(understand/*) + 快照 |
| 2 | 数据检索 | 三路分组：数据库（匹配/提取/总结）、论文（构建/检索/下载）、补充材料（查找/总结，含"正在验证表 X" substatus） | `step_progress`(retrieval/*) |
| 3 | 数据提取 | 四步线性：论文提取 → 字段验证定位（bbox，失败原因列表）→ 图片提取 → 总结 | `step_progress`(extraction/*) |
| 4 | 质量检查 | agent 列表动态追加（Profiling/QualityAssessment/QualityScoring…）+ 轨迹展开 | `agent_started/completed` |
| 5 | 数据清洗 | 规范化/冲突消解 agent + 流转轮次分组（flow 事件）+ 人工审核 HITL 卡 | `agent_*` + `flow_*` + `clarification` |
| 6 | 数据交付 | 导出/洞察 agent + 完成态 | `agent_*` + `flow_*` |
| 7 | 任务完成 | LLM 总结（后端生成，卡 7 唯一走 LLM 的文案）+ 结果区入口 | `message`(ai) + `task_completed` |

**弹卡规则**：understand/retrieval/extraction/quality_check 有 `stage_started` 事件触发弹卡；**clean/deliver/done 无 stage_started**（契约设计），由首个 agent 事件 / `stage_completed` 自动弹卡（`usePipeline` 已实现，勿删）。

---

## 6. SSE 事件协议（13 种，seq 全局单调递增）

| 事件 | payload 要点 | 消费端 |
|---|---|---|
| `task_queued` / `task_started` | `{task_id}` | 前端无分支（静默） |
| `stage_started` / `stage_completed` | `{stage_id, name}` / `{stage_id, duration, status?}` | 卡片状态机（skipped 态支持） |
| `step_progress` | `{stage_id, step, progress{completed,total}, data}` | 子步骤/分组步骤补丁；`data` 只带数字，前端拼文案 |
| `agent_started` / `agent_completed` | `{stage_id, agent, duration, traces?}` | 卡 4-6 agent 列表（流式追加，traces 累积） |
| `flow_started` / `flow_completed` | `{stage_id, flow_id, round, name}` | 卡 5 流转轮次分组（M-13 已实现） |
| `clarification` | `{stage_id, cl_type, title, fields, question}` | HITL 澄清卡（重放不重弹） |
| `message` | `{role, content}` | 对话时间线（AI 消息 Markdown 渲染） |
| `error` | `{level: warn\|fatal, node, message}` | fatal→任务失败+红字；warn→卡片错误行累积 |
| `log` | `{node, level, message}` | 日志抽屉（500 条截断）+ 按运行窗口归属 stage.logs / agent.logs（工作流下钻执行日志）。**后端无独立 tool_call 事件**——检查器评分/LLM/httpx 工具调用明细全部在节点级 log 里 |
| `task_completed` / `task_cancelled` / `task_failed` | `{summary?}` / `{reason?}` / `{error}` | 终态收尾（清理挂起澄清、输入栏恢复） |
| `task_title_ready` | `{task_id, title}` | 列表标题异步更新（按 task_id 归属） |

**关键机制**：
- **seq 幂等去重**：快照重放与 SSE 续播可能交叠，`applyEvent` 按 `ev.seq <= lastSeqRef` 丢弃重复
- **log 归属同步窗口**：运行中的阶段/Agent 由 `activeStagesRef` / `activeAgentsRef` 在 `applyEvent` 内**同步**维护——`stagesRef` 是 useEffect 镜像，快照重放（同步 forEach）期间滞后，依赖它会导致历史任务日志全部归属失败
- **断线续播**（D1-4）：EventSource onerror → close → 按 `lastSeqRef` 重建流（重连不重复）
- **任务终态后关流**（M-06）：收到终态事件立即关闭 SSE（流不再有新事件）
- **重放不重弹澄清**：快照重放的 clarification 不置 pending（挂起状态由 `snap.pending_clarification` 精确恢复）

---

## 7. HTTP API 对接表（全部封装于 `frontend/src/services/api.js`）

| 方法/路径 | 用途 | 前端函数 |
|---|---|---|
| POST `/api/upload` | PDF 上传（两步流程第 1 步，返回 `{pdf_ids, rejected}`） | `uploadFiles` |
| POST `/api/tasks` | 建任务 `{query, pdf_ids}` → `{task_id, status: queued}` | `createTask` |
| GET `/api/tasks?limit&offset&status` | 任务列表（强制分页，D8-4） | `listTasks` |
| GET `/api/tasks/{id}/state` | 快照：task + state + events + pending_clarification | `getState` |
| POST `/api/tasks/{id}/resume` | HITL 回答（非挂起期 409） | `resumeTask` |
| POST `/api/tasks/{id}/cancel` | 取消（终态/非中断态语义已修复） | `cancelTask` |
| POST `/api/tasks/{id}/retry` | 同 query 重建（新 task_id） | `retryTask` |
| POST `/api/tasks/{id}/replay` | 事件级重放（2026-08-27）：body `{speed=10, answer_timeout_sec?}` → 回放任务 `{task_id, replay_of}` | `replayTask` |
| GET `/api/tasks/{id}/records` `sources` `figures` `quality` `exports` | 重度数据（右侧面板 Tab + 主区记录表） | `getRecords` 等 |
| GET `/api/tasks/{id}/events?after_seq=N` | SSE 流（也可 HTTP 拉事件数组） | `openEventStream` |
| POST `/api/tasks/{id}/open-output` `open-file` | 本地打开输出目录/文件（D9-3） | `openFile` |
| GET/PUT `/api/config` | 配置状态（只回是否配置）/ 写回 .env（需 `X-Requested-With: AstroQuery` 头） | `getConfig`/`putConfig` |
| GET `/static/figures/{task_id}/{fname}` | 图证静态路由（挂载收窄到 output/figures/） | 直接 <img> |

---

## 8. HITL 澄清机制

```
节点 interrupt → web_runner 发 clarification 事件（结构化 {cl_type,title,fields,question}）
  → 前端弹澄清卡（对话流内嵌，可回溯多轮）
  → 用户回答（快捷按钮 / 自由输入）
  → POST /resume {answer} → Command(resume=answer) 恢复流水线
```

- 5 类澄清点：ask_properties（选性质）、final_confirm（y/m/n 确认）、human_review 系列（人工审核 1-5）
- 快捷按钮前端按 `cl_type` 生成（`CLARIFICATION_QUICK_BUTTONS`）；human_review 按后端 options 渲染
- 15 分钟无回答自动取消（后端超时 → task_cancelled → 前端清挂起 + 输入栏恢复 + 卡片灰态）
- resume 失败（409）前端保留卡可重试（H-18 修复）

---

## 9. 关键设计决策速查（改代码前必读）

1. **前端拼字段**：`step_progress.data` 只带数字 → `formatStepDetail` 拼中文；禁止把 `data` 对象直接渲染
2. **任务标识**：全链路统一 `task.task_id`（后端 D8-4 键名），无 `id` 兼容键
3. **状态词表**：后端终态为 `error`（executor 写 error，兼容旧 failed）；前端 `status.jsx` 双词表
4. **agent 事件流式**：卡 4-6 无预置 agent 列表，全部靠事件动态追加（勿恢复 mock 预置）
5. **clean/deliver/done 无 stage_started**：靠 agent/completed 事件弹卡（勿删 usePipeline 的补弹逻辑）
6. **DetailPanel 重拉**：依赖 `[task?.task_id, task?.status]`（任务完成时刷新），勿改回只依赖 id
7. **快照 output 接线**：`openTask` 从 `snap.state` 构建卡 1 完成态（`buildUnderstandOutput`，snake→camel）
8. **SSE 关闭时机**：终态事件 + 组件卸载 + 任务切换（三处都关，防泄漏）
9. **导出目录**：`output/{task_id[:8]}/`（run_id 绑定任务，M-18）；静态挂载仅 `output/figures/`（H-05/H-06）
10. **配置写回**：`PUT /api/config` 必须带 `X-Requested-With: AstroQuery` 头（CORS 白名单 + 校验头防跨源投毒）
11. **log 归属用同步窗口**：`activeStagesRef`/`activeAgentsRef` 在 `applyEvent` 内同步维护，勿改回读 `stagesRef`（快照重放期间滞后，历史任务日志会全部归属失败）；日志按 agent_started→completed 窗口挂到 `agent.logs`
12. **工具调用明细 = 节点级 log**：后端没有独立 `tool_call` 事件类型；检查器评分/LLM/httpx 调用明细全部在 `log` 事件里，工作流下钻 L3"执行日志"是唯一呈现入口（勿再写"后端未上报工具明细"类文案）
13. **记录详情走 /state 血缘**：`RecordDetailDialog` 的来源/处理轨迹/冲突/Insight 全部来自 `quality_report`（`per_record_trace` / `provenance` / `resolution_report.annotations` / `field_insights` / `per_source_routes`），首次点开行时懒加载 `getQuality`+`getSources` 并缓存，勿随表格预拉
14. **视觉走 seed token**：新样式禁止硬编码颜色——从 `--seed-bg/fg/primary/accent/surface/radius` 经 `color-mix()` 派生（深色模式只覆写 seed）；动效统一 `cubic-bezier(0.16,1,0.3,1)` 并尊重 `prefers-reduced-motion`

---

## 10. 运行与构建

```bash
# 后端（回放模式，零 LLM 费用；必须 python -c 代码内注入环境变量）
cd E:/work/frontend/astroquery_final
python -c "import os; os.environ['LLM_CASSETTE']=r'E:/work/frontend/astroquery_final/tests/cassettes/m13_query.yaml'; os.environ['LLM_RECORD_MODE']='once'; import uvicorn; uvicorn.run('web.main:app', host='127.0.0.1', port=8000)"

# 后端（真实模式，会花 LLM 钱）
python -m uvicorn web.main:app --port 8000

# 前端（开发，proxy 到 :8000）
cd frontend && npm run dev          # :5173

# 单进程生产交付（M-20）：构建后由后端直接挂载 dist
cd frontend && npm run build        # 生成 dist/
python -m uvicorn web.main:app --port 8000   # GET / 直接返回前端页面

# 测试（全 mock 离线）
python -m pytest tests/             # addopts 已排除 network，380+ 测试
```

**配置**（前端设置页 → PUT /api/config 写回 `.env`）：DashScope（质量管线必需）、OPENAI 兼容、ADS token。

**依赖**：`pip install -e .`（pyproject 已声明全部运行时依赖，含 Web 栈；vcrpy 在 dev extra）。

---

## 11. 已知限制与注意事项

- **回放模式数据正确性受限**：VCR 只按 URL/body 匹配，错位风险已被 H-11（smart_body matcher）+ H-12（并发串行化）大幅降低，但数据正确性最终验收建议真实模式跑一次并重新录制 cassette（`tests/test_e2e_recorded.py -m network`）
- **前端无自动化测试基建**（无 test/lint 脚本）：验证靠 `npm run build` + 回放端到端；`tests/test_web_offline.py` 覆盖后端契约（70+ 测试）
- **并发限制**：执行器并发=1，新任务排队 queued
- **日志量大**：单任务 400+ log 事件（日志抽屉 500 条截断 + 渲染 200 行截断；阶段日志保留最近 200 条、单 Agent 执行日志保留最近 300 条）

---

## 11B. 事件级重放（2026-08-27，演示回放机制，前端零解析改动）

**背景**：演示需要"完整重演一次真实查询全过程（时间压缩）"。VCR cassette 重跑
（LLM_CASSETTE）本质是"重新生成"行为——VLM 宽松匹配 + 顺序消费导致级联错位，
已废弃用于演示（旧 VCR 路径保留不动，回归测试仍覆盖）。

**原理**：真实运行的每个 SSE 事件已完整落库（events 表）。演示 = 新建"回放任务"，
后端把源任务已落库事件按压缩节奏**重新 emit 一遍**——走既有 EventBus/SSE 通道，
行为逐事件一致（就是真实事件本身），零错位可能。

### 数据流

```
侧边栏已完成任务悬停 → 点"重放" → POST /api/tasks/{src}/replay {speed: 10}
  → 创建回放任务（replay_of=src、title="重放 · …"、state_json={replay_meta}）→ 排队执行
  → executor 按 replay_of 分流 → web/replayer.run_replay：
      读源 events → 逐事件 emit（跳过生命周期/澄清回答/源 message）
      节奏 = max(源 ts 间隔 / speed, 20ms)（2026-08-27：上限取消，长停顿真实等比；
      下限 20ms 防连发 log 段 SSE 洪泛丢事件）；老任务 ts=NULL → 类型默认
      （log/step_progress 40ms，其余 150ms）；澄清事件真实等待用户回答
  → 序列完 → 写源 state_json 到回放任务行 → _finish 发 task_completed
    → 尾随 message(ai, 源总结原文)（与真实时序同构 → awaitSummaryRef 立即关流）
```

### 关键机制与约定（改代码必读）

1. **回放任务就是普通任务**：前端列表/打开/澄清/取消/结果全走既有路径，零改动。
   仅侧边栏有"回放"徽标（`task.replay_of`）与悬停"重放"按钮（completed 态显示）。
2. **数据端点映射**：`/records /sources /figures /quality /exports /result
   /export/{f} /open-output /open-file` 对回放任务自动映射到源任务（`_resolve_source_task`，
   main.py）——records/quality/洞察与源一致，图证 URL 指向源 task_id 目录（零拷贝）。
   **`/state /events /events/history /tasks/{id}` 一律字面 id**（前端 openTask 以快照
   lastSeq 续播 SSE，映射会导致 after_seq 大于实时 seq 而黑屏）。
3. **事件序列与真实同构**：源生命周期事件（task_queued/started/title_ready/completed/
   cancelled/failed）与源 `clarification_answered` 不转发；源 `message` 不即时转发，
   其 ai 总结原文在回放任务自身 task_completed 之后补发（`_finish` 的 trailing 参数）。
4. **澄清真实等待**：重放到澄清事件时挂起（复用 _AnswerSlot + POST resume），
   超时默认 15 分钟（可经 replay body `answer_timeout_sec` 覆盖，持久化于
   `state_json.replay_meta`——排队期间参数不落内存）。
5. **事件 payload 无元数据键**：重放剥离 seq/ts/task_id（EventBus.publish 注入新 seq，
   残留旧 seq 会覆盖导致前端 seq 幂等去重崩溃）。
6. **守卫**：源必须 completed（error/cancelled 无终态事件可供收尾，v1 收紧）；同一
   源同时仅一个活跃回放（409）；删除源时活跃回放 → 409，否则级联删回放行+events；
   嵌套重放（重放一个回放）扁平化为最上游源。
7. **events 表新增 `ts REAL` 列**（EventBus.publish 落 time.time()）：新真实任务的
   事件带真实时间戳 → 重放节奏精确压缩；老任务 ts=NULL → 类型默认节奏。

### 节奏说明

- 新任务（有 ts）：相邻间隔 = clamp(Δts / speed, 20ms, 1500ms)——真实 30 分钟 →
  演示约 1-3 分钟（speed 10-20）。
- 老任务（无 ts）：log/step_progress 40ms、其余 150ms——1053 事件 ≈ 60-90 秒。
- 总时长下界 ≈ 20ms × 事件数（前端渲染节流）；澄清等待不计入压缩。

### 工作流视图与三级下钻（WorkflowView / StageDetailPanel）

主区工具栏"对话 / 工作流"切换（共享同一份 pipeline 状态）。工作流视图 = KPI 概览带（总耗时/阶段进度/当前阶段/瓶颈）+ 纵向执行时间线；点击阶段节点打开右侧 `StageDetailPanel` 三级下钻：

| 层级 | 内容 |
|---|---|
| L1 | 阶段流程图（WorkflowView 节点） |
| L2 | 阶段执行明细：子步骤/检索分组进度、flow 轮次、Agent 列表（含"N 条执行日志 / N 条修改"徽章）、阶段错误、阶段日志 |
| L3 | Agent 明细：耗时 / reason / **数据修改轨迹**（`agent.traces`：field before→after + tool + confidence）/ **执行日志 · 工具与检查器调用**（`agent.logs`） |

**执行日志来源**：后端没有独立 `tool_call` 事件；检查器逐来源评分（`[ExtractionQuality] score=…`）、LLM 初始化（`[llm]`）、httpx 工具调用等明细全部是节点级 `log` 事件。`usePipeline` 按 `agent_started→agent_completed` 运行窗口把日志归属到各 Agent（真实快照验证：1043 条日志 1040 条命中，QualityAssessmentAgent 独占 255 条）。评估类 Agent 的 `traces` 为 null 属正常（只读不写），此时 L3 如实标注"未修改数据"。

### 记录详情弹窗（RecordDetailDialog）

主区记录表格行可点击 → 居中毛玻璃弹窗，呈现该条记录的完整血缘（首次点开懒加载 `getQuality`+`getSources` 并缓存）：数据来源（DB：表/键/原始列/行号；论文：页码/bbox/上下文原文）、处理轨迹（`per_record_trace`：原始值→最终值 + 逐次修改的 stage/before/after/reason）、冲突标注（`resolution_report.annotations` 按实体+字段匹配，标注本记录来源是否涉事）、Insight 建议（`field_insights`，来源类型一致的排前）、字段定义（`field_definitions`）+ 低置信记录警示（`usage_recommendations.low_confidence_records`）。Esc / 点击遮罩关闭；弹窗体 `flex + minHeight:0 + overflowY:auto` 保证小屏可滚动。

### DetailPanel 8 Tab

原 6 Tab 扩展为 8：**概览 / 质量 / 运行** / 来源 / 图证 / 轨迹 / 洞察 / 下载。新增两 Tab 全部消费真实数据：

- **质量**（`GET /quality` → `report_state.quality`）：总分 + 置信区间 + 等级徽章 + 路由分布（`route_counts`），逐来源评分行（升序，含分数条、路由 chip、原因文案）。路由键位于 `report_state.quality.per_source_routes / per_source_reasons / route_counts`——**不在 `quality_scoring` 内**（曾踩坑，61/61 命中验证后修正）。
- **运行**（`workflow_state` + `output_state.quality_summary.processing_statistics`）：LLM 调用 / 工具调用 / 总耗时 / B⇄C 循环次数 4 统计卡 + `workflow_history` 审计时间线（时间 + agent + stage + reason + duration）。

### 毛玻璃设计系统与过渡动画

- **seed token**：`--seed-bg/fg/primary/accent/surface/radius`，其余颜色一律 `color-mix()` 派生；深色模式 `html[data-theme='dark']` 只覆写 seed；`--bg-ambient` 双色 radial 环境光让半透明可见；`@supports not (backdrop-filter)` 降为 92% 不透明兜底。
- **玻璃层级**：`.glass`（浮层：面板/弹窗/toast，blur 18px）> `--surface-bg`（74% 半透明卡片）。
- **过渡动画**：tab/视图切换内容按 `key` 重挂载触发 `animate-tab-in`（淡入 + 6px 上移，0.24s）；主区对话/工作流切换仅淡入（避免 transform 干扰内部 fixed 浮层）；`.tab-btn` / `.filter-chip` / `.log-chip` 状态变化 0.16s 微过渡；全部动效尊重 `prefers-reduced-motion`。
