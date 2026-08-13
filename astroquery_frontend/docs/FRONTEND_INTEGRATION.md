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
│   │   └── usePipeline.js         # ★ 前端核心：SSE 事件消费 → stage reducer
│   ├── mock/pipeline.js           # 阶段定义/初始结构/澄清快捷按钮（非演示数据）
│   ├── components/
│   │   ├── chat/                  # ChatView（时间线+输入区）、StageCard（7 卡）、ClarificationCard
│   │   ├── results/               # ResultTabs（主区记录表格）、OutputFiles（输出文件区）
│   │   ├── layout/                # Sidebar（任务列表）、DetailPanel（右侧详情 6 Tab）
│   │   ├── log/                   # LogDrawer（实时日志，500 条上限 + 渲染 200 行截断）
│   │   ├── settings/              # SettingsDialog（配置页，GET/PUT /api/config）
│   │   └── ui/                    # button/scroll-area/toast（Radix + cva）
│   └── lib/markdown.jsx           # react-markdown 封装（AI 消息渲染）
├── vite.config.js                 # proxy（/api /static → :8000）+ preview 同配 + VITE_BASE
└── package.json                   # dev/build/preview（无 test/lint，验证靠 build）
```

---

## 3. 三栏布局（WEB_DESIGN 块 1）

```
┌─ 侧边栏 240px（可折叠）─┬─ 主区 ──────────────────┬─ 右侧详情面板 380px（可折叠）─┐
│ 新建提取任务             │ 工具栏（任务标题+状态徽标） │ 概览 / 来源 / 图证 / 轨迹     │
│ 任务列表（无限滚动）      │ 对话时间线：              │ / 洞察 / 输出文件（6 Tab）    │
│ 状态筛选 全部/运行中/…   │   AI 消息 · 7 阶段卡片    │ （DetailPanel 按 [task_id,   │
│ 底部设置入口             │   澄清卡（内嵌对话流）     │  status] 重拉）              │
│                         │ 输入区（自然语言+PDF 上传）│                             │
└─────────────────────────┴───────────────────────────┴─────────────────────────────┘
```

- 侧边栏任务条目：标题 + 相对时间 + 状态圆点（queued=灰"排队中"、running=蓝呼吸、completed=绿、error=红、cancelled=灰）
- 点"新建提取任务"清空主区（含 SSE 关闭与右侧面板重置）

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
  ├─ stage_started/completed   → 卡片状态 + 时间线弹卡
  ├─ step_progress             → locateStep 定位子步骤 + formatStepDetail 拼中文
  ├─ agent_started/completed   → 质量管线 agent 动态追加（流式，无预置列表）
  ├─ flow_started/completed    → 卡 5 动态流转节点（规范化/冲突消解 × 轮次）
  ├─ clarification             → 挂起澄清卡（按 cl_type 渲染 + 快捷按钮）
  ├─ message / log / error     → 消息时间线 / 日志抽屉（500 截断）/ 错误行
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
| `log` | `{node, level, message}` | 日志抽屉（500 条截断） |
| `task_completed` / `task_cancelled` / `task_failed` | `{summary?}` / `{reason?}` / `{error}` | 终态收尾（清理挂起澄清、输入栏恢复） |
| `task_title_ready` | `{task_id, title}` | 列表标题异步更新（按 task_id 归属） |

**关键机制**：
- **seq 幂等去重**：快照重放与 SSE 续播可能交叠，`applyEvent` 按 `ev.seq <= lastSeqRef` 丢弃重复
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
- **日志量大**：单任务 400+ log 事件（前端 500 条截断 + 渲染 200 行截断已处理）
