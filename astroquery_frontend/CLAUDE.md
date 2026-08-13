# AstroQuery AI — Web 应用项目地图（交接文档）

> 本文件是理解整个项目的入口。请**按"分层阅读"顺序**读完下面的文件，再动手改任何代码。
> 项目状态：后端 5 模块 + 前端 API 对接已完成；**VCR 回放联调有已知问题（见 §7）**；真实端到端测试尚未运行（下一步最重要）。

---

## 1. 项目是什么

把 CLI 版天文数据检索流水线（`astroquery-ai`）变成 Web 应用：用户输入自然语言查询（如"M13 的距离、年龄和金属丰度"）→ 意图澄清（HITL）→ 27 个 VizieR 星表 + ADS 论文检索 → PDF 多模态提取 → 质量管线（评估/规范化/冲突/导出/洞察）→ 前端实时可视化 7 阶段卡片 + 结果区。

**技术栈**：Python FastAPI（后端）+ React 18/Vite/Tailwind（前端，`frontend/` 目录）+ LangGraph（流水线）+ sqlite（任务/事件持久化）+ VCR（LLM 录制回放）。

---

## 2. 分层阅读顺序（重要：按序读，每层读完再进下一层）

### 第 1 层：设计文档（先读这两个，所有决策都在里面）
1. `docs/WEB_DESIGN.md` —— 前端 UI 设计全案（用户逐条审批定稿）
   - 7 卡结构：任务理解 → 数据检索 → 数据提取 → 质量检查 → 数据清洗 → 数据交付 → 任务完成
   - 卡片展开模式（垂直时间线/三路分组/agent 树）、HITL 澄清卡、结果区、输入区、辅助设施
2. `docs/API_CONTRACT.md` —— API 契约 10 轮审核定稿
   - 端点全表（~15 个）、SSE 事件流 12 种事件、HITL resume、任务状态机、VCR 回放方案
   - **关键约定**：轻量状态走 SSE、重度数据走 HTTP；阶段总结前端拼字段（后端只给数字）；仅卡 7 最终总结走 LLM（qwen3.7-flash）

### 第 2 层：后端核心（服务层 + 事件化执行）
3. `events.py`（顶层）—— 事件发射器单例：subgraphs 埋点调 `emit`，web 启动 `configure(bus.publish)`；离线测试 no-op
4. `web/main.py` —— FastAPI 全部端点 + 上传暂存 + SSE 流 + 静态图证 + config 写 .env
5. `web/executor.py` —— 异步执行器：后台线程、并发=1 排队、resume/cancel、15 分钟澄清超时、VCR 回放分支（`LLM_CASSETTE` 环境变量）
6. `web/task_store.py` —— sqlite 持久化（tasks/events 表，seq 自增 = 断线续播）
7. `web/event_bus.py` —— 发布→落库+订阅队列（SSE 用）
8. `astroquery_ai/web_runner.py` —— 事件化 runner：SqliteSaver + interrupt→澄清事件 + get_answer 阻塞 + 卡 7 总结（**注意：summary 直接接收 runner 的 result，不要从 store 读快照**）
9. `web/summary.py` —— LLM 总结（含 `_is_usable_summary` 防错位响应透传）
10. `web/log_bridge.py` —— 节点 logger → SSE log 事件（thread-local task_id）

### 第 3 层：节点埋点（进度/agent 事件从哪来）
11. `subgraphs/subgraph2/nodes/`：`database_query.py`（星表循环进度）、`pdf_download.py`、`supplementary_query.py`、`ads_search.py`（查询串构建/检索去重）
12. `subgraphs/subgraph3/nodes/`：`vlm_extractor.py`、`bbox_annotator.py`、`figure_extractor.py`、`result_builder.py`
13. `astroquery_ai/property_standardization.py`（P1：卡 1 子步骤 confirm/simbad/research）
14. `quality_pipeline/agent_events.py` + 5 个子图 `*_graph.py`（assessment/normalization/conflict/export/insights 的 agent 事件包装）
15. `astroquery_ai/main_graph.py`（`create_main_graph(checkpointer, event_cb)` 阶段事件映射）

### 第 4 层：前端
16. `frontend/src/services/api.js` —— 全部端点封装 + SSE 流
17. `frontend/src/hooks/usePipeline.js` —— **SSE 事件消费 → stage reducer**（前端核心！含 log→stage/agent 归属）
18. `frontend/src/components/`：`chat/`（ChatView/StageCard/ClarificationCard）、`workflow/`（WorkflowView/StageDetailPanel 三级下钻）、`results/`（ResultTabs/RecordDetail/OutputFiles）、`layout/`（Sidebar/DetailPanel 8 Tab）、`settings/`、`log/`、`ui/`（toast/button）
19. `frontend/vite.config.js` —— proxy `/api`、`/static` → :8000

### 第 5 层：测试
20. `tests/test_web_offline.py` —— 10 个离线测试（store/总线/执行器/runner interrupt 循环/上传校验）——**全 mock 零费用，改后端先跑它**
21. `tests/test_e2e_recorded.py` —— VCR 录制回放 E2E（`-m network` 运行；首次录制 16 分钟，之后回放 2 分钟）

---

## 3. 常用命令

```bash
# 后端（回放模式）
cd E:/work/frontend/astroquery_final
python -c "import os; os.environ['LLM_CASSETTE']=r'E:/work/frontend/astroquery_final/tests/cassettes/m13_query.yaml'; os.environ['LLM_RECORD_MODE']='once'; import uvicorn; uvicorn.run('web.main:app', host='127.0.0.1', port=8000)"
# 后端（真实模式：去掉 LLM_CASSETTE 两行即可，会花 LLM 钱）
python -m uvicorn web.main:app --port 8000

# 前端
cd E:/work/frontend/astroquery_final/frontend && npm run dev   # :5173，proxy 到 8000

# 测试
python -m pytest tests/test_web_offline.py                      # 离线（免费，先跑这个）
python -m pytest tests/test_e2e_recorded.py -m network          # VCR E2E（首次录制花钱，之后回放）
```

**注意**：前端 dev server 和 8000 后端可能已有残留进程，端口占用时先杀。

---

## 4. 当前完成状态

| 模块 | 状态 |
|---|---|
| 后端 ① FastAPI 应用（15+ 端点/SSE/上传/静态/config） | ✅ 实现，离线测试绿 |
| 后端 ② 异步执行器（事件总线/sqlite 持久化/SqliteSaver/并发1/超时/cancel） | ✅ |
| 后端 ③ 节点埋点（卡 1 子步骤/卡 2 三路/卡 3 四步/质量 agent 事件） | ✅ |
| 后端 ④ interrupt 结构化（5 澄清点 title/fields/error + human_review HITL） | ✅ |
| 后端 ⑤ LLM 总结（卡 7 总结 + 任务标题，含防错位校验） | ✅ |
| 前端 API 对接（usePipeline/上传/澄清/结果区/侧边栏/设置/日志） | ✅ 构建通过 |
| VCR 录制回放 | ⚠️ pytest 级 OK；**后端运行级有响应错位问题（见 §7）** |
| 真实端到端测试 | ❌ **未运行（下一步）** |

---

## 5. 已知问题清单（新窗口必读）

1. **【最重要】VCR 回放模式数据错位**：后端 `LLM_CASSETTE` 回放时，VCR 只按 URL 匹配**不校验请求内容（body）**，若当前请求与录制时不同（prompt/参数变化）→ 返回错位响应 → 数据荒诞（查询串 1 个/6 篇/0 条/bbox 全失败）。已在 `web/summary.py` 加防透传校验（降级模板），但**检索/VLM 等环节的数据错位无法根治**。**数据正确性验证必须用真实模式**（去掉 LLM_CASSETTE）。
2. **真实端到端未运行**：M13 全流程真实跑（~15 分钟，花一次 LLM 钱）是最终验收的唯一可靠方式。跑完同时可重新录制 cassette。
3. **前端完成态产出未完整实现**：契约 D6-1 规定 stage output 走 `GET /api/tasks/{id}/state` 快照，但前端尚未实现"从快照 output 渲染卡 1 完成态三项产出（目标天体/SIMBAD/标准性质）"——目前卡 1 完成态无内容。同理卡头摘要（D6-5 前端拼）未完整实现。
4. **质量管线 flow 事件未实现**：契约的 `flow_started/flow_completed`（卡 5 动态流转节点）后端未发；前端目前靠 agent 事件驱动 clean/deliver 卡弹出（可用但无轮次分组）。
5. **僵尸 executor 线程**：任务卡在澄清等待时重启后端即可清；数据库 running 任务需手动 `UPDATE tasks SET status='cancelled' WHERE status='running'`。
6. **log 事件量大**（一次任务 400+ 条 log 事件进 SSE），前端日志抽屉无节流——性能待优化。
7. **summary 顺序 bug 已修但未验证**：`web_runner._events` 现在把 runner 的 result 传给 `on_final_summary(task_id, state)`；`web/main.py` 的 `_summary_fn` 签名已改为 `(task_id, state)`。**不要再改回从 store 读快照**。
8. 既有 31 个测试失败已修复（用户漏传 4 个文件：planning/normalization/validation agent + supplementary_query），现仅剩 1 个环境性失败（`test_layer3_golden`：try/except* 在 Python 3.14 行为差异）。

---

## 6. 下一步行动（按优先级）

1. **切真实模式跑 M13 全流程**（最终验收）：`python -m uvicorn web.main:app --port 8000`（无 LLM_CASSETTE），前端 5173 提交"M13 的距离、年龄和金属丰度"，澄清输入"距离、年龄和金属丰度"→ 确认(y)。验证：7 卡完整、数字合理、右侧栏有数据、summary 正常。
2. 真实跑通后**重新录制 cassette**（`tests/test_e2e_recorded.py -m network` 会覆盖 m13_query.yaml），之后回放联调数据才正确。
3. 补前端"快照 output 渲染"（问题 3）。
4. 实现质量管线 flow 事件（问题 4，需在 `quality_pipeline/routers.py` 的 dispatch/loop 发事件）。
5. 日志节流（问题 6）。

---

## 7. 关键设计决策速查（避免踩坑）

- **前端拼字段原则**：后端事件 `step_progress.data` 只带原始数字，前端 `usePipeline.js` 的 `formatStepDetail` 拼中文文本（**不要把 data 对象直接塞 detail 渲染，会崩溃**）
- **澄清卡定位**：后端 clarification 事件必须带 `stage_id`（`web_runner._CLAR_STAGES` 按 cl_type 推断），前端按它渲染；quickButtons 在前端按 cl_type 生成（`CLARIFICATION_QUICK_BUTTONS`）
- **agent 事件是流式的**：前端 agents 列表动态追加，不要依赖预置列表
- **clean/deliver/done 卡无 stage_started 事件**：前端在 agent 事件/stage_completed 时自动弹卡（usePipeline 已实现，勿删）
- **右侧栏数据**：DetailPanel 依赖 `[task?.task_id, task?.status]` 重拉（任务完成时刷新），不要改回只依赖 id（task.id 已在 B7 统一为 task.task_id）
- **log 归属用同步窗口**：usePipeline 的 `activeStagesRef`/`activeAgentsRef` 在 applyEvent 内同步维护，勿改回读 `stagesRef`（快照重放期间滞后，历史任务日志会归属失败）；节点级 log 按 agent 运行窗口挂到 `agent.logs`，是工作流下钻"执行日志/工具调用明细"的唯一数据源（后端无独立 tool_call 事件）
- **VCR 只对 pytest 装饰器方式完全可靠**；executor 线程内 use_cassette 会打大量 "Appending" 日志（是回放不是录制，勿误判）
- **回放模式启动**：必须用 `python -c` 代码内注入环境变量（`os.environ['LLM_CASSETTE']=...`），shell 前缀在后台任务里不可靠

## 8. 视觉闭环（改 UI 后必做）

改任何前端 UI 后，用"截图 → 多模态审查 → 修复 → 再截图"闭环验证（qwen-mm-plugins-api MCP 已连接）：

1. **截图**：`powershell -ExecutionPolicy Bypass -File scripts/screenshot.ps1 output/screen_N.png`（截主屏；**先 `cmd /c start http://127.0.0.1:5173` 确保浏览器在前台**，否则截到终端）
2. **审查**：`vision_chat`（qwen）读截图，按 5 维审查：布局对齐/样式一致/内容显示（乱码、原始 JSON、超长小数）/组件状态/难看区域
3. **修复** → 截图再验证（qwen 确认修复生效）
4. **注意**：表格在对话区底部需滚动才能看到表头/末尾——全屏截图只能看到可视区，视口外内容不算 bug；长标题 ellipsis 截断是设计行为（悬停 title 可见完整），按钮不被挤出即可（h1 必须有 `minWidth: 0`）
