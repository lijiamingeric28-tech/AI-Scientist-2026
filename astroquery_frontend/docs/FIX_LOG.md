# FIX_LOG — 60 条审计修复日志

> 本文件记录 P0 基线及后续 60 条审计修复的每一批次结果。
> 格式约定：每批修复完成后，追加一节（日期 → 变更 → 全量/专项测试结果 → 失败归类），不要改动历史节。

---

## 基线节（2026-08-12）

**基线 commit**：`c82b7e2c4c799bb803412d445bf26e29fc342e69`（`chore: baseline（60条审计修复起点）`）

### 全量 pytest 结果

命令：`PYTHONIOENCODING=utf-8 python -m pytest tests/ -q --tb=no`（pytest 9.1.1，Python 3.14.5）

- 收集 387 个用例，网络标记去选 3 个（`test_e2e_m13_query` + `test_smoke_network.py` 整文件 2 个）
- 实际执行 384：**383 通过 / 1 失败**（pytest 退出码 1）
- 失败列表（1 个）：
  - `tests/test_layer3_golden.py::test_golden_corpus_funnel_and_effective_success`
    - 归类：**环境性失败（Python 版本差异，非本次审计引入）**
    - 具体原因：corpus 回归片段 `reg_try_except_star_py310` 期望沙箱将 `except*` 语法判为 `syntax_error`（该片段按 Python 3.10 语义设计），但本机 Python 3.14.5 中 `except*` 语法合法 → 该片段走 dry-run 后被判为 `noop`，与 `expect_kind=syntax_error` 不符。
    - 附带现象：`有效成功率 23/35 (65.7%)` 低于 85% 阈值（同类原因：部分片段在 3.14 下的行为与 3.10 预期不同）。
- **与预期名单的偏差**：任务预设失败名单（2x `test_gen_catalog_schema_*` + 1x `test_golden_corpus_funnel`）与实测不符——实测 `test_audit_fixes_retrieval.py::test_gen_catalog_schema_column_source_union` 与 `test_audit_fixes_retrieval.py::test_gen_catalog_schema_aliases_cover_escaped_columns` **已通过**（此前 lastfailed 缓存 18:26 陈旧记录显示失败，本次实测全绿），仅 golden 1 个失败。以实测为准。

### offline 基线结果

命令：`python -m pytest tests/test_web_offline.py -p no:cacheprovider -q`

- **10 passed**（exit 0），全绿。覆盖 TaskStore CRUD/事件序、EventBus 发布订阅、上传/任务端点校验、Executor 排队与取消、web_runner interrupt 循环与超时取消。

### 基础设施说明

- 端口清理：`netstat -ano | grep ':8000'` 无 LISTENING 残留，无需 kill。
- Python：3.14.5（`C:\Python314`）；pytest：9.1.1。注意：pytest 9.x 的 `-q` 模式不再输出 `N passed, M failed in Xs` 计数行，通过数由进度标记数（383 `.` + 1 `F`）+ `--collect-only`（384/387 collected, 3 deselected）交叉核对得出。
- git：新建仓库 `git init -b main`，user.name=`audit-fix` / user.email=`audit@local`（本仓库首次提交即基线）。
- .gitignore 追加：`tests/cassettes/`、`web/data/`、`frontend/dist/`、`frontend/node_modules/`（node_modules 为额外排除项，避免 5000+ 文件混入基线）。
- 基线提交共 378 个文件；验证 `git ls-files` 不含 `.env`、cassettes、`web/data`、`dist`、`node_modules`。

### 修复起点备忘

后续 60 条修复的验收基线：全量测试需维持「0 新增失败」，最终目标消灭上述 1 个环境性失败（方案候选：按 Python 版本条件化 `reg_try_except_star_py310` 片段的 `expect_kind`，或在 Python ≥3.11 上改用其他必然 `syntax_error` 的构造）。

### 基线复核（2026-08-13）

- **复核 commit**：`a76822b`（HEAD，`fix(test): test_layer3_golden 语法错误片段改版本无关`，叠加于基线 `c82b7e2` 与 P0 记录 `2ff413c` 之上）。
- **全量 pytest**：`PYTHONIOENCODING=utf-8 python -m pytest tests/ -q`（后台运行，实测约 3 分钟）→ **PYTEST_EXIT=0 全绿**。收集 384 个用例全部通过、0 失败（与 `--collect-only` 的 384 交叉核对；pytest 9.x `-q` 无计数尾行，以退出码 + 进度标记核验）。
- **golden 修复确认**：`tests/test_layer3_golden.py::test_golden_corpus_funnel_and_effective_success` **已通过**——`reg_try_except_star_py310` 片段改版本无关后，唯一的环境性失败已消除，新基线 0 失败。
- **offline**：`python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **10 passed**（exit 0），全绿。
- **基础设施**：端口 8000 无 LISTENING 残留（`netstat -ano | grep ':8000'` 无输出）；git 已是仓库（未重新 init / 未改 .gitignore / 未重复提交基线），工作区干净，`git ls-files` 不含 .env/cassettes/web/data/dist/node_modules。
- **结论**：修复起点基线已从「383 通过 / 1 环境性失败」升级为「**384 通过 / 0 失败**」，后续 60 条修复的验收基线同步更新为「全量 0 失败 + offline 10 passed」。

---

## 批次 B1「测试基建」（2026-08-13）

**commit**：`53a405c`（`fix: B1 测试基建 M-21/M-07/L-11`）

### 条目修复表

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| M-07 | client fixture 重绑事件源：`events.configure(m.bus.publish)` + `log_bridge.install(m.bus)`（install 增加重绑分支：`_handler._bus` 跟随新 bus），防离线测试经旧通道向真实 web/data/tasks.db 写孤儿 log/埋点事件；teardown 调 `m.executor.stop()`。executor 新增 `stop()`（`_pending` 放 None 哨兵 + join loop 线程）。`test_create_task_moves_pdf` monkeypatch `web.executor.run_task_streaming` 阻断真实流水线并等线程收尾；新增 `test_offline_tests_do_not_pollute_real_db` 回归锚点：假 runner 显式触发 log+step_progress 双污染通道，断言事件只落 tmp store、真实库（只读 URI 计数）事件数不变 | r1 失败（pollution probe 用 INFO 级别：pytest logging 插件先挂 root handler 使 basicConfig 不生效，root 保持 WARNING 丢弃 INFO 记录，log 事件未落库）→ r2 通过 | pass |
| M-21 | 按 fix_suggestion 8 项锚点补测试：①SSE after_seq=N 补发 seq>N 升序且与 store.get_events 逐条相等（TestClient/httpx ASGITransport 与 EventSourceResponse 流式交互本环境阻塞，改为直接调用端点协程迭代 body_iterator）；②/state pending_clarification 仅 running 且末事件为澄清时返回（旧逻辑返回被后续事件覆盖的旧澄清，按锚点修正 web/main.py）；③retry 新 task_id+旧事件保留+pdf copy；④/api/config GET 永不回传明文+PUT monkeypatch `_ENV_FILE` 写回；⑤/export 用 `../` 与 `%2e%2e/` 断言 404+合法文件 200；⑥resume 非澄清等待 409；⑦上传超限 rejected[0].reason 含 50MB+混合部分拒收；⑧move 双端断言（修复 test_create_task_moves_pdf 用 app.extra 取不到 monkeypatch 后 UPLOAD_DIR 的恒真断言） | r1 失败（SSE 测试 client.stream 挂起，starlette TestClient/httpx 与 EventSourceResponse 流式交互阻塞 120s 超时；手动 ASGI harness 验证 app 正常，系传输层限制）→ r2 失败（/state 旧逻辑末事件非澄清仍返回最后一个澄清，与锚点②不符）→ r3 通过 | pass |
| L-11 | log_bridge 用 contextvars.ContextVar 替代 threading.local（handler 与 set_task 均改读/写 ContextVar）。实测 Python 3.14.5 子线程与 ThreadPoolExecutor worker 均不隐式继承 contextvars，故 install() 内对 TPE 的 submit 做显式透传：提交时 copy_context()，worker 内 ctx.run 执行，节点内 VLM/bbox/下载/图提取等 TPE worker 线程日志可见 task_id。回归测试 test_log_bridge_worker_thread_log：TPE worker 线程 + 同线程双路径日志均落库；红测确认旧 threading.local 机制下 worker 线程事件数为 0 | r1 通过 | pass |

### 门禁结果

- **G1（本批相关测试，10 个用例）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py::{10 个测试} -p no:cacheprovider -q` → **10 passed**，pass。
- **G2（离线 web 全量）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **19 passed**（exit 0），pass。
- **G3（全量离线测试）**：**skip**——本批白名单不含 subgraphs/ 与 quality_pipeline/ 生产代码（B1 只改 web 层/前端/测试/配置），全量由后续碰核心管线的批次覆盖。
- **越界检测**：git status --porcelain 解析改动文件 = `tests/test_web_offline.py`、`web/main.py`、`web/log_bridge.py`、`web/executor.py`，全部在批白名单内，**无越界文件**，未回滚任何文件。
- **结论**：门禁全绿，条目 M-07 / M-21 / L-11 全部标记 fixed（web_audit_findings.json 已追加 fix_status）。

---

## 批次 B2「状态机终态簇（尖峰）」（2026-08-13）

**commit**：`860c89a`（`fix: B2 状态机终态簇（尖峰） CR-01/H-07/H-08/H-09/M-12/M-17`）

### 条目修复表

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| CR-01 | 总结生成从 `_events`（wrap finally 在 invoke 返回前触发、result 恒陈旧）移到 runner 尾部：最后一次 invoke 返回后、发 task_completed 前用真实终态调 on_final_summary，删除误导注释；task_completed 先发、总结异步线程补发（兼 M-12）。回归锚点 DP-04：假图发 done 事件后 on_final_summary 收到含 final_output 的 state | r1 失败（monkeypatched create_main_graph lambda 缺 should_cancel kwarg TypeError；wrap-cancel 测试 checkpointer 需 thread_id ValueError；M-12 测试 e["type"] on str）→ r2 失败（task_completed 先于慢总结测试 StopIteration，summary_done 先于 bus.message 落库竞态，测试改轮询等 ai 消息）→ r3 通过 | pass |
| H-07 | get_answer 超时分支同步发 task_cancelled(reason=timeout) + slot.cancel()；`_finish` 弹槽后检查 slot.cancelled，为真则落 cancelled 而非覆写 completed。CLARIFICATION_TIMEOUT 提升为模块常量（测试 monkeypatch 缩短注入）。锚点 W08-05：短超时后 DB status==cancelled 且事件含 task_cancelled + error fatal、无 task_completed | r1 失败（同批公共 8 项失败）→ r2 失败（M-12 竞态 1 项）→ r3 通过 | pass |
| H-08 | ① `_CancelledError` 移到 main_graph，create_main_graph 增 should_cancel 参数，wrap 进入/退出边界检查并抛异常终止执行中的图；② executor.cancel 两个分支（slot+queued）立即 bus.emit(task_cancelled)；③ runner 发 task_completed 前查 should_cancel 已取消不发；runner `_answer_handler` 不再重复发（防双份）。锚点 DP-08：queued 取消收到 task_cancelled | r1 失败（同批公共 8 项，含 wrap-cancel 测试补 thread_id config）→ r2 失败（M-12 竞态 1 项）→ r3 通过 | pass |
| H-09 | ① runner 尾部 result.clarification_status==cancelled → 发 task_cancelled(user_cancelled) 而非 task_completed；③ 取消/非天文分支补发 stage_completed(understand, status=cancelled) 灰态；② executor 对 cancelled 结果标记 slot.cancel()，`_finish` 落 DB cancelled；④ main_graph wrap 同图实例 `_active_stages` 去重澄清重入的重复 stage_started。锚点：选 n 事件流含 task_cancelled 无 task_completed、卡 1 灰态 | r1 失败（同批公共 8 项）→ r2 失败（M-12 竞态 1 项）→ r3 通过 | pass |
| M-12 | runner 尾部先发 task_completed 再在 daemon 线程异步生成 LLM 总结（慢/超时 LLM 不阻塞执行线程与排队任务）；executor 标题生成移入 `_gen_title` daemon 线程，`_finish` 不等待（D8-2 task_title_ready 异步语义）。锚点：慢 LLM 时 task_completed 先于 ai 总结消息到达、标题阻塞时队列及时释放 | r1 失败（同批公共 8 项）→ r2 失败（本条目测试 StopIteration：summary_done 先于 bus.message 落库，测试改轮询等 ai 消息）→ r3 通过 | pass |
| M-17 | generate_final_summary 的 prompt 模板化：target = state.target_entity or state.user_query or 本次查询，硬编码「M13 数据检索任务」改为「{target}」（与 generate_task_title 同模式）。锚点：M31 查询（含无 target_entity 时 user_query 兜底）断言 prompt 含 M31、不含 M13 | r1 失败（同批公共 8 项，本条目测试本身首轮已绿）→ r2 失败（M-12 竞态 1 项）→ r3 通过 | pass |

### 门禁结果

- **G1（本批相关测试，11 个用例）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py::{11 个测试} -p no:cacheprovider -q` → **11 passed**（exit 0），pass。
- **G2（离线 web 全量）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **30 passed**（exit 0），pass。
- **G3（全量离线测试）**：`(PYTHONIOENCODING=utf-8 python -m pytest tests/ -q > /tmp/pytest_gate_B2.log 2>&1; echo "PYTEST_EXIT=$?" >> ...) &` 后台运行（实测约 13 分钟），轮询 log → **PYTEST_EXIT=0**（全部通过、0 失败），pass。
- **越界检测**：git status --porcelain 解析改动文件 = `astroquery_ai/main_graph.py`、`astroquery_ai/web_runner.py`、`tests/test_web_offline.py`、`web/executor.py`、`web/summary.py`，全部在批白名单内，**无越界文件**，未回滚任何文件。
- **结论**：门禁全绿，条目 CR-01 / H-07 / H-08 / H-09 / M-12 / M-17 全部标记 fixed（web_audit_findings.json 已追加 fix_status）。

---

## 批次 B3「resume/取消端点」（2026-08-13）

**commit**：`19115e1`（`fix: B3 resume/取消端点 H-04/L-06/L-07`）

### 条目修复表

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| H-04 | ① `_AnswerSlot` 加 waiting 标志：wait() 前置 True、返回后置 False（finally），set_answer 仅 waiting 且未 cancelled 时写入并返回 bool，reset 同步清标志；executor.resume 传播 set_answer 返回值（非等待期 → False → HTTP 409），新增 `Executor.is_waiting_clarification(task_id)` 暴露真实挂起；② main.py /state 在 running+末事件为澄清基础上再经 `executor.is_waiting_clarification` 确认（已答复/非等待 → pending_clarification null）。③ 前端收到 409 收起澄清卡属前端文件，受文件锁约束未改（后端 409 契约已就位）。回归测试：非等待期 resume 断言 409 且答案未写入、已答复澄清 /state 返回 null、等待期 resume 200 并真实消费、_AnswerSlot 单元语义 | r1 通过（全量 web_offline）→ r2 通过（定向 `-k "waiting or 404 or overwrite or pending_clarification or resume"`）→ r3 通过（全量重跑两遍 + exit code 校验防线程 flaky + ruff check） | pass |
| L-06 | resume/cancel 端点先 `store.get_task(task_id)`，不存在则 404「任务不存在」，存在再走 executor 判可操作性（409 保留）。与同族端点（get_task/retry/state 等）404 语义一致，错误文案不再误导为状态冲突 | r1 通过（全量）→ r2 通过（定向） | pass |
| L-07 | cancel 全程持 `_lock`，与 `_finish` 状态写入同一临界区：锁内二次读取 rec 状态，仅当 status in ('queued','running') 才置 cancelled（slot 分支与 queued 分支均如此），已完成/失败终态（含与 `_finish` 竞态中 pop 前的陈旧槽）返回 False 不被覆写 | r1 通过（全量）→ r2 通过（定向） | pass |

### 门禁结果

- **G1（本批相关测试，6 个用例）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py::{test_answer_slot_waiting_semantics,test_resume_409_task_running_not_waiting,test_state_pending_clarification_null_when_not_waiting,test_state_pending_clarification,test_resume_cancel_404_nonexistent,test_cancel_does_not_overwrite_completed} -p no:cacheprovider -q` → **6 passed**（exit 0），pass。
- **G2（离线 web 全量）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **35 passed**（exit 0），pass。
- **G3（全量离线测试）**：**skip**——本批白名单不含 subgraphs/ 与 quality_pipeline/ 生产代码（B3 只改 web 层/前端/测试/配置），全量由后续碰核心管线的批次覆盖。
- **越界检测**：git status --porcelain 解析改动文件 = `astroquery_ai/web_runner.py`、`web/executor.py`、`web/main.py`、`tests/test_web_offline.py`，全部在批白名单内，**无越界文件**，未回滚任何文件。
- **结论**：门禁全绿，条目 H-04 / L-06 / L-07 全部标记 fixed（web_audit_findings.json 已追加 fix_status）。

---

## 批次 B4「VCR 回放链路」（2026-08-13）

**commit**：`9136cdc`（`fix: B4 VCR 回放链路 H-11/H-12/H-13/H-14/M-11/L-14/H-16`）

### 条目修复表

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| H-11 | executor 回放 VCR 的 match_on 增 "body"（`_VCR_MATCH_ON`，同 URL POST 按请求体/prompt 区分，GET body=None 不受影响）；新增 `validate_replay_query`：回放前解析（进程级缓存）cassette 首个 LLM chat 请求的首条 user prompt，当前 query 不包含于其中则抛错拒绝回放，任务 fail-fast 不进入 runner | r1 通过 | pass |
| H-12 | executor 级 RLock（`_CASSETTE_PLAY_LOCK`）幂等包装 cassette.play_response，串行化 play_counts 检查-自增；`_limit_vlm_concurrency` 在 VCR 分支把 VLM settings.concurrency.max_workers 降为 1（vlm_extractor.py 只读，改运行期全局配置） | r1 通过 | pass |
| H-14 | LLM_RECORD_MODE 默认改 'none'（未匹配即抛错，不再静默真实录制计费）；`validate_cassette_config`：LLM_CASSETTE 缺失 + 非显式录制（all/once/new_episodes 允许首次录制）→ 启动（`_vcr_startup_selftest`）与任务（`_run_one`）均 fail-fast 抛错；executor 日志同时打印 mode 与 interactions 数 | r1 通过 | pass |
| M-11 | import 期自测探针整体移除，迁入 `@app.on_event('startup')` 的 `_vcr_startup_selftest`（可直测）；cassette 缺失先 exists() 检查：默认 'none' 抛错、显式录制跳过探针，探针绝不在 'none' 下产生网络请求；timeout 15s→3s；'Appending' INFO 日志经 `_DowngradeAppendingFilter` 降 DEBUG（消除 141 行/9.6MB 洪泛） | r1 通过 | pass |
| L-14 | `_CASSETTE_PARSE_CACHE` 进程级单例缓存 cassette YAML 解析结果（58MB 每进程一次，实测 12.8s 首解析、后续 0.0s，H-11 校验复用），缺失文件负缓存；加载期 'Appending' 日志降 DEBUG。cassette 按 LLM/下载分文件与录制退出全量重写属录制端/vcrpy 库内行为，超出本批文件锁范围（vcrpy 只读） | r1 通过 | pass |
| H-13 | ①清空 tests/cassettes/m13_query.yaml 中 103 处 authorization 头键+103 处 Bearer 值行（共 206 行，保留 CRLF 逐字节重写）；yaml 全量解析通过、141 条交互完好、authorization/Bearer/sk- 零残留（门禁复核：grep 计数 0）。②录制配置加 filter_headers=[('authorization',None)] + filter_query_parameters 脱敏（未来重录不再落盘密钥）。③.gitignore 基线已含 tests/cassettes/（git show HEAD 验证），无需改动。④回归测试 test_cassette_contains_no_secrets：离线扫描 cassette 断言无 authorization 键/明文 Bearer | r1 通过（`-m 'not network'`）→ r2 通过（全量 11 passed, 1 deselected） | pass |
| H-16 | 新增断言助手 assert_m13_contract 覆盖五锚点：①target_entity==M13 且 requested_properties 含距离/年龄/金属丰度；②records 非空且每条 field_name/field_value/field_unit 非空；③stage_started 全集+stage_completed 配对（按真实完成运行 ground truth 校准：understand/retrieval/extraction/quality_check started + done completed，clean/deliver 无 stage 事件系设计使然）；④seq 严格单调递增；⑤删除 bus_events 死代码（_Bus 子类）。E2E 测试改调契约并保留澄清/task_completed 断言。离线注入回归：干净样本通过 + 9 种错位注入（目标错位/性质缺失/records 空/字段空或缺失/缺卡/缺 done/seq 乱序）必须 AssertionError | r1 通过（`-m 'not network'`）→ r2 通过（全量 11 passed, 1 deselected） | pass |

### 门禁结果

- **G1（本批相关测试，23 个用例）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py::{12 个} tests/test_e2e_recorded.py::{test_cassette_contains_no_secrets,test_m13_contract_accepts_valid_data,test_m13_contract_rejects_mismatched_data(9 参数化)} -p no:cacheprovider -q` → **23 passed**（exit 0），pass。
- **G2（离线 web 全量）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **47 passed**（exit 0，pytest 9.x 无计数行，按进度标记数核对），pass。
- **G3（全量离线测试）**：`(PYTHONIOENCODING=utf-8 python -m pytest tests/ -q > /tmp/pytest_gate_B4.log 2>&1; echo "PYTEST_EXIT=$?" >> ...) &` 后台运行（实测约 12 分钟），轮询 log → **PYTEST_EXIT=0**（全部通过、0 失败），pass。
- **越界检测**：git status --porcelain 解析改动文件 = `tests/test_e2e_recorded.py`、`tests/test_web_offline.py`、`web/executor.py`、`web/main.py`，全部在批白名单内，**无越界文件**，未回滚任何文件（cassette 被 .gitignore 忽略未入库，脱敏只落盘）。
- **WARN（人工动作）**：H-13 修复发现已泄露两个真实密钥（DashScope ws 密钥 sk-ws-… 与 sk-d9f0…），虽已从 cassette 脱敏，但密钥轮换为人工动作，需立即轮换。
- **结论**：门禁全绿，条目 H-11 / H-12 / H-13 / H-14 / M-11 / L-14 / H-16 全部标记 fixed（web_audit_findings.json 已追加 fix_status）。

---

## 批次 B5「SSE 去重簇（前后端同批）」（2026-08-13）

**commit**：`29a35f4`（`fix: B5 SSE 去重簇（前后端同批） CR-02/M-06/H-17/M-04`）

### 条目修复表

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| CR-02 | **后端**（web/main.py）：①新增 `GET /api/tasks/{id}/events/history`（D8-3：历史回看走 HTTP 批量，SSE 只做实时+断点续播）；②stream_events 改为先 `bus.subscribe` 再取 store 快照，快照后已入队事件按 `ev.seq>replayed_last` 去重补发——消除「重放→订阅」间隙丢事件与重复 seq（DP-12 后端侧锚点）；/state 的 pending_clarification 真实挂起守卫（M-21）覆盖「回放 clarification 不置 pending」。**前端**（usePipeline.js）：openTask 快照重放后把 lastSeqRef.current 传给 openEventStream（after_seq 续播）；applyEvent 开头按 ev.seq 幂等去重；onerror 中关闭旧流并按 lastSeq 重建（重试上限 8 防死循环）；快照重放（replay=true）的 clarification 不再置 pending，挂起仅由 snap.pending_clarification 恢复；快照重放后 lastSeqRef 归零（任务切换防跨任务误去重） | 后端 r1 失败（EventQueue 漏本地导入 NameError）→ r2 失败（dropped 区间断言顺序不符）→ r3 通过（全量 web_offline）；前端 3 轮全过（node --check / vite build / harness.mjs 行为验证） | pass |
| M-06 | **后端**（web/event_bus.py、web/main.py）：①EventQueue 分级丢弃：队列满仅允许丢 log/step_progress 并合并记录 dropped_seq 区间，关键事件（stage_*/clarification/task_*/message/error）腾位入队不丢；②订阅时捕获归属 loop，执行器线程发布经 `loop.call_soon_threadsafe` 投递（跨线程 put_nowait 安全化，loop 已关闭则告警丢弃）；③stream_events 终态事件（task_completed/cancelled/failed）后 TTL 收尾窗口（SSE_DONE_TTL=15s，尾随 ai 总结仍投递，M-12 兼容）超时正常关闭流，不再永续占连接。**前端**（usePipeline.js）：断线重连携带 lastSeqRef 走 after_seq 续播（onerror 重建流）；task_completed/task_cancelled/task_failed/致命 error 事件关闭 SSE；快照显示任务已终态时不再开流 | 后端 r1 失败（同批公共 1 项）→ r2 失败（dropped 顺序断言）→ r3 通过；前端 3 轮全过 | pass |
| H-17 | usePipeline.js：①openTask 在 await getState 之后与开流之前都加 taskIdRef 归属校验，乱序返回的旧快照整体丢弃；②openEventStream 返回值先存局部变量 es，taskIdRef 仍归属本任务才赋 esRef，否则立即 es.close()；③applyEvent 增加可选 taskId 归属校验，旧流残留事件不注入新任务视图；④切换任务时 openTask 开头 close 旧流并置 null，无双连接/不泄漏订阅 | 3 轮全过（node --check / vite build / harness.mjs：乱序快照 A→B 无串台、只为 B 开流；切换时 A 流关闭；旧流残留事件被拒） | pass |
| M-04 | usePipeline.js：openTask 消费 snap.state，新增 buildUnderstandOutput() 将后端 target_entity/simbad_info{main_id,otype,ra,dec}/property_spec[{property_id,name_cn,unit}] 映射为卡 1 stage.output（snake→camel，键名与 aggregator/property_standardization 核对）；无 target_entity 不产 output；同时按 output 拼装卡头摘要「已确认目标天体 X 与 N 项标准性质」（与 mock 文案一致）。StageCard 的 UnderstandOutput 既有渲染零改动 | 3 轮全过（node --check / vite build / harness.mjs：快照含 output 的 targetEntity/simbad/properties 映射、卡头摘要断言；空 state 不误产 output） | pass |

### 门禁结果

- **G1（本批相关测试，6 个用例）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py::{test_events_history_http_endpoint,test_sse_no_gap_events_published_during_replay,test_sse_closes_after_terminal_event,test_sse_done_ttl_delivers_trailing_then_closes,test_event_bus_dropped_range_and_critical_kept,test_event_bus_publish_threadsafe_from_worker_thread} -p no:cacheprovider -q` → **6 passed**（exit 0），pass。
- **G2（离线 web 全量）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **53 passed**（exit 0），pass。
- **G3（全量离线测试）**：**skip**——本批白名单不含 subgraphs/ 与 quality_pipeline/ 生产代码（B5 只改 web 层/前端/测试/配置），全量由后续碰核心管线的批次覆盖。
- **G4（前端构建）**：`cd frontend && npm run build`（vite v6.4.3，313 modules transformed）→ **build 成功**，pass。
- **越界检测**：git status --porcelain 解析改动文件 = `frontend/src/hooks/usePipeline.js`、`tests/test_web_offline.py`、`web/event_bus.py`、`web/main.py`，全部在批白名单内，**无越界文件**，未回滚任何文件。
- **结论**：门禁全绿，条目 CR-02 / M-06 / H-17 / M-04 全部标记 fixed（web_audit_findings.json 已追加 fix_status）。

---

## 批次 B6「pending/澄清生命周期」（2026-08-13）

**commit**：`5545e03`（`fix: B6 pending/澄清生命周期 H-02/H-18/M-05/M-23`）

### 条目修复表

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| H-02 | usePipeline 新增 clearPending 助手：error(fatal)/task_cancelled/task_failed 三分支统一置空 pending 与 pendingRef（ChatView clarifying 随之为 false，输入栏与提交恢复可用）；fatal 的 ev.message 追加为 AI 消息（D10-3 澄清超时显式提示）；挂起澄清所属 stage 置 cancelled 灰态。后端超时事件序（fatal 先于 task_cancelled、含 D10-3 文案）由新回归测试锁定 | r1 通过（esbuild 语法校验）→ r2 通过（tests/test_web_b6_pending.py::test_timeout_fatal_error_precedes_cancel） | pass |
| H-18 | submitAnswer 改为 await resume 成功后再清 pending 并回填澄清历史（失败不记答案）；失败恢复 pendingRef.current=cl + setPending({...cl, error}) 卡内红字提示并 rethrow；新增 submittingRef 防重入（pending 在 await 期间保留，双击不双发）；ClarificationCard 侧 catch 失败避免未处理 rejection，保留输入内容允许直接重发 | r1 失败（node --check 不支持 .jsx ESM 扩展名，工具限制非代码问题）→ r2 通过（esbuild transform 双文件校验） | pass |
| M-05 | live 澄清分支 pendingRef.current 与 setPending 同构，补上 stageId（pendingRef.current = { ...cl, stageId: ev.stage_id }）；submitAnswer 历史回填按 cl.stageId 定位卡片命中，澄清历史末条 answer 不再恒为空、不再每轮显示「（跳过）」 | r1 通过（node --check） | pass |
| M-23 | 前端补齐 error/warn 消费侧（D10 死承诺的消费半）：非 fatal 且带 stage_id 的 error 事件累积到 stage.errors；StageCard 头部左边框变红（红态）+ 展开区渲染 ⚠ 错误行。后端节点降级生产者位于只读子图、D10 总表修订为只读文档，超出本批可写范围，未触碰；warn 事件经 bus→store 字段完整传输由新测试锁定，后续有子图写权限的批次可接生产者 | r1 通过（esbuild 语法校验）→ r2 通过（tests/test_web_b6_pending.py::test_error_warn_event_roundtrip_preserves_fields） | pass |

### 门禁结果

- **G1（本批相关测试，2 个用例）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_b6_pending.py -p no:cacheprovider -q` → **2 passed**（exit 0），pass。
- **G2（离线 web 全量）**：`PYTHONIOENCODING=utf-8 python -m pytest tests/test_web_offline.py -p no:cacheprovider -q` → **53 passed**（exit 0，pytest 9.x 无计数行，按进度标记数核对），pass。
- **G3（全量离线测试）**：**skip**——本批白名单不含 subgraphs/ 与 quality_pipeline/ 生产代码（B6 只改 web 层/前端/测试/配置），全量由后续碰核心管线的批次覆盖。
- **G4（前端构建）**：`cd frontend && npm run build`（vite v6.4.3，313 modules transformed）→ **build 成功**，pass。
- **越界检测**：git status --porcelain 解析改动文件 = `frontend/src/hooks/usePipeline.js`、`frontend/src/components/chat/ClarificationCard.jsx`、`frontend/src/components/chat/StageCard.jsx`、`tests/test_web_b6_pending.py`（本批自建测试文件，沿用 B5 先例属批内），全部在批白名单内，**无越界文件**，未回滚任何文件。
- **结论**：门禁全绿，条目 H-02 / H-18 / M-05 / M-23 全部标记 fixed（web_audit_findings.json 已追加 fix_status）。

## B7 任务标识与状态词表（手动完成，commit 见下）

> 背景：B7 两轮门禁因跨批测试回归失败（B4 的 H-11/H-14 锚点断言 status=='failed'，B7 H-01 词表统一为 'error'；test_web_offline.py 在 B7 白名单外）。中断后由主流程手动重做，同步两处断言兼容 error。

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| CR-03 | 前端全链路 task.id→task.task_id（App/Sidebar/DetailPanel/ChatView/usePipeline 切换 effect）；后端按 D8-4 不补 id 兼容键 | R1（G1/G2/G4 全绿） | pass |
| H-01 | executor 异常终态统一写 error（_finish 不覆写 error）；main.py failed→error 归一；task_store error 筛选兼容 failed；status.jsx 补 failed 别名；Sidebar 失败筛选/重试兼容 | R1 pass | pass |
| M-02 | usePipeline 新增 reset()（task 变 null 清空 messages/stages/timeline/pending/logs + 关 SSE + 重置 refs）；DetailPanel task null 清空各 state | R1 pass | pass |
| L-01 | 后端 _gen_title bus.publish 携带 task_id（修复 emit 关键字/位置参数冲突 TypeError）；前端透传完整事件，App 按 ev.task_id 归属更新 | R1 pass | pass |
| M-08 | list_tasks 显式列 SELECT（task_id,query,title,status,created_at,completed_at），不返回 state_json/pdf_paths；get_task 保持完整 | R1 pass | pass |

### 批次门禁
- G1（test_web_b7_tasks + test_b7_status_vocab）：EXIT=0（含 1 个 xfail 契约登记）
- G2（test_web_offline.py 全量）：EXIT=0（含两处断言同步：`in ("error", "failed")`）
- G3：跳过（B7 白名单不含 subgraphs/quality_pipeline 生产代码）
- G4（npm run build）：EXIT=0
- 越界文件：无

### 备注
- B8-subgraph（M-15/L-08）的 5 个节点文件改动已恢复在工作树，待 B8 批次门禁后随 B8 commit 提交
- B8-quality（H-10/M-13/M-16）在途改动已丢弃，resume 后重跑

## B8 质量管线埋点（主对话完成，commit 见下）

> 背景：B8 门禁 G3 曾报 3 个失败，经复现实验确认为全量负载下时序 flaky（非代码回归）：test_sse_done_ttl 的 0.4s TTL 窗口 vs 0.1s 晚发消息、2 个 executor 轮询测试的 5s deadline 全量下超时。修复：TTL 放宽 2.0s、全部轮询 deadline 5s→20s。B8 代码经中断恢复（备份完成态）重新验证：G1 17 passed、G2 全绿、全量复现仅剩 flaky 1 个（已修）。

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| M-15 | database_query/ads_search/pdf_download/bbox_annotator/figure_extractor 早退路径补发 step 终止事件（failed/skipped + data 摘要） | R1 pass | pass |
| L-08 | figure_extractor 循环内只发 running，completed 循环后统一发 | R1 pass | pass |
| H-10 | human_review 4 类 interrupt + final_confirm_modify 补 question 键；web_runner 兜底 text；options 透传前端渲染按钮 | R1 pass | pass |
| M-13 | graph.py _flow_wrap（flow_started/completed 配对）+ pdf_converter 埋点 + 前端 FLOW_NAMES 消费 | R1 pass | pass |
| M-16 | human_review_node 包 _wrap(HumanReviewAgent) 发 agent 事件 | R1 pass | pass |

### 批次门禁（主对话执行）
- G1（test_b8_telemetry + test_b8_quality_telemetry）：17 passed
- G2（test_web_offline.py 全量）：EXIT=0（含 flaky 稳健性修复）
- G3（全量复现）：备份版仅 1 个 flaky（test_sse_done_ttl）→ 已修 → offline 全量 EXIT=0
- G4（npm run build）：待 B9 前验证

## B9 前端 agent 展示与性能（主对话完成，commit 见下）

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| M-14 | usePipeline agent 分支 traces 累积（mergeTraces 三元组去重 timestamp+field+after，与 quality_state._merge_dict 一致） | R1 pass | pass |
| M-22 | makeInitialStages 初始 agents 统一 null（不再预置 QA_MOCK，真实任务无 M31 演示文案/数字） | R1 pass | pass |
| M-03 | logs 500 环形截断 + LogDrawer 渲染最近 200 行 + 计数分母真实行数 | R1 pass | pass |
| L-09 | StageCard confidence null 不渲染该段（无"置信度 undefined"） | R1 pass | pass |
| L-10 | supplementary_query 表验证前发 substatus + 前端 step_progress 消费 data.substatus + formatStepDetail 分支 | R1 pass（test_b9_telemetry） | pass |

### 批次门禁（主对话执行）
- G1（test_b9_telemetry）：1 passed
- G2（test_web_offline + test_subgraph2）：EXIT=0
- G3（全量 384 测试，后台）：PYTEST_EXIT=0 全绿
- G4（npm run build）：EXIT=0

## B10 上传与任务创建（主对话完成，commit 见下）

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| H-03 | api.js uploadFiles 补 res.ok 检查 + formatErrorDetail；submitQuery 失败冒泡保留输入 | R1 pass | pass |
| M-09 | upload 分块读取 1MB/块累计超限截断（不再整文件入内存 OOM） | R1 pass | pass |
| M-10 | move 逐文件 try/except + pdf_ids 去重；失败回滚置 cancelled + 409 | R1 pass（新测试 409/无孤儿） | pass |
| L-15 | 扩展名白名单（伪装 %PDF 的非 pdf 扩展名 rejected）；同步旧断言兼容两种拒绝文案 | R1 pass | pass |
| L-02 | ChatView 清理移入成功分支（失败保留输入与已选 PDF） | R1 pass | pass |
| L-03 | api.js formatErrorDetail 错误体归一（数组/对象/字符串） | R1 pass | pass |

### 批次门禁（主对话执行）
- G1（新测试 2 个）：pass
- G2（test_web_offline.py 全量）：EXIT=0
- G3：跳过（白名单不含 subgraphs/quality_pipeline）
- G4（npm run build）：EXIT=0

## B11 数据交付导出（主对话完成，commit 见下）

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| M-18 | quality_state.make_initial_state 加 run_id 可选参数；quality_adapter 透传 state.query_id（Web=task_id）→ 导出目录 output/{task_id[:8]}/；get_exports/export_file/open-output 统一扫描导出目录（此前扫 tasks.output_dir 恒空） | R1 pass（新测试 exports 非空 + export 200） | pass |
| L-13 | api.js 补 openFile(taskId,name)；OutputFiles 接 taskId 调真实 POST /open-file（不再 mock toast） | R1 pass | pass |

### 批次门禁（主对话执行）
- G1b（新测试 + test_quality_pipeline）：EXIT=0
- G2（test_web_offline.py 全量）：EXIT=0
- G3（全量 384 测试，后台）：PYTEST_EXIT=0 全绿
- G4（npm run build）：EXIT=0

## B12 安全与图证（主对话完成，commit 见下）

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| H-05 | CORS 白名单（禁 *）；PUT /api/config 校验 X-Requested-With 头（跨源 preflight 即拒）；静态挂载收窄 output/figures/；前端 putConfig 带头 | R1 pass | pass |
| H-06 | get_figures image_url 用 image_path basename（配合收窄挂载，恒 404 修复） | R1 pass（新测试） | pass |
| L-04 | export_file/open-file 改 is_relative_to；open-file name 拒绝分隔符 | R1 pass（新测试） | pass |
| L-05 | .env 重写保留注释行 + 值单行化限长 | R1 pass（新测试） | pass |
| M-01 | SettingsDialog 大写比对（KEY_MAP[f.key].toUpperCase()） | R1 pass（build） | pass |

### 批次门禁（主对话执行）
- G1（test_subgraph3 + test_audit_fixes_retrieval + 新测试 3 个）：EXIT=0
- G2（test_web_offline.py 全量）：EXIT=0
- G3（全量后台）：PYTEST_EXIT=0 全绿
- G4（npm run build）：EXIT=0

## B13 构建部署链（主对话完成，commit 见下）

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| M-19 | vite.config.js 增 preview.proxy（preview 模式 API 可用） | R1 pass（build） | pass |
| M-20 | 后端挂载 frontend/dist 单进程交付（冒烟：GET / 200 index.html + /api/tasks 200）；vite base + VITE_API_BASE 环境注入 | R1 pass（单进程冒烟） | pass |
| H-15 | pyproject dependencies 补 Web 栈 4 依赖 + vcrpy dev extra；README 同步 | R1 pass（import 冒烟） | pass |

### 批次门禁（主对话执行）
- G1：无新测试（配置类，回归锚点=冒烟）
- G2（test_web_offline.py 全量）：EXIT=0
- G3：跳过（白名单不含 subgraphs/quality_pipeline）
- G4（npm run build）：EXIT=0
- 单进程冒烟：GET / → 200（index.html）、GET /api/tasks → 200

## B14 死代码清理（主对话完成，commit 见下）

| 条目 | 怎么修的 | 测试轮次 | 结果 |
|---|---|---|---|
| M-24 | 删 mock/results.js、mock/tasks.js、QualityReport 组件、QA_MOCK（grep 零引用后删） | R1 pass（build） | pass |
| L-12 | 删 useMockPipeline.js（600+ 行无引用钩子） | R1 pass（build） | pass |

### 批次门禁（主对话执行）
- G2（test_web_offline.py 全量）：EXIT=0
- G3：跳过（纯前端批）
- G4（npm run build）：EXIT=0

## 最终验收（P15，主对话执行）

### 全量与构建
- 全量 pytest（384+ 测试，后台）：**PYTEST_EXIT=0 全绿**
- 前端 build：EXIT=0

### 回放模式端到端（LLM_CASSETTE + once，M13 全流程）
| 断言 | 结果 |
|---|---|
| create_task 200 + 任务到达终态 completed | PASS |
| stage 事件覆盖 7 卡（started 4 + completed 含 done/clean/deliver） | PASS |
| clarification 事件（final_confirm，cassette 录制路径决定次数） | PASS |
| task_completed + flow_started/flow_completed（M-13 生效） | PASS |
| SSE seq 严格单调无重复（960 事件，CR-02 生效） | PASS |
| final_output 非空（records=3 sources=5，CR-01 生效） | PASS |
| figures image_url 3/3 可达 200（H-06 生效） | PASS |
| exports 非空（8 文件，M-18 生效） | PASS |
| quality 200 / 已完成 resume 拒绝 409（L-06 生效） | PASS |
| **合计** | **12/12 PASS** |

### 验收发现并修复
- **H-11 回归**：全局 match_on 加 body 误伤 dashscope VLM 请求（prompt 含动态文件名/页码，重放必然不命中 → 任务卡在 extraction）。修复：自定义 `smart_body` matcher——chat/completions 严格 body（防错位），VLM 宽松（可回放）。新增 `test_smart_body_matcher_vlm_loose` 回归锚点。
- 验收客户端自身两处 bug（SSE 错配、PNG 误解析）已修正，不影响产品代码。

### 遗留说明
- 回放模式数据正确性仍受 VCR 不校验语义影响（错位风险已由 H-11/H-12 大幅降低）；最终数据正确性验收建议真实模式跑一次 M13 并重新录制 cassette。

---

## 验收后前端增强迭代（2026-08-13，纯前端，后端零改动）

> P15 最终验收之后的产品化迭代，不属于 60 条审计清单；按时间顺序追加记录。
> 每轮验证方式统一为 `cd frontend && npm run build`（vite 6.4.3）+ 浏览器实机走查。

| 轮次 | 内容 | 关键改动 | 验证 |
|---|---|---|---|
| F1 | DetailPanel 质量/运行 Tab 接线 + 执行统计 + 取消任务 | 质量 Tab 消费 `report_state.quality`（评分/CI/逐来源分数与路由），运行 Tab 消费 `workflow_state` 计数 + `workflow_history` 审计时间线 + `processing_statistics`；工具栏取消按钮 → `POST /cancel` | build 通过 |
| F2 | 毛玻璃风格强化 | `--surface-bg` 降至 74% 半透明、`--glass-bg` 58% + blur 18px、`--bg-ambient` 环境光、`@supports` 兜底 | build 通过 |
| F3 | 记录详情弹窗（RecordDetailDialog） | 记录表行点击 → 居中玻璃弹窗：来源/处理轨迹（per_record_trace）/冲突标注（annotations）/Insight 建议（field_insights）/字段定义；懒加载 getQuality+getSources 缓存；修正路由键归属（per_source_routes 在 report_state.quality 而非 quality_scoring）与 extraction_method chip（vlm_text/vlm_table 前缀判断）；快照验证 5 项血缘匹配率 60+/61 | build 通过 |
| F4 | 工作流下钻补齐工具调用明细 | 排查确认后端无 tool_call 事件、明细在节点级 log；usePipeline 新增 activeStagesRef/activeAgentsRef 同步运行窗口，日志按 agent_started→completed 窗口归属 agent.logs（阶段上限 30→200、Agent 上限 300），修复快照重放期间日志归属整体失效；StageDetailPanel L3 新增"执行日志 · 工具与检查器调用"分区 + Agent 行日志徽章；真实快照模拟 1043 条日志归属命中 1040 | build 通过 |
| F5 | 选项卡过渡动画 | 新增 tab-in 进场动画（淡入+6px 上移，0.24s）应用于 DetailPanel 分区切换与下钻 L2↔L3；主区对话/工作流切换淡入（仅 opacity）；.tab-btn/.filter-chip/.log-chip 状态微过渡；prefers-reduced-motion 降级 | build 通过 |

### 说明
- F1-F5 均遵守「不改后端逻辑」约束，未触碰 `web/`、`astroquery_ai/`、`quality_pipeline/`、`subgraphs/`。
- 设计文档同步：`docs/FRONTEND_INTEGRATION.md` §2/§3/§4/§6/§9/§11 更新并新增 §11A 章节。
