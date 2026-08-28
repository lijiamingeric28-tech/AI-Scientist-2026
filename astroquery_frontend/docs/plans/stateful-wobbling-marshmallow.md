# 事件级重放机制（演示回放全量重构）

## Context

**问题**：演示需要"完整、高保真地重演一次真实查询的全过程（时间压缩）"。当前 VCR cassette 重跑的本质是"重新生成"行为——VLM 宽松匹配 + 顺序消费使任何分支差异级联错位，实测错配严重，已修到不可维护。用户决定：**废弃 cassette 用于演示，重做事件级重放**（旧 VCR 路径保留不动、不杂揉；未来仍跑真实查询，事件自然落库即成为回放素材）。

**核心洞察**：真实运行的每个 SSE 事件（15 种类型，~1053 事件/任务）已完整落库。演示 = 新建"回放任务"，后端把源任务已落库事件按压缩节奏重新 emit —— 走既有 EventBus/SSE 通道，前端零解析改动，行为逐事件一致，零错位可能。

**用户决策（2026-08-27）**：澄清卡真实等待用户回答（复用 _AnswerSlot）；前端任务列表加"重放"按钮；其他前端需求后续再提。

## 设计概览

```
侧边栏旧任务悬停 → 点"重放" → POST /api/tasks/{src}/replay
  → 创建回放任务（replay_of=src、state_json={replay_meta:{speed, of}}）→ executor.submit（并发=1 排队）
  → _run_one 按 replay_of 分流 → web/replayer.run_replay：
      read 源 events + 源 state_json
      → 逐事件 emit（跳过生命周期事件与源 message；澄清事件真实等待 get_answer）
      → 节奏 = clamp(Δts/speed, 20ms, 1500ms)（events 表新增 ts 列：新任务落真实间隔，旧任务类型默认）
      → 序列完 → 写源 state_json 到回放任务行 → finally _finish(task_completed, 尾随 message=源总结原文)
  → 前端实时流与真实运行完全同构；结果端点映射到源任务 → 数据/图证/质量/洞察/导出全量可用（零文件拷贝）
```

## 关键事实（已由探索验证）

- 事件尾部真实顺序：`stage_completed(done) → task_completed → message(ai 总结) → task_title_ready`——message 在 completed 之后。
- payload 无任何 ts/timestamp；events 表无时间列。
- 前端 `awaitSummaryRef`：task_completed 后等 ai message 才关 SSE（20s 兜底）——重放必须同构补发总结才能秒关。
- 前端 `openTask` 先 /state 快照重放再以快照 lastSeq 开 SSE——**/state、/events 绝不能被映射改写**。
- 测试基建：client fixture（重绑 store/bus/executor + TestClient）或纯构造 Executor + monkeypatch。

## 实现分步

### Step 1 `web/task_store.py`：列与幂等迁移

- `_LIST_COLUMNS` 加 `replay_of`。
- `_ensure_column()` 辅助（PRAGMA table_info 检查后 ALTER）：tasks 加 `replay_of TEXT DEFAULT NULL`、events 加 `ts REAL`（建表 DDL 同时直接带上，新库免 ALTER）。
- `create_task(..., replay_of=None)`；`append_event(task_id, payload, ts=None)`。
- `get_events` 返回 `{"seq", "ts", **payload}`。
- 新增 `active_replay_exists(source_id) -> bool`、`replay_ids_of(source_id) -> List[str]`。

### Step 2 `web/event_bus.py`：落真时间戳

`publish` 改为 `self._store.append_event(task_id, event, ts=time.time())`。旧行 ts=NULL → 重放走类型默认；回放任务自身事件带真实 ts → 嵌套重放节奏自动继承。

### Step 3 `web/replayer.py`（新文件，零 executor 依赖）

```python
REPLAY_SKIP = frozenset({"task_queued","task_started","task_completed","task_cancelled",
                         "task_failed","task_title_ready","clarification_answered"})
DEFAULT_INTERVAL = {"log":0.04,"step_progress":0.04, **其余类型0.15}
CLAMP_MIN, CLAMP_MAX = 0.020, 1.500

def interval_between(prev_ts, cur_ts, cur_type, speed)  # 纯函数：无 ts→默认；有→clamp(Δt/speed)
def run_replay(bus, store, task_id, replay_of, slot, speed=10, get_answer=None,
               should_cancel=None, sleep=time.sleep, clarification_timeout=None)
```

主循环要点：
- **`payload = {k:v for k,v in ev.items() if k not in ("seq","ts","task_id")}`**——防旧 seq 覆盖新 seq、防 ts/task_id 污染（发布事件必有坑）。
- 跳过清单不转发；`message` 仅记录 `content`（role=ai）作为收尾总结（源 message 不即时转发）；`clarification` 事件：emit → 调 get_answer 真实等待（超时 → fatal error + task_cancelled + slot.cancel，复制现有闭包语义）→ 清答后继续；其余事件：`_sleep_checked(wait, sleep, should_cancel)`（50ms 分片检查取消）→ emit。
- 返回 `{"cancelled": bool, "state_json_text": 源state_json文本, "summary": 源总结}`。
- **ts 列作为节奏来源**：`interval_between(prev_ts, ev.get("ts"), etype, speed)`。

### Step 4 `web/executor.py`：分流 + 尾随消息（单次 _finish）

- `_run_one` 顶部 `rec = store.get_task(task_id)`；`rec.get("replay_of")` 非空 → replayer 分支：
  - 从 `state_json.replay_meta` 解析 `speed`/`answer_timeout_sec`（**排队期间参数不能走内存**，持久化在 state_json）
  - 结束（未取消时）：`update_task(state_json=out["state_json_text"])` 后 `trailing=[{"type":"message","role":"ai","content": out["summary"]}]`，`return`
  - 原路径（VCR/graph/title 线程）不动
- `_finish(task_id, trailing=None)`：status 落库 → emit task_completed → **同线程顺序 publish trailing**（message 紧随 task_completed，与真实时序同构）。
- `finally: self._finish(task_id, trailing=trailing)`——**唯一收尾出口**，禁止 replayer 内部调 _finish（P0-3：二次调用会把下一任务 `_current` 置 None 破坏并发=1）。
- 回放任务 title 线程天然跳过（_gen_title 只在原路径）。
- 取消中途：cancelled=True → trailing 空 → _finish 见 slot.cancelled 落 cancelled 静默收尾。

### Step 5 `web/main.py`：重放端点 + 结果端点映射 + 删除级联

- **`_resolve_source_task(task_id)`**：`replay_of` 且源存在 → 源 id；否则原 id。**仅用于结果类端点**：/result /records /sources /figures /quality /exports /export/{f} /open-output /open-file。**/state /events /events/history /tasks/{id} 一律字面 id**（防快照黑屏）。
- `POST /api/tasks/{task_id}/replay`（body `{speed: int=10, answer_timeout_sec?: float}`）：
  - 404 不存在；409 源 running/queued；**409 源非 completed**（v1 收紧：error/cancelled 源不可重放，Plan 审查结论——cancelled 源会使 SSE 无终态事件永久悬挂）；409 源无事件；409 `active_replay_exists`（防双击排队两个）。
  - `base = rec["replay_of"] or task_id`（嵌套重放扁平化）；创建任务（query=`回放：…` 截断 MAX_QUERY_LEN、title=`重放 · {源title}`、replay_of=base、state_json=`{"replay_meta":{...}}`）→ `executor.submit` → 返回 `{task_id, replay_of, status}`。
- 删除级联：源整删/批删前若 `active_replay_exists` → 409/`active`；否则先级联删回放行+events 再删源。DELETE /data 内容级清理不级联（state_json 保留 → records/quality 仍可用；figures/exports 缺失走前端已有空态降级），注释说明。

### Step 6 前端（最小改动）

- `api.js`：`replayTask(taskId, speed=10)`。
- `icons.jsx`：`Icon.Play`（与 Refresh 区分，重试按钮不变）。
- `Sidebar.jsx`：props 加 `onReplay`；任务行 title 旁 `replay_of` 存在 → "回放"徽标；终态（completed）悬停区加"重放"按钮（与 error 的"重试"同一行、互斥）。
- `App.jsx`：`handleReplay`——in-flight Set 防重 → `apiReplayTask` → toast → `loadTasks(0)` → `setSelectedId(new_id)`（仿 handleNewTask）。
- usePipeline 零改动。

### Step 7 文档

docs/API_CONTRACT.md、FRONTEND_INTEGRATION.md 补：replay 端点、events 响应 ts 字段、tasks 列表 replay_of。

## 测试清单（tests/test_web_offline.py，复用现有 fixture，全部离线）

1. `test_replay_migration_idempotent`——旧 schema 库初始化两遍无错；两表列齐全
2. `test_interval_between_clamp_and_defaults`——纯函数边界（无 ts 默认 / 除速 / 上下钳制）
3. `test_replay_endpoint_404_and_409_guards`——404；queued/error/空事件源 409；active_replay 409
4. `test_replay_run_event_order_and_tail`——回放任务事件：无跳过类、无源 message、唯一 task_completed 后紧跟 `message(ai, 源总结)`；源 events 不变
5. `test_replay_payload_no_stale_seq`——raw SQL 断言 payload 行无 seq/ts 键；ts 列非 NULL；type 集合=源（剔除跳过类）
6. `test_replay_clarification_waits_and_resume`——澄清后事件在 resume("y") 后才落库；/state pending_clarification 非空
7. `test_replay_clarification_timeout_cancels`——monkeypatch timeout→cancelled + fatal error + task_cancelled，无 task_completed
8. `test_replay_cancel_midway`——阻塞中 cancel → cancelled、无补发 message
9. `test_replay_state_copy_and_endpoint_mapping`——/records /quality /result 与源一致；/figures image_url 前缀为源 id；/exports /export/{f} 走源目录；/state events 是回放自己的；/events/history 仅回放事件
10. `test_replay_of_replay_flattens`——嵌套重放 replay_of == 最上游源 id
11. `test_delete_source_cascades_replays` + `test_delete_source_blocked_by_active_replay`
12. `test_list_tasks_includes_replay_of`
13. 回归：`test_executor_task_completed_after_persist_before_slow_summary`、`test_sse_replay_after_seq`、`test_state_pending_clarification`、全量 pytest

## 手动验收

1. `python -m web.main`（老库迁移幂等）+ `npm run dev`
2. 旧任务悬停"重放"→ 新任务自动选中 → 压缩节奏走完整流程 → 澄清卡真实等待 → 回答后继续 → **AI 总结出现后 SSE ≤2s 关闭（非 20s 兜底）** → 结果表/洞察/质量分布与源一致
3. 重放中再点"重放"→ 409 toast；重放中点"取消任务"→ 立即取消无残留
4. 结果页逐个验证：图证 URL 指向源 id（可打开）、exports/export 打开、open-output 打开源导出目录
5. 删除源（整删）→ 级联；内容级清理源 figures → 回放图证降级空串
6. 回放中重启后端 → 孤儿纠偏 cancelled，无悬挂
7. `pytest tests/` 全绿（含既有 VCR 回归）

## 关键文件

- `web/replayer.py`（新建）、`web/executor.py`（分流 + _finish trailing）、`web/main.py`（端点 + 映射 + 级联）、`web/task_store.py`（迁移）、`web/event_bus.py`（ts）
- `frontend/src/services/api.js`、`components/layout/Sidebar.jsx`、`App.jsx`、`components/icons.jsx`
- `tests/test_web_offline.py`、`docs/API_CONTRACT.md`、`docs/FRONTEND_INTEGRATION.md`
