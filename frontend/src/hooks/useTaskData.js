import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/services/api'
import { previewReadKey } from '@/services/resultPages'

const READERS = { reviewActivity:api.getReviewActivity, analysisRecords:api.getAnalysisRecords, records: api.getRecords, sources: api.getSources, sourceList: api.getSourceList, figures: api.getFigures, coverage: api.getCoverage, quality: api.getQuality, exports: api.getExports, materials:api.getMaterials, changes:api.getChanges, insights:api.getInsights, differences:api.getDifferences, activity:api.getActivity, matrix:api.getCoverageMatrix }
const empty = (status, ended = false) => Object.fromEntries(Object.keys(READERS).map(key => [key, { status, data: null, error: null, ended }]))

// Every read uses the delivery visible to this task or replay. The epoch and
// resource versions prevent a late response from replacing a newer selection.
export function useTaskData(task, taskDone, loadLegacy = false, showPreview = true) {
  const taskId = task?.task_id
  const deliveryId = task?.delivery_ref?.id
  const deliveryRevision = task?.delivery_ref?.version
  const ready = !!deliveryId
  const partial = ready && ['cancelled','error','failed','interrupted','budget_exhausted'].includes(task?.status)
  const availability = !ready ? 'waiting' : partial ? 'partial' : 'ready'
  const [state, setState] = useState({ taskId: null, deliveryId: null, deliveryRevision:null, resources: empty('waiting') })
  const [preview, setPreview] = useState(null)
  const previewRevision = previewReadKey(task)
  const [previewPaging,setPreviewPaging]=useState(null)
  const previewOffset=previewPaging&&previewPaging.revision===previewRevision&&previewPaging.taskId===taskId?previewPaging.offset:0
  const previewEligible = showPreview && (!task?.readOnly || task?.presentation?.historical===false) && !ready && !!task?.query_ref && !['legacy','replay'].includes(task?.kind) && task?.science_state!=='sealed' && (task?.preview_revision!=null || typeof task?.core_event_cursor==='number')
  useEffect(() => {
    if (!taskId || !previewEligible) return
    const controller = new AbortController()
    setPreview({taskId,revision:previewRevision,status:'settling'})
    api.getPreview(taskId, { signal: controller.signal },{offset:previewOffset,limit:50,...(task.preview_revision?{expected_preview_id:task.preview_revision}:previewOffset&&previewPaging?.token?{expected_preview_id:previewPaging.token}:{})}).then(data => {
      if (!controller.signal.aborted) setPreview({ taskId, revision:previewRevision, status: 'success', data })
    }).catch(error => {
      if (!controller.signal.aborted) setPreview({ taskId, revision:previewRevision, status: 'error', error: error.message })
    })
    return () => controller.abort()
  }, [taskId, previewEligible, previewRevision,previewOffset])
  const epoch = useRef(0), versions = useRef({}), current = useRef(null), snapshot = useRef(null)
  const controllers = useRef(new Map())
  current.current = { taskId, deliveryId, deliveryRevision, availability }
  const reload = useCallback(async (only) => {
    if (!taskId || current.current.availability === 'waiting') return
    const generation = epoch.current
    const keys = typeof only === 'string' && READERS[only] ? [only] : Object.keys(READERS)
    await Promise.allSettled(keys.map(async key => {
      controllers.current.get(key)?.abort()
      const controller = new AbortController()
      controllers.current.set(key, controller)
      const version = versions.current[key] = (versions.current[key] || 0) + 1
      const valid = () => !controller.signal.aborted && epoch.current === generation && current.current.taskId === taskId && current.current.deliveryId === deliveryId && current.current.deliveryRevision === deliveryRevision && current.current.availability !== 'waiting' && versions.current[key] === version
      const update = patch => { if (valid()) setState(prev => {
        if (!valid()) return prev
        const resources = prev.taskId === taskId && prev.deliveryId === deliveryId && prev.deliveryRevision === deliveryRevision ? prev.resources : empty('settling')
        return { taskId, deliveryId, deliveryRevision, resources: { ...resources, [key]: { ...resources[key], ...patch } } }
      }) }
      update({ status: 'settling', refreshing: true, error: null })
      const read = async () => {
        try {
          let data
          if(key==='records' && !loadLegacy) {
            const page=await api.getRecordsPage(taskId,deliveryId,deliveryRevision,{}, {signal:controller.signal})
            data=Object.assign(page.items,{page, total:page.aggregates?.total??page.total,aggregates:page.aggregates,snapshot_ref:page.snapshot_ref})
          } else data = await READERS[key](taskId, deliveryId, deliveryRevision, { signal: controller.signal })
          if (!valid()) return
          const scope = data?.snapshot_ref || data?.report?.snapshot_ref
          if (scope && snapshot.current && JSON.stringify(scope)!==JSON.stringify(snapshot.current)) throw new Error('此资源的科学快照与当前成果版本不一致，请重新读取')
          if (scope) snapshot.current=scope
          update({ status: 'success', data, error: null, refreshing: false })
        } catch (error) { update({ status: 'error', error: error.message, refreshing: false }) }
        finally { if (controllers.current.get(key) === controller) controllers.current.delete(key) }
      }
      await read()
    }))
  }, [taskId, deliveryId, deliveryRevision, availability, loadLegacy])
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
    return () => { epoch.current++; for (const controller of controllers.current.values()) controller.abort(); controllers.current.clear() }
  }, [taskId, deliveryId, deliveryRevision, availability, loadLegacy])
  useEffect(() => {
    if (loadLegacy && taskId && ready) ensure(...Object.keys(READERS).filter(key => !['sourceList','analysisRecords','reviewActivity'].includes(key)))
  }, [loadLegacy, taskId, ready, ensure])
  let resources = state.taskId === taskId && state.deliveryId === deliveryId && state.deliveryRevision === deliveryRevision && ready
    ? state.resources : empty(ready ? 'settling' : 'waiting', taskDone || ['failed','cancelled','error'].includes(task?.status))
  if (task?.readOnly && Array.isArray(resources.exports.data)) {
    const visible = resources.exports.data.filter(file => file.created_at && file.created_at <= task.presentation?.at && file.delivery_revision === deliveryRevision)
    resources = { ...resources, exports: { ...resources.exports, data: visible } }
  }
  const visiblePreview=previewEligible&&preview?.taskId===taskId&&preview.revision===previewRevision?{...preview,onPage:offset=>setPreviewPaging({taskId,revision:previewRevision,offset,token:preview.data?.preview_id})}:null
  return { taskId,deliveryId,deliveryRevision,availability, preview:visiblePreview, resources, reload, ensure,
    getDetail:(type,id,options)=>({record:api.getRecord,source:api.getSource,figure:api.getFigure}[type])(taskId,deliveryId,deliveryRevision,id,options) }
}
