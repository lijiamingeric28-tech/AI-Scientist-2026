import { useCallback, useEffect, useRef, useState } from 'react'
import { getAgentMessages, newOperationId, sendAgentChat, stopAgentReply } from '@/services/api'

const blank = []
const streamError = '连接已中断，正在尝试恢复这轮回答。'

export function useFollowup(taskId, deliveryId, deliveryRevision, enabled) {
  const identity = enabled ? [taskId, deliveryId, deliveryRevision].join(':') : ''
  const [history, setHistory] = useState({ key: '', rows: blank })
  const scope = { delivery_id: deliveryId, delivery_revision: deliveryRevision,
    ...(history.key === identity && history.scope?.snapshot_ref ? { snapshot_ref: history.scope.snapshot_ref } : {}) }
  const [problem, setProblem] = useState(null)
  const [session, setSession] = useState(null)
  const [branch, setBranch] = useState({})
  const currentIdentity = useRef(identity)
  const sessionRef = useRef(null)
  const lastSend = useRef(null)
  const version = useRef(0)
  currentIdentity.current = identity

  const rows = history.key === identity ? history.rows : blank
  const pending = session?.key === identity ? session : null
  const busy = Boolean(pending || rows.some(row => row.status === 'generating'))
  const error = problem?.key === identity ? problem.text : ''
  const selectionKey = identity ? 'astroquery.followup.versions.' + identity : ''
  const selectedAnswers = branch.key === selectionKey ? branch.values : {}

  const merge = useCallback((key, ...messages) => {
    // A delayed stop receipt from another scope must not invalidate this scope's pending read.
    if (currentIdentity.current !== key) return
    version.current++
    setHistory(history => {
      if (currentIdentity.current !== key) return history
      const next = new Map((history.key === key ? history.rows : []).map(row => [row.id, row]))
      for (const message of messages) if (message?.id) next.set(message.id, message)
      return { key, scope: messages.find(message => message?.scope)?.scope || history.scope, rows: [...next.values()] }
    })
  }, [])

  const load = useCallback(async (signal) => {
    if (!identity) return
    const before = version.current
    const result = await getAgentMessages(taskId, { delivery_id: deliveryId, delivery_revision: deliveryRevision }, { signal })
    if (signal?.aborted || currentIdentity.current !== identity || before !== version.current) return
    setHistory({ key: identity, scope: result.scope, rows: result.messages || [] })
    if (lastSend.current && result.messages?.some(row => row.request_id === lastSend.current.request_id)) {
      lastSend.current = null
    }
    if (!lastSend.current) setProblem(previous => previous?.key === identity ? null : previous)
  }, [identity, taskId, deliveryId, deliveryRevision])

  useEffect(() => {
    if (!identity) return
    const controller = new AbortController()
    load(controller.signal).catch(() => {
      if (!controller.signal.aborted) setProblem({ key: identity, text: '追问历史暂时无法读取。' })
    })
    try {
      setBranch({ key: selectionKey, values: JSON.parse(localStorage.getItem(selectionKey)) || {} })
    } catch { setBranch({ key: selectionKey, values: {} }) }
    return () => {
      controller.abort()
      const running = sessionRef.current
      if (running?.key === identity) {
        running.controller.abort()
        sessionRef.current = null
        setSession(previous => previous?.key === identity ? null : previous)
      }
      if (lastSend.current?.key === identity) lastSend.current = null
    }
  }, [identity, load, selectionKey])

  useEffect(() => {
    if (pending || (!busy && !error) || !identity) return
    const controller = new AbortController()
    const interval = window.setInterval(() => load(controller.signal).catch(() => {}), 950)
    return () => { controller.abort(); clearInterval(interval) }
  }, [pending, busy, error, identity, load])

  function choose(questionId, answerId) {
    const values = { ...selectedAnswers, [questionId]: answerId }
    setBranch({ key: selectionKey, values })
    try { localStorage.setItem(selectionKey, JSON.stringify(values)) } catch { /* session still works */ }
  }

  async function stop() {
    const running = sessionRef.current
    if (running?.key === identity && !running.message?.id) {
      running.stopRequested = true
      setSession({ ...running })
      return
    }
    const message = running?.key === identity ? running.message : rows.find(row => row.status === 'generating')
    if (!message) return
    try {
      const stopped = await stopAgentReply(taskId, message.id)
      merge(identity, stopped)
    } catch (err) {
      if (currentIdentity.current === identity) setProblem({ key: identity, text: err.message })
    }
  }

  async function ask({ text, recordIds = [], markers = [], selections = [], materialAnalysisRef, retryOf, repairBlock, requestId, resend = false }) {
    if (!identity || busy || sessionRef.current?.key === identity) return false
    const resume = resend && lastSend.current?.key === identity ? lastSend.current : null
    const body = resume?.body || {
      ...scope, content: text || '', request_id: requestId || newOperationId(),
      record_ids: recordIds.slice(0, 40), markers: markers.slice(0, 16), selections: selections.slice(0, 6),
      selected_answers: Object.values(selectedAnswers).slice(-24),
      retry_of: retryOf || null, repair_block: repairBlock || null,
      ...(materialAnalysisRef ? {material_analysis_ref:materialAnalysisRef} : {}),
    }
    const controller = new AbortController()
    const running = { key: identity, controller, message: null, action: '', question: null }
    sessionRef.current = running
    lastSend.current = { key: identity, body, request_id: body.request_id }
    setSession({ ...running })
    setProblem(null)
    let acknowledged = false
    let done = false
    try {
      await sendAgentChat(taskId, body, (name, data) => {
        if (currentIdentity.current !== identity || controller.signal.aborted) return
        if (name === 'agent_started') {
          acknowledged = true
          running.message = data.message
          running.question = data.question
          merge(identity, data.question, running.message)
          if (retryOf) choose(data.question.id, data.message.id)
          if (running.stopRequested) stopAgentReply(taskId, running.message.id).then(message => merge(identity, message), () => {})
          setSession({ ...running })
        } else if (name === 'agent_block' && running.message) {
          const previous = running.message
          const blocks = new Map((previous.answer?.blocks || []).map(block => [block.id, block]))
          blocks.set(data.block.id, data.block)
          const citations = new Map((previous.citations || []).map(ref => [ref.citation_id, ref]))
          data.citations.forEach(ref => citations.set(ref.citation_id, ref))
          running.message = { ...previous, answer: { version: 1, blocks: [...blocks.values()] }, citations: [...citations.values()] }
          merge(identity, running.message)
        } else if (name === 'agent_tool_call' || name === 'agent_status') {
          running.action = data.label || data.message || ''
          setSession({ ...running })
        } else if (name === 'agent_done') {
          done = true
          acknowledged = true
          lastSend.current = null
          setProblem(null)
          merge(identity, data)
        }
      }, controller.signal)
      if (!done && !controller.signal.aborted) setProblem({ key: identity, text: streamError })
    } catch (err) {
      if (!controller.signal.aborted && currentIdentity.current === identity) {
        if (err.status && err.status < 500 && err.code !== 'AGENT_BUSY') lastSend.current = null
        setProblem({ key: identity, text: err.status ? err.message : streamError })
      }
    } finally {
      if (sessionRef.current === running) {
        sessionRef.current = null
        setSession(null)
        if (!done) load(controller.signal).catch(() => {})
      }
    }
    return acknowledged || Boolean(lastSend.current)
  }

  return {
    rows, busy, error, pending, selectedAnswers, choose, ask, stop,
    retryConnection: () => lastSend.current?.key === identity ? ask({ resend: true }) :
      load().then(() => setProblem(null), () => {}),
  }
}
