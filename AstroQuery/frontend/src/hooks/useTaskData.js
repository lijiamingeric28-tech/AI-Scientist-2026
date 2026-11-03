import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/services/api'

const READERS = { records: api.getRecords, sources: api.getSources, figures: api.getFigures, coverage: api.getCoverage, quality: api.getQuality, exports: api.getExports, materials:api.getMaterials, changes:api.getChanges, insights:api.getInsights, differences:api.getDifferences, activity:api.getActivity, matrix:api.getCoverageMatrix }
const empty = (status, ended = false) => Object.fromEntries(Object.keys(READERS).map(key => [key, { status, data: null, error: null, ended }]))

// Final endpoints resolve a replay to its source case: never request them while
// replay is active. Epoch + per-resource versions also reject late old responses.
export function useTaskData(task, taskDone, loadLegacy = false) {
  const taskId = task?.task_id
  const deliveryId = task?.delivery_ref?.id
  const deliveryRevision = task?.delivery_ref?.version
  const ready = !!deliveryId
  const partial = ready && ['cancelled','error','failed','interrupted','budget_exhausted'].includes(task?.status)
  const availability = !ready ? 'waiting' : partial ? 'partial' : 'ready'
  const [state, setState] = useState({ taskId: null, deliveryId: null, deliveryRevision:null, resources: empty('waiting') })
  const [preview, setPreview] = useState(null)
  const previewEligible = (!task?.readOnly || task?.presentation?.historical===false) && !ready && !!task?.query_ref && !['legacy','replay'].includes(task?.kind) && task?.science_state!=='sealed' && typeof task?.core_event_cursor==='number'
  useEffect(() => {
    let cancelled = false
    setPreview(null)
    if (taskId && previewEligible) {
      api.getPreview(taskId).then(data => {
        if (!cancelled) setPreview({ taskId, status: 'success', data })
      }).catch(error => {
        if (!cancelled) setPreview({ taskId, status: 'error', error: error.message })
      })
    }
    return () => { cancelled = true }
  }, [taskId, previewEligible, task?.core_event_cursor])
  const epoch = useRef(0), versions = useRef({}), current = useRef(null), snapshot = useRef(null)
  current.current = { taskId, deliveryId, deliveryRevision, availability }
  const reload = useCallback(async (only) => {
    if (!taskId || current.current.availability === 'waiting') return
    const generation = epoch.current
    const keys = typeof only === 'string' && READERS[only] ? [only] : Object.keys(READERS)
    await Promise.allSettled(keys.map(async key => {
      const version = versions.current[key] = (versions.current[key] || 0) + 1
      const valid = () => epoch.current === generation && current.current.taskId === taskId && current.current.deliveryId === deliveryId && current.current.deliveryRevision === deliveryRevision && current.current.availability !== 'waiting' && versions.current[key] === version
      const update = patch => { if (valid()) setState(prev => valid() ? ({ taskId, deliveryId, deliveryRevision, resources: { ...(prev.taskId === taskId && prev.deliveryId === deliveryId ? prev.resources : empty('settling')), [key]: { ...prev.resources[key], ...patch } } }) : prev) }
      update({ status: 'settling', refreshing: true, error: null })
      const read = async () => {
        try {
          const data = await READERS[key](taskId, deliveryId, deliveryRevision)
          if (!valid()) return
          const scope = data?.snapshot_ref || data?.report?.snapshot_ref
          if (scope && snapshot.current && JSON.stringify(scope)!==JSON.stringify(snapshot.current)) throw new Error('此资源的科学快照与当前成果版本不一致，请重新读取')
          if (scope) snapshot.current=scope
          update({ status: 'success', data, error: null, refreshing: false })
        } catch (error) { update({ status: 'error', error: error.message, refreshing: false }) }
      }
      await read()
    }))
  }, [taskId, deliveryId, deliveryRevision, availability])
  const requested = useRef(new Set())
  const ensure = useCallback((...keys) => {
    if (!ready || current.current.taskId !== taskId || current.current.deliveryRevision !== deliveryRevision) return
    for (const key of keys) {
      if (READERS[key] && !requested.current.has(key)) {
        requested.current.add(key)
        void reload(key)
      }
    }
  }, [ready, reload, taskId, deliveryRevision])
  useEffect(() => {
    epoch.current++
    versions.current = {}
    snapshot.current = null
    requested.current = new Set()
    setState({ taskId, deliveryId, deliveryRevision, resources: empty(availability === 'waiting' ? 'waiting' : 'settling') })
    return () => { epoch.current++ }
  }, [taskId, deliveryId, deliveryRevision, availability])
  useEffect(() => {
    if (loadLegacy && taskId && ready) ensure(...Object.keys(READERS))
  }, [loadLegacy, taskId, ready, ensure])
  let resources = state.taskId === taskId && state.deliveryId === deliveryId && state.deliveryRevision === deliveryRevision && ready
    ? state.resources : empty('waiting', taskDone || ['failed','cancelled','error'].includes(task?.status))
  if (task?.readOnly && Array.isArray(resources.exports.data)) {
    const visible = resources.exports.data.filter(file => file.created_at && file.created_at <= task.presentation?.at && file.delivery_revision === deliveryRevision)
    resources = { ...resources, exports: { ...resources.exports, data: visible } }
  }
  return { taskId,deliveryId,deliveryRevision,availability, preview: previewEligible && preview?.taskId === taskId ? preview : null, resources, reload, ensure }
}
