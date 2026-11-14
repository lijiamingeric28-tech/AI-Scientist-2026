# 资料详情页与结构化科研解读实施计划

用户已批准完整方案。本文件记录执行接口和安全边界；目标是去掉独立“总结与洞察”，把资料详情作为阅读入口，按需生成两种独立补充报告。

约束：普通隔离暂存＋源码/数据库恢复快照；保留当前分支、HEAD、暂存区和用户未提交修改；不提交推送。不运行真实样例生成，不修改科研规则、历史对象或导出内容。主题全部使用现有语义变量；横屏1440/1280/1024。

## 1 数据投影
- 现有materials workbench详情增加available_properties/profile/准确范围统计；只从已封存对象计算本资料条件、波段、单位、历元描述，未知不推测。
- 本资料和property_comparison范围分别固定IDs，旧报告复用需明确区分全性质范围；不能将全任务记录数当资料记录数。
- 测试投影、引用完整性与历史边界，GET不调用模型。

## 2 补充服务
- 新service MaterialAnalysisService，SQLite独立运行表material_analysis_runs，完成报告用不可变material_analysis对象；不改原任务生命周期/query/delivery/insight指针。
- GET/POST /api/tasks/{tid}/deliveries/{did}/material-analysis，精确修订/资料/性质及scope=material|property_comparison；GET支持report_version、at_seq、sealed_only。POST需要operation_id、expected_delivery_revision，返回run_id。状态GET /api/tasks/{tid}/material-analysis-runs/{rid}，停止POST .../{rid}/stop。
- 按准确交付、上下文hash、范围、输入协议去重；任务重启保存检查点，未完成运行标记interrupted，明确重试；成功版本不覆盖。
- Model输出复用现有已资格化的research-property-short-2协议及M11 profile，MaterialAnalysis/1是新的存储/引用投影，不隐式获得新的科学资格。每次调用仍走production ProfileAuthority和预算；仅精确运行许可允许已完成live任务进行M11只读分析，不能使用material_summary宽松许可。新增/改变执行协议必须重新资格检查。
- 分批复用property_insight_generation.plan，全部记录覆盖，单批一次主调用＋一次局部修复，已有检查点复用。字段参考测量只引用真实ID，理论公式只从保存知识解析，建议不自动执行；无依据不默认high。
- 新任务使用task_knowledge.load，旧任务用historical_knowledge_context只读依据；保存运行context供生成/追问一致使用。GET无模型，历史回放不可POST。

## 3 页面
- 删除DataView独立导航与相关急切加载，旧insights记忆回退candidates；历史API保留。
- 紧凑身份/PDF/来源链接＋性质胶囊＋局部锚点；资料概览、原总结与解读、使用建议、跨来源对照、数据图像、来源。
- 新MaterialReading组件管理严格scope缓存/迟到请求保护/手动生成/版本选择/状态，新增MaterialAnalysisView呈现四段、参考测量/理论/建议/场景；公式复用LatexMath。来源说明和知识点击覆盖抽屉。
- 记录/附表/图像局部tabs按需读；生成状态5秒轻量轮询，隐藏停止，后台任务不随离开页面取消。返回保持筛选/分页/滚动。
- 追问携带material_analysis_ref，backend按相同任务交付和context验证并载入所选补充报告。

## 4 验证与交付
- 按任务RED→GREEN目标测试；全量frontend测试/build、backend离线回归、实际挂载UI和主题/横屏检查。
- 7份真实样例原始导出5格式逐个比较，权威原表与知识文件哈希不变（新增空辅助表单列）。
- 一次最终独立fresh-context review；修复后覆盖测试。文件哈希保护回写，静态入口最后更新，重启后科学预检ready、前端HMR保留；不自动调用模型。
