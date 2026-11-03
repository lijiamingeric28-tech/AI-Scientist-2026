const LABELS = { prepare: '请求理解与天体核验', start_science: '冻结请求与分支调度', catalog_discover: '动态星表发现', catalog_extract: '星表对象匹配与提取', attachment_extract: '附件表格核验与提取',
  literature_discover: '文献检索与作品去重', acquire_window: '正文获取与版本核验', attachment_discover: '官方附件发现', paper_batch: '正文分批视觉提取',
  source_reconcile: '作品内主体、结果与来源复核', apply_source_recheck: '应用来源复核与重新质检', interpret_uncertainty: '原报不确定度核验', review_source_gap: '责任模块补核',
  quality_verify:'统一原文质检', quality_reextract:'有据局部重提与复检', quality_citation_enrich:'原文引用的一层摘要', compare_results:'有据重复归档与疑似矛盾核验',
  assess_batch: '数据语义与处理路由', normalize: '同量标准化与独立核验', apply_review: '人工解释复检', finalize: '处理后复检、差异与数据封口', insights: '数据洞察' }
const EXECUTION_LABELS = { catalog: '星表检索与提取', literature: '文献检索', acquisition: '正文及官方附件获取', extraction: '正文、附件提取与作品复核', quality: '质量检查与必要人工审核', normalization: '同量标准化', postcheck: '处理后复检与差异', delivery: '快照与交付', insight: '洞察解释' }
const EXECUTION_CARDS = { catalog: 'retrieval', literature: 'retrieval', acquisition: 'retrieval', extraction: 'extraction', quality: 'quality_check', normalization: 'clean', postcheck: 'deliver', delivery: 'deliver', insight: 'insight' }
const status = value => ({ succeeded: 'completed', failed: 'error', not_run: 'skipped', ready: 'waiting', waiting_dependency: 'waiting', awaiting_review: 'waiting' }[value] || value)
function phase(jobs) { return !jobs.length ? 'waiting' : jobs.some(job => job.status === 'running') ? 'running' : jobs.some(job => ['ready', 'waiting_dependency', 'awaiting_review'].includes(job.status)) ? 'waiting' : jobs.some(job => job.status === 'failed') ? 'error' : jobs.every(job => ['succeeded', 'not_run', 'cancelled'].includes(job.status)) ? 'completed' : 'waiting' }
export function runtimeStage(base, projection, snapshot) {
  if (projection.blocks) return { ...base, ...projection, business: true, materials: base.id === 'retrieval' ? snapshot.presentation?.materials || [] : [],
    substeps: [], flows: [], groups: [], agents: [], clarifications: [], errors: [],
    properties: snapshot.presentation?.properties || [], counts: snapshot.presentation?.counts || {},
    target: snapshot.presentation?.target, lifecycle: snapshot.presentation?.lifecycle,
    activeStage: snapshot.presentation?.active_stage, wallSeconds: snapshot.presentation?.wall_seconds,
    activity: snapshot.presentation?.chat_activity, deliverySummary: snapshot.presentation?.delivery_summary,
    request: snapshot.presentation?.request,
    delivered: Boolean(snapshot.presentation?.delivery_ref), progress: snapshot.presentation?.chat_progress || {},
    recordCounts: snapshot.presentation?.records_per_property, insightStates: snapshot.presentation?.insight_properties || {},
    cleanExample: snapshot.presentation?.clean_example, comparisonByProperty: snapshot.presentation?.comparison_by_property || {},
    reviews: snapshot.presentation?.reviews || [],
    uniqueReadable: snapshot.presentation?.unique_readable, reviewReceipts: snapshot.presentation?.review_receipts || [] }
  const jobs = projection.jobs || []
  const agents = jobs.map(job => ({ id: job.job_id, agent: LABELS[job.kind] || job.kind, name: job.owner, label: LABELS[job.kind] || job.kind,
    status: status(job.status), logs: [], reason: job.reason, source_id: job.payload?.table_id || job.payload?.work_id }))
  const result = { ...base, ...projection, substeps: [], flows: [], groups: [], clarifications: [], status: status(projection.status), agents,
    sequential: Boolean(snapshot.execution_stage),
    summary: projection.total ? `${projection.completed}/${projection.total} 项作业已提交` : '',
    errors: jobs.filter(job => job.status === 'failed').map(job => ({ node: LABELS[job.kind] || job.kind, message: job.reason || '此项未完成，详见覆盖记录' })) }
  const execution = snapshot.execution_stage
  if (execution && EXECUTION_CARDS[execution.stage_id] === base.id && !['completed', 'failed', 'cancelled'].includes(snapshot.lifecycle)) {
    result.summary = `${EXECUTION_LABELS[execution.stage_id]} · ${execution.running || 0} 项正在执行，${execution.pending || 0} 项待处理${execution.waiting_resource ? `（${execution.waiting_resource} 项等待资源）` : ''}`
  }
  if (base.id === 'understand' && snapshot.draft?.target) {
    const target = snapshot.draft.target, selected = new Set(snapshot.draft.selected_property_ids)
    result.output = { targetEntity: target.main_id, simbad: { mainId: target.main_id, otype: target.primary_otype, ra: target.coordinates?.ra_deg, dec: target.coordinates?.dec_deg, aliases: target.aliases },
      properties: (snapshot.draft.property_support?.bindings || []).filter(binding => selected.has(binding.property_id)).map(binding => ({ propertyId: binding.property_id, name: binding.definition.name_cn, unit: binding.output_profile.unit.canonical_symbol || '' })) }
  }
  if (['understand', 'insight', 'deliver'].includes(base.id)) result.substeps = jobs.map(job => ({ id: job.job_id, label: LABELS[job.kind] || job.kind, status: status(job.status), detail: job.reason || '' }))
  if (base.id === 'retrieval') {
    const groups = [ ['database', '星表检索', [['database/discovery', '动态发现', ['catalog_discover']], ['database/match', '对象匹配与列提取', ['catalog_extract']]]],
      ['paper', '文献检索与正文获取', [['paper/search', '作品检索、去重与排序', ['literature_discover']], ['paper/download', '正文获取与版本核验', ['acquire_window']]]],
      ['supplementary', '官方结构化附件', [['supplementary/find', '官方关联与文件发现', ['attachment_discover']], ['supplementary/summary', '对象、列和测量核验', ['attachment_extract']]]] ]
    result.groups = groups.map(([id, name, steps]) => ({ id, name, steps: steps.map(([stepId, label, kinds]) => {
      const items = jobs.filter(job => kinds.includes(job.kind)), running = items.find(job => job.status === 'running')
      return { id: stepId, label, status: phase(items), detail: items.length ? '进度表示已登记作业，科学覆盖及缺口单独记录。' : '尚无此步骤的已登记作业',
        ...(items.length ? { progress: { completed: items.filter(job => job.status === 'succeeded').length, total: items.length, current: running?.payload?.table_id || running?.payload?.work_id || '' } } : {}) }
    }).filter(step => !result.sequential || step.id !== 'supplementary/summary') }))
  }
  if (base.id === 'extraction') result.substeps = jobs.map(job => ({ id: job.job_id, label: LABELS[job.kind] || job.kind, status: status(job.status),
    detail: job.payload?.core_pages?.length ? `核心页：${job.payload.core_pages.join('、')}；来源：${job.payload.work_id}` : job.reason || '' }))
  if (base.id === 'clean') {
    result.agents = agents.map(agent => ({ ...agent, flow_id: 'normalization', round: 0 }))
    result.flows = jobs.length ? [{ flowId: 'normalization', round: 0, status: phase(jobs), note: '各测量是否转换成功见处理报告' }] : []
    if (snapshot.delivery_ref && !result.sequential) result.flows.push({ flowId: 'conflict', round: 0, status: 'completed', note: '依据已封口快照生成差异说明' })
    const reviews = snapshot.reviews || []
    if (reviews.length && !result.sequential) {
      const pending = reviews.some(review => ['pending', 'accepted'].includes(review.status))
      result.flows.push({ flowId: 'human_review', round: 0, status: pending ? 'waiting' : 'completed', note: pending ? '等待判断或责任模块复检' : '答案与复检记录已保存' })
      result.agents.push(...(snapshot.jobs || []).filter(job => job.kind === 'apply_review').map(job => ({ id: job.job_id, agent: LABELS[job.kind], status: status(job.status), flow_id: 'human_review', round: 0 })))
    }
  }
  if (base.id === 'quality_check' && result.sequential) {
    result.substeps = (snapshot.reviews || []).map(review => ({ id: review.review_id, label: '人工判断与答后复检',
      status: ['pending', 'accepted'].includes(review.status) ? 'waiting' : 'completed',
      detail: review.status === 'pending' ? '等待依据原件判断' : review.status === 'accepted' ? '答案已收到，等待责任模块复检' : review.status === 'applied' ? '答案和复检记录已保存' : review.answer ? '答复未应用，原因见详情' : '未应用人工答案，关闭原因见详情' }))
  }
  if (base.id === 'insight' && projection.scope === 'disabled_pending_content') { result.status='skipped'; result.summary='新洞察待知识内容接入，本轮未启用（零模型调用）' }
  return result
}
