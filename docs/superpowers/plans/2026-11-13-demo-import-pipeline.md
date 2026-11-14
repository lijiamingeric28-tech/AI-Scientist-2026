# 大样例导入时间优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 缩短最新 SN 2014J 样例首次完整导入时间，不增加流式接口，不改变展示或科研内容。

**Architecture:** 在现有 `PublishedDemos.open` 内优化导入关键路径，实验验证有界流水线能否重叠解压、解析和 SQLite 写入。更大缓冲与缓存实验无稳定收益，不采用。将完整 FULL WAL 提交之后的 checkpoint 页整理单独维护，使其与后续阅读重叠；每个样例服务最多一个维护线程，无法准备时使用原同步路径，服务关闭时等待线程退出。只有实际测量有效的改动进入产品；保持校验、逐行顺序、同样例单飞、单次权威事务和完整持久化强度。

**Tech Stack:** Python 标准库 lzma/io/threading/queue、SQLite、pytest；不引入依赖。

**Spec:** 用户本聊天选择“还是优化导入时间”；沿用已批准 `docs/superpowers/specs/2026-11-13-sample-startup-loading-design.md` 的数据和科学安全边界。

## Global Constraints

- 不修改 `.jsonl.xz` 内容或格式、科学规范、历史数据、导出与前端样式。
- 不降低 synchronous、外键或完整事务要求；不跳过包哈希、身份、表结构、任务及快照检查。
- 复用此前隔离暂存目录；回写前保存本轮原文件哈希，只回写本轮通过验证的文件。保留现有未提交修改，不提交或推送。
- 大行可超过缓冲预算，但不得无界积累大行；生产者失败、消费者失败或取消都必须退出，不留下线程或半成品任务。

## Review Focus

- 最后一个损坏行仍使全部数据库写入回滚，失败可重试。
- 大于缓冲预算的单行不死锁，批处理顺序与原始 BLOB 字节保持一致。
- 单任务及不同任务并发不重复导入，不耗尽线程或阻塞其他已导入样例。
- 写入错误必须及时终止生产者，不能卡在队列或吞掉原始错误。
- 更大的缓冲不改变 JSON 编码、完整性检查及最终 EOF/压缩流校验。

## Tasks

- [x] **1 测量与保全：** 保存 importer/tests 及哈希。用最新样例的隔离临时数据库，分别测原路径、缓冲和流水线；记录完整导入、提交、解压/解析时间。先运行现有导入回归，基线为 6 项通过。
- [x] **2 测试先行：** 在 `AstroQuery/tests/rebuild/test_demo_loading_speed.py` 添加完整提交不等待 checkpoint 的并发测试、崩溃后 WAL 恢复、提交错误与 anchor 准备失败回退测试；覆盖有界预读、大行、读尾异常、写入失败和准备中断。新增行为均经过失败到通过验证。
- [x] **3 最小实现：** 修改 `AstroQuery/backend/src/astroquery_ai/runtime/published_demos.py`，并在 `api/http.py` 的既有生命周期释放时等待维护退出；采用有效的有界预读及 checkpoint 重叠，保留返回值、锁、FULL 提交及事务边界。22 项专项测试和 Ruff 通过；增加 SQLite 修复版本守卫，独立复审通过。
- [x] **4 验证与交付：** 最新样例 5 组独立进程首次导入前后比较；全部 7 份样例 API 及原始行指纹一致。后端离线全量 1428 项通过，专项 22 项通过。三个文件按哈希回写并重启后端，前端 HMR 保留；全部权威表与用户知识文件审计一致。实际收益及剩余成本见 `docs/performance/2026-11-13-demo-import.md`，完整可读 P95 仍为 8.499 秒，不宣称达标。
