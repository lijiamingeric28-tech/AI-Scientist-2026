# Web 层审计报告（WEB_AUDIT_REPORT）

> 审查日期：2026-08-12 ｜ 审查对象：`astroquery_final/` Web 层（`web/` + `astroquery_ai/web_runner.py` + 前端 `frontend/src/` + Web 相关埋点/测试/VCR 链路）
> 审查方法：8 单元独立初审 + 8 个对抗验证 agent（默认推翻制，仅 confirmed 入报告）+ 动态探针（DP-01~DP-12 在线 / DF-01~DF-04 磁盘取证）
> 对齐基准：docs/AUDIT_REPORT.md（2026-08-10 上轮）的严重度口径与 §5.1「被推翻条目」惯例

## 1. 审查概览

### 1.1 范围与方法

- **8 个审查单元**：W01 前端事件流核心（usePipeline/api.js/mock）｜W02 前端组件层（渲染/props/状态映射）｜W03 Web 后端 API 面｜W04 执行器/事件流/测试基建｜W05 质量管线事件埋点｜W06 任务模型与契约｜W07 部署/构建/VCR 链路｜W08 测试体系
- **两阶段**：每单元独立初审（只读、禁网络/LLM）→ 对抗验证（逐条重读代码尝试推翻、修正行号）；动态层 D1（DP-01~DP-12 在线探针：真实任务运行 + SSE 抓包 + DB 取证）与 D2（DF-01~DF-04 离线磁盘/DB 取证）
- 种子体系：Tier A（9 条，优先复核）/ Tier B（32 条）/ Tier C（6 条探索项），共 47 条种子

### 1.2 统计摘要

| 单元 | 种子 | 种子确认 | 新发现确认 | confirmed | refuted | uncertain |
|------|------|---------|-----------|-----------|---------|-----------|
| W01 前端事件流核心 | 9 | 9 | 9 | 18 | 2 | 0 |
| W02 前端组件层 | 9 | 7 | 15 | 22 | 2 | 0 |
| W03 Web 后端 API | 5 | 5 | 11 | 16 | 0 | 0 |
| W04 执行器/事件流 | 11 | 11 | 8 | 19 | 1 | 0 |
| W05 质量管线事件 | 5 | 3 | 1 | 4 | 1 | 0 |
| W06 契约/VCR 链路 | 1 | 0 | 9 | 9 | 3 | 0 |
| W07 部署/构建 | 5 | 5 | 8 | 13 | 0 | 0 |
| W08 测试体系 | 2 | 2 | 9 | 11 | 0 | 0 |
| **合计** | **47** | **42** | **70** | **112** | **9** | **0** |

> 种子确认口径：按种子归属单元统计（含跨单元终裁映射，如 P2-UPLOAD→W02-05、F15-FE→W01-02、P3-CONFIG-C→W02-01、F17-IMPACT→W04-05、F8-REACH→W04-11、F16-BUG→W05-01[refuted]）。Tier C 的 F7 未获终裁，记入第 7 章局限。新发现 = 本单元 confirmed − 种子确认，合计 70 条。

**confirmed 严重度分布**（去重合并后 60 条）：critical **3** ｜ high **18** ｜ medium **24** ｜ low **15**

**confirmed 类别分布**：state_contract 16 ｜ interface_mismatch 10 ｜ error_handling 7 ｜ test_gap 7 ｜ data_correctness 6 ｜ security 4 ｜ performance 4 ｜ config_drift 4 ｜ logic_bug 4 ｜ dead_code 3 ｜ build_deploy 3 ｜ resource_leak 1

**refuted 分布**：9 条裁决，去重合并后 7 条（W02-07+P3-BBOX、W05-01+F16+F16-BUG 各并一条），见第 6 章。

> 去重说明（同根因合并为主条目，保留全部 file:line 锚点，机器可读文件记 duplicate_of）：W04-01/W05-02/F4 → CR-01；W02-03/P0-1/P0-2/W01-01/W03-02/W01-02 → CR-02；W02-02/W03-05/P1-STATUS → H-01；W02-05/W01-05 → H-03；W03-03/W04-07/F15/F9 → H-04；W03-04/F12/W03-11 → H-05；W03-01/W07-04/F2 → H-06；W04-02/F1/W08-05 → H-07；W04-03/F5 → H-08；W05-03/F10 → H-09；W05-04/F6 → H-10；W07-03/F18 → H-12；W07-08/W08-06 → H-15；W08-07/T2-E2E → H-16；W01-04/P2-SWITCH → H-17；W01-03/P2-409 → H-18；W02-01/P3-CONFIG → M-01；W02-06/P2-NEW → M-02；W02-09/P3-LOG → M-03；W02-13/P1-SNAP/P1-SUMM → M-04；W02-11/W01-06 → M-05；W03-10/W04-11/W04-04/W03-13/F14/F8 → M-06；W04-05/W08-02/F17 → M-07；W03-06/W04-09/F11 → M-08；W05-06/F20 → M-13；W07-09/B1-PROXY → M-19；W07-10/B3-DIST/B2-BASE/B4-ENV → M-20；T1-COVER/W08-01/W08-03/W08-04/W08-08 → M-21；W03-09/F13 → M-11。

## 2. 审查方法与流程

1. **初审（8 finder agents 并行）**：按单元执行维度清单——事件流契约（D1-4 断点续播/SSE 去重/队列语义）、状态机（D2/D5 终态迁移）、安全面（CORS/认证/静态挂载/路径白名单）、性能（日志洪泛/全量重放/大体积响应）、部署链（vite preview/dist 承载/依赖声明）、测试缺口（端点覆盖/E2E 断言强度）。
2. **对抗验证（8 verifier agents 并行）**：逐条重读 `file:line` ±30 行独立推演失败链，**默认 refute**；仅能独立证毕才判 confirmed；行号有误但问题成立 → confirmed + corrected_line；需网络/LLM 才能判定 → uncertain。动态层对 12 个关键机制打探针（DP-01 图证 URL、DP-02 exports、DP-04 summary 0/0、DP-07 陈旧答案、DP-08 取消事件、DP-10 流无结束、DP-11 日志洪泛、DP-12 双通道一致性等），DF-01~DF-04 对 web/data/tasks.db、cassette、output/ 目录做磁盘取证。
3. **合成**：同根因去重 → 按严重度分级 → 契约对照（confirmed 条目的 contract_ref 合并 + SSE 事件逐一对照）→ 本报告 + 机器可读 `web_audit_findings.json`。**0 条 uncertain**（所有候选均在静态+探针约束下证毕或证伪）。

**严重度定义**（沿用上轮）：critical = 主路径静默错误数据/必然崩溃/安全/契约断裂；high = 边缘路径错误/重试缺陷/资源泄漏；medium = 死代码/配置漂移/性能/统计不准；low = 影响极小。

**动态证据要点**：DP-04 两任务 summary 恒 0/0（实际 6/3、7/3 条记录）｜DP-07 74 次幽灵 resume 全 200 且陈旧答案被自动消费｜DP-08 queued 取消 0 事件｜DP-10 SSE 流永续｜DP-11 单任务 425 条 log 占事件 76%｜DP-12 542 事件集快照与 SSE 双通道各交付一次｜DP-01 16/16 图证 URL 404｜DP-02 exports 恒空而磁盘 8-hex 目录真实存在｜DF-01 全库 0 条 task_cancelled/task_failed/task_title_ready/flow_*，10/10 澄清 question 为空｜DF-03 46 个 8-hex 导出目录与任务时刻一一对应。

## 3. 总体结论

### 3.1 子系统健康度

| 子系统 | 评价 | 关键问题数 |
|--------|------|-----------|
| 前端事件流核心（usePipeline/api.js） | **高风险**。SSE 双份应用+重连全量重放（CR-02）为任何任务打开必现；澄清生命周期三缺陷（H-02 输入锁死/H-18 无回滚/H-04 陈旧答案）叠加 | C1/H5/M6/L3 |
| 前端组件层 | **中等偏高**。状态词表 failed/error 断裂（H-01）、task.id 断链（CR-03）导致失败与历史功能不可用；大量展示层失真（M-01~M-05） | C1/H2/M7/L2 |
| Web 后端 API 面（W03） | **高风险**。安全面（CORS*/零认证/静态全树暴露）与契约断裂密集；上传/SSE 队列/图证/导出均有系统性失效 | C1/H5/M6/L5 |
| 执行器/事件流（W04） | **高风险**。卡 7 总结陈旧 state（CR-01）主路径必现；超时/cancel 状态机分叉（H-07/H-08/H-09）；测试 fixture 污染真实 DB（M-07） | C1/H3/M5/L4 |
| 质量管线事件埋点（W05） | 中等。HITL question 恒空（H-10）使人工审核 Web 端不可用；flow 事件未实现、traces 展示丢失 | C0/H2/M4/L2 |
| 契约/VCR 链路（W06） | **高风险**。回放顺序错配/并发竞态/密钥泄露/静默真实调用四重问题，回放模式数据可信度存疑 | C0/H5/M2 |
| 部署/构建（W07） | 中等。依赖声明缺失致新环境装不起来（H-15）；构建产物无承载方、preview 失效 | C0/H1/M3/L2 |
| 测试体系（W08） | 中等。离线覆盖缺口大（M-21）、E2E 断言仅存在性（H-16）、恒真断言（并入 M-21） | C0/H1/M2/L1 |

### 3.2 关键风险 Top 10

| # | 风险 | 严重度 | 一句话影响 |
|---|------|--------|-----------|
| 1 | 卡 7 总结读取陈旧 result（`web_runner.py:158`，DP-04 实证 2/2） | **critical** | 每个完成任务的消息恒报「0 个数据源、0 条记录」，主路径静默错误数据 |
| 2 | SSE 快照+after_seq=0 双份应用、断线重连全量重放（`usePipeline.js:188`/`api.js:88`，DP-12 实证） | **critical** | 打开任何历史任务消息/日志/澄清历史翻倍，重连再次翻倍；已答澄清卡重弹 |
| 3 | 前端 task.id vs 后端 task_id 断链（`App.jsx:31`/`task_store.py:89`） | **critical** | 历史回看不可用、右侧面板与结果区对新任务永久空白 |
| 4 | CORS * + 零认证 + 静态挂载整个 output/（`main.py:96/486`） | high | 恶意网页可读全部任务数据与用户 PDF、改 .env 投毒、触发 os.startfile |
| 5 | 图证 image_url 双错位恒 404（`main.py:310`，DP-01 16/16 404） | high | 图证 Tab 全裂图，D7-3/D9-4 功能整体失效 |
| 6 | 澄清超时 15min 任务终态被覆写 completed（`executor.py:86-92/155-161`） | high | DB「已完成」与事件流「已取消」分叉，DF-01 全库 0 条 task_cancelled 佐证 |
| 7 | resume 不校验挂起状态 + /state 陈旧 pending（DP-07 74 次幽灵 resume 全 200） | high | 陈旧答案自动消费进下一轮真实澄清，HITL 决策污染 |
| 8 | VCR 回放不校验 body + 并发无锁 + cassette 缺失静默真实调用 + 明文密钥 | high×4 | 回放错位数据、并发错配、真实计费、仓库泄露有效凭证 |
| 9 | 失败任务状态词表断裂（executor 写 failed，前端用 error） | high | 失败任务显示「未知」、从失败筛选消失、重试按钮永不出现 |
| 10 | exports 恒空（run_id 随机目录与任务解耦，DP-02/DF-03 实证） | high | 数据交付（D9）功能整体失效，输出文件区永远为空 |

## 4. 按严重度问题清单

### 4.1 Critical（3 条）

**CR-01. 卡 7 最终总结读取陈旧 result：所有完成任务恒报「0 个数据源、0 条记录」（主路径静默错误数据）**
- **位置**：`astroquery_ai/web_runner.py:158`（on_final_summary 回调）→ `astroquery_ai/main_graph.py:158-161`（wrap finally）→ `web/summary.py:64-85`（降级模板）；web/main.py:59-61
- **类别**：data_correctness ｜ **契约**：D6-3
- **失败场景**：quality_finalize 是 END 前必经节点，mode="end" wrap 的 finally 在 `app.invoke` 尚未返回时同步发 `stage_completed(done)`；闭包 result 此时仍是 `{}`（首轮）或上一轮 `__interrupt__` dict，恒无 final_output → `generate_final_summary` 得空 state → n_sources=n_records=0 → LLM prompt 与降级模板均报「共提取 0 个数据源、0 条记录」。DP-04 动态实证 2/2 独立任务：message（seq 3583/4125）报 0/0，实际 final_output sources=6/records=3 与 sources=7/records=3。
- **证据链**：web_runner.py:140 `result={}`；:175/:182 invoke 返回后才赋值；main_graph.py:159-161 finally 先于 invoke 返回触发；summary.py:64 `final = (state or {}).get("final_output") or {}`；CLAUDE.md §7.7 声称已修实未修——修复只把「从 store 读快照」换成「闭包 result」，取值时刻仍早于最终赋值，:157 注释「当前最终 state」与代码事实不符。
- **修复建议**：总结生成移到最后一次 app.invoke 返回之后（runner 尾部、发 task_completed 之前），或 wrap finally 把 fn 返回值经 event_cb 一并传出、_events 用之；删除误导注释。回归锚点：DP-04 场景红测——假图发 done 事件后断言 on_final_summary 收到含 final_output 的 state；E2E 断言 summary 数字与 records 实际数一致（与 H-16 联动）。
- **验证**：confirmed（W04-01/W05-02/F4，三 agent 独立证毕；由 high 上调 critical：主路径 100% 复现静默错误数据）

**CR-02. SSE 事件双份应用 + 断线重连全量重放：消息/日志/澄清历史重复、已答澄清卡重弹（D1-4 断线续播未实现）**
- **位置**：`frontend/src/hooks/usePipeline.js:172-191`（快照重放后 openEventStream 不传 afterSeq）、:65/72（lastSeqRef 只写不读）、:74-76/:122-134/:140-141（无条件 append）；`frontend/src/services/api.js:88-89`（after_seq=0 默认）、:96-99（onError 空）；`web/main.py:250-251`（每次连接全量回放）、:184（快照返回全部事件）
- **类别**：state_contract ｜ **契约**：D1-4 / D8-3
- **失败场景**：openTask 先 `events.forEach(applyEvent)` 重放快照全部事件（:175），随后 :188 以 after_seq=0 开 SSE → 服务端再全量回放同一事件集；message/log/clarification 无条件 append 无 seq 去重（stage 时间线有 some() 守卫不重复）；EventSource 自动重连复用同一 URL（仍 after_seq=0）→ 每次重连再次翻倍。DP-12 实证：同一 542 事件集经 /state 快照与 SSE after_seq=0 回放各交付一次；DP-11 单任务 425 条 log → 打开历史任务日志即 850 行、对话消息双份。重放 clarification 事件绕过 main.py:187-191 的 running 守卫把已答澄清重弹为 pending 卡（W01-02 证实），用户再提交 → 409。
- **证据链**：usePipeline.js:65/72 lastSeqRef 写入后全仓库无其他读取（grep 证实）；api.js:88-89 `afterSeq=0` 默认；main.py:250-251/184；DP-12/DP-11 动态闭合。
- **修复建议**：① 快照重放后把 lastSeqRef.current 传给 `api.openEventStream(taskId, handlers, lastSeqRef.current)`；② applyEvent 开头按 ev.seq 幂等去重；③ EventSource 无法改重连 URL → onerror 中 close 并用 lastSeq 重建流（或改 fetch ReadableStream 带参重连）；④ 按 D8-3 提供独立 HTTP 事件数组端点供历史回看，SSE 只做实时。回归锚点：DP-12 一致性断言（快照重放 + SSE 续播后无重复 seq）；重放 clarification 不置 pending。
- **验证**：confirmed（W02-03/P0-1/P0-2/W01-01/W03-02/W01-02 六裁决同根合并）

**CR-03. 前端任务对象用 task.id 而后端/契约返回 task_id：历史回看、右侧面板、结果区全链路断链**
- **位置**：`frontend/src/App.jsx:31`（find(t.id===selectedId)）；`frontend/src/components/layout/Sidebar.jsx:118-122/160`（task.id）；`frontend/src/components/layout/DetailPanel.jsx:76-99`（if(!task?.id) return 守卫内五个接口）；`frontend/src/components/chat/ChatView.jsx:171`（ResultTabs taskId=task?.id）；`frontend/src/hooks/usePipeline.js:195-200`（切换 effect 以 task?.id 为门）；`web/task_store.py:89`（dict(r) 无 id 键）
- **类别**：interface_mismatch ｜ **契约**：D8-4
- **失败场景**：list_tasks 返回 items 含 task_id 无 id（全仓库后端无任何 id 兼容键，仅 mock/tasks.js 用 id）→ 点侧边栏 onSelect(task.id=undefined) → selectedId=undefined → selected=null → openTask 不触发 → 历史回看死；新建任务 submitQuery(task.task_id) 直开流可跑，但 DetailPanel 守卫与 ResultTabs `if(!taskId) return` 使右侧栏与记录表对新任务也永远空白；handleRetry 传 undefined → POST /api/tasks/undefined/retry 404。
- **修复建议**：推荐前端统一改 task.task_id（App.jsx:31 find、Sidebar key/onSelect/onRetry、DetailPanel 守卫与五个调用、ChatView:171、usePipeline.js:195-200、App.jsx:90 handleTaskTitle 同步改）；或后端 list_tasks/get_task 补 `id=task_id` 兼容键（不推荐，与 D8-4 键名相悖）。回归锚点：侧边栏点击历史任务 → DetailPanel 拉取五接口、ResultTabs 渲染记录表。
- **验证**：confirmed（W06-01）

### 4.2 High（18 条）

**H-01. 失败任务状态词表断裂（后端只写 failed，前端全链路用 error）：徽标「未知」、失败筛选恒空、重试按钮永不出现**
- **位置**：`web/executor.py:149`（唯一失败写入 status="failed"）、:160（failed/cancelled 不覆写）；`frontend/src/components/status.jsx:3-17/37-38`；`frontend/src/components/layout/Sidebar.jsx:31/42/156`；`frontend/src/App.jsx:35`；`web/task_store.py:79-83`（SQL 精确匹配）
- **类别**：interface_mismatch ｜ **契约**：D2-4 / D8 状态映射表
- **失败场景**：全仓 grep 无任何 status='error' 写入，真实执行线程异常（executor.py:146-150 路径）时失败任务 status='failed' → STATUS_LABELS 无 failed → 灰点「未知」；失败筛选 key='error' → 前端过滤恒空且传给后端 status='error' → SQL 0 行；:156 重试条件 status==='error' 恒假 → D2-4 重试入口在 UI 永不出现。契约自身不一致：D2 状态机定 failed、D8 前端映射表定 error，两端各实现一半。
- **修复建议**：单点定义终态枚举——后端统一为 error（executor.py:149 同步改），或两端接受别名（status.jsx 补 failed 映射、Sidebar 失败档匹配 failed、list_tasks 对 status=error 同时匹配 failed），以契约 D8 表为准并修正 API_CONTRACT 的 D2 状态机文案。回归锚点：注入 status='failed' 任务断言徽标红色「失败」、失败档可见、重试按钮出现。
- **验证**：confirmed（W02-02/W03-05/P1-STATUS）

**H-02. task_cancelled/澄清超时后 pending 不清理：输入栏永久禁用、无「澄清超时，任务已取消」提示（D10-3 违约）**
- **位置**：`frontend/src/hooks/usePipeline.js:145-151`（task_cancelled/task_failed 只 setTaskDone）、:135-139（error(fatal) 丢弃 ev.message）；`frontend/src/components/chat/ChatView.jsx:106/244/263/269/123`（clarifying=!!pending 恒 true）；`web/executor.py:87`（fatal 错误文本）
- **类别**：state_contract ｜ **契约**：D10-3
- **失败场景**：澄清卡挂起 15 分钟无回答 → 后端发 error(fatal,"澄清超时（15 分钟），任务已取消")+task_cancelled → 前端只 taskDone、pending 残留 → ChatView clarifying 恒 true → 输入框与提交永久 disabled、handleSubmit 提前 return；无任何「已取消」灰卡或提示文字（对照 useMockPipeline.js:599-600 会 patchStage cancelled + addMessage「查询已取消」未在真实管线复刻）。新建按钮（App.jsx:61）只清 selectedId 不清 pending（叠加 M-02），用户必须切换其他任务才解困。
- **修复建议**：① task_cancelled/task_failed/error(fatal) 分支统一 `setPending(null); pendingRef.current=null`；② fatal error 的 ev.message 追加为 AI 消息（满足 D10-3 显式提示）；③ 挂起澄清所属 stage 置 cancelled 灰态。回归锚点：构造超时事件序列断言输入框恢复可输入、提示消息存在、卡片灰态。
- **验证**：confirmed（W02-04）

**H-03. 上传失败静默放行：uploadFiles 无 res.ok 检查，任务无 PDF 静默创建执行，错误原因丢失**
- **位置**：`frontend/src/services/api.js:24-28`（裸 fetch().then(r=>r.json())）；`frontend/src/hooks/usePipeline.js:206-210`（`if (up.rejected?.length) throw` 跳过 undefined）；`web/main.py:126-128`（pdf_ids 默认 []）
- **类别**：error_handling ｜ **契约**：D4-2 / D10 错误处理总表
- **失败场景**：上传 4xx/5xx（磁盘满 500、422 等）响应体 JSON {detail} 正常解析不抛错 → up.rejected undefined、pdfIds=undefined → JSON.stringify 丢弃 undefined pdf_ids → 后端默认 [] → 任务不带任何用户 PDF 静默创建执行；契约要求失败 toast + 输入框保留，此处连 toast 都没有（catch 只接 throw 路径），ChatView finally 还清空输入与文件（叠加 L-02）；若 404 返回 HTML 则 r.json() 抛 SyntaxError，报错信息完全失真。
- **修复建议**：uploadFiles 复用 request() 的 res.ok 检查（`if (!r.ok) { 解析 detail; throw }`）；submitQuery 上传失败时保留已选文件 chip 供重试。回归锚点：mock 上传 500/422 断言抛错、无任务创建、文件 chip 保留。
- **验证**：confirmed（W02-05/W01-05，verifier 补正失败链为「任务无 PDF 静默创建」而非 400）

**H-04. resume 不校验真实挂起状态 + /state 把已答复澄清当 pending：陈旧答案自动消费进下一轮真实澄清**
- **位置**：`web/executor.py:164-169`（slot 存在即 set_answer 返回 True）、:84-92（wait 是唯一挂起点）；`astroquery_ai/web_runner.py:78-93`（_AnswerSlot 无 waiting 标志，reset 后仍可预置）；`web/main.py:186-191`（status=running 取最后一条澄清事件为 pending_clarification）、:199-204（409 语义不校验挂起）
- **类别**：state_contract ｜ **契约**：D5-1 / D5-4
- **失败场景**：slot 自 _start_locked 创建至 _finish 才 pop，任务运行全程存在 → 非等待期 POST /resume 恒 200 并 set_answer；get_answer 的 wait 在事件已置位时立即返回 → 陈旧答案被下一次真实澄清（final_confirm/human_review）未经用户确认自动消费。DP-07 动态实证：首澄清出现前 1.5s 提交 resume "garbage" → 200 被接受 → 无人再提交即被自动消费 → 图重入澄清子图 → 第 2 个澄清阻塞至外部 cancel；主任务 74 次幽灵 resume 全部 200。/state 对 running 任务返回最后一条澄清事件（已答复不消失）→ 重连/重开时误显挂起卡，配合重放（CR-02）注入陈旧答案。
- **修复建议**：① _AnswerSlot 加 waiting 标志：wait 前置 True、返回后置 False，resume 仅 waiting 且未 cancelled 时 set_answer，否则返回 False → HTTP 409；② GET /state 的 pending_clarification 改由 executor 暴露真实挂起状态；③ 前端收到 409 收起澄清卡。回归锚点：DP-07 红测——非等待期 resume 断言 409、/state 对已答复澄清返回 null。
- **验证**：confirmed（W03-03/W04-07/F15/F9）

**H-05. CORS allow_origins=* + 全端点零认证 + 静态挂载暴露整个 output/：数据外泄、配置投毒、任意写操作**
- **位置**：`web/main.py:96`（CORSMiddleware * 全路由）；:452-479（PUT /api/config 无认证写回 .env）；:391-410（open-file/open-output → os.startfile）；:486（`StaticFiles(directory=OUTPUT_DIR)` 暴露 output/ 全树含 user_pdfs/ 与导出文件）
- **类别**：security ｜ **契约**：D10-1 / D10-2 / D9-4
- **失败场景**：恶意网页跨源 fetch 直连 http://127.0.0.1:8000（简单请求免预检，响应带 ACAO:* 可读；PUT 预检也被 * 放行）→ 读取全部任务数据（/api/tasks、/state、/records）、/static/figures/<tid>/user_pdfs/*.pdf 与导出 json/csv（get_exports 返回全部文件名可作枚举字典）；PUT /api/config 可改写 .env（重启后 base_url 投毒把 LLM 流量导向攻击者服务器；verifier 补正：get_settings 为 lru_cache、进程内不生效，投毒仅在重启后生效）；open-file 触发 os.startfile。verifier 修正 finder 一处事实错误：uvicorn 0.51 默认 host=127.0.0.1，「局域网/公网可达」不成立，但浏览器同机跨源直连 127.0.0.1 攻击面成立（Firefox/Safari 无 PNA 缓解）。
- **修复建议**：① CORS 白名单（http://localhost:5173、http://127.0.0.1:5173），禁用 *；② 本地会话认证（启动 token + Host 头 + 随机端口校验）；③ 静态挂载收窄到 `StaticFiles(directory=OUTPUT_DIR/"figures")`（导出与 user_pdfs 不再静态可达，与 H-06 修复联动）；④ PUT /api/config 至少要求自定义 X-API-Token 头。回归锚点：跨源 fetch 断言无 ACAO:*；/static/figures/<tid>/user_pdfs/ 与导出文件 404。
- **验证**：confirmed（W03-04/F12/W03-11）

**H-06. 图证 image_url 双错位恒 404：读错键（file_name 不存在）+ 缺 figures/ 路径段，D7-3/D9-4 图证功能整体静默失效**
- **位置**：`web/main.py:310`（`f"/static/figures/{task_id}/{f.get('file_name','')}"`）；:486（挂载根=OUTPUT_DIR）；`subgraphs/subgraph3/nodes/figure_extractor.py:116-133`（写 image_path='figures/<tid>/<fname>'，无 file_name 键）；`frontend/src/components/layout/DetailPanel.jsx:24-27`（非空 image_url 直渲 <img>）
- **类别**：interface_mismatch ｜ **契约**：D7-3 / D9-4
- **失败场景**：双重错位——(a) 端点读不存在的 file_name 键恒得空串；(b) 挂载根是 output/，正确 URL 需多一个 figures/ 段。DP-01 动态实证 16/16 条 image_url 均以空 file_name 结尾且 HEAD 404；磁盘真实文件 2013MNRAS.430..459D_p1_f1.png 经 `/static/figures/figures/{tid}/{fname}` 构造的 URL 200；bbox 恒 None（figure_evidence 无 bbox_2d/bbox 键）。任务完成→state_json 写 figure_evidence→get_figures 返回坏 URL→前端破图，图证 Tab 全裂。
- **修复建议**：image_url 改直接拼接生产字段 `f"/static/figures/{f.get('image_path','')}"`（image_path 已含 figures/<tid>/<fname>，配合当前 output/ 挂载根）；或按 H-05 收窄挂载根到 output/figures 并把 URL 改 /static/figures/<tid>/<fname>；bbox 按契约 D7-3 定为可选字段或生产侧补取。回归锚点：DP-01——对 output/figures/<tid>/ 真实文件断言 image_url 200。
- **验证**：confirmed（W03-01/W07-04/F2）

**H-07. 澄清超时（D5-3，15 分钟）任务终态被覆写为 completed：事件流 task_cancelled 与 DB completed 直接矛盾**
- **位置**：`web/executor.py:86-92`（超时分支仅 bus.error(fatal)+slot.cancel()+return None，无 DB 更新）；:155-161（_finish 见 status='running' 不在 failed/cancelled 集合 → 强制 completed）；`astroquery_ai/web_runner.py:147-149`（发 task_cancelled + raise _CancelledError）；:185-187（内捕后正常 return，异常不冒泡）
- **类别**：state_contract ｜ **契约**：D5-3 / D10-3
- **失败场景**：15 分钟无回答 → 事件流发 fatal error + task_cancelled，DB 却经 _finish 置 completed；侧边栏绿色「已完成」与对话流「已取消」并存，三处矛盾（DB/事件流/中断残留快照）。verifier 修正：executor.py:148 引用不实（那是通用 except 分支，超时路径被 _CancelledError 内捕不命中）；DF-01 佐证状态机断裂（全库 0 条 task_cancelled、9 个 cancelled 任务 completed_at 批量 UPDATE 特征）。
- **修复建议**：超时分支与 cancel 对齐：get_answer 超时同步 `update_task(status="cancelled", completed_at=...)`；或 _finish 前检查 slot.cancelled 为真则跳过 completed 覆写。回归锚点：W08-05 红测——注入短超时后断言 DB status=='cancelled' 且事件含 task_cancelled/error fatal。
- **验证**：confirmed（W04-02/F1/W08-05）

**H-08. cancel 不终止执行线程（D1-8 未兑现）+ queued 取消无任何事件通知**
- **位置**：`web/executor.py:171-181`（仅 slot.cancel()+update_task(cancelled)，零事件）；`astroquery_ai/web_runner.py:147`（should_cancel 仅在澄清边界检查）；:155-160（图照常发 stage_completed(done)+task_completed）
- **类别**：state_contract ｜ **契约**：D1-8
- **失败场景**：非澄清阶段（检索/VLM/质量管线，分钟级）取消后图照常跑至 END 并发完成事件——场景 A 浪费 LLM/网络费用且同任务双终态（DB 已取消 vs 事件流完成）；queued 分支（:177-180）只改 DB。DP-08 动态实证：queued 取消 200/status=cancelled 但 SSE 全文件 0 处 task_cancelled、流保持打开；澄清中取消事件正常送达（seq 4462）——「永远收不到」修正为「仅 queued 与计算中途成立」。
- **修复建议**：① 取消检查下沉到 main_graph wrap 节点边界（进入/退出节点时检查 should_cancel 并抛 _CancelledError）；② cancel 时立即 bus.emit(task_cancelled, reason='cancelled')（含 queued 分支）；③ runner 发 task_completed 前检查 should_cancel，已取消只发 task_cancelled。回归锚点：DP-08——queued 取消断言收到 task_cancelled。
- **验证**：confirmed（W04-03/F5）

**H-09. 取消路径（final_confirm 选 n）发 task_completed 而非 task_cancelled，且 understand 卡 stage_completed 永久缺失**
- **位置**：`astroquery_ai/main_graph.py:88-90`（cancelled→aggregation 跳过 property_std）、:166-172（stage_completed 仅 property_std/quality_finalize 发）；`subgraphs/subgraph1/nodes/final_confirm.py:137-141`（置 clarification_status="cancelled"）；`astroquery_ai/web_runner.py:155-160`（无条件发 message+task_completed）；`web/executor.py:160-161`
- **类别**：state_contract ｜ **契约**：D5-5（选 n → task_cancelled 统一灰态）
- **失败场景**：选 n → 路由 aggregation → quality(空数据 skipped) → quality_finalize wrap finally 无条件发 stage_completed(done) → runner 发 message(ai 总结)+task_completed；全链无 task_cancelled、DB 置 completed；understand 的 stage_started 已发（mode="start"）但 stage_completed 永不发 → 卡 1 永久「进行中」。DP-06 实证 started/completed 不配对（取消任务 started=1/completed=0，1 次澄清 started=2/completed=1 的重复 start 亦实证）。
- **修复建议**：① runner 循环退出后检查 result.clarification_status=="cancelled" → 发 task_cancelled 而非 task_completed；② _finish 对 cancelled 不覆写（与 H-07 同机制）；③ 取消/非天文分支补发 understand stage_completed(status="cancelled")；④ wrap 内对已启动未完成的 stage_id 去重（抑制澄清重入的重复 stage_started）。回归锚点：选 n 断言事件流含 task_cancelled 且无 task_completed、卡 1 灰态。
- **验证**：confirmed（W05-03/F10）

**H-10. HITL 澄清 question 恒空：human_review 与 final_confirm_modify 的 interrupt payload 只有 text 键，Web 端人工审核卡无任何指引**
- **位置**：`subgraphs/data_human_review/human_review_agent.py:151/449/463/483/505/531`（human_review_next/verdict/custom_value/reason 均只有 text/options）；`subgraphs/subgraph1/nodes/final_confirm.py:118-122`（final_confirm_modify 只有 {type,title,text}）；`astroquery_ai/web_runner.py:113`（`raw.get("question","")` 恒空）；`frontend/src/components/chat/ClarificationCard.jsx:54`（question 门控「原文」按钮、:119 description 恒假）
- **类别**：interface_mismatch ｜ **契约**：D3-2（结构化 {cl_type,title,fields,question}）
- **失败场景**：web_runner 只读 question 键，但 6 个 human_review interrupt 与 final_confirm_modify 均无该键（text 被丢弃）→ 澄清事件 question=""；前端 human_review 无 fields/无 quickButtons/无 options/无 question → 只剩 title+空输入框，用户无从得知应输入 [1]提交裁决/[2]送回评估/[3]取消 或裁决 1-5，HITL 人工审核在 Web 端实际不可用。DP-05 实证 3 任务 5 个真实澄清 question 全空（fields 带值）；DF-01 10/10 clarification question 为空。
- **修复建议**：生产端 interrupt payload 补 question 键（取 text 指引去分隔符）；web_runner 兜底 `question = raw.get("question") or raw.get("text", "")`；透传 options 并在 CLARIFICATION_QUICK_BUTTONS 补 human_review 类型。回归锚点：DP-05——构造 human_review interrupt 断言澄清事件 question 非空、前端渲染快捷选项。
- **验证**：confirmed（W05-04/F6）

**H-11. VCR 回放不校验请求 body（match_on 默认不含 body）：prompt 与录制不同时静默返回错位响应**
- **位置**：`web/executor.py:104-107` 与 `tests/test_e2e_recorded.py:34-38`（均未指定 match_on）；`vcr/config.py:38`（默认六元组 method/scheme/host/port/path/query）；`web/summary.py:46-59`（_is_usable_summary 为下游兜底补丁）
- **类别**：logic_bug
- **失败场景**：所有 LLM 调用为 POST 同 URL（/chat/completions），回放按「同 URL 首个未播放」顺序交付录制响应，与当前请求内容无关 → 查询串/实体/数值错位、静默错误数据。项目自证：CLAUDE.md §5.1「查询串 1 个/6 篇/0 条/bbox 全失败」即此机制；summary.py 的防透传校验仅兜住卡 7 总结。
- **修复建议**：LLM 回放专用 match_on 增 "body"（POST 按请求体区分 prompt；GET/下载请求 body 为空不受影响）；回放前校验 cassette 记录的 query/首条 prompt 与当前查询一致，不一致拒绝回放。回归锚点：修改 prompt 后回放断言不命中旧交互。
- **验证**：confirmed（W07-06）

**H-12. vcrpy 8.3.0 无任何线程锁：15 并发 VLM 回放 play_counts 检查-自增非原子 → 响应错配/越界抛异常**
- **位置**：`tests/cassettes/m13_query.yaml:273903-280409`（54 条同 URL VLM 交互，req 跨 232s、相邻完成间隔中位 618ms << 单请求 4s，证明并发形态）；`subgraphs/subgraph3/nodes/vlm_extractor.py:86`（ThreadPoolExecutor max_workers=15）；`vcr/cassette.py:258-268`（play_response 无锁非原子）；vcr/stubs 全文件 grep 零锁原语
- **类别**：logic_bug
- **失败场景**：回放期两线程可同时通过 `play_counts[index]==0` 检查取走同一记录（每个请求得到另一篇论文的响应），其余记录被跳过；54 次消费完后任何重试 → write_protected → CannotOverwriteExistingCassetteException → vlm_extractor 捕获记 extraction_failed（静默）。F18（回放按完成序消费与录制请求序不一致的错位机制）与 D8 种子同家族并入本条目（verifier 修正：错位「必然发生」过强，但贡献性成立）。
- **修复建议**：对 Cassette 实例（或 executor 级）加 RLock 串行化 play_response 检查-自增；回放模式 VLM max_workers 降为 1；match_on 加 body 不能防同 URL 竞态，锁才是根治；录制端对并发同 URL 请求串行化。回归锚点：多线程并发回放断言无重复消费 seq。
- **验证**：confirmed（W07-03/F18）

**H-13. tests/cassettes/m13_query.yaml 明文记录真实 API Bearer 密钥且未 .gitignore：提交/分发即泄露**
- **位置**：`tests/cassettes/m13_query.yaml:22-23`（`authorization: Bearer sk-ws-H.EDIIHIY...`，deepseek 交互同）、:280430 附近；`.gitignore:1-33`（无 tests/cassettes/ 条目）；`tests/test_e2e_recorded.py:10-11`（明确「gitignore 建议保留」）
- **类别**：security
- **失败场景**：141 条交互请求头均含明文 Bearer（录制期真实 200 调用，为有效工作空间级凭证）；58MB cassette 作为赛题交付物提交/打包/分发即外泄，任何人可冒用计费 API 与工作空间资源。密钥有效性未在本轮复测（禁止网络），但来源为真实 200 调用。
- **修复建议**：.gitignore 增 `tests/cassettes/*.yaml`；录制用 `filter_headers=[('authorization', None)]` + filter_query_parameters 脱敏；立即轮换已泄露的 MaaS/DeepSeek 密钥。回归锚点：grep cassette 断言无 authorization 键。
- **验证**：confirmed（W07-05）

**H-14. LLM_RECORD_MODE 默认 'once'：cassette 缺失时 vcrpy 静默降级为真实录制（真实计费），日志仍谎报 "(replay)"**
- **位置**：`web/executor.py:27`（`os.environ.get("LLM_RECORD_MODE","once")`）、:109-110（无论 mode 恒打印 "(replay)"）；`vcr/cassette.py:360-369`（_load 捕获 CassetteNotFoundError → rewound=False）、:224（write_protected 仅 rewound 时成立）；stubs/__init__.py:287-310（未匹配真实发送并 append）
- **类别**：config_drift
- **失败场景**：once 模式写保护仅当文件存在；LLM_CASSETTE 拼错/未录制/换机器 → 全任务真实调用真实 .env 密钥（计费、结果与录制不同），退出时 _save 全量重写 58MB；日志「VCR cassette loaded: 0 interactions (replay)」造成回放已生效假象。回放（离线）保证完全依赖「文件存在」这一隐性前提。
- **修复建议**：默认值改 'none'（未匹配即抛错，显式录制才用 all/once）；启动校验：设置 LLM_CASSETTE 但文件不存在 → 启动直接报错退出；日志同时打印 mode 与 interactions 数。回归锚点：cassette 缺失时断言启动失败而非发请求。
- **验证**：confirmed（W07-07）

**H-15. pyproject.toml/requirements 未声明 web 栈运行时依赖：全新环境按文档安装后装不起来**
- **位置**：`pyproject.toml:10-34`（无 fastapi/uvicorn/sse-starlette/vcrpy）、:36-44（dev 无 vcrpy）；`astroquery_ai/requirements.txt`（三者皆无）；`web/main.py:19-24/504`；`web/executor.py:101`；`astroquery_ai/web_runner.py:22`（langgraph_checkpoint_sqlite 为独立包，langgraph-1.2.8 METADATA 不传递引入）
- **类别**：config_drift
- **失败场景**：全新环境按 README `pip install -r astroquery_ai/requirements.txt` 后启动后端在 web_runner 导入即 ModuleNotFoundError（回放模式再叠加 vcrpy 缺失任务 ImportError → failed）；pytest 收集即挂。当前环境能跑是 site-packages 偶然完备，非声明保证。verifier 修正：requires-python ">=3.10" 与 log_bridge 不存在版本错配（该部分 finder 自否，同意）。
- **修复建议**：dependencies 增 fastapi>=0.110、uvicorn>=0.25、sse-starlette>=1.6、langgraph-checkpoint-sqlite>=2.0，vcrpy 放 dev extra；同步 README。回归锚点：干净 venv 按文档安装后 import web.main 成功。
- **验证**：confirmed（W07-08/W08-06）

**H-16. test_e2e_recorded 断言仅存在性：VCR 错位数据（项目自述头号已知问题）下全绿；bus_events 收集后从未断言**
- **位置**：`tests/test_e2e_recorded.py:73-85`（5 条断言全为存在性：in types ×3、clar≥1、'records' in final）、:48-53（bus_events 死代码）
- **类别**：test_gap
- **失败场景**：零内容/零数值/零顺序断言 → 查询串错、数值荒诞、0 条记录全部放行（'records' 键存在不等于非空/正确）；仅澄清次数>2 时才以 StopIteration 显式失败；唯一自动化 E2E 防线对项目自述头号已知问题完全无感。
- **修复建议**：断言锚点：① final["target_entity"]=="M13" 且 requested_properties 含 距离/年龄/金属丰度；② records 非空且每条 field_name/field_value/field_unit 非空；③ 7 卡 stage_started 全集与 stage_completed 配对；④ 事件 seq 严格单调递增；⑤ 删除 bus_events 死代码。回归锚点：注入错位数据断言测试失败。
- **验证**：confirmed（W08-07/T2-E2E）

**H-17. openTask 任务切换竞态：快照乱序返回跨任务串台 + SSE 流句柄被覆写泄漏**
- **位置**：`frontend/src/hooks/usePipeline.js:158-192`（:160 同步写 taskIdRef → :173 await api.getState 后无 `taskIdRef.current===taskId` 守卫 → :188 直接覆写 esRef）；:195-200（切换 effect 无串行化）；api.js:96-99（onError 空）
- **类别**：error_handling
- **失败场景**：快速 A→B 切换且 A/B 快照响应乱序返回时，后 resolve 的旧任务事件被应用到当前（B）视图（applyEvent 无 taskId 归属校验）；旧流句柄被覆写永不 close（卸载只关 esRef.current），其 onEvent 继续注入 → B 视图混入 A 事件、B 的连接与服务端订阅残留。DP 数据规模（542 事件 JSON）放大 getState 延迟窗口。
- **修复建议**：await 后加 `if (taskIdRef.current !== taskId) return`；openEventStream 返回值先存局部变量，`taskIdRef.current===taskId` 才赋 esRef，否则立即 es.close()；applyEvent 可选带 taskId 校验。回归锚点：模拟乱序快照响应断言无跨任务事件、无双连接。
- **验证**：confirmed（W01-04/P2-SWITCH）

**H-18. submitAnswer 乐观清 pending 无回滚：resume 失败（网络/409）后澄清卡消失、无重试入口、后端挂到 15 分钟超时**
- **位置**：`frontend/src/hooks/usePipeline.js:226-234`（:232-234 先 `pendingRef.current=null; setPending(null)` 再 `await api.resumeTask`，全函数无 try/catch）；`frontend/src/components/chat/ClarificationCard.jsx:21-24`（快捷按钮 onSubmit 不 await 不 catch → unhandledrejection 零反馈）；ChatView.jsx:134-135（主路径 toast 但无回滚）
- **类别**：error_handling ｜ **契约**：D5-1 / D10
- **失败场景**：resume 请求失败（网络抖动）→ 答案丢失、卡片已消失、历史已记答案、无重试入口 → 后端仍等待 → 15 分钟超时取消，前后端状态不一致。verifier 推翻种子「双击双发」机制（pendingRef 在 await 前同步置空，第二击必读 null 走 :219 早退），但失败回滚缺陷独立成立（DP-07 亦证 stale resume 多为 200，409 罕见但网络错误可达）。
- **修复建议**：await 成功后再清 pending（失败恢复 `pendingRef.current=cl; setPending(cl)` 并 toast 允许重答）；ClarificationCard 侧 catch 显示错误；加 submitting 标志防重入。回归锚点：mock resume reject 断言卡恢复可重试、历史未记答案。
- **验证**：confirmed（W01-03/P2-409）

### 4.3 Medium（24 条）

**M-01. SettingsDialog 配置状态大小写不匹配：'已配置' 徽标与计数恒不命中**
- **位置**：`frontend/src/components/settings/SettingsDialog.jsx:72-85`（configuredKeys 存大写、:84 envKey=KEY_MAP[k] 小写、:85 includes 恒 false）、:50-57（KEY_MAP 全小写）；`web/main.py:418-419/437`（_ENV_KEYS 大写、configured 键大写）；.env.example 亦大写
- **类别**：interface_mismatch ｜ **契约**：D10-2
- **失败场景**：GET /api/config 返回大写键（DASHSCOPE_API_KEY…），KEY_MAP 值为小写（dashscope_api_key…）→ `configuredKeys.includes(envKey(f.key))` 大写列表 vs 小写查询恒 false → 「已配置」徽标永不显示、计数恒「0/6 项已填 · 必填 0/2」，即使 .env 已配置 6 项（后端 PUT 映射为小写→大写，说明 GET 侧键应为大写）。仅展示误导，无数据损坏。
- **修复建议**：① isConfigured 改大写比对 `configuredKeys.includes(f.key.toUpperCase())`；② 或 KEY_MAP 保留两套键，比对 `configuredKeys.includes(KEY_MAP[f.key].toUpperCase())`。回归锚点：后端注入大写 configured 断言徽标出现与计数正确。
- **验证**：confirmed（W02-01/P3-CONFIG）

**M-02. 「新建提取任务」只清 selectedId：主区旧对话/SSE 流与右侧面板旧数据全部残留**
- **位置**：`frontend/src/App.jsx:61-63`（handleNew 仅 setSelectedId(null)）；`frontend/src/hooks/usePipeline.js:195-200`（task=null 不触发清理、esRef 不关闭）；`frontend/src/components/layout/DetailPanel.jsx:75-99`（task 无 id 直接 return，旧数据留存）
- **类别**：state_contract ｜ **契约**：WEB_DESIGN-C1（点击新建清空主区、聚焦输入框）
- **失败场景**：点「新建」后主区仍是上一任务全部卡片且 SSE 继续实时跳变（事件继续 applyEvent 重渲染）；右侧面板显示旧任务数据（概览状态为 '—'）；旧任务未完成时输入栏保持禁用（叠加 H-02/W02-04 场景）。直到用户提交新查询（submitQuery→openTask）才重置。
- **修复建议**：usePipeline 暴露 reset()（task 为 null 时清空 messages/stages/timeline/pending/logs 并 esRef.current?.close()）；DetailPanel 在 task null 时清空各 state。回归锚点：handleNew 后断言消息/卡片/日志清空、SSE 关闭。
- **验证**：confirmed（W02-06/P2-NEW）

**M-03. 日志抽屉无节流全量重渲染 + 计数分母用 mock 常量：真实模式 400+ 行每事件整表重建**
- **位置**：`frontend/src/components/log/LogDrawer.jsx:24-41`（useEffect([open,liveLogs]) 每事件全量 setLines 重建）、:78（分母 MOCK_LOGS.length=38）、:109-116（每行 4 span 全量重渲染）；`frontend/src/hooks/usePipeline.js:140-141`（log 无条件 append）；`frontend/src/mock/logs.js`（38 条）
- **类别**：performance
- **失败场景**：真实模式下 liveLogs=[] 亦为 truthy → mock 回退永不启用，分母必为 mock 常量 38 → 显示「412/38 行」式荒谬值；每条 log 事件触发全数组重建+每行 4 span 重渲染，SSE 每 2-3 秒洪泛（DP-11 425 条/任务）时 UI 掉帧；叠加 CR-02 双份应用后行数再翻倍。
- **修复建议**：① logs 容量上限（500 条环形截断）；② 行数>200 时 requestAnimationFrame 合并或视口截断渲染；③ 计数分母改 `liveLogs ? lines.length : MOCK_LOGS.length`（或去分母）。回归锚点：注入 500+ log 断言渲染行数与交互帧率。
- **验证**：confirmed（W02-09/P3-LOG，verifier 修正 MOCK_LOGS 为 38 非 36）

**M-04. 卡 1 完成态 output 与卡头摘要未接线：snap.state 被丢弃、summary 恒走兜底文案（D6-1/D6-5 悬空）**
- **位置**：`frontend/src/hooks/usePipeline.js:173-175`（快照仅重放 events，snap.state 未消费）、:80-83（stage_completed 只写 status/duration）；`frontend/src/components/chat/StageCard.jsx:416-423`（statusText 恒走兜底）、:491-493（stage.output && 恒假）；`frontend/src/mock/pipeline.js:271`（summary:''）；`web/main.py:174-192`（后端已返回 state_json 含 target_entity/simbad_info/property_spec）
- **类别**：dead_code ｜ **契约**：D6-1 / D6-5
- **失败场景**：openTask 从不消费 snap.state → 卡 1 完成态三项产出空白（UnderstandOutput 死代码）、所有卡头摘要退化为「已完成/进行中…」，与 mock 演示行为不一致。CLAUDE.md §5.3 自认已知缺口，但契约仍悬空。
- **修复建议**：openTask 从 snap.state 读取各 stage output 映射 stage.output（snake→camel：targetEntity/simbad{mainId,otype,ra,dec}/properties，property_spec 键名需与后端 aggregator 核对）；卡头摘要按 D6-5 用 output/step_progress data 拼装。回归锚点：快照含 output 断言卡 1 渲染三项产出与卡头摘要。
- **验证**：confirmed（W02-13/P1-SNAP/P1-SUMM）

**M-05. pendingRef 缺 stageId：澄清历史 answer 回填恒失败**
- **位置**：`frontend/src/hooks/usePipeline.js:128-129`（pendingRef.current=cl 无 stageId，stageId 只进 setPending）、:226-231（`s.id === cl.stageId` 恒 undefined 比较）；`frontend/src/components/chat/StageCard.jsx:390`（`cl.answer || '（跳过）'`）；对照快照路径 :178-183 含 stageId（两路径不一致）
- **类别**：logic_bug ｜ **契约**：D5-4
- **失败场景**：live 澄清（SSE 到达，最常见路径）必走 :128 分支 → 回填永不命中 → 澄清历史末条 answer 恒 '' → 每轮都显示「（跳过）」（多轮澄清 D5-7 历史完全失真）。仅快照恢复路径行为正确。
- **修复建议**：`pendingRef.current = { ...cl, stageId: ev.stage_id }`（与 setPending 同构）。回归锚点：live 澄清提交后断言历史 answer 回填。
- **验证**：confirmed（W02-11/W01-06）

**M-06. SSE 订阅队列满即丢 + 重放/订阅间隙丢失窗口 + 流无结束信号 + 跨线程 put_nowait（事件流缺口家族）**
- **位置**：`web/main.py:253`（asyncio.Queue(maxsize=200)）、:250-264（gen 先重放后 subscribe、EventSourceResponse ping=15 永续）；`web/event_bus.py:35-38`（QueueFull 仅 warning 丢弃）、:28-39（先落库再通知）；`frontend/src/hooks/usePipeline.js:65/72`（lastSeqRef 只写不读）；`frontend/src/services/api.js:88-89`（afterSeq 恒 0）
- **类别**：error_handling ｜ **契约**：D3-3 / D1-4
- **失败场景**：①队列满（200）即丢事件，log 洪泛（DP-11 425 条/任务，76% 为 log）突发时可达；丢弃为全局序不保证先丢 log → stage_completed/clarification 可被丢；前端无 gap 检测，仅在重开任务全量重放后恢复；②「DB 重放→bus.subscribe」之间发布的事件对该连接永久缺失（微秒级结构性窗口，任务运行中随时可 publish）；③任务完成后流无限保持（DP-10 实证 15s 收 162KB 全量重放+持续 ping，每已完成任务永占连接与订阅队列，重连恒全量重放）；④执行器线程跨线程 put_nowait 非线程安全（Python 3.14.5 实测唤醒正常、lost-wakeup 理论竞态未观测，低风险子项）。
- **修复建议**：①分级丢弃——stage_*/clarification/task_*/message 不丢，仅允许丢 log/step_progress 并记录 dropped_seq 范围；②先 subscribe 再重放 + 重放后补 get_events(last_seq) 去重（或 EventBus 维护 per-task 已发布游标）；③任务终态后关闭 SSE 流或 TTL 空闲关闭；④重连携带 lastSeqRef 走 after_seq 续播；⑤发布侧 loop.call_soon_threadsafe 包装。回归锚点：队列满断言关键事件不丢；重放间隙事件补发断言；任务完成后流关闭断言。
- **验证**：confirmed（W03-10/W04-11/W04-04/W03-13/F14/F8，F8 的「延迟到心跳」子主张未复现，机制保留）

**M-07. 测试 fixture 单例未重绑 emitter/log_bridge：离线测试向真实 tasks.db 写孤儿事件**
- **位置**：`tests/test_web_offline.py:73-88`（fixture 仅重建 m.store/m.bus/m.executor）、:109-115（test_create_task_moves_pdf 走真实主图）；`web/main.py:72-74`（import 期 configure_emitter/install_log_bridge 绑定原始 bus→真实 DB）；`web/log_bridge.py:42-48`（install 后不再换 bus）；`web/executor.py:98`（log_set_task）
- **类别**：test_gap
- **失败场景**：测试任务线程内 main_graph 的 logger.info 与埋点经旧通道写入真实 web/data/tasks.db（task_id 在真实 tasks 表不存在），跨测试累积污染；import web.main 还启动原始 executor daemon 线程（_loop 永久阻塞），每 client 测试再建一线程；污染面含 log 事件 + subgraph 埋点 emit_progress。
- **修复建议**：fixture 重绑 events._emit_fn 与 log_bridge handler 到新 bus（或 monkeypatch 路径后重新 import web.main）；test_create_task_moves_pdf 同时 monkeypatch create_main_graph；executor 提供 stop()/join 或 session 级单例。回归锚点：测试后断言真实 DB 事件数不变。
- **验证**：confirmed（W04-05/W08-02/F17）

**M-08. list_tasks 整行返回：state_json/pdf_paths 随列表膨胀且形状与 get_task 不一致**
- **位置**：`web/task_store.py:80/86-89`（SELECT *、[dict(r)] 原样返回）、:64-74（get_task 对 pdf_paths 做 json.loads）；`web/main.py:161`；`web/executor.py:135`（state_json=整个 LangGraph result）
- **类别**：performance ｜ **契约**：D8-4
- **失败场景**：DB 实测 3 个 completed 任务 state_json 各 379/469/459KB（合计 1.3MB）；limit=50 时列表响应 ~20-25MB（verifier 修正规模：非「数十 MB/单响应」但达该量级趋势）；list 侧 pdf_paths 为 JSON 字符串而 get_task 为列表，同字段两种形状；state_json 无任何消费者。
- **修复建议**：list_tasks 显式列 SELECT（task_id, query, title, status, created_at, completed_at），不取 state_json/pdf_paths；get_task 详情需要 state 走 /state 端点；或复用 get_task 解析统一形状。回归锚点：断言列表响应无 state_json 键且体积受限。
- **验证**：confirmed（W03-06/W04-09/F11）

**M-09. upload 先整文件读入内存再判 50MB：超大上传先受损后拒绝（D4-1 框架层限制未落地）**
- **位置**：`web/main.py:108-111`（`data = await f.read()` 全量读入后 `if len(data)>MAX`）、:43（MAX_UPLOAD_BYTES=50MB）、:104（多文件 File(...)）
- **类别**：resource_leak ｜ **契约**：D4-1（明确「需修改 Web 框架底层限制」）
- **失败场景**：Starlette 1MB 以上落盘 SpooledTemporaryFile 后 read 全量回内存 → 2GB 上传内存峰值≈文件大小 → 32 位进程/低内存机 OOM；uvicorn 0.51 无请求体上限参数、无框架层限制被配置；多文件为逐文件处理，峰值≈单文件而非并发叠加（verifier 修正）。
- **修复建议**：分块读取并在累计超过 MAX_UPLOAD_BYTES 时立即截断拒绝（`while chunk := await f.read(1MB)`），不再整块读入；或配置 uvicorn max request body / 中间件按 Content-Length+流式累计提前 413。回归锚点：monkeypatch MAX 后传超限文件断言 rejected 且内存峰值受限。
- **验证**：confirmed（W03-07）

**M-10. create_task 校验与 Move 非原子：并发同 pdf_id 致 move 抛异常 → 500 + 永久 queued 孤儿任务**
- **位置**：`web/main.py:139-155`（:140-142 存在性校验 → :143 先落库 output/pending → :149-153 shutil.move 循环无 try/except → :155 executor.submit）
- **类别**：error_handling ｜ **契约**：D4-6 / D4-3
- **失败场景**：两并发请求同 pdf_id 均过校验 → 第二个 move 抛 FileNotFoundError → 未捕获 500 → 该任务行从未 submit 永久 status=queued；重启无恢复逻辑（_loop 只消费显式 submit 入队）。verifier 修正 finder 描述顺序（实际校验 :139-142 在 create_task :143 之前），但 TOCTOU 竞态与孤儿任务结论独立成立。
- **修复建议**：move 循环逐文件 try/except，失败即回滚（删已建任务行或置 status=cancelled 记录原因）并返回 400/409 说明 pdf 已被占用；pdf_ids 去重；上传阶段把文件与唯一 pid 绑定。回归锚点：并发同 pdf_id 断言 400/409 且无 queued 孤儿行。
- **验证**：confirmed（W03-08）

**M-11. VCR 启动自测在模块 import 期执行：无 fail-fast、日志洪泛放大（211MB/5 任务）**
- **位置**：`web/main.py:80-93`（模块顶层自测，任何 import web.main 含 pytest 都执行）、:90（OpenAI(api_key="x", base_url="https://api.deepseek.com", timeout=15)）；`web/executor.py:26-27`（_CASSETTE_MODE 默认 'once'，cassette 缺失时 VCR 录制而非快速失败）
- **类别**：build_deploy
- **失败场景**：cassette 缺失时自测向真实 api.deepseek.com 发请求（最长阻塞导入 15s，仅 except warning）；DP-09 实证 cassette 存在时 play_count=1 零网络调用但无 fail-fast；启动 141 行 'Appending' 日志（~9.6MB），5 任务后 /tmp/backend_audit.log 达 211MB/3938 行；LLM_CASSETTE 拼错路径时自测与任务静默真实调用（与 H-14 叠加）。
- **修复建议**：自测移入 @app.on_event('startup') 或诊断开关下执行；cassette 缺失先 _cp.exists() 检查跳过而非进入录制；timeout 降 3s 不阻塞启动路径；'Appending' 日志降 debug 级。回归锚点：无 cassette 时 import 不产生网络请求、日志可控。
- **验证**：confirmed（W03-09/F13，verifier 补正：pytest 环境默认不设 LLM_CASSETTE，仅按 CLAUDE.md 命令且路径错误时触发）

**M-12. 执行器线程内同步 LLM 阻塞完成事件与排队任务（最坏 60+60 秒）**
- **位置**：`astroquery_ai/web_runner.py:155-160`（summary 在 done 回调内同步执行，message/task_completed 在总结后发）；`web/executor.py:139-145`（标题 LLM 在 _finish 前同步执行）、:44-45（单 worker 执行线程）、:155-161（_finish 才释放 _current）；`web/summary.py:38`（timeout=60）
- **类别**：performance ｜ **契约**：D8-2
- **失败场景**：LLM 慢或不可达（悬挂至 60s 超时）时任务已完成但前端 60s 收不到 message/task_completed，排队任务延迟最多 60s 才启动（标题再 60s）。verifier 补正：stage_completed(done) 于 :154 在总结前已 publish，实际延迟的是 ai message、task_completed 与队列释放。
- **修复建议**：先发 task_completed 再异步生成总结/标题（D8-2 已声明 task_title_ready 异步语义）；标题生成移出执行器线程（_finish 不等待）；或缩短 LLM 超时。回归锚点：慢 LLM 断言 task_completed 先于总结消息到达、排队任务及时启动。
- **验证**：confirmed（W04-10）

**M-13. flow_started/flow_completed 无发送方 + clean/deliver 卡永久 running + pdf_converter 无埋点**
- **位置**：`astroquery_ai/main_graph.py:165-173`（_NODES 无 clean/deliver 映射）；`frontend/src/hooks/usePipeline.js:118`（agent 事件只置 waiting→running 永无 completed）；`subgraphs/subgraph3/nodes/pdf_converter.py:1`（位置修正：subgraph3 非 subgraph2，pdf_batch_converter 仅 logger 无 emit_progress）；CLAUDE.md §5.4 自认
- **类别**：state_contract ｜ **契约**：D6-flow_events / D6-4
- **失败场景**：全仓 grep flow_started/flow_completed 零发送方（DF-01 实证 DB flow_* 计数 0）；卡 5「数据清洗」/卡 6「数据交付」每条正常任务永久「进行中…」，轮次分组无法呈现（规范化第 1 轮/冲突第 1 轮/规范化第 2 轮被按 agent 名去重折叠）；pdf_converter 转换阶段（多篇大 PDF 时耗时）前端无任何进度信号（'paper' 步最早由 vlm_extractor.py:106 发）。
- **修复建议**：按契约在 quality_pipeline/routers.py dispatch/loop 处实现 flow_started/completed（flow_id=轮次、round=loop_round），agent 事件带 flow_id；pdf_converter 循环内加 'paper' step_progress（completed/total/current，完成/失败时发 completed）；最小修复：clean/deliver 出口补发 stage_completed。回归锚点：正常任务断言卡 5/6 到达 completed 且 flow 事件配对。
- **验证**：confirmed（W05-06/F20）

**M-14. agent traces 前端「替换」而非「累积」：规范化多轮/回跳场景第 1 轮轨迹丢失（D7-5）**
- **位置**：`frontend/src/hooks/usePipeline.js:115`（`traces: ev.traces || a.traces` 增量替换）；`quality_pipeline/agent_events.py:62`（生产侧每轮只带增量切片）；`subgraphs/data_normalization/normalization_graph.py:64-71`（Validation Retry→planning 重跑 normalization）
- **类别**：interface_mismatch ｜ **契约**：D7-5（事件累积，前端持有）
- **失败场景**：normalization 第 1 轮 20 条 → Retry 第 2 轮增量 5 条 → 前端同一 NormalizationAgent 行被替换为 5 条，第 1 轮对用户不可见（HumanReview E→B 同理）；数据本身无损，展示丢失。
- **修复建议**：前端改为累积 `traces: a.traces ? [...(a.traces||[]), ...(ev.traces||[])] : (ev.traces||null)`；重放按 timestamp+field+after 三元组去重（与 quality_state._merge_dict 策略一致）。回归锚点：两轮增量事件断言 traces 长度=和。
- **验证**：confirmed（W05-07）

**M-15. 失败/空数据早退路径不发子步骤终止事件：子步骤永久 waiting**
- **位置**：`subgraphs/subgraph2/nodes/database_query.py:72-81`（配置失败，埋点在 :92 后）、`ads_search.py:404-421`（无论文，埋点在 :465）、`pdf_download.py:290-303`（空 papers，埋点在 :391）、`subgraphs/subgraph3/nodes/bbox_annotator.py:90-94`（total_tasks==0，completed 在 :206）、`figure_extractor.py:163-166`（无页面）
- **类别**：test_gap ｜ **契约**：D6-6
- **失败场景**：这些路径零事件 → 对应子步骤前端永久 waiting，而 stage_completed 由 wrap finally 无条件发（main_graph.py:158-161）→ 卡片完成与子步骤悬空矛盾（如 ADS 全 429 时论文②③、补充①全 waiting）。
- **修复建议**：各早退分支补发对应 step 终止事件（status=failed/skipped，带 data 摘要如 paper/search {per_query:[],deduped:0}、paper/download {downloaded:0,failed:0}、bbox {success:0,failed:0}）；前端对非 running/waiting 有明确展示。回归锚点：空数据路径断言收到 skipped 事件。
- **验证**：confirmed（W05-08）

**M-16. HumanReviewAgent 节点未包 wrap_agent_node：卡 5 人工审核零活动反馈**
- **位置**：`quality_pipeline/graph.py:67-70`（human_review_node 直调 HumanReviewAgent().run(state)）；对照组 5 个子图 *_graph.py 全部 _wrap（normalization_graph.py:49-65 等）
- **类别**：test_gap ｜ **契约**：D6 卡4-6（agent 行 ← agent_started/completed）
- **失败场景**：5 子图外的第 6 个 agent 节点遗漏事件包装 → HITL 挂起与完成均无 HumanReview 活动行，用户会误以为任务卡死。
- **修复建议**：graph.py human_review_node 改 `_wrap("HumanReviewAgent", HumanReviewAgent().run, "clean")(state)`（返回结构不含 data_trace 时 traces 自动省略）。回归锚点：触发 HumanReview 断言 agent_started(HumanReviewAgent) 与 agent_completed。
- **验证**：confirmed（W05-05）

**M-17. 卡 7 总结 prompt 硬编码「M13 数据检索任务」：非 M13 查询错误引用天体名**
- **位置**：`web/summary.py:74`（prompt 首行写死，与 query/target 无关）
- **类别**：data_correctness ｜ **契约**：D6-3
- **失败场景**：任何非 M13 查询（M31 等）的卡 7 总结以 M13 为主体生成 → AI 消息出现错误天体名；当前被 CR-01 掩盖（总结恒 0/0），CR-01 修复后即刻用户可见。确定性 prompt 缺陷。
- **修复建议**：prompt 模板化 `f"...总结一次「{state.get('target_entity') or user_query}」数据检索任务的结果..."`（generate_final_summary 已可拿到 state，与 generate_task_title:91 同模式）。回归锚点：M31 查询断言总结含 M31。
- **验证**：confirmed（W04-06）

**M-18. exports 恒空：导出落随机 8-hex 目录与任务完全解耦，D9 数据交付功能整体失效**
- **位置**：`quality_pipeline/state.py:408`（run_id=str(uuid.uuid4())）；`subgraphs/data_export/agents/export_generation_agent.py:182-190`（_resolve_output_dir 用 run_id[:8]）；`web/main.py:326-345`（get_exports 遍历 tasks.output_dir 恒 []）、:366-376（export_file 对真实文件 404）
- **类别**：interface_mismatch ｜ **契约**：D9-2 / D9-3
- **失败场景**：导出文件写入 output/{8hex}/（与任务完全解耦）→ API 永远扫描不到。DP-02 实证两已完成任务 exports 均 []，而 output/c70b6a99/（8 文件，manifest exported_at=2026-08-12T21:49:24、row_count=3、validation_passed=true）与 output/9326fb8c/ 真实存在；DF-03 磁盘对照：12 任务 output_dir 全在但仅空 user_pdfs/，46 个 8-hex 目录 269 JSON+90 CSV 与任务运行时刻一一对应。输出文件区永远为空、打开/下载不可达。
- **修复建议**：导出目录与任务绑定（EXPORT_OUTPUT_DIR 改 output/{task_id}/，或 quality_adapter 把 run_id→task_id 映射落库、API 按映射扫描）；最小修复：get_exports 先按 OUTPUT_DIR 下 run 目录 manifest 关联任务。回归锚点：DP-02——任务完成后断言 exports 非空且 export_file 200。
- **验证**：confirmed（F3）

**M-19. vite proxy 仅配置 server 块：npm run preview 下 /api、/static 全部不可用**
- **位置**：`frontend/vite.config.js:12-19`（proxy 位于 server 块）；`frontend/package.json:9`（"preview": "vite preview"，preview 不继承 server.proxy）；`frontend/src/services/api.js:5`（BASE='/api'）
- **类别**：build_deploy
- **失败场景**：vite preview 下 GET /api/* 被 SPA fallback 重写为 /index.html 返回 200 text/html → api.js res.json() 抛 SyntaxError；POST /api 404；/static 404（verifier 已按 vite 6 源码核实 fallback 条件：fetch 默认 Accept */* 命中）。preview 脚本不可用。
- **修复建议**：vite.config.js 增 `preview: { proxy: { '/api': ..., '/static': ... } }`（vite 5+ 支持 preview.proxy）；或删除 preview 脚本文档改为生产用后端挂载 dist。回归锚点：preview 模式断言 /api/tasks 返回 JSON。
- **验证**：confirmed（W07-09/B1-PROXY）

**M-20. 构建部署链断裂：无 base 配置、dist 无承载方、BASE 硬编码 /api**
- **位置**：`frontend/vite.config.js:5-20`（无 base/build 配置）；`frontend/dist/index.html:6-7`（/assets/* 绝对路径引用）；`web/main.py:486`（仅挂 /static/figures，不伺服 dist）；`frontend/src/services/api.js:5`（BASE 硬编码，全 src 无 VITE_/import.meta.env）；仓库无 dockerfile/nginx/部署脚本
- **类别**：build_deploy
- **失败场景**：构建产物存在但无任何承载路径：仅起后端 '/' 404、仅起 preview 见 M-19、子路径部署时 /assets、/api、/static 全 404；改 API 地址需改源码。B2-BASE/B3-DIST/B4-ENV 同链并入（verifier：构建链断言与磁盘一致 DF-04，dist 是无人托管的死产物）。
- **修复建议**：① 后端 `app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True))`（注意与 /api、/static 路由顺序）单进程交付，dist 入 .gitignore；② 或提供 nginx 站点模板；③ 子路径部署：vite base 与 api.js BASE 用 VITE_API_BASE 环境注入。回归锚点：单进程启动断言 '/' 返回 index.html 且 /api 正常。
- **验证**：confirmed（W07-10/B3-DIST/B2-BASE/B4-ENV）

**M-21. 离线测试覆盖缺口：SSE/重度数据端点/超时路径/上传大小分支/恒真断言**
- **位置**：`tests/test_web_offline.py:91-115`（仅覆盖 /api/upload 与 POST /api/tasks 4 项端点）、:115（test_create_task_moves_pdf 断言 `client.app.extra.get("UPLOAD_DIR", Path(""))`——fastapi 0.141.1 实测 extra 恒 {} → 恒退化为 CWD 检查恒真，D4-3 move 双向零验证）、:42-49（仅测 store 层 after_seq）
- **类别**：test_gap ｜ **契约**：D1-4 / D8-3 / D5-4 / D4-3 / D4-1
- **失败场景**：/events、/state、/result、/records、/sources、/figures、/quality、/exports、/export、/config、/retry、/resume、/cancel、open-file/open-output 全零覆盖；上传 50MB 分支与混合「部分拒收」无测试；executor 超时路径（F1/H-07）、VCR 分支、title 生成、log_bridge、summary 降级均无测试。
- **修复建议**：断言锚点：① SSE after_seq=N 首帧补发 seq>N 且升序、与 store.get_events 逐条相等；② /state 的 pending_clarification 仅 running 且末事件为 clarification 时返回；③ retry 新 task_id+旧事件保留+pdf copy；④ /api/config GET 永不回传明文 + PUT（monkeypatch _ENV_FILE）写回断言；⑤ /export/{file} 用 ../ 断言 404；⑥ resume 对非澄清等待 409；⑦ 上传超限 rejected[0].reason 含 50MB；⑧ move 双端断言（暂存区不存在 + OUTPUT_DIR/{task_id}/user_pdfs 存在，task_id 取响应）。回归锚点：逐项红测。
- **验证**：confirmed（T1-COVER/W08-01/W08-03/W08-04/W08-08）

**M-22. quality_check 卡预置 QA_MOCK：mock 文案与 M31 演示数字进入真实任务渲染**
- **位置**：`frontend/src/mock/pipeline.js:280`（quality_check 卡 agents 预置 QA_MOCK.checkAgents）、:155-173（reason「构建数据画像（138 条记录 · 20 来源）」「完整性 92 · 一致性 88」+ 3 条 M31 mock traces）；`frontend/src/hooks/usePipeline.js:110-118`（agent 更新只写 status/duration/traces，保留 reason）；`quality_pipeline/agent_events.py:39-44`（事件仅 agent/duration/traces）
- **类别**：data_correctness
- **失败场景**：真实任务质量检查卡显示 M31 演示文案与数字（DP-01 实证真实 quality 卡 agent_completed 均无 traces → mock traces 原样展示），用户把演示数据误认为本任务结果。
- **修复建议**：真实路径下 quality_check 初始 agents 置 null 依赖 agent 事件动态追加；或 makeInitialStages 对 quality_check 仅保留 id/agent 占位去掉 reason/traces。回归锚点：真实任务断言无 mock 文案与数字。
- **验证**：confirmed（W01-09）

**M-23. error warn 级事件无消费侧（生产侧亦无 warn 生产者）：D10 错误总表两端死承诺**
- **位置**：`frontend/src/hooks/usePipeline.js:135-139`（error 分支仅处理 fatal）；`web/executor.py:87/148`（全库 bus.error 仅 fatal 两处）；节点降级只走 logger→log 事件
- **类别**：state_contract ｜ **契约**：D10（阶段失败 warn → 卡片红态+错误行）
- **失败场景**：warn 分支无任何状态写入，error warn 事件在服务端根本不存在 → 「阶段失败(warn)→卡片红态+错误行」两端均为死承诺；降级失败用户仅能从日志抽屉得知（叠加 M-03 洪泛更难找）。
- **修复建议**：两端补齐——节点降级处发 error warn 事件，或明确降级走 log 并同步修订 D10 总表；前端累积 stage.error 列表供 StageCard 渲染红态与错误行。回归锚点：注入 warn 事件断言卡片红态。
- **验证**：confirmed（W01-07）

**M-24. 死代码：mock/results.js、mock/tasks.js、QualityReport 组件**
- **位置**：`frontend/src/mock/results.js:1`（头部注释自称演示用确定性生成器）、`frontend/src/mock/tasks.js:1`；`frontend/src/components/results/ResultTabs.jsx:173/8`（QualityReport 仅定义与文件头注释提及）
- **类别**：dead_code
- **失败场景**：全 frontend/src grep 无任何 import 引用（被引用的仅 mock/pipeline.js、mock/logs.js）；QualityReport 无消费者（DetailPanel 只导入 SourcesList/OutputFiles）。死代码+死导出，易误导后续维护者。
- **修复建议**：删除或确认无演示用途后清理；配套 W07-11 的工程建议（补 eslint/vitest 门禁）。回归锚点：grep 断言零引用后删除。
- **验证**：confirmed（P3-DEAD2）

### 4.4 Low（15 条）

**L-01. task_title_ready 忽略 task_id 字段（D8-2 契约字段未用）：切换竞态窗口标题错配/丢失**
- **位置**：`frontend/src/App.jsx:89-91`（handleTaskTitle 按 `t.id===selectedId` 匹配，task_id 被丢弃）；`frontend/src/hooks/usePipeline.js:152-153`（只透传 ev.title）；`web/executor.py:143`（后端携带 task_id）
- **类别**：interface_mismatch ｜ **契约**：D8-2
- **失败场景**：A 的标题事件在选中 B 时到达 → 错配到 B 或整体丢弃，列表条目标题残留/丢失。事件只对选中任务流动，窗口较窄；影响限于列表标题错配/丢失。
- **修复建议**：handleTaskTitle 接收完整 payload 按 ev.task_id 更新（`prev.map(t => t.id===payload.task_id ? {...t, title: payload.title} : t)`）；usePipeline 透传 ev。回归锚点：切换竞态注入标题事件断言正确归属。
- **验证**：confirmed（W02-10）

**L-02. 提交失败 finally 清空输入与文件：契约「输入框内容保留」直接违背**
- **位置**：`frontend/src/components/chat/ChatView.jsx:134-140`（catch 只 toast，finally 无条件 `setInput(''); setFiles([])`）
- **类别**：state_contract ｜ **契约**：D10 错误处理总表（任务创建失败 4xx → toast + 输入框内容保留）
- **失败场景**：query 超长 400（D4-5）、pdf_id 校验 400（D4-6）、上传失败（H-03）等场景命中 → 用户已输入的长查询与已选 PDF 全部丢失，需重打重选。
- **修复建议**：setInput('')/setFiles([]) 移入 try 成功分支（submitQuery 返回后），catch 分支保留输入与文件。回归锚点：mock 400 断言输入与文件保留。
- **验证**：confirmed（W02-12）

**L-03. request() 错误体未归一 + 空 body SyntaxError + SSE 404 无限重连**
- **位置**：`frontend/src/services/api.js:15-20`（`new Error(detail)`，FastAPI 422 detail 为数组 → '[object Object]'；r.json() 对 204/空 body 抛 SyntaxError）；:88-101（openEventStream 对 404 按 spec 无限自动重连）
- **类别**：error_handling
- **失败场景**：pdf_ids 非法 422 → toast 显示 [object Object]；打开已删除任务 → getState 404 被 catch{} 吞掉 → 对 /events 持续重试。均为边缘路径。
- **修复建议**：detail 为数组/对象时 JSON.stringify 或取首项 message；res.json() 包 try 兼容空 body；openEventStream 增加 onopen 未触发即 close+上报，避免 404 无限重连。回归锚点：422 断言错误消息可读。
- **验证**：confirmed（W01-08）

**L-04. export_file/open-file 路径白名单用 startswith 前缀匹配：防穿越脆弱实现**
- **位置**：`web/main.py:374/398`（`str(target).startswith(str(out_dir))`）
- **类别**：security ｜ **契约**：D9-3
- **失败场景**：构造性场景：兄弟任务目录名以当前 task_id 为字符串前缀时（uuid4 前缀碰撞实践不可达），open-file 的 name（JSON body 可含 ../）可指向兄弟任务文件；校验逻辑本身错误属防穿越脆弱实现（export_file 的 file_name 为路径参数 %2F 解码后可含斜杠，需前缀碰撞才可达）。
- **修复建议**：改用 `target.is_relative_to(out_dir)`（或 os.path.commonpath）严格包含判断；open-file 的 name 先 `Path(name).name` 拒绝含分隔符输入。回归锚点：../ 构造断言 404。
- **验证**：confirmed（W03-14）

**L-05. PUT /api/config 重写 .env 丢注释与空行 + 值内换行可注入新键**
- **位置**：`web/main.py:468-479`（:476 只保留非注释非空行 → .env 6 行 # 注释与空行在任意一次保存后永久丢失；:471 `f"{k}={vals[k]}"` 无换行转义）；:425-429（_env_values 逐行解析）
- **类别**：config_drift ｜ **契约**：D10-1
- **失败场景**：保存任意配置后注释说明与空行被静默删除（verifier 修正：注释实为 6 行非 9 行）；值含 '\n' 被拆多行，下一行形如 KEY=value 会被 _env_values 当作新键读入（verifier 修正：全后端无 dotenv 加载器，「重启后被系统环境读取」不成立——注入影响限于 .env 文件污染与 _env_values 杂键）。
- **修复建议**：① 重写 .env 保留原注释行；② 值写回前单行化（replace('\n','').replace('\r','')）并限长（512 字符）。回归锚点：保存后断言注释行数与文件结构不变。
- **验证**：confirmed（W03-15）

**L-06. resume/cancel 对不存在任务返回 409 而非 404：HTTP 语义不一致 + 误导文案**
- **位置**：`web/main.py:202-212`；`web/executor.py:164-181`（对不存在 task 的 slot/rec 查询均为 None → return False 无法区分）
- **类别**：interface_mismatch
- **失败场景**：任务已删/URL 误拼 → 409「任务未在澄清等待中」误导用户为状态冲突；同族其它端点对不存在任务均 404（main.py:169/246/273/330/219）。
- **修复建议**：resume/cancel 端点先 store.get_task(task_id)，不存在则 404；再调 executor 判断可操作性（409）。回归锚点：不存在任务 resume 断言 404。
- **验证**：confirmed（W03-16）

**L-07. cancel 无锁读 _slots 不二次校验：与 _finish 竞态把已完成任务覆写为 cancelled**
- **位置**：`web/executor.py:171-175`（无 _lock 读 _slots + update_task 不校验状态）；:155-161（_finish 在锁内 pop slot 写 completed）
- **类别**：state_contract ｜ **契约**：D2-2
- **失败场景**：任务完成瞬间用户点取消 → cancel 读到陈旧 slot → 后写 update_task(cancelled) 覆写 completed；终态与已发 task_completed 事件矛盾。毫秒级窗口且需完成瞬间点击，影响极小。
- **修复建议**：cancel 全程持 _lock，拿到 slot 后二次读取 rec 状态，仅当 status in ('queued','running') 才置 cancelled；或 _finish 与 cancel 状态写入同一临界区，后写者校验当前状态。回归锚点：并发模拟断言终态不被覆写。
- **验证**：confirmed（W04-08）

**L-08. figure_extractor 同一步骤发两条 completed（事件重复）**
- **位置**：`subgraphs/subgraph3/nodes/figure_extractor.py:198-203`（循环内 completed==len(tasks) 且 %5==0 时发 status="completed" 无 data）；:209-213（循环后又发第二条 completed+data{figures}）
- **类别**：dead_code ｜ **契约**：D6 卡3
- **失败场景**：len(tasks) 恰为 5 的倍数时同一 step 'figure' 两条 completed；前端幂等不崩溃，但 D8-3 事件落库与 after_seq 重放会看到重复完成事件。
- **修复建议**：循环内只发 running（去掉 completed 分支），completed 统一由 :209 循环后埋点发。回归锚点：构造 5 倍数任务断言单条 completed。
- **验证**：confirmed（W05-09）

**L-09. data_trace 无 confidence：前端轨迹渲染显示「置信度 undefined」**
- **位置**：`subgraphs/data_normalization/agents/normalization_agent.py:425-434`（data_trace.append 无 confidence 键）、:678-689（_append_trace 同）；`frontend/src/components/chat/StageCard.jsx:207`（`{t.reason} · 置信度 {t.confidence}`）；设计 WEB_DESIGN.md 层3 定义含 confidence（mock pipeline.js:162-164 有值）
- **类别**：interface_mismatch ｜ **契约**：D7-5
- **失败场景**：每条轨迹显示「置信度 undefined」，用户观感脏数据；属性缺失不崩溃。
- **修复建议**：二选一：① normalization_agent 写入时补 confidence（确定性置信度 1.0 或 op 记录值）；② StageCard.jsx:207 对 undefined 不渲染该段。回归锚点：轨迹渲染断言无 undefined。
- **验证**：confirmed（W05-10）

**L-10. 补充材料子状态 data.substatus 从未产出：「正在验证表 J/MNRAS/427/1463…」文字永久缺失**
- **位置**：`subgraphs/subgraph2/nodes/supplementary_query.py:344-347`（supplementary/find 事件只带 progress 无 data{substatus}）；`frontend/src/components/chat/StageCard.jsx:354-358`（step.substatus 恒 null，仅 mock 有值）；WEB_DESIGN.md:112
- **类别**：test_gap ｜ **契约**：D6-6（补充进度 ← data{substatus}）
- **失败场景**：论文内验证表阶段（耗时最长）前端只见进度条无当前表号文字，长任务期间无中间信息。功能可用，仅设计要求的子状态缺失。
- **修复建议**：supplementary_query 循环内发 data={"substatus": f"正在验证表 {table_id}"}（_catalog_real_exists/LLM 判断处更新）；前端 formatStepDetail 增加 supplementary/find 分支。回归锚点：事件断言含 substatus。
- **验证**：confirmed（W05-11）

**L-11. log_bridge 用 threading.local 路由 task_id：worker 线程日志全被丢弃（版本前提修正：全版本存在）**
- **位置**：`web/log_bridge.py:25-35`（emit 读 _local.task_id）；`web/executor.py:98`（仅执行线程 set_task）；vlm/bbox/pdf/figure 的 ThreadPoolExecutor 工作线程（subgraphs/subgraph3/nodes/）
- **类别**：logic_bug
- **失败场景**：verifier 实测 Python 3.14.5 子线程读父线程 threading.local 为 None（不继承），且 3.12 whatsnew 无 thread-local 继承变更 → 前提「3.12+ 子线程继承」错误，缺陷全版本存在：worker 线程日志（VLM/bbox/下载/图提取）全部被 log_bridge 丢弃。仅影响 SSE 日志抽屉观测完整性，不损任务数据。
- **修复建议**：用 contextvars.ContextVar 替代 threading.local（contextvars 随线程/任务传播，ThreadPoolExecutor 亦传播）；或在 worker 提交时显式透传 task_id。回归锚点：worker 线程 emit 断言事件落库。
- **验证**：confirmed（F19，verifier 修正前提并保持缺陷成立）

**L-12. 死代码 useMockPipeline.js（600+ 行钩子）**
- **位置**：`frontend/src/hooks/useMockPipeline.js:25`；全库 grep 仅命中定义自身与 usePipeline.js:1 注释中的文字（ChatView.jsx:11 只 import usePipeline）
- **类别**：dead_code
- **失败场景**：600+ 行钩子为死代码（mock/pipeline.js 仍被 usePipeline 使用，死的仅是 useMockPipeline.js 本身）；其行为基准曾对 W02-04 实现产生误导（参照其 cancelled 行为未复刻）。
- **修复建议**：删除或标记为演示归档。回归锚点：grep 零引用后删除。
- **验证**：confirmed（P3-DEAD1）

**L-13. OutputFiles「打开」仍是 mock toast：api.js 无 openFile 封装，/open-file 已实现未对接**
- **位置**：`frontend/src/components/results/ResultTabs.jsx:217-220`（openFile 仅 toast('mock：将打开...')）；`frontend/src/services/api.js`（16 个导出函数无 openFile）；后端 POST /api/tasks/{id}/open-file 已实现（main.py:391-401, os.startfile）
- **类别**：dead_code ｜ **契约**：D9-3
- **失败场景**：「打开」按钮无真实效果且以 mock 提示掩盖；叠加 M-18（exports 恒空）下载 Tab 本就无文件可操作。
- **修复建议**：api.js 补 openFile(name) 封装并让 ResultTabs 调用真实接口 + toast 错误；同步修复 M-18 后文件才可操作。回归锚点：点击打开断言调用真实端点。
- **验证**：confirmed（P3-OUTPUT）

**L-14. 58MB cassette 每次任务/启动全量 YAML 解析 + 录制退出全量重写**
- **位置**：`web/executor.py:109`（每任务一次 use_cassette 全量解析）；`web/main.py:87`（启动自测再一次）；tests/cassettes/m13_query.yaml（58,329,621 字节/141 交互）；vcr cassette.py:350-358（_save 全量重写）
- **类别**：performance
- **失败场景**：回放模式每次任务提交/启动阻塞秒级；录制模式每次退出全量重写 58MB；叠加 DP-09 的 'Appending' 日志洪泛（~9.6MB/次）。
- **修复建议**：cassette 按用途分文件（LLM 与下载分离），回放任务只加载 LLM 文件；进程级单例缓存解析结果；加载期日志降 debug。回归锚点：回放任务提交时间受控。
- **验证**：confirmed（W07-12）

**L-15. 上传校验缺扩展名检查：D4-2「扩展名 + 魔数」降级为单维度**
- **位置**：`web/main.py:112-115`（仅 `data.startswith(b"%PDF")` 一种拒绝分支）；:116-117（存储名一律 {pid}.pdf，循环内无任何 f.filename 扩展名检查）
- **类别**：config_drift ｜ **契约**：D4-2
- **失败场景**：任意非 .pdf 扩展名文件只要文件头 %PDF（可伪造）即被接受；扩展名维度完全无校验，契约降级为单维度。影响限于上传准入口径与契约不符，无直接安全后果。
- **修复建议**：魔数校验后追加扩展名白名单 `Path(f.filename or "").suffix.lower() == ".pdf"`，不满足计入 rejected（reason='扩展名不是 .pdf'）。回归锚点：伪装 .txt 断言 rejected。
- **验证**：confirmed（W03-12）

## 5. 契约对照表

> 由 confirmed 条目的 contract_ref 合并生成（W06 未产出独立 contract_matrix，逐项以本轮证据链为准）。判定：✅符合 ｜ ❌违反 ｜ ⚠️部分 ｜ 🚫未实现。

| 决策编号 | 契约定案 | 实现位置 | 判定 | 证据关联 |
|---------|---------|---------|------|---------|
| D1-4 | 快照 + 从断点续播（断线重连不重复） | usePipeline.js:172-191、api.js:88-89、main.py:250-251 | ❌ | CR-02（DP-12 双通道实证）、M-06 |
| D1-8 | 取消需终止执行线程 | executor.py:171-181、web_runner.py:147 | ❌ | H-08（DP-08 实证） |
| D2-4 | 状态机终态 + 失败可重试 | executor.py:149、status.jsx、Sidebar.jsx:156 | ⚠️ | H-01（failed/error 两端各半） |
| D3-2 | 澄清结构化 {cl_type,title,fields,question} | web_runner.py:113、human_review_agent.py:151 等 | ❌ | H-10（DP-05/DF-01 实证 question 全空） |
| D3-3 | 轻量状态走 SSE（不丢关键事件） | main.py:253、event_bus.py:35-38 | ⚠️ | M-06（队列满即丢、流无结束信号） |
| D4-1 | 50MB 统一口径 + 修改框架层请求体上限 | main.py:43/108-111 | ⚠️ | M-09（先整读后拒绝，框架层未配置） |
| D4-2 | 上传校验：扩展名 + %PDF 魔数 + {pdf_ids,rejected} | main.py:107-118 | ⚠️ | L-15（无扩展名校验）、H-03 |
| D4-3 | 暂存区 Move → 任务目录 | main.py:143-155 | ⚠️ | M-10（无原子性）、M-21（恒真断言） |
| D4-6 | pdf_id 存在性校验 | main.py:139-142 | ⚠️ | M-10（TOCTOU） |
| D5-1 | resume 仅在挂起澄清时生效 | executor.py:164-169、web_runner.py:78-93 | ❌ | H-04（DP-07 74 次幽灵 resume 全 200）、H-18 |
| D5-3 | 澄清超时 15 分钟 → 任务取消（cancelled） | executor.py:86-92 | ❌ | H-07（终态被覆写 completed） |
| D5-4 | 快照含「当前挂起」澄清 payload | main.py:186-191 | ❌ | H-04（已答复澄清仍报 pending）、M-05 |
| D5-5 | 选 n 取消 → task_cancelled 统一灰态 | main_graph.py:88-90/172 | ❌ | H-09（发 task_completed 且卡 1 无 completed） |
| D6-1 | stage output 走 /state 快照 | main.py:173-192、usePipeline.js:172-184 | ⚠️ | M-04（后端有、前端未接线） |
| D6-3 | 卡 7 总结反映本次任务 | web_runner.py:155-160、summary.py:64/74 | ❌ | CR-01（DP-04 0/0 实证）、M-17（M13 硬编码） |
| D6-5 | 卡头摘要前端拼字段 | StageCard.jsx:416-423 | 🚫 | M-04（恒走兜底文案） |
| D6-6 | step_progress 子步骤事件齐全 | 各子图埋点 | ⚠️ | M-15（5 处早退路径零事件）、L-10、M-13 |
| D6-flow | flow_started/flow_completed 事件对 | 全仓（无发送方） | 🚫 | M-13（DF-01 flow_* 计数 0） |
| D7-3 | 图证接口 {id,source_id,page,bbox,image_url} | main.py:303-311 | ❌ | H-06（DP-01 16/16 404，bbox 恒 None） |
| D7-5 | 修改轨迹 traces 事件累积（前端持有） | agent_events.py:62、usePipeline.js:115 | ⚠️ | M-14（前端替换非累积）、L-09（无 confidence） |
| D8-2 | task_title_ready {seq,type,task_id,title} | executor.py:143、App.jsx:89-91 | ⚠️ | L-01（task_id 未用）、M-12（同步阻塞） |
| D8-3 | 历史回看走 HTTP 批量、拒绝 SSE 实时重放 | main.py:242-264、api.js:88-89 | ❌ | CR-02（SSE 恒全量重放）、M-21（无测试） |
| D8-4 | 列表 items 仅 {task_id,title,status,created_at} | task_store.py:76-89、main.py:159-162 | ❌ | CR-03（无 id 键）、M-08（整行 state_json） |
| D9-2/D9-3 | 导出文件列表/打开下载端点 | main.py:326-376 | ❌ | M-18（DP-02/DF-03 恒空）、L-13、L-04 |
| D9-4 | 图证静态路由（仅服务图证预览） | main.py:486 | ⚠️ | H-05（暴露整个 output/ 含 user_pdfs 与导出） |
| D10 | 错误处理总表（toast+输入保留+卡片红态） | api.js、usePipeline.js、ChatView.jsx | ⚠️ | H-03、L-02、M-23（warn 两端死承诺） |
| D10-1/D10-2 | config 写回 .env / 永不回传明文 | main.py:433-479 | ⚠️ | H-05（无认证）、L-05（丢注释）、M-01（GET 侧 ✅ 符合） |
| D10-3 | 澄清超时显式提示「已取消」+ 灰态 | usePipeline.js:145-151 | ❌ | H-02（无提示、输入永久禁用）、H-07 |
| WEB_DESIGN C1 | 点击新建清空主区、聚焦输入框 | App.jsx:61-63 | ⚠️ | M-02（只清 selectedId） |

### 5.1 SSE 事件流 13 种事件逐一对照

| 事件 | 契约定案要点 | 生产端 | 前端消费 | 判定 | 证据关联 |
|------|-------------|--------|---------|------|---------|
| task_queued | 入队通知 | executor.py:48-55 | usePipeline | ✅ 符合 | DF-01 实测 2 条 |
| task_started | 开始执行 | executor.py:91-100 | usePipeline | ✅ 符合 | DF-01 实测 10 条 |
| task_completed | 完成通知 | web_runner.py:159-160 | usePipeline.js:141-143 | ⚠️ 部分 | 取消路径误发（H-09）；同步 LLM 延迟（M-12） |
| task_cancelled | 取消通知（D5-5 统一灰态） | web_runner.py:147-149（仅澄清边界） | usePipeline.js:145-147 | 🚫 近乎未实现 | DF-01 全库 0 条；cancel/超时/queued 路径不发（H-07/H-08）；pending 不清理（H-02） |
| task_failed | 失败通知 | executor.py:146-150 | usePipeline.js:148-151 | ⚠️ 部分 | 状态词表 failed/error 断裂（H-01） |
| stage_started | 阶段开始 | main_graph.py:166 | usePipeline.js:77-79 | ⚠️ 部分 | 澄清重入重复发（F10，DP-06 started=2/completed=1） |
| stage_completed | 阶段完成 | main_graph.py:158-161 | usePipeline.js:80-83 | ⚠️ 部分 | 取消路径缺失（H-09）；done 时序错误致总结 0/0（CR-01） |
| step_progress | 子步骤进度 | 各子图节点 | usePipeline.js:84-106 | ⚠️ 部分 | 早退路径缺失（M-15）；figure 双 completed（L-08）；pdf_converter 无埋点（M-13） |
| agent_started | agent 开始 | agent_events.py:39 | usePipeline.js:110-118 | ⚠️ 部分 | HumanReview 未包装（M-16） |
| agent_completed | agent 完成 + traces | agent_events.py:42-44 | usePipeline.js:113-117 | ⚠️ 部分 | traces 替换非累积（M-14）；confidence 缺失（L-09） |
| clarification | 澄清事件 | web_runner.py:111-118 | usePipeline.js:122-134 | ❌ 违反 | question 恒空（H-10，DP-05 5/5）；stageId 丢失（M-05）；重放重弹（CR-02） |
| message | AI 消息 | web_runner.py:156-158 | usePipeline.js:74-76 | ⚠️ 部分 | 双份应用（CR-02）；总结 0/0（CR-01） |
| log | 节点日志 | log_bridge.py:25-35 | usePipeline.js:140-141 | ⚠️ 部分 | 洪泛无节流（M-03）；worker 线程日志丢失（L-11） |
| error（补充） | 错误事件 fatal/warn | executor.py:87/148（仅 fatal） | usePipeline.js:135-139 | ⚠️ 部分 | warn 无生产者无消费者（M-23） |
| task_title_ready（补充，D8-2） | 异步标题 {task_id,title} | executor.py:138-145 | App.jsx:89-91 | ⚠️ 部分 | task_id 字段未用（L-01） |
| flow_started/flow_completed（补充，第 6 轮） | 流转节点事件对 | 无发送方 | 无消费方 | 🚫 未实现 | M-13（DF-01 flow_* 计数 0） |

## 6. 被推翻条目表（7 条）

> 对齐上轮 AUDIT_REPORT §5.1 惯例：仅列摘要与推翻理由（refuted 裁决 9 条，同根因合并后 7 条）。

| # | 原主张（裁决号） | 摘要 | 推翻理由 |
|---|----------------|------|---------|
| R-01 | W02-07 / P3-BBOX | FigureThumb SVG 分支对 bbox 无空守卫 → b[0]*200 TypeError 白屏 | 生产端 get_figures（main.py:303-311）对每条 figure 恒构造非空 image_url（file_name 为空也拼出 '/static/figures/<tid>/'）→ DetailPanel.jsx:24 `if (fig.image_url)` 恒真 → 恒走 img 分支（有 `b &&` 守卫）；SVG 分支（:40-55）当前为死路径，TypeError 不可达。bbox 恒 None 属实但仅使 img 分支不画红框。注意：按 H-06 修复把 image_url 改为条件拼接后此崩溃点将变可达——修复时须同步补 b 守卫。 |
| R-02 | W02-08 | ResultTabs 不随 taskId 重置 records/page → A 的记录显示在 B 名下、页码越界空表 | 任务切换必触发 openTask → setStages(makeInitialStages())（usePipeline.js:164），done 卡 status='waiting' → ChatView.jsx:171 渲染条件为假 → ResultTabs 卸载 → records/page 随实例销毁重置；快照重放重新完成后以全新实例挂载并重新 fetch。「残留/越界」均不可达。真正残余缺陷是 :255 `.then` 无 `.catch`（fetch 失败停留在「加载记录…」无错误提示，低严重度，未单独立项）。 |
| R-03 | P1-RACE | 主区记录表格大概率永远空白（done 事件先于 state_json 写入的时序竞态） | Tier A 动态证据不闭合：DP-03 起 60 次×50ms 连续锤 GET /records 恒返回 3 条从未空。窗口虽存在（web_runner.py:155-160 在 app.invoke 内发 done，executor.py:133-135 在 invoke 返回后写库），但为毫秒级且被客户端链路（SSE 投递→渲染→fetch）延迟掩盖，外部 HTTP 不可观测；「records 必然为空」被 60/60 非空反证。理论竞态无实证路径，不构成可报告缺陷（若未来快照写入变慢需复核）。 |
| R-04 | W05-01 / F16 / F16-BUG | agent_completed.traces 仅 NormalizationAgent 携带，违反 D7-5「修改轨迹」契约 | 契约语义主体是「修改数据的轨迹」而非每个 agent 必带；全仓库写 data_trace 的唯一 agent 即 Normalization（normalization_agent.py:374 复制全量累积列表 + :463 整体返回 → agent_events.py:62 切片正确）；其余被 wrap 的 agent 均不返回 data_state 也不改数据，不带 traces 是正确行为。DB 实证（DF-01：57 个 agent_completed 仅 3 个带 traces、均为 NormalizationAgent）正是该正确行为的写照。机制属潜在脆弱性（未来 agent 若只返回增量字段将静默丢 traces），非现行问题。 |
| R-05 | W07-01 | 启动自测消耗 cassette 回放预算 → 第 35 次 LLM 调用失败 | play_counts 为 Cassette 实例状态（vcr/cassette.py:197，__enter__ 每次 cls.load() 新建实例、不持久化），自测与任务各自独立实例，自测消耗的第 1 条不传递给任务 → 预算不缩减。次级子主张（cassette 缺失时自测向真实 api.deepseek.com 发请求并 append）本身为真，但该机制由 W07-07/H-14 与 M-11 完整覆盖，自测假 key 失败被 except 兜底为 warning。 |
| R-06 | W07-02 | cassette 中 54 条 VLM 交互「明文 body + content-encoding:gzip 头」→ 回放时 requests 解码必然失败（DecodeError），VLM 回放全部失效 | vcrpy 在 urllib3 connection 层打补丁（patch.py:476-508），conn.getresponse() 直接返回 VCRHTTPResponse；urllib3 2.7 pool._make_request 原样返回、requests 2.34.2 iter_content 走 self.raw.stream(decode_content=True) → VCRHTTPResponse.stream 忽略 decode_content 原样吐字节 → urllib3 的 _decode/DecodeError 在回放路径永不执行，dashscope response.json() 直接解析明文成功。header/body 不一致属实（54/54 统计确认）但回放路径无影响；CLAUDE.md §5.1 的「0 条/bbox 全失败」由 W07-06 的按 URL 顺序错配解释。仅不经 requests 直用 urllib3 的客户端才可能触发，本项目不适用。 |
| R-07 | W07-11 | 前端无 lint/test/typecheck 脚本与 VITE_ 环境体系为审计发现 | 事实链全部成立（package.json:6-10 仅 dev/build/preview；src 全量 grep VITE_ 零命中），但按审计「问题」定义（错误行为/崩溃/契约违反/安全/死代码/性能）无任何运行时影响环节，属开发流程/工具链建议而非审计发现。工程建议已并入 M-20/M-24 修复建议。 |

## 7. 局限与未覆盖

1. **F7 种子（Tier C）未获终裁**：「create_task 响应恒 queued」主张经静态核对与契约 D4-7 定案（创建即 queued）一致，判为不成立但未单独立项验证。
2. **动态验证边界**：全程禁止网络/LLM——cassette 密钥有效性未复测、真实模式 E2E 未运行（CLAUDE.md §5.2 亦未执行）；DF-04 构建链为静态断言未做副本构建；DP-03 同类竞态（记录表窗口、W04-04 微秒级窗口）not_reproduced，属结构性成立但无运行实证。
3. **M-06 可达性未定量**：队列满丢事件的真实触发概率依赖慢消费者/断连检测延迟（F8-REACH 场景未做节流消费者复现实验）；W07-12 的 cassette 解析耗时未实测（秒级为经验估计）。
4. **契约文档位置**：契约实体位于仓库外 `E:\work\frontend\docs\API_CONTRACT.md` 与 `E:\work\frontend\docs\WEB_DESIGN.md`（非 `astroquery_final/docs/`，该目录下仅有 archive 版本）；本轮 W06 单元与各 finder/verifier 均已按上述路径引用契约原文，SSE 13 种事件契约定案依据契约原文核对。
5. **覆盖边界**：质量管线 270 个既有测试不在本轮范围（上轮已审）；前端无任何自动化测试；human_review 场景未在真实 DB 触发过（代码链确定性成立但无运行实证）；真实任务仅 M13 型查询（DP 探针），其他查询形态未覆盖。
6. **uncertain = 0**：所有候选均在静态 + 探针约束下证毕或证伪；对「结构性成立但未动态命中」的条目（M-06 窗口、L-11 机制）按 confirmed 处理并在文中标注验证深度。

## 8. 修复路线图（按优先级，含回归测试锚点）

### P0 主路径正确性（阻断级，先修）

| # | 条目 | 最小修复 | 回归测试锚点 |
|---|------|---------|-------------|
| 1 | CR-01 总结 0/0 | 总结移到最后一次 invoke 返回后；或 wrap finally 传 fn 返回值 | 假图发 done 后断言 on_final_summary 收到含 final_output 的 state（DP-04 红测）；E2E summary 数字与 records 一致 |
| 2 | CR-02 SSE 双份/重放 | openTask 快照重放后传 lastSeqRef.current；applyEvent 按 seq 去重；onerror 重建流 | DP-12 一致性断言：快照+SSE 后无重复 seq；断线重连不翻倍；重放不重弹澄清卡 |
| 3 | CR-03 task.id 断链 | 前端统一 task.task_id（App/Sidebar/DetailPanel/ChatView/usePipeline） | 点击历史任务 → DetailPanel 五接口 + ResultTabs 渲染（端到端） |
| 4 | H-06 图证 404 | image_url 用 f.get('image_path') 拼接（或收窄挂载+改 URL） | DP-01：对 output/figures/<tid>/ 真实文件断言 image_url 200 |
| 5 | H-03 上传静默放行 | uploadFiles 补 res.ok 检查 + 失败保留 chips | mock 500/422 上传断言抛错、无任务创建 |
| 6 | H-07 超时→completed | 超时分支同步置 cancelled；_finish 检查 slot.cancelled | 注入短超时断言 status=='cancelled' + task_cancelled 事件（W08-05 红测） |
| 7 | H-01 failed 词表 | 单点定义终态枚举（后端 error 或两端别名） | 注入 failed 任务断言徽标/筛选/重试按钮 |

### P1 安全与数据完整性

| # | 条目 | 最小修复 | 回归测试锚点 |
|---|------|---------|-------------|
| 8 | H-05 CORS/认证/静态挂载 | CORS 白名单；静态收窄至 output/figures；config 加 token | 跨源断言无 ACAO:*；user_pdfs/导出文件 404 |
| 9 | H-13 密钥泄露 | .gitignore 排除 cassette；录制 filter_headers 脱敏；轮换密钥 | grep cassette 断言无 authorization 键 |
| 10 | H-04 陈旧答案 | _AnswerSlot 加 waiting 标志；/state 由 executor 暴露真实挂起 | DP-07 红测：非等待期 resume 409、已答复澄清 /state 返回 null |
| 11 | H-08/H-09 取消语义 | cancel 发 task_cancelled（含 queued）；done 前查 should_cancel；_finish 不覆写 cancelled | DP-08：queued 取消收事件；选 n 断言 task_cancelled 且卡 1 灰态 |
| 12 | H-10 question 恒空 | interrupt payload 补 question；web_runner 兜底 text | DP-05：human_review interrupt 断言 question 非空 |
| 13 | H-11/H-12/H-14 VCR 链路 | match_on 加 body；Cassette 加 RLock/回放串行；默认 'none'+启动 fail-fast | 改 prompt 回放不命中旧交互；并发回放无重复消费；cassette 缺失启动报错 |
| 14 | M-18 exports 恒空 | 导出目录绑定任务（EXPORT_OUTPUT_DIR=output/{task_id}/） | DP-02：任务完成后 exports 非空且 export_file 200 |
| 15 | H-15 依赖声明 | pyproject 补 fastapi/uvicorn/sse-starlette/sqlite + vcrpy dev extra | 干净 venv 按文档安装后 import web.main 成功 |

### P2 状态机与体验

| # | 条目 | 最小修复 | 回归测试锚点 |
|---|------|---------|-------------|
| 16 | H-02 pending 锁死 | 终态分支清 pending；fatal message 追加；卡灰态 | 超时事件序列断言输入恢复+提示存在 |
| 17 | H-17/H-18 切换/回滚 | openTask 守卫 + 流关闭；resume 成功后再清 pending | 乱序快照无串台；mock resume reject 卡恢复 |
| 18 | M-01..M-05 展示层 | 键大写比对；handleNew reset；日志计数分母；snap.state 接线；pendingRef 带 stageId | 各条目锚点（配置徽标/新建清空/行数/卡 1 产出/历史回填） |
| 19 | M-06 事件流缺口 | 分级丢弃 + 先订阅后重放 + 终态关流 + after_seq 续播 | 队列满关键事件不丢；重放间隙补发；任务完成流关闭 |
| 20 | M-21/H-16 测试补强 | 按 M-21 断言锚点补离线测试；E2E 加数据合理性断言 | 逐项红测；注入错位数据断言 E2E 失败 |

### P3 性能与清理

| # | 条目 | 最小修复 | 回归测试锚点 |
|---|------|---------|-------------|
| 21 | M-03/M-08/M-12/M-14 | 日志节流/列表瘦身/总结异步/traces 累积 | 500+ log 渲染可控；列表无 state_json；慢 LLM 先 task_completed；两轮 traces 求和 |
| 22 | M-07 测试污染 | fixture 重绑 emitter/log_bridge + 假图 | 测试后真实 DB 事件数不变 |
| 23 | M-19/M-20 部署链 | preview.proxy；后端挂载 dist；VITE_API_BASE | preview 模式 /api 通；单进程 '/' 返回 index.html |
| 24 | M-24/L-12/L-13 死代码 | 删除/归档 useMockPipeline、mock/results、mock/tasks、QualityReport；api.js 补 openFile | grep 零引用；点击打开调真实端点 |
| 25 | L-01..L-15 低严重度 | 按各条目最小修复 | 各条目回归锚点 |
