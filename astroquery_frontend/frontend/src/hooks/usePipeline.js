/* usePipeline —— 真实 API 事件流消费
 *
 * 事件（docs/API_CONTRACT.md 12 种）→ 前端 stage/timeline/pending 状态：
 *   stage_started / stage_completed / step_progress / agent_started|completed /
 *   clarification / message / error / log / task_* / task_title_ready
 *
 * 与 mock 的差异只在数据源：mock 用定时器，这里用 SSE + REST。
 * ChatView / StageCard 等组件零改动（保持"渲染模型与数据源解耦"）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '@/services/api'
import { makeInitialStages, CLARIFICATION_QUICK_BUTTONS } from '@/mock/pipeline'

let seq = 0
const nextId = () => `evt-${++seq}`

/* step_progress.path: "database/match" 等 → stage 内定位 */
function locateStep(stage_id, path) {
  if (stage_id === 'understand') return { kind: 'substeps', id: path }        // confirm/simbad/research
  if (stage_id === 'extraction') return { kind: 'substeps', id: path }        // paper/bbox/figure/summary
  if (stage_id === 'retrieval') {
    const [group, step] = path.split('/')                                     // database/match 等
    return { kind: 'groups', group, step }
  }
  return null
}

/* M-14：traces 累积 + 三元组去重（(timestamp, field, after) 唯一，与
 * quality_state._merge_dict 策略一致）——规范化多轮/回跳场景不丢第 1 轮轨迹 */
function mergeTraces(oldTraces, newTraces) {
  if (!oldTraces || !oldTraces.length) return newTraces || null
  if (!newTraces || !newTraces.length) return oldTraces
  const seen = new Set(oldTraces.map((t) => `${t.timestamp}|${t.field}|${t.after}`))
  const merged = [...oldTraces]
  for (const t of newTraces) {
    const k = `${t.timestamp}|${t.field}|${t.after}`
    if (!seen.has(k)) { seen.add(k); merged.push(t) }
  }
  return merged
}

/* 契约 D6-6：后端 data 只带原始数字，前端拼中文文本（防对象渲染崩溃） */
function formatStepDetail(stageId, step, data) {
  if (!data || typeof data !== 'object') return ''
  const g = (k) => data[k]
  if (stageId === 'retrieval') {
    if (step === 'database/match') return `匹配到 ${g('matched_catalogs')} 类星表，共 ${g('total_queries')} 次查询`
    if (step === 'database/summary') return `成功 ${g('success')} 个表 · 失败 ${g('failed')} 个 · 提取 ${g('records')} 条数据`
    if (step === 'paper/build') return `构建 ${g('total')} 个查询串：${(g('groups') || []).join(' / ')}`
    if (step === 'paper/search') {
      const per = (g('per_query') || []).map((n, i) => `查询串 ${i + 1}「${(g('groups') || [])[i] || ''}」${n} 篇`)
      return `${per.join(' · ')} → 合并去重 ${g('deduped')} 篇`
    }
    if (step === 'paper/download') return `已下载 ${g('downloaded')} 篇 · 失败 ${g('failed')} 篇`
    if (step === 'supplementary/summary') return `找到 ${g('tables')} 张表 · 提取 ${g('records')} 条数据`
    if (step === 'supplementary/find') return g('substatus') || '正在定位补充材料表'   // L-10
    return ''
  }
  if (stageId === 'extraction') {
    if (step === 'paper') return `${g('papers')} 篇论文提取完成，共 ${g('records')} 条数据`
    if (step === 'bbox') return `${g('success')} 条验证成功 · ${g('failed')} 条验证失败`
    if (step === 'figure') return `提取 ${g('figures')} 张图片`
    if (step === 'summary') return `论文：${g('sources')} 个 source · ${g('records')} 条 record`
    return ''
  }
  return ''
}

/* 契约 D6-1/D6-5（M-04）：快照 state → 卡 1 完成态 output（snake→camel）。
 * 键名对齐后端：target_entity / simbad_info{main_id,otype,ra,dec} /
 * property_spec[{property_id,name_cn,unit}]（property_standardization.build_property_spec） */
function buildUnderstandOutput(state) {
  const targetEntity = state.target_entity
  if (!targetEntity) return null
  const simbad = state.simbad_info || {}
  const props = Array.isArray(state.property_spec) ? state.property_spec : []
  return {
    targetEntity,
    simbad: {
      mainId: simbad.main_id || null,
      otype: simbad.otype || null,
      ra: simbad.ra || null,
      dec: simbad.dec || null,
    },
    properties: props.map((p) => ({ propertyId: p.property_id, name: p.name_cn, unit: p.unit })),
  }
}

export function usePipeline(task, { onTaskDone, onTaskTitle } = {}) {
  const [messages, setMessages] = useState([])
  const [stages, setStages] = useState(makeInitialStages)
  const [timeline, setTimeline] = useState([])
  const [pending, setPending] = useState(null)
  const [started, setStarted] = useState(false)
  const [taskDone, setTaskDone] = useState(false)
  const [logs, setLogs] = useState([])

  const esRef = useRef(null)
  const lastSeqRef = useRef(0)
  const taskIdRef = useRef(null)
  const pendingRef = useRef(null)   // 当前挂起澄清（供 submitAnswer）
  const submittingRef = useRef(false)  // H-18: resume 在途标志（防双击重发）

  /* ── 事件 → 状态 reducer ── */
  const applyEvent = useCallback((ev, taskId, replay = false) => {
    const { type } = ev
    // CR-02：seq 幂等去重（快照重放与 SSE 续播可能交叠同一事件；断线重建同理）
    if (ev.seq && ev.seq <= lastSeqRef.current) return
    // H-17：事件归属校验（快照乱序返回 / 旧流残留事件不得串台到当前任务）
    if (taskId != null && taskIdRef.current !== taskId) return
    if (ev.seq) lastSeqRef.current = ev.seq
    // 终态/致命事件 → 关闭 SSE（流不会再有新事件，避免长连接悬挂 —— M-06/DP-10）
    const closeStream = () => { if (esRef.current) { esRef.current.close(); esRef.current = null } }
    // H-02①③: 终态/致命事件统一清理挂起澄清——pending 置空（ChatView clarifying
    // 随之为 false，输入栏与提交恢复可用）+ 挂起澄清所属卡片置 cancelled 灰态
    const clearPending = () => {
      const stageId = pendingRef.current?.stageId
      pendingRef.current = null
      setPending(null)
      if (stageId) {
        setStages((prev) => prev.map((s) => (s.id === stageId && s.status !== 'completed' ? { ...s, status: 'cancelled' } : s)))
      }
    }

    if (type === 'message') {
      setMessages((prev) => [...prev, { id: nextId(), role: ev.role, content: ev.content }])
      setTimeline((prev) => [...prev, { kind: 'msg', id: prev.length }])
    } else if (type === 'stage_started') {
      setStages((prev) => prev.map((s) => (s.id === ev.stage_id ? { ...s, status: 'running' } : s)))
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'stage_completed') {
      setStages((prev) => prev.map((s) => (s.id === ev.stage_id ? { ...s, status: ev.status || 'completed', duration: ev.duration ? `${ev.duration}s` : s.duration } : s)))
      // done 卡只有 completed 事件（main_graph quality_finalize=end 模式）→ 补弹卡
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'step_progress') {
      const loc = locateStep(ev.stage_id, ev.step)
      if (!loc) return
      const patch = { status: ev.status }
      if (ev.progress) patch.progress = { ...ev.progress }
      if (ev.data) {
        patch.detail = formatStepDetail(ev.stage_id, ev.step, ev.data)   // 数字对象 → 中文文本
        if (Array.isArray(ev.data.failures)) patch.failures = ev.data.failures  // bbox 失败原因
        if (typeof ev.data.substatus === 'string') patch.substatus = ev.data.substatus  // L-10：表级验证进度
      }
      if (loc.kind === 'groups') {
        setStages((prev) => prev.map((s) => s.id !== ev.stage_id ? s : {
          ...s,
          groups: (s.groups || []).map((g) => g.id !== loc.group ? g : {
            ...g,
            steps: g.steps.map((st) => st.id === loc.step ? { ...st, ...patch } : st),
          }),
        }))
      } else {
        setStages((prev) => prev.map((s) => s.id !== ev.stage_id ? s : {
          ...s,
          substeps: (s.substeps || []).map((st) => st.id === loc.id ? { ...st, ...patch } : st),
        }))
      }
    } else if (type === 'agent_started' || type === 'agent_completed') {
      const status = type === 'agent_started' ? 'running' : 'completed'
      // 后端 agent 事件是流式的（无预置列表）——动态追加
      setStages((prev) => prev.map((s) => {
        if (s.id !== ev.stage_id) return s
        const has = (s.agents || []).some((a) => a.agent === ev.agent)
        const agents = has
          ? (s.agents || []).map((a) => a.agent === ev.agent
              // M-14：traces 累积而非替换（规范化多轮/回跳场景第 1 轮轨迹不丢）；
              // 按 timestamp+field+after 三元组去重（与 quality_state._merge_dict 策略一致）
              ? { ...a, status, duration: type === 'agent_completed' ? (ev.duration ? `${ev.duration}s` : a.duration) : a.duration, traces: mergeTraces(a.traces, ev.traces) }
              : a)
          : [...(s.agents || []), { id: ev.agent, agent: ev.agent, status, duration: type === 'agent_completed' ? `${ev.duration}s` : null, traces: ev.traces || null }]
        return { ...s, agents, status: s.status === 'waiting' ? 'running' : s.status }
      }))
      // clean/deliver 卡没有 stage_started 事件 → 首个 agent 事件时弹卡
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'clarification') {
      const cl = {
        type: ev.cl_type, title: ev.title, fields: ev.fields,
        question: ev.question, error: ev.error,
        quickButtons: CLARIFICATION_QUICK_BUTTONS[ev.cl_type] || [],  // 契约 D5-1/2：final_confirm 按钮
      }
      // CR-02：快照重放中的 clarification 不置 pending（已答/已过事件不得重弹；
      // 挂起状态由 snap.pending_clarification 精确恢复，live 流正常置 pending）
      if (!replay) {
        // M-05：pendingRef 与 setPending 同构（都含 stageId）——submitAnswer
        // 历史回填依赖 cl.stageId 定位卡片，缺它则回填永不命中、answer 恒 ''
        pendingRef.current = { ...cl, stageId: ev.stage_id }
        setPending({ ...cl, stageId: ev.stage_id })
      }
      // 澄清历史追加到所属卡片
      setStages((prev) => prev.map((s) => s.id !== ev.stage_id ? s : {
        ...s,
        clarifications: [...(s.clarifications || []), { type: ev.cl_type, question: ev.question, answer: '' }],
      }))
    } else if (type === 'error') {
      if (ev.level === 'fatal') {
        closeStream()
        // H-02①: fatal → 清理挂起澄清（输入栏恢复）；②: ev.message 显式追加为
        // AI 消息（D10-3 澄清超时提示）；③: 挂起澄清所属卡片置灰（clearPending）
        clearPending()
        setMessages((prev) => [...prev, { id: nextId(), role: 'ai', content: `⚠️ ${ev.message || '任务失败'}` }])
        setTaskDone(true)
        onTaskDone?.()
      } else if (ev.stage_id) {
        // M-23: warn 级阶段错误 → 累积到所属卡片 errors（StageCard 渲染红态+错误行）
        setStages((prev) => prev.map((s) => s.id !== ev.stage_id ? s : {
          ...s,
          errors: [...(s.errors || []), { node: ev.node, message: ev.message }],
        }))
      }
    } else if (type === 'log') {
      // M-03：容量上限 500 环形截断（单任务 400+ log 事件，防无界累积 + 全量重渲染）
      setLogs((prev) => [...prev, { id: nextId(), node: ev.node, level: ev.level, message: ev.message }].slice(-500))
    } else if (type === 'task_completed' || type === 'task_cancelled') {
      closeStream()
      // H-02①③: task_cancelled（澄清超时/用户取消）清理挂起澄清 + 卡片置灰
      if (type === 'task_cancelled') clearPending()
      setTaskDone(true)
      onTaskDone?.()
    } else if (type === 'task_failed') {
      closeStream()
      clearPending()
      setMessages((prev) => [...prev, { id: nextId(), role: 'ai', content: `⚠️ 任务失败：${ev.error || ''}` }])
      setTaskDone(true)
      onTaskDone?.()
    } else if (type === 'task_title_ready') {
      onTaskTitle?.(ev)   // L-01：透传完整事件（含 task_id），App 按归属更新列表
    }
  }, [onTaskDone, onTaskTitle])

  /* ── 打开任务：先拉快照恢复历史，再 SSE 续播 ── */
  const openTask = useCallback(async (taskId) => {
    if (!taskId) return
    taskIdRef.current = taskId
    setStarted(true)
    setTaskDone(false)
    setMessages([])
    setStages(makeInitialStages())
    setTimeline([])
    setPending(null)
    setLogs([])
    pendingRef.current = null
    esRef.current?.close()
    esRef.current = null
    lastSeqRef.current = 0   // CR-02：每次打开任务重置，快照重放确定续播锚点

    // 快照恢复（历史任务回看 / 断线恢复，契约 D6-1/D5-4）
    try {
      const snap = await api.getState(taskId)
      // H-17：快照乱序返回 → 丢弃过期响应（任务已切换）
      if (taskIdRef.current !== taskId) return
      const events = snap.events || []
      events.forEach((e) => applyEvent(e, taskId, true))   // replay=true：重放 clarification 不置 pending
      if (snap.pending_clarification) {
        const pc = snap.pending_clarification
        const cl = {
          ...pc, stageId: pc.stage_id,
          quickButtons: CLARIFICATION_QUICK_BUTTONS[pc.cl_type] || [],
        }
        setPending(cl)
        pendingRef.current = cl
      }
      // 契约 D6-1/D6-5（M-04）：快照 state 的卡 1 output 接线 + 卡头摘要
      const out = buildUnderstandOutput(snap.state || {})
      if (out) {
        setStages((prev) => prev.map((s) => s.id !== 'understand' ? s : {
          ...s,
          output: out,
          summary: `已确认目标天体 ${out.targetEntity} 与 ${out.properties.length} 项标准性质`,
        }))
      }
      // M-06：任务已终态 → 不再开 SSE（流不会有新事件，避免长连接悬挂）
      const status = snap.task && snap.task.status
      if (status && status !== 'queued' && status !== 'running') return
    } catch { /* 快照失败忽略（新任务可能无事件） */ }

    // SSE 实时续播：携带快照重放后的 lastSeq 锚点（CR-02 / 契约 D1-4 断线续播）
    if (taskIdRef.current !== taskId) return   // H-17：await 间隙任务已切换，不再开流
    let es = null
    let retries = 0
    const handlers = {
      onEvent: (ev) => { retries = 0; applyEvent(ev, taskId) },
      onError: () => {
        // EventSource 自动重连复用原 URL（after_seq=0 会全量重放）→ 关闭并按 lastSeq 重建（CR-02）
        if (taskIdRef.current !== taskId || !es || esRef.current !== es) return
        es.close()
        retries += 1
        if (retries > 8) { esRef.current = null; return }   // 连续失败放弃，避免重连死循环
        es = api.openEventStream(taskId, handlers, lastSeqRef.current)
        if (taskIdRef.current !== taskId) { es.close(); return }
        esRef.current = es
      },
    }
    es = api.openEventStream(taskId, handlers, lastSeqRef.current)
    // H-17：await 间隙任务已切换 → 新流立即关闭（不泄漏连接/订阅）
    if (taskIdRef.current !== taskId) { es.close(); return }
    esRef.current = es
  }, [applyEvent])

  /* 任务切换（App/侧边栏点击） */
  const reset = useCallback(() => {
    // M-02：新建任务（task 变 null）→ 清空主区全部状态并关闭 SSE
    taskIdRef.current = null
    lastSeqRef.current = 0
    pendingRef.current = null
    esRef.current?.close()
    esRef.current = null
    setStarted(false)
    setTaskDone(false)
    setMessages([])
    setStages(makeInitialStages())
    setTimeline([])
    setPending(null)
    setLogs([])
  }, [])

  useEffect(() => {
    if (!task) {
      reset()
      return
    }
    // CR-03：后端/契约键名为 task_id（D8-4），前端全链路统一
    if (task.task_id && taskIdRef.current !== task.task_id) {
      openTask(task.task_id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task, reset])

  /* ── 提交新查询：上传 → 建任务 → 打开流 ── */
  const submitQuery = useCallback(async (query, fileList) => {
    let pdfIds = []
    if (fileList && fileList.length) {
      const up = await api.uploadFiles(fileList)
      if (up.rejected?.length) throw new Error(up.rejected[0].reason)
      pdfIds = up.pdf_ids
    }
    const task = await api.createTask(query, pdfIds)
    await openTask(task.task_id)
    return task.task_id
  }, [openTask])

  /* ── 澄清回答（契约 D5：POST resume） ── */
  const submitAnswer = useCallback(async (answer) => {
    const tid = taskIdRef.current
    const cl = pendingRef.current
    if (!tid || !cl) return
    // M-09 前端校验（契约 D5-1/2）：final_confirm 只允许 y/m/n
    if (cl.type === 'final_confirm' && !['y', 'yes', '确认', '是', 'm', 'modify', '修改', 'n', '取消'].includes(String(answer).trim().toLowerCase())) {
      setPending((p) => ({ ...p, error: '输入无效，请选择 [确认 (y)] [修改 (m)] 或 [取消 (n)]' }))
      return
    }
    // H-18: pending 在 await 期间保留（成功后才清）→ 双击/连点必须防重入
    if (submittingRef.current) return
    submittingRef.current = true
    try {
      await api.resumeTask(tid, answer)
      // H-18: await 成功后再清 pending + 回填澄清历史（失败不记答案、卡保留可重试）
      pendingRef.current = null
      setPending(null)
      setStages((prev) => prev.map((s) => s.id === cl.stageId ? {
        ...s,
        clarifications: (s.clarifications || []).map((c, i) =>
          i === s.clarifications.length - 1 ? { ...c, answer } : c
        ),
      } : s))
    } catch (err) {
      // H-18: resume 失败（网络/409）→ 恢复挂起澄清卡 + 卡内错误提示，允许重答
      pendingRef.current = cl
      setPending({ ...cl, error: `提交失败：${err.message || '网络错误'}，请重试` })
      throw err
    } finally {
      submittingRef.current = false
    }
  }, [])

  /* 清理 */
  useEffect(() => () => esRef.current?.close(), [])

  return {
    messages, stages, timeline, pending, started, taskDone, logs,
    submitQuery, submitAnswer,
  }
}