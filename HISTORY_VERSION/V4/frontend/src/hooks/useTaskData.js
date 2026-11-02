import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/services/api'

const READERS = { records: api.getRecords, sources: api.getSources, figures: api.getFigures, quality: api.getQuality, exports: api.getExports }
const empty = (status, ended = false) => Object.fromEntries(Object.keys(READERS).map(key => [key, { status, data: null, error: null, ended }]))
const DELAYS = [500, 1500, 3000]
const isEmpty = data => data == null || (Array.isArray(data) ? !data.length : !Object.keys(data.quality_report || data).length)

// Final endpoints resolve a replay to its source case: never request them while
// replay is active. Epoch + per-resource versions also reject late old responses.
export function useTaskData(task, taskDone, succeeded = false) {
  const taskId = task?.task_id
  const ready = task?.status === 'completed' || (taskDone && succeeded)
  const partial = !ready && !task?.replay_of && ['failed', 'cancelled', 'error'].includes(task?.status)
  const availability = ready ? 'ready' : partial ? 'partial' : 'waiting'
  const [state, setState] = useState({ taskId: null, resources: empty('waiting') })
  const epoch = useRef(0), versions = useRef({}), timers = useRef(new Set()), current = useRef(null)
  current.current = { taskId, availability }
  const clearTimers = useCallback(() => { timers.current.forEach(clearTimeout); timers.current.clear() }, [])
  const reload = useCallback(async (only) => {
    if (!taskId || current.current.availability === 'waiting') return
    const generation = epoch.current
    const keys = typeof only === 'string' && READERS[only] ? [only] : Object.keys(READERS)
    await Promise.allSettled(keys.map(async key => {
      const version = versions.current[key] = (versions.current[key] || 0) + 1
      const valid = () => epoch.current === generation && current.current.taskId === taskId && current.current.availability !== 'waiting' && versions.current[key] === version
      const update = patch => { if (valid()) setState(prev => ({ taskId, resources: { ...(prev.taskId === taskId ? prev.resources : empty('settling')), [key]: { ...prev.resources[key], ...patch } } })) }
      update({ status: 'settling', refreshing: true, error: null })
      const read = async attempt => {
        try {
          const data = await READERS[key](taskId)
          if (!valid()) return
          if (isEmpty(data) && availability === 'ready' && attempt < DELAYS.length) {
            const timer = setTimeout(() => { timers.current.delete(timer); if (valid()) read(attempt + 1) }, DELAYS[attempt])
            timers.current.add(timer)
            return
          }
          update({ status: 'success', data, error: null, refreshing: false })
        } catch (error) { update({ status: 'error', error: error.message, refreshing: false }) }
      }
      await read(0)
    }))
  }, [taskId, availability])
  useEffect(() => {
    epoch.current++; versions.current = {}; clearTimers()
    setState(prev => ({ taskId, resources: availability === 'waiting' ? empty('waiting') : prev.taskId === taskId ? prev.resources : empty('settling') }))
    if (taskId && availability !== 'waiting') reload()
    return () => { epoch.current++; clearTimers() }
  }, [taskId, availability, reload, clearTimers])
  return { availability, resources: state.taskId === taskId && availability !== 'waiting' ? state.resources : empty('waiting', taskDone || ['failed', 'cancelled', 'error'].includes(task?.status)), reload }
}
