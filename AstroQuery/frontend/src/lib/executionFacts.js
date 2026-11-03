const MODULES = new Set(['quality_check', 'clean', 'deliver', 'insight'])
export function timingEvent(event) {
  if (!/^(task_|stage_|flow_|agent_)/.test(event.type || '')) return null
  const stage = event.flow_id === 'insights' || /^(FieldInsight|Relationship|Recommendation|Synthesis)Agent$/.test(event.agent || '') ? 'insight' : event.stage_id
  return { type: event.type, seq: event.seq, ts: event.ts, stage_id: stage, duration: event.duration, agent: event.agent, flow_id: event.flow_id }
}
export function intervalSeconds(intervals) {
  const ordered = intervals.filter(([a,b]) => Number.isFinite(a) && Number.isFinite(b) && b >= a).sort((a,b) => a[0] - b[0])
  let sum = 0, end = null
  for (const [a,b] of ordered) { sum += end == null || a > end ? b-a : Math.max(0,b-end); end = end == null ? b : Math.max(end,b) }
  return sum
}
export function stageSeconds(events, stageId) {
  const rows = events.filter(event => event.stage_id === stageId)
  if (!MODULES.has(stageId)) {
    const ends = rows.filter(event => event.type === 'stage_completed' && Number.isFinite(event.duration) && event.duration >= 0)
    return ends.length ? ends.reduce((sum, event) => sum + event.duration, 0) : null
  }
  const ends = rows.filter(event => event.type === 'agent_completed' && Number.isFinite(event.duration) && event.duration >= 0)
  // Stored backend timestamps are required; live SSE does not include ts.
  // Never substitute receipt timestamps or sum overlapping agent durations.
  if (!ends.length || ends.some(event => !Number.isFinite(event.ts))) return null
  return intervalSeconds(ends.map(event => [event.ts - event.duration, event.ts]))
}
export function taskSeconds(events, task, now = Date.now()) {
  const starts = events.filter(event => event.type === 'task_started' && Number.isFinite(event.ts))
  const ends = events.filter(event => ['task_completed','task_cancelled','task_failed'].includes(event.type) && Number.isFinite(event.ts))
  const start = starts[0]?.ts * 1000
  const end = ends[0]?.ts * 1000
  const terminal = ['completed','error','failed','cancelled'].includes(task?.status)
  if (Number.isFinite(start)) return { seconds: Math.max(0, ((Number.isFinite(end) ? end : terminal ? Date.parse(task.completed_at) : now) - start) / 1000), basis: '从开始执行到终止，含等待确认' }
  const created = Date.parse(task?.created_at), completed = Date.parse(task?.completed_at)
  if (!Number.isFinite(created) || (terminal && !Number.isFinite(completed))) return { seconds: null, basis: '该任务未提供完整计时' }
  return { seconds: Math.max(0, ((terminal ? completed : now) - created) / 1000), basis: '从创建到终止，含排队与等待确认' }
}
