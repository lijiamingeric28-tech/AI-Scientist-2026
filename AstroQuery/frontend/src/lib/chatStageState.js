const failures = new Set(['error', 'failed', 'budget_exhausted', 'definition_invalidated'])
const order = ['understand','retrieval','extraction','quality_check','clean','comparison','deliver','insight','done']

// Chat reports the phase of work. Coverage and failed individual jobs stay in the execution view.
export function chatStageState(stage) {
  const { id, status, lifecycle, activeStage } = stage
  if (status === 'skipped' || status === 'pending' || stage.seen === false) return status
  if (id === 'done' || id === activeStage) {
    if (lifecycle === 'cancelled') return 'cancelled'
    if (failures.has(lifecycle)) return 'failed'
    if (lifecycle === 'paused' || lifecycle === 'interrupted' || lifecycle === 'pausing') return 'paused'
    if (lifecycle === 'cancelling') return 'cancelling'
    if (lifecycle === 'waiting_review' || lifecycle === 'waiting_input') return 'waiting'
  }
  if (lifecycle === 'completed') return 'completed'
  if (status === 'partial') {
    if (id === activeStage) return 'running'
    if (order.indexOf(id) < order.indexOf(activeStage) || stage.intervals?.some(i => i.end)) return 'completed'
    return 'waiting'
  }
  return status
}

export function elapsedTime(value) {
  if (!Number.isFinite(value)) return ''
  const seconds = Math.round(value)
  return seconds < 60 ? seconds+' 秒' : Math.floor(seconds/60)+' 分 '+String(seconds%60).padStart(2,'0')+' 秒'
}
