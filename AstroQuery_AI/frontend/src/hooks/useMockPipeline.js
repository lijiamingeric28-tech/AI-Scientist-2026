/* useMockPipeline —— 模拟真实 SSE 事件流
 *
 * 完整模拟 7 阶段流水线，生成与真实后端一致的事件序列。
 * 用于开发/演示，无需启动后端服务。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { makeInitialStages, CLARIFICATION_QUICK_BUTTONS } from '@/mock/pipeline'

let seq = 0
const nextId = () => `evt-${++seq}`

/* 模拟事件延迟（ms） */
const delay = (ms) => new Promise((r) => setTimeout(r, ms))

/* 模拟 M31 天体查询的完整事件序列 */
async function* mockEventStream(query) {
  let s = 0
  const ev = (type, data) => ({ seq: ++s, type, ...data })

  // ===== 阶段 1: 任务理解 =====
  yield ev('message', { role: 'ai', content: `好的，我来帮您查询「${query}」的相关数据。让我先确认一下查询目标。` })
  yield ev('stage_started', { stage_id: 'understand' })

  // 子步骤 1: 查询确认
  yield ev('step_progress', { stage_id: 'understand', step: 'confirm', status: 'running' })
  await delay(800)
  yield ev('step_progress', { stage_id: 'understand', step: 'confirm', status: 'completed', data: { query } })

  // 子步骤 2: SIMBAD 查询
  yield ev('step_progress', { stage_id: 'understand', step: 'simbad', status: 'running' })
  await delay(1200)
  yield ev('step_progress', { stage_id: 'understand', step: 'simbad', status: 'completed', data: { main_id: 'M 31', otype: 'G', ra: '00:42:44.33', dec: '+41:16:07.5' } })

  // 子步骤 3: 研究方向确定
  yield ev('step_progress', { stage_id: 'understand', step: 'research', status: 'running' })
  await delay(1000)
  yield ev('step_progress', { stage_id: 'understand', step: 'research', status: 'completed', data: { properties: ['distance', 'metallicity', 'mass'] } })

  yield ev('stage_completed', { stage_id: 'understand', status: 'completed', duration: 3.0 })
  yield ev('message', { role: 'ai', content: '已确认目标天体 **M31**（仙女座星系），将检索距离、金属丰度、总质量三项标准性质。' })

  // ===== 阶段 2: 数据检索 =====
  yield ev('stage_started', { stage_id: 'retrieval' })

  // 数据库检索
  yield ev('step_progress', { stage_id: 'retrieval', step: 'database/match', status: 'running' })
  await delay(600)
  yield ev('step_progress', { stage_id: 'retrieval', step: 'database/match', status: 'completed', data: { matched_catalogs: 5, total_queries: 12 } })

  yield ev('step_progress', { stage_id: 'retrieval', step: 'database/extract', status: 'running', progress: { completed: 0, total: 12 } })
  for (let i = 1; i <= 12; i++) {
    await delay(200)
    yield ev('step_progress', { stage_id: 'retrieval', step: 'database/extract', status: 'running', progress: { completed: i, total: 12, current_catalog: ['Gaia DR3', '2MASS', 'AllWISE', 'SDSS DR9', 'Pan-STARRS1'][i % 5] } })
  }
  yield ev('step_progress', { stage_id: 'retrieval', step: 'database/extract', status: 'completed', data: { success: 11, failed: 1, records: 86 } })

  yield ev('step_progress', { stage_id: 'retrieval', step: 'database/summary', status: 'running' })
  await delay(400)
  yield ev('step_progress', { stage_id: 'retrieval', step: 'database/summary', status: 'completed', data: { success: 11, failed: 1, records: 86 } })

  // 论文检索
  yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/build', status: 'running' })
  await delay(500)
  yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/build', status: 'completed', data: { total: 2, groups: ['距离族', '金属丰度族'] } })

  yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/search', status: 'running' })
  await delay(1500)
  yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/search', status: 'completed', data: { per_query: [12, 8], groups: ['距离族', '金属丰度族'], deduped: 15 } })

  yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/download', status: 'running', progress: { completed: 0, total: 15 } })
  for (let i = 1; i <= 15; i++) {
    await delay(300)
    yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/download', status: 'running', progress: { completed: i, total: 15 } })
  }
  yield ev('step_progress', { stage_id: 'retrieval', step: 'paper/download', status: 'completed', data: { downloaded: 12, failed: 3 } })

  // 补充材料
  yield ev('step_progress', { stage_id: 'retrieval', step: 'supplementary/find', status: 'running' })
  await delay(800)
  yield ev('step_progress', { stage_id: 'retrieval', step: 'supplementary/find', status: 'completed', data: { tables: 4 } })

  yield ev('step_progress', { stage_id: 'retrieval', step: 'supplementary/summary', status: 'running' })
  await delay(400)
  yield ev('step_progress', { stage_id: 'retrieval', step: 'supplementary/summary', status: 'completed', data: { tables: 4, records: 28 } })

  yield ev('stage_completed', { stage_id: 'retrieval', status: 'completed', duration: 8.2 })
  yield ev('message', { role: 'ai', content: '检索完成：从 5 类星表获取 86 条数据，下载 12 篇论文，找到 4 张补充材料表。' })

  // ===== 阶段 3: 数据提取 =====
  yield ev('stage_started', { stage_id: 'extraction' })

  yield ev('step_progress', { stage_id: 'extraction', step: 'paper', status: 'running', progress: { completed: 0, total: 12 } })
  for (let i = 1; i <= 12; i++) {
    await delay(400)
    yield ev('step_progress', { stage_id: 'extraction', step: 'paper', status: 'running', progress: { completed: i, total: 12 } })
  }
  yield ev('step_progress', { stage_id: 'extraction', step: 'paper', status: 'completed', data: { papers: 12, records: 24 } })

  yield ev('step_progress', { stage_id: 'extraction', step: 'bbox', status: 'running', progress: { completed: 0, total: 24 } })
  for (let i = 1; i <= 24; i++) {
    await delay(150)
    yield ev('step_progress', { stage_id: 'extraction', step: 'bbox', status: 'running', progress: { completed: i, total: 24 } })
  }
  yield ev('step_progress', { stage_id: 'extraction', step: 'bbox', status: 'completed', data: { success: 22, failed: 2 } })

  yield ev('step_progress', { stage_id: 'extraction', step: 'figure', status: 'running' })
  await delay(1000)
  yield ev('step_progress', { stage_id: 'extraction', step: 'figure', status: 'completed', data: { figures: 5 } })

  yield ev('step_progress', { stage_id: 'extraction', step: 'summary', status: 'running' })
  await delay(500)
  yield ev('step_progress', { stage_id: 'extraction', step: 'summary', status: 'completed', data: { sources: 12, records: 24 } })

  yield ev('stage_completed', { stage_id: 'extraction', status: 'completed', duration: 12.4 })
  yield ev('message', { role: 'ai', content: '提取完成：12 篇论文共提取 24 条记录，5 张图证。开始质量检查。' })

  // ===== 阶段 4: 质量检查 =====
  yield ev('stage_started', { stage_id: 'quality_check' })

  const agents4 = ['ProfilingAgent', 'QualityAssessmentAgent', 'QualityScoringAgent', 'DecisionReasoningAgent']
  for (const agent of agents4) {
    yield ev('agent_started', { stage_id: 'quality_check', agent })
    await delay(800 + Math.random() * 600)
    yield ev('agent_completed', { stage_id: 'quality_check', agent, duration: (0.8 + Math.random() * 0.6).toFixed(1) })
  }

  yield ev('stage_completed', { stage_id: 'quality_check', status: 'completed', duration: 4.1 })
  yield ev('message', { role: 'ai', content: '质量检查完成：数据完整性 92%，一致性 88%，发现 3 处冲突待消解。进入数据清洗阶段。' })

  // ===== 阶段 5: 数据清洗 =====
  yield ev('stage_started', { stage_id: 'clean' })

  const agents5a = ['SourceRouterAgent', 'ToolPlanningAgent', 'ToolExecutorAgent', 'ValidationAgent', 'ReportAgent']
  for (const agent of agents5a) {
    yield ev('agent_started', { stage_id: 'clean', agent })
    await delay(600 + Math.random() * 500)
    yield ev('agent_completed', { stage_id: 'clean', agent, duration: (0.6 + Math.random() * 0.5).toFixed(1) })
  }

  // 冲突消解轮次
  yield ev('flow_started', { stage_id: 'clean', round: 1 })
  const agents5b = ['ConflictIdentificationAgent', 'ConflictClassificationAgent', 'ResolutionReasoningAgent']
  for (const agent of agents5b) {
    yield ev('agent_started', { stage_id: 'clean', agent })
    await delay(700 + Math.random() * 400)
    yield ev('agent_completed', { stage_id: 'clean', agent, duration: (0.7 + Math.random() * 0.4).toFixed(1) })
  }
  yield ev('flow_completed', { stage_id: 'clean', round: 1 })

  yield ev('stage_completed', { stage_id: 'clean', status: 'completed', duration: 6.8 })
  yield ev('message', { role: 'ai', content: '数据清洗完成：规范化处理 24 条记录，消解 3 处冲突。准备交付。' })

  // ===== 阶段 6: 数据交付 =====
  yield ev('stage_started', { stage_id: 'deliver' })

  const agents6 = ['DataOrganizationAgent', 'SchemaFormattingAgent', 'MetadataGenerationAgent', 'TraceabilityConstructionAgent', 'OutputValidationAgent']
  for (const agent of agents6) {
    yield ev('agent_started', { stage_id: 'deliver', agent })
    await delay(500 + Math.random() * 400)
    yield ev('agent_completed', { stage_id: 'deliver', agent, duration: (0.5 + Math.random() * 0.4).toFixed(1) })
  }

  yield ev('stage_completed', { stage_id: 'deliver', status: 'completed', duration: 3.2 })

  // ===== 阶段 7: 任务完成 =====
  yield ev('stage_started', { stage_id: 'done' })
  await delay(1000)
  yield ev('message', { role: 'ai', content: `## 任务完成\n\n已成功查询 **M31**（仙女座星系）的天文数据：\n\n- **距离**：785 ± 25 kpc\n- **金属丰度**：[Fe/H] = -0.42 ± 0.08\n- **总质量**：(1.5 ± 0.3) × 10¹² M☉\n\n数据来源：12 篇论文 + 5 类星表，共 86 条原始记录，经质量检查与冲突消解后交付 24 条高质量记录。\n\n详细结果请查看右侧面板。` })
  yield ev('stage_completed', { stage_id: 'done', status: 'completed', duration: 1.0 })
  yield ev('task_completed', {})
}

export function useMockPipeline(task, { onTaskDone, onTaskTitle } = {}) {
  const [messages, setMessages] = useState([])
  const [stages, setStages] = useState(makeInitialStages)
  const [timeline, setTimeline] = useState([])
  const [pending, setPending] = useState(null)
  const [started, setStarted] = useState(false)
  const [taskDone, setTaskDone] = useState(false)
  const [logs, setLogs] = useState([])

  const runningRef = useRef(false)
  const taskIdRef = useRef(null)
  const onTaskDoneRef = useRef(onTaskDone)
  useEffect(() => { onTaskDoneRef.current = onTaskDone }, [onTaskDone])

  const applyEvent = useCallback((ev) => {
    const { type } = ev

    if (type === 'message') {
      const id = nextId()
      setMessages((prev) => [...prev, { id, role: ev.role, content: ev.content }])
      setTimeline((prev) => [...prev, { kind: 'msg', id }])
    } else if (type === 'stage_started') {
      setStages((prev) => prev.map((s) => (s.id === ev.stage_id ? { ...s, status: 'running' } : s)))
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'stage_completed') {
      setStages((prev) => prev.map((s) => (s.id === ev.stage_id ? { ...s, status: ev.status || 'completed', duration: ev.duration ? `${ev.duration}s` : s.duration } : s)))
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'step_progress') {
      const stageId = ev.stage_id
      const step = ev.step
      const patch = { status: ev.status }
      if (ev.progress) patch.progress = { ...ev.progress }
      if (ev.data) {
        // 简化的 detail 生成
        if (stageId === 'understand') {
          if (step === 'confirm') patch.detail = `查询确认：${ev.data.query || ''}`
          if (step === 'simbad') patch.detail = `SIMBAD: ${ev.data.main_id || ''} · ${ev.data.otype || ''}`
          if (step === 'research') patch.detail = `确定 ${ev.data.properties?.length || 0} 项标准性质`
        } else if (stageId === 'retrieval') {
          const [group, stepName] = step.split('/')
          if (group === 'database' && stepName === 'match') patch.detail = `匹配到 ${ev.data.matched_catalogs} 类星表，共 ${ev.data.total_queries} 次查询`
          if (group === 'database' && stepName === 'extract') patch.detail = `提取进度 ${ev.progress?.completed || 0}/${ev.progress?.total || 0}`
          if (group === 'database' && stepName === 'summary') patch.detail = `成功 ${ev.data.success} 个表 · 失败 ${ev.data.failed} 个 · 提取 ${ev.data.records} 条数据`
          if (group === 'paper' && stepName === 'build') patch.detail = `构建 ${ev.data.total} 个查询串：${(ev.data.groups || []).join(' / ')}`
          if (group === 'paper' && stepName === 'search') patch.detail = `去重后 ${ev.data.deduped} 篇`
          if (group === 'paper' && stepName === 'download') patch.detail = `已下载 ${ev.data.downloaded} 篇 · 失败 ${ev.data.failed} 篇`
          if (group === 'supplementary' && stepName === 'find') patch.detail = `找到 ${ev.data.tables} 张表`
          if (group === 'supplementary' && stepName === 'summary') patch.detail = `提取 ${ev.data.records} 条数据`
        } else if (stageId === 'extraction') {
          if (step === 'paper') patch.detail = `${ev.data.papers} 篇论文提取完成，共 ${ev.data.records} 条数据`
          if (step === 'bbox') patch.detail = `${ev.data.success} 条验证成功 · ${ev.data.failed} 条验证失败`
          if (step === 'figure') patch.detail = `提取 ${ev.data.figures} 张图片`
          if (step === 'summary') patch.detail = `论文：${ev.data.sources} 个 source · ${ev.data.records} 条 record`
        }
      }

      if (stageId === 'retrieval') {
        const [group, stepName] = step.split('/')
        setStages((prev) => prev.map((s) => s.id !== stageId ? s : {
          ...s,
          groups: (s.groups || []).map((g) => g.id !== group ? g : {
            ...g,
            steps: g.steps.map((st) => st.id === stepName ? { ...st, ...patch } : st),
          }),
        }))
      } else {
        setStages((prev) => prev.map((s) => s.id !== stageId ? s : {
          ...s,
          substeps: (s.substeps || []).map((st) => st.id === step ? { ...st, ...patch } : st),
        }))
      }
    } else if (type === 'agent_started' || type === 'agent_completed') {
      const status = type === 'agent_started' ? 'running' : 'completed'
      setStages((prev) => prev.map((s) => {
        if (s.id !== ev.stage_id) return s
        const has = (s.agents || []).some((a) => a.agent === ev.agent)
        const agents = has
          ? (s.agents || []).map((a) => a.agent === ev.agent ? { ...a, status, duration: type === 'agent_completed' ? `${ev.duration}s` : a.duration } : a)
          : [...(s.agents || []), { id: ev.agent, agent: ev.agent, status, duration: type === 'agent_completed' ? `${ev.duration}s` : null }]
        return { ...s, agents, status: s.status === 'waiting' ? 'running' : s.status }
      }))
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'task_completed' || type === 'task_cancelled') {
      setTaskDone(true)
      onTaskDoneRef.current?.()
    } else if (type === 'log') {
      setLogs((prev) => [...prev, { id: nextId(), node: ev.node, level: ev.level, message: ev.message }].slice(-500))
    }
  }, [])  // 空依赖：onTaskDone 通过 ref 访问

  const runSimulation = useCallback(async (query) => {
    if (runningRef.current) return
    runningRef.current = true

    setStarted(true)
    setTaskDone(false)
    setMessages([])
    setStages(makeInitialStages())
    setTimeline([])
    setPending(null)
    setLogs([])

    try {
      for await (const ev of mockEventStream(query)) {
        if (!runningRef.current) break
        applyEvent(ev)
      }
    } catch (err) {
      console.error('Mock pipeline error:', err)
    } finally {
      runningRef.current = false
    }
  }, [applyEvent])

  const submitQuery = useCallback(async (query) => {
    const mockTaskId = `mock-${Date.now()}`
    taskIdRef.current = mockTaskId
    await runSimulation(query)
    return mockTaskId
  }, [runSimulation])

  const submitAnswer = useCallback(async (answer) => {
    setPending(null)
  }, [])

  /* 任务切换：task 变 null 时清空状态 */
  useEffect(() => {
    if (!task) {
      runningRef.current = false
      taskIdRef.current = null
      setStarted(false)
      setTaskDone(false)
      setMessages([])
      setStages(makeInitialStages())
      setTimeline([])
      setPending(null)
      setLogs([])
    }
  }, [task])

  useEffect(() => () => { runningRef.current = false }, [])

  return {
    messages, stages, timeline, pending, started, taskDone, logs,
    submitQuery, submitAnswer,
  }
}
