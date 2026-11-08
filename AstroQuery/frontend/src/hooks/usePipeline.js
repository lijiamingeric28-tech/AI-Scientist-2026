import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from '@/services/api'
import { makeInitialStages } from '@/lib/stages'
import { runtimeStage } from '@/lib/runtimeStages'
import { conversationTimeline } from '@/lib/conversationTimeline'

const TERMINAL = new Set(['completed', 'failed', 'error', 'cancelled', 'budget_exhausted', 'definition_invalidated'])
const DELAYS = [1000, 2000, 5000, 10000, 30000]
const IMMEDIATE_EVENTS = new Set(['task_state_changed', 'execution_stage_changed', 'question_ready', 'query_confirmed', 'review_ready', 'answer_received', 'review_applied', 'review_withdrawn', 'delivery_ready'])

export function usePipeline(task, { onTaskDone, onTaskUpdate, playback = null, conversation = true } = {}) {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState('')
  const [connectionStatus, setConnection] = useState('connected')
  const active = useRef({ id: null, epoch: 0, revision: 0, cursor: 0 })
  const source = useRef(null), timer = useRef(null), updateTimer = useRef(null), loading = useRef(null), again = useRef(false)
  const callbacks = useRef(null); callbacks.current = { onTaskDone, onTaskUpdate, status: task?.status }
  const lastDone = useRef(null), retries = useRef(0), submitted = useRef(null), creation = useRef(null)
  const playbackRef = useRef(playback); playbackRef.current = playback
  const conversationRef = useRef(conversation); conversationRef.current = conversation
  const lastScope = useRef(null)
  const frames=useRef(new Map())

  const refresh = useCallback(async () => {
    if (!active.current.id) return
    const { id, epoch } = active.current
    const player=playbackRef.current
    if(player && (!player.ready || player.taskId!==id))return
    const seq=player?.seq
    const full = !!player || conversationRef.current
    if (loading.current?.id === id && loading.current?.epoch === epoch && loading.current.full === full) { again.current = true; return }
    loading.current?.controller.abort()
    const operation = { id, epoch, full, controller: new AbortController() }
    loading.current = operation
    lastScope.current = full
    try {
      const options = {signal: operation.controller.signal}
      let state, shown
      if (full) {
        [state, shown] = await Promise.all([
          player ? {task_id:id,revision:0} : api.getConversationState(id,options),
          (player && frames.current.get(seq)) || api.getPresentation(id,seq,options),
        ])
      } else {
        state = await api.getWorkspaceState(id, options)
        shown = state.presentation || await api.getPresentation(id, null, options)
      }
      state.presentation = shown
      if (player) {
        if(operation.controller.signal.aborted || active.current.epoch!==epoch)return
        frames.current.set(seq,shown)
        if(frames.current.size>64)frames.current.delete(frames.current.keys().next().value)
        state.lifecycle=shown.lifecycle; state.status=shown.lifecycle; state.delivery_ref=shown.delivery_ref;state.query_ref=null
        state.pending=null; state.reviews=[]; state.messages=shown.messages; state.insight_ref=shown.insight_ref || null;state.core_event_cursor=shown.cursor;state.readOnly=true
        if(shown.legacy_available){
          const archive=await api.getState(id,{signal:operation.controller.signal})
          Object.assign(state,{kind:'legacy',legacy_version:archive.legacy_version,legacy:archive.legacy,legacy_archive_artifact_id:archive.legacy_archive_artifact_id,delivery_ref:archive.delivery_ref,messages:archive.messages})
        }
      }
      if (operation.controller.signal.aborted || active.current.id !== id || active.current.epoch !== epoch || state.revision < active.current.revision || state.core_event_cursor < active.current.cursor) return
      active.current.revision = state.revision
      active.current.cursor = state.core_event_cursor
      setSnapshot(state); setError('')
      if (!player) {
        const { status, onTaskUpdate: update, onTaskDone: done } = callbacks.current
        update?.(state)
        if (TERMINAL.has(state.lifecycle) && lastDone.current !== id) {
          lastDone.current = id
          source.current?.close(); clearTimeout(timer.current); clearTimeout(updateTimer.current); updateTimer.current = null
          if (!TERMINAL.has(status)) done?.()
        }
      }
    } catch (err) {
      if (!operation.controller.signal.aborted && active.current.id === id && active.current.epoch === epoch) setError(err.message)
    } finally {
      if (loading.current === operation) {
        loading.current = null
        if (again.current) { again.current = false; queueMicrotask(refresh) }
      }
    }
  }, [])

  const connect = useCallback(() => {
    source.current?.close(); clearTimeout(timer.current)
    const { id, epoch } = active.current
    if (!id || lastDone.current === id || TERMINAL.has(callbacks.current.status)) return
    if (playbackRef.current) return
    source.current = api.openEventStream(id, {
      onEvent: event => {
        if (active.current.id !== id || active.current.epoch !== epoch || event.task_id !== id) return
        if (event.seq <= active.current.cursor) return
        // Events only request a fresh authoritative view. A gap never changes
        // stages or acknowledges answers locally; the snapshot closes the gap.
        retries.current = 0; setConnection('connected')
        if (IMMEDIATE_EVENTS.has(event.kind)) {
          clearTimeout(updateTimer.current); updateTimer.current = null; refresh()
        } else if (!updateTimer.current) {
          updateTimer.current = setTimeout(() => { updateTimer.current = null; refresh() }, 150)
        }
      },
      onError: () => {
        if (active.current.id !== id || active.current.epoch !== epoch) return
        setConnection('reconnecting')
        timer.current = setTimeout(() => { refresh().finally(() => {
          if (active.current.id === id && active.current.epoch === epoch) connect()
        }) }, DELAYS[Math.min(retries.current++, DELAYS.length - 1)])
      },
      onEnd: () => { if (active.current.id === id && active.current.epoch === epoch) refresh() },
    }, active.current.cursor)
  }, [refresh])

  useEffect(() => {
    active.current = { id: task?.task_id || null, epoch: active.current.epoch + 1, revision: 0, cursor: 0 }
    const { id, epoch } = active.current
    loading.current?.controller.abort(); loading.current = null; again.current = false
    lastScope.current = null; lastDone.current = null
    retries.current = 0; submitted.current = null; setSnapshot(null); setError('');frames.current.clear();setConnection('connected')
    if (id && !playbackRef.current) refresh().finally(() => {
      if (active.current.id === id && active.current.epoch === epoch) connect()
    })
    return () => { active.current.epoch++; loading.current?.controller.abort(); source.current?.close(); clearTimeout(timer.current); clearTimeout(updateTimer.current); updateTimer.current = null }
  }, [task?.task_id, Boolean(playback), refresh, connect])
  useEffect(() => {
    if (task?.task_id && !playback && conversation && lastScope.current === false) refresh()
  }, [conversation, task?.task_id, Boolean(playback), refresh])

  useEffect(() => {
    if (!playbackRef.current || !task?.task_id) return
    // Only manual discontinuities invalidate a read. Normal forward playback
    // finishes the in-flight frame, then asks for the newest requested frame.
    active.current.epoch++; active.current.revision=0; active.current.cursor=0
    loading.current?.controller.abort(); loading.current=null; again.current=false
  }, [playback?.seekRevision, task?.task_id])
  useEffect(()=>{if(playback?.ready)refresh()},[playback?.ready,playback?.seq,playback?.seekRevision,task?.task_id,refresh])
  useEffect(()=>{
    if(snapshot?.readOnly && snapshot.task_id===task?.task_id)playbackRef.current?.shown(snapshot.task_id,snapshot.presentation.cursor)
  },[snapshot,task?.task_id])

  const submitQuery = useCallback(async (query, preferences) => {
    const signature = JSON.stringify([query, preferences])
    if (creation.current?.signature !== signature) creation.current = { query, signature, operationId: api.newOperationId() }
    const result = await api.createTask(query, creation.current.operationId, preferences)
    creation.current = null
    return result.task_id
  }, [])

  const submitAnswer = useCallback(async action => {
    const current = snapshot
    if (playbackRef.current || current?.readOnly) throw new Error('只读视图不能提交答案或操作原任务')
    if (!current || current.workspace_only || current.task_id !== active.current.id) throw new Error('对话仍在读取，请稍后再试')
    const epoch = active.current.epoch
    const signature = JSON.stringify({ taskId: current.task_id, question: current.pending?.question_id, reviewId: action.review_id, action })
    if (!submitted.current || submitted.current.signature !== signature) submitted.current = { signature, id: api.newOperationId() }
    const operation = submitted.current
    try {
      if (action.review_id) {
        const review = current.reviews.find(r => r.review_id === action.review_id)
        if (!review) throw new Error('审核问题已变化，请刷新')
        await api.reviewAnswer(current.task_id, { task_id: current.task_id, review_id: review.review_id, review_revision: review.revision,
          basis_hash: review.basis_hash, client_request_id: submitted.current.id, action: action.action,
          reason: action.reason, selected_interpretation_id: null, correction: action.correction || null,
          ...(current.review_actor?.simulation ? {simulation:true} : {}),
          ...(action.comparison_outcome ? {comparison_outcome: action.comparison_outcome} : {}),
          ...(action.correction_measurement_id ? {correction_measurement_id:action.correction_measurement_id} : {}) })
      } else if (action.control) {
        await api.controlTask(current.task_id, action.control, { operation_id: submitted.current.id, expected_revision: current.revision })
      } else {
        await api.draftAction(current.task_id, { protocol_version: 2, operation_id: submitted.current.id, expected_revision: current.revision,
          question_id: current.pending?.question_id || null, action })
      }
      if (submitted.current === operation) submitted.current = null
      if (active.current.id === current.task_id && active.current.epoch === epoch) await refresh()
    } catch (err) { if (active.current.id === current.task_id && active.current.epoch === epoch) setError(err.message); throw err }
  }, [snapshot, refresh])

  const current = snapshot && snapshot.task_id === task?.task_id && (playback ? snapshot.readOnly && snapshot.presentation?.cursor<=playback.seq : !snapshot.readOnly) ? snapshot : null
  const stages = useMemo(()=>makeInitialStages().map(base => {
    const projection = current?.presentation?.stages?.find(s => s.id === base.id) || current?.stages?.find(s => s.id === base.id)
    if (projection?.blocks) return runtimeStage(base, projection, current)
    if (base.id === 'done') return { ...base, status: current && TERMINAL.has(current.lifecycle) ? current.lifecycle === 'completed' ? 'completed' : 'failed' : 'pending' }
    if (current?.workspace_only && !TERMINAL.has(current.lifecycle) && current.presentation?.active_stage === base.id) return { ...base, status: 'running' }
    if (!projection) return { ...base, status: 'pending' }
    return runtimeStage(base, projection, current)
  }),[current])
  const messages = useMemo(()=>(current?.messages || []).map((m, i) => ({ id: m.message_id || `message-${i}`, role: m.role, content: m.text, at:m.created_at, seq:m.seq })),[current])
  const timeline = useMemo(()=>current?.workspace_only ? [] : conversationTimeline(messages,stages,current?.presentation),[messages,stages,current])

  const paused = current && ['paused', 'interrupted'].includes(current.lifecycle)
  const pending = !playback && !current?.readOnly && current && (current.pending || paused || current.workspace_only && current.lifecycle === 'waiting_review') ? {
    protocol_version: 2, type: 'runtime_question', stageId: current.query_ref ? 'quality_check' : 'understand',
    title: current.pending?.title || (paused ? '任务已暂停，进度已保存' : '质量检查'), state: {...current,reviews:[]}, error: error || current.draft?.last_error?.message,
  } : null
  return { taskId: current?.task_id || task?.task_id, snapshot: current, messages, stages, timeline, pending,
    started: !!current, conversationReady: !!current && !current.workspace_only, playback, readOnly: !!playback || !!current?.readOnly, presentation: current?.presentation, taskDone: !!current && TERMINAL.has(current.lifecycle), logs: [], sourceScores: null, executionFacts: [],
    connectionStatus, error, reconnect: () => { refresh().finally(connect) }, submitQuery, submitAnswer, refresh }
}
