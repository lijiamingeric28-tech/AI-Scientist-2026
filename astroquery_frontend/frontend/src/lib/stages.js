/* 流水线阶段结构定义（与数据源无关）
 *
 * 结构对齐后端：
 * - 阶段状态: waiting | running | completed | error | skipped | cancelled
 * - 澄清 payload 对齐 subgraph1 interrupt 真实结构（type/question/target_entity/requested_properties）
 * - 完成态输出对齐 MainGraphState 字段（target_entity / simbad_info / property_spec）
 *
 * 注：本文件只提供"骨架结构"。真实数值全部来自 SSE 事件流 / state 快照
 * （hooks/usePipeline.js），不存在 mock 数据。
 */

export const STAGE_DEFS = [
  { id: 'understand', name: '任务理解' },
  { id: 'retrieval', name: '数据检索' },
  { id: 'extraction', name: '数据提取' },
  { id: 'quality_check', name: '质量检查' },
  { id: 'clean', name: '数据清洗' },
  { id: 'deliver', name: '数据交付' },
  { id: 'insight', name: '数据洞察' },
  { id: 'done', name: '任务完成' },
]

/* 「数据洞察」阶段（前端虚拟阶段）：后端把 insights 子图挂在 deliver 阶段内
 * （flow_id='insights'），前端把它提升为独立阶段展示。
 * 4 个 agent 线性串联：字段洞察 → 跨字段关系 → 使用建议 → 综合叙述。
 * 状态由 flow_started/flow_completed(flow_id='insights') 事件推导；
 * 报告内容来自 /state 快照的 final_output.quality_report.output_state.insights。 */
export const INSIGHT_AGENTS = [
  { id: 'FieldInsightAgent', label: '字段洞察' },
  { id: 'RelationshipAgent', label: '跨字段关系' },
  { id: 'RecommendationAgent', label: '使用建议' },
  { id: 'SynthesisAgent', label: '综合叙述' },
]

/* insights flow_id → 中文展示名（工作流下钻 / flow 列表用）。
 * human_review 为前端虚拟流程（2026-08-27）：后端 HumanReview 是独立节点
 * （无 flow 事件，只有 HumanReviewAgent 的 agent 事件）——前端按固定三块
 * 结构展示卡 5：规范化/冲突消解/人工审核（未触发时显示占位“按需被选”）。 */
export const FLOW_LABELS = {
  normalization: '数据规范化',
  conflict: '冲突消解',
  human_review: '人工审核',
  export: '数据导出',
  insights: '数据洞察',
}

/* 卡 5「数据清洗」固定块顺序（人工审核虚拟块恒显示，未触发占位） */
export const CLEAN_FLOW_BLOCKS = ['normalization', 'conflict', 'human_review']

/* 清洗阶段 Agent → 所属子图 flow_id 的兜底映射（2026-08-27）。
 * 权威归属来自后端 agent 事件的 flow_id 字段（quality_pipeline/agent_events.py
 * wrap_agent_node 以 subgraph 参数写入）——真实运行/重放新事件直接可用；
 * 旧任务（无 flow_id 字段的历史事件）按子图结构的 agent 名单退化为名字匹配：
 *   normalization 子图：SourceRouter/Planning/Normalization/Validation/Report
 *   conflict 子图：VarianceAggregation/DifferenceClassification/AnomalyVerification/
 *     AnnotationConfidence/AnnotationReport
 *   human_review：HumanReviewAgent
 *   assessment → 质量检查（不进清洗卡）；deliver 子图 agent 不进清洗卡。 */
const FLOW_BY_AGENT_NAME = [
  [/^(SourceRouter|Planning|Normalization|PreNormalization|Validation|Report)/, 'normalization'],
  [/^(VarianceAggregation|DifferenceClassification|AnomalyVerification|Annotation|Conflict)/, 'conflict'],
  [/^HumanReview/, 'human_review'],
]
const FLOW_AGENT_FALLBACK = 'other'

export function flowIdOfAgent(name) {
  for (const [re, fid] of FLOW_BY_AGENT_NAME) {
    if (re.test(name || '')) return fid
  }
  return FLOW_AGENT_FALLBACK
}

/* 卡 1「任务理解」展开：垂直时间线子步骤（对齐后端 step_progress.path） */
export const UNDERSTAND_SUBSTEPS = [
  { id: 'confirm', label: '查询确认' },
  { id: 'simbad', label: 'SIMBAD 查询' },
  { id: 'research', label: '研究方向确定' },
]

/* 卡 2「数据检索」三路分组初始结构（对齐后端 retrieval 子图三路） */
export function makeRetrievalGroups() {
  return [
    {
      id: 'database',
      name: '数据库',
      steps: [
        { id: 'match', label: '数据匹配', status: 'waiting', detail: null },
        { id: 'extract', label: '数据提取', status: 'waiting', detail: null, progress: null },
        { id: 'summary', label: '总结', status: 'waiting', detail: null },
      ],
    },
    {
      id: 'paper',
      name: '论文',
      steps: [
        { id: 'build', label: '构建查询串', status: 'waiting', detail: null },
        { id: 'search', label: '检索与去重', status: 'waiting', detail: null },
        { id: 'download', label: '下载', status: 'waiting', detail: null, progress: null },
      ],
    },
    {
      id: 'supplementary',
      name: '补充材料',
      steps: [
        { id: 'find', label: '查找补充材料', status: 'waiting', detail: null, progress: null, substatus: null },
        { id: 'summary', label: '总结', status: 'waiting', detail: null },
      ],
    },
  ]
}

/* 卡 3「数据提取」四步线性展开（对齐后端节点：
 * pdf_batch_converter→vlm_batch_extractor→bbox_batch_annotator→figure_extractor→result_builder） */
export function makeExtractionSubsteps() {
  return [
    { id: 'paper', label: '论文提取', status: 'waiting', detail: null, progress: null },
    { id: 'bbox', label: '字段验证与定位', status: 'waiting', detail: null, progress: null, failures: null },
    { id: 'figure', label: '图片提取', status: 'waiting', detail: null, progress: null },
    { id: 'summary', label: '总结', status: 'waiting', detail: null },
  ]
}

/* 初始阶段骨架：agents 统一 null——渲染完全依赖后端 agent 事件动态追加。
 * insight 阶段预置 4 个 agent 子步骤（INSIGHT_AGENTS），状态随 flow/agent 事件更新。
 * flows/logs：供工作流下钻沉淀（flow 轮次 / 阶段执行期日志）。 */
export function makeInitialStages() {
  return STAGE_DEFS.map((def) => ({
    ...def,
    status: 'waiting',
    duration: null,
    summary: '',
    expanded: false,
    output: null,
    substeps: def.id === 'understand'
      ? UNDERSTAND_SUBSTEPS.map((s) => ({ ...s, status: 'waiting' }))
      : def.id === 'extraction'
        ? makeExtractionSubsteps()
        : def.id === 'insight'
          ? INSIGHT_AGENTS.map((a) => ({ id: a.id, label: a.label, status: 'waiting' }))
          : null,
    groups: def.id === 'retrieval' ? makeRetrievalGroups() : null,
    agents: null,
    flow: null,
    flows: [],
    logs: [],
    clarifications: [],
  }))
}

/* 澄清类型 → 快捷按钮（后端 interrupt 无候选列表，快捷按钮按 type 推导：
 * ask_properties 接受"全部"；final_confirm 接受 y/m/n）
 */
export const CLARIFICATION_QUICK_BUTTONS = {
  ask_properties: [{ label: '全部', value: '全部' }],
  final_confirm: [
    { label: '确认 (y)', value: 'y' },
    { label: '修改 (m)', value: 'm' },
    { label: '取消 (n)', value: 'n' },
  ],
  /* 2026-09-02：人工审核（质量管线 HITL）可点击选项卡——
     按后端 interrupt 的 options 字段生成（verdict [1-5] / next [1-3]）*/
  human_review_verdict: [
    { label: '采用 Source A (1)', value: '1' },
    { label: '采用 Source B (2)', value: '2' },
    { label: '自定义值 (3)', value: '3' },
    { label: '保留两者 (4)', value: '4' },
    { label: '跳过-保留原样 (5)', value: '5' },
  ],
  human_review_next: [
    { label: '提交裁决-执行修改 (1)', value: '1' },
    { label: '送回重新评估 (2)', value: '2' },
    { label: '取消-保留状态 (3)', value: '3' },
  ],
  human_review_custom_value: [],
  human_review_reason: [],
  /* 2026-09-02: 批量面板自绘选项卡，无静态快捷按钮 */
  human_review_batch: [],
}
