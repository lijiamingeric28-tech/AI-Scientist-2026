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
import { makeInitialStages, CLARIFICATION_QUICK_BUTTONS, STAGE_DEFS } from '@/lib/stages'
import { fmtDuration } from '@/lib/format'

let seq = 0
const nextId = () => `evt-${++seq}`

/* 耗时按后端模块统计的阶段：quality_check=assessment、clean=normalization+conflict、
 * deliver=export、insight=insights。这些阶段的耗时由各模块 agent_completed.duration
 * 累加得出——quality_check 的 stage_completed.duration 横跨整条质量流水线（含清洗/
 * 交付/洞察），直接用会把后续所有阶段的耗时都算进"质量检查"。 */
const MODULE_DURATION_STAGES = ['quality_check', 'clean', 'deliver', 'insight']

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

/* 契约 D6-5：卡头摘要前端拼字段 —— stage_completed 时用累积的步骤数据 /
 * agent 列表拼出具体数字摘要（替代泛化的"已完成"）。
 * stats 为 step_progress.data 累积器（stage → step → data）。 */
function composeStageSummary(stageId, stats, stage) {
  const g = (step, k) => stats?.[stageId]?.[step]?.[k]
  if (stageId === 'retrieval') {
    const parts = []
    const dbRecords = g('database/summary', 'records')
    if (dbRecords != null) parts.push(`星表提取 ${dbRecords} 条`)
    const dl = g('paper/download', 'downloaded')
    if (dl != null) {
      const failed = g('paper/download', 'failed')
      parts.push(`下载论文 ${dl} 篇${failed ? `（${failed} 篇失败）` : ''}`)
    }
    const supp = g('supplementary/summary', 'records')
    if (supp) parts.push(`补充材料 ${supp} 条`)
    return parts.join(' · ') || null
  }
  if (stageId === 'extraction') {
    const parts = []
    const rec = g('summary', 'records') ?? g('paper', 'records')
    if (rec != null) parts.push(`提取 ${rec} 条记录`)
    const figs = g('figure', 'figures')
    if (figs != null) parts.push(`${figs} 张图证`)
    return parts.join(' · ') || null
  }
  const agents = Array.isArray(stage.agents) ? stage.agents : []
  if (stageId === 'quality_check') {
    return agents.length ? `${agents.length} 个评估 Agent 完成` : null
  }
  if (stageId === 'clean') {
    const tr = agents.reduce((n, a) => n + ((a.traces || []).length), 0)
    return agents.length ? `${agents.length} 个清洗 Agent${tr ? ` · ${tr} 条修改轨迹` : ''}` : null
  }
  if (stageId === 'deliver') {
    return agents.length ? `${agents.length} 个交付 Agent 完成` : null
  }
  return null
}

const STAGE_NAMES = Object.fromEntries(STAGE_DEFS.map((d) => [d.id, d.name]))

/* 已完成阶段的「数据」摘要（用于转场旁白「已完成 X（数据）」）。
 * retrieval/extraction 用 stats 累积的 step 数据；understand 用已确认目标。 */
function stageDataSummary(stageId, stats, target) {
  if (stageId === 'understand') return target ? `已确认目标 ${target}` : null
  if (stageId === 'retrieval') {
    const parts = []
    const db = stats?.retrieval?.['database/summary']?.records
    if (db != null) parts.push(`星表提取 ${db} 条`)
    const dl = stats?.retrieval?.['paper/download']?.downloaded
    if (dl != null) parts.push(`下载论文 ${dl} 篇`)
    const supp = stats?.retrieval?.['supplementary/summary']?.records
    if (supp) parts.push(`补充材料 ${supp} 条`)
    return parts.length ? parts.join(' · ') : null
  }
  if (stageId === 'extraction') {
    const parts = []
    const rec = stats?.extraction?.summary?.records ?? stats?.extraction?.paper?.records
    if (rec != null) parts.push(`提取 ${rec} 条记录`)
    const figs = stats?.extraction?.figure?.figures
    if (figs != null) parts.push(`${figs} 张图证`)
    return parts.length ? parts.join(' · ') : null
  }
  return null
}

/* 契约 D6-1/D6-5（M-04）：快照 state → 卡 1 完成态 output（snake→camel）。
 * 键名对齐后端：target_entity / simbad_info{main_id,otype,ra,dec} /
 * property_spec[{property_id,name_cn,unit}]（property_standardization.build_property_spec） */
function buildUnderstandOutput(state) {
  const targetEntity = state.target_entity
  if (!targetEntity) return null
  const simbad = state.simbad_info || {}
  const props = Array.isArray(state.property_spec) ? state.property_spec : []
  // SIMBAD 别名：优先 ALIASES 数组，退回 ids 竖线串（部分源缺坐标，卡 1 用别名兜底展示）
  const aliases = Array.isArray(simbad.ALIASES) && simbad.ALIASES.length
    ? simbad.ALIASES
    : (typeof simbad.ids === 'string' && simbad.ids ? simbad.ids.split('|').map((s) => s.trim()).filter(Boolean) : [])
  return {
    targetEntity,
    simbad: {
      mainId: simbad.main_id || null,
      otype: simbad.otype || null,
      ra: simbad.ra || null,
      dec: simbad.dec || null,
      aliases,
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
  // 数据洞察报告（来源 /state 快照 final_output.quality_report.output_state.insights）
  const [insights, setInsights] = useState(null)
  // 数据源质量分布（report_state.quality.quality_scoring.per_source_scores + 各源等级）——
  // 洞察卡「数据源质量分布」图的数据源（[{id, score, level}]，按分数降序）
  const [sourceScores, setSourceScores] = useState(null)

  const esRef = useRef(null)
  const lastSeqRef = useRef(0)
  const taskIdRef = useRef(null)
  const pendingRef = useRef(null)   // 当前挂起澄清（供 submitAnswer）
  const submittingRef = useRef(false)  // H-18: resume 在途标志（防双击重发）
  // D6-5：step_progress.data 累积器（stage → step → data），stage_completed 时拼卡头摘要
  const statsRef = useRef({})
  // insights flow 进行中标志：此后 stage_id='deliver' 的 agent 事件归属 insight 虚拟阶段
  const insightActiveRef = useRef(false)
  // 模块化耗时累积器（stage → 秒）：quality_check=assessment 模块、clean=normalization+conflict、
  // deliver=export、insight=insights——用各模块 agent_completed.duration 累加。
  // quality_check 的 stage_completed.duration 横跨整条质量流水线（含清洗/交付/洞察），不可用。
  const modDurRef = useRef({})
  // stages 镜像（提供阶段规范顺序；log 归属的运行判定改用下方同步 ref）
  const stagesRef = useRef([])
  useEffect(() => { stagesRef.current = stages }, [stages])
  // log 归属（同步版）：stagesRef 在快照重放期间滞后（useEffect 渲染后才更新），
  // 历史任务回看时所有日志会因此无法归属到阶段/Agent。运行中的阶段与 Agent
  // 必须在 applyEvent 内同步维护。后端无独立 tool_call 事件，但节点级 log
  //（检查器评分 / LLM 初始化 / httpx 工具调用）可按 agent_started→completed
  // 窗口精确归属到各 Agent（工作流下钻 L3 的"执行日志"即来源于此）。
  const activeStagesRef = useRef(new Set())   // 运行中的 stage_id 集合
  const activeAgentsRef = useRef(new Map())   // stageId -> Map(agent 名 -> 启动 seq)
  // P0-5：log 归属两级回退 — 无运行窗口时承接日志（阶段间隙/终态收尾/completed 后
  // 迟到的节点日志），否则此前"无运行 stage 即 return / 只认运行中 agent"导致
  // 大量日志只进全局抽屉、Agent L3"执行日志"分区恒空
  const lastStageRef = useRef(null)           // 最近活跃/完成的 stage_id
  const recentAgentsRef = useRef(new Map())   // stageId -> Map(agent 名 -> 完成 seq)
  // P0-9：log 批量节流——质量管线阶段 400+ log 事件逐个 setStages（stage.logs +
  // agent.logs 全量更新）造成渲染风暴/主线程卡顿（CLAUDE.md 已知问题 6，实证
  // 卡状态迟迟不更新）。缓冲后每 100ms 批量 flush 一次，最终一致。
  const logBufferRef = useRef([])             // [{entry, stageId, agentName}]
  const logTimerRef = useRef(null)
  // 2026-08-27：quality_check 完成兜底延迟确认定时器——快照重放/流式中
  //「已见 agents 全完成」不代表评估结束（QualityAssessmentAgent 等后续 agent
  // 可能尚未开始），立即置 completed 会造成「卡头已完成 + Agent 执行中」的不一致
  // 状态（用户实测白屏前的失真画面）。延迟 300ms 竞争窗口：期间收到新
  // agent_started 则作废；窗口到期时仍无运行中 agent 才置 completed。
  const qcDoneTimerRef = useRef(null)
  // task_completed 后等待 LLM 总结 message（role=ai）到达的标记——到达才关 SSE 流
  const awaitSummaryRef = useRef(false)
  // 转场旁白状态：卡片出现顺序 / 开场白是否已发 / 已确认目标天体
  const cardOrderRef = useRef([])             // stage_id 出现顺序（驱动「已完成 X，下面 Y」）
  const introDoneRef = useRef(false)          // 开场白只发一次（首卡理解首次 step 时）
  const understandTargetRef = useRef(null)    // understand 完成时记录 target_entity（转场数据用）

  /* 追加一条对话气泡（消息 + 时间线同步，id 用 nextId 字符串保持一致） */
  const pushMessage = useCallback((role, content) => {
    const id = nextId()
    setMessages((prev) => [...prev, { id, role, content }])
    setTimeline((prev) => [...prev, { kind: 'msg', id }])
  }, [])

  /* 卡片首次出现 → 补上一张卡的「已完成 X（数据），下面开始 Y」。
   * 不挂在 stage_completed 上：clean/deliver/quality_check 的 stage_completed
   * 迟到（整条质量流水线收尾时才发），会导致旁白乱序。改为下一张卡出现时补前一张。 */
  const noteCardAppeared = useCallback((stageId) => {
    if (!stageId || cardOrderRef.current.includes(stageId)) return
    const prev = cardOrderRef.current[cardOrderRef.current.length - 1]
    cardOrderRef.current.push(stageId)
    if (stageId === 'done') return   // 收尾卡：转场由最终 LLM 总结承担，不再发「下面开始任务完成」
    if (!prev) return
    const prevName = STAGE_NAMES[prev]
    const curName = STAGE_NAMES[stageId]
    if (!prevName || !curName) return
    const data = stageDataSummary(prev, statsRef.current, understandTargetRef.current)
    pushMessage('ai', `已完成「${data ? `${prevName}（${data}）` : prevName}」，下面开始「${curName}」。`)
  }, [pushMessage])

  /* ── 数据洞察 hydration：insights 内容不在事件流里，只能从 /state 快照
   *    final_output.quality_report.output_state.insights 读取。
   *    打开任务（快照恢复）与任务完成（final_output 落盘）后各调用一次。 ── */
  const hydrateInsights = useCallback((state) => {
    // 数据源质量分布（独立于 insights 报告；有质量报告即可提取）
    const quality = state?.final_output?.quality_report?.report_state?.quality
    const scoring = quality?.quality_scoring || {}
    const perSource = scoring.per_source_scores || {}
    const srcMeta = quality?.sources || {}
    const list = Object.entries(perSource)
      .map(([id, score]) => ({
        id,
        score: Number(score) || 0,
        level: srcMeta?.[id]?.quality_scoring?.quality_level || 'poor',
      }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
    if (list.length) setSourceScores(list)
    const ins = state?.final_output?.quality_report?.output_state?.insights
    if (!ins || typeof ins !== 'object') return false
    setInsights(ins)
    const fi = Array.isArray(ins.field_insights) ? ins.field_insights.length : 0
    const rel = Array.isArray(ins.cross_field_relationships) ? ins.cross_field_relationships.length : 0
    const rec = ins.usage_recommendations && Array.isArray(ins.usage_recommendations.suitable_use_cases)
      ? ins.usage_recommendations.suitable_use_cases.length : 0
    const parts = []
    if (fi) parts.push(`${fi} 条字段洞察`)
    if (rel) parts.push(`${rel} 条跨字段关系`)
    if (rec) parts.push(`${rec} 条使用建议`)
    const summary = parts.length ? parts.join(' · ') : '已生成数据洞察报告'
    setStages((prev) => prev.map((s) => (s.id === 'insight'
      ? { ...s, status: 'completed', output: ins, summary }
      : s)))
    setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === 'insight')
      ? prev : [...prev, { kind: 'stage', id: 'insight' }]))
    return true
  }, [])

  /* ── P0-9：log 批量 flush（一次 setLogs + 一次 setStages，替代逐事件渲染） ── */
  const flushLogs = useCallback(() => {
    logTimerRef.current = null
    const batch = logBufferRef.current
    logBufferRef.current = []
    if (!batch.length) return
    // 全局日志（M-03 500 条环形截断）
    setLogs((prev) => [...prev, ...batch.map((b) => b.entry)].slice(-500))
    // 阶段/Agent 归属：按 stageId 分组（agent 再按名分组），一次 setStages
    const byStage = new Map()   // stageId -> { items: [], agentMap: Map(agent -> items) }
    for (const b of batch) {
      if (!b.stageId) continue
      let g = byStage.get(b.stageId)
      if (!g) { g = { items: [], agentMap: new Map() }; byStage.set(b.stageId, g) }
      g.items.push(b.entry)
      if (b.agentName) {
        if (!g.agentMap.has(b.agentName)) g.agentMap.set(b.agentName, [])
        g.agentMap.get(b.agentName).push(b.entry)
      }
    }
    if (byStage.size) {
      setStages((prev) => prev.map((s) => {
        const g = byStage.get(s.id)
        if (!g) return s
        const next = { ...s, logs: [...(s.logs || []), ...g.items].slice(-200) }
        if (g.agentMap.size) {
          next.agents = (s.agents || []).map((a) => {
            const items = g.agentMap.get(a.id || a.agent)
            return items ? { ...a, logs: [...(a.logs || []), ...items].slice(-300) } : a
          })
        }
        return next
      }))
    }
  }, [])

  const scheduleLogFlush = useCallback(() => {
    if (logTimerRef.current) return
    logTimerRef.current = setTimeout(() => flushLogs(), 100)
  }, [flushLogs])

  // 终态/任务切换：立即 flush 剩余缓冲（防尾部日志丢失）
  const flushLogsNow = useCallback(() => {
    if (logTimerRef.current) { clearTimeout(logTimerRef.current); logTimerRef.current = null }
    flushLogs()
  }, [flushLogs])

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
      const id = nextId()
      setMessages((prev) => [...prev, { id, role: ev.role, content: ev.content }])
      setTimeline((prev) => {
        // LLM 总结（task_completed 后异步补发）排在 done entry 之前，使渲染顺序为
        // …洞察卡 → 总结 → 结果表格（done 卡不渲染本体，表格在 done entry 处展示）
        const doneIdx = prev.findIndex((t) => t.kind === 'stage' && t.id === 'done')
        if (doneIdx >= 0) return [...prev.slice(0, doneIdx), { kind: 'msg', id }, ...prev.slice(doneIdx)]
        return [...prev, { kind: 'msg', id }]
      })
      // 总结 message（task 已完成、role=ai）到达 → 关闭 SSE（此前 task_completed 立即关流丢总结）
      if (awaitSummaryRef.current && ev.role === 'ai') {
        awaitSummaryRef.current = false
        closeStream()
      }
    } else if (type === 'stage_started') {
      activeStagesRef.current.add(ev.stage_id)   // 同步维护：log 归属用
      lastStageRef.current = ev.stage_id         // P0-5：最近活跃阶段
      // 开场白：首卡「任务理解」出现时发一句，紧跟用户提问（澄清卡之前）
      if (ev.stage_id === 'understand' && !introDoneRef.current) {
        introDoneRef.current = true
        pushMessage('ai', '好的，我先开始「任务理解」——确认目标天体与要提取的标准性质。')
      }
      setStages((prev) => prev.map((s) => (s.id === ev.stage_id ? { ...s, status: 'running' } : s)))
      noteCardAppeared(ev.stage_id)
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'stage_completed') {
      activeStagesRef.current.delete(ev.stage_id)  // P0-5：完成即出运行窗口，记最近
      lastStageRef.current = ev.stage_id
      setStages((prev) => prev.map((s) => {
        if (s.id !== ev.stage_id) return s
        // D6-5：卡头摘要——已有（如卡 1 快照接线）不覆盖，否则用累积数据拼数字摘要
        const summary = s.summary || composeStageSummary(ev.stage_id, statsRef.current, s) || s.summary
        // 2026-08-14：卡 1 完成态实时 output——后端 stage_completed(understand)
        // 携带 target_entity/simbad_info/property_spec，运行中即渲染标准性质
        //（此前只在 openTask 快照恢复时建 output，需刷新才显示）
        const out = (ev.stage_id === 'understand' && ev.target_entity && !s.output)
          ? buildUnderstandOutput(ev)
          : s.output
        // 模块级阶段的耗时由 agent 事件累加（见 MODULE_DURATION_STAGES）——
        // quality_check 的 stage_completed.duration 横跨整条质量流水线，不可用；
        // duration<=0（如 done）视为未计时
        const useEventDuration = ev.duration > 0 && !MODULE_DURATION_STAGES.includes(ev.stage_id)
        return {
          ...s, status: ev.status || 'completed',
          duration: useEventDuration ? fmtDuration(ev.duration) : s.duration,
          summary: out && out !== s.output ? `已确认目标天体 ${out.targetEntity} 与 ${out.properties.length} 项标准性质` : summary,
          output: out,
        }
      }))
      // done 卡只有 completed 事件（main_graph quality_finalize=end 模式）→ 补弹卡
      // 记录确认目标（understand 转场旁白的「已确认目标 X」数据来源）
      if (ev.stage_id === 'understand' && ev.target_entity) {
        understandTargetRef.current = ev.target_entity
      }
      noteCardAppeared(ev.stage_id)
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === ev.stage_id) ? prev : [...prev, { kind: 'stage', id: ev.stage_id }]))
    } else if (type === 'step_progress') {
      const loc = locateStep(ev.stage_id, ev.step)
      if (!loc) return
      // D6-5：累积步骤数据（供 stage_completed 拼卡头摘要；合并保留同 step 多次上报的键）
      if (ev.data && typeof ev.data === 'object') {
        const byStage = statsRef.current[ev.stage_id] || (statsRef.current[ev.stage_id] = {})
        byStage[ev.step] = { ...(byStage[ev.step] || {}), ...ev.data }
        // 2026-08-27: 卡3 步骤①"论文提取"分段——pdf_converter('convert') 与
        // vlm_extractor('extract') 共用 step='paper'，按 phase 落到不同 sub 阶段
        if (ev.data.phase) {
          const byStage2 = statsRef.current[ev.stage_id] || (statsRef.current[ev.stage_id] = {})
          byStage2[`${ev.step}/${ev.data.phase}`] = { ...(byStage2[`${ev.step}/${ev.data.phase}`] || {}), ...ev.data }
        }
      }
      const patch = { status: ev.status }
      if (ev.progress) patch.progress = { ...ev.progress }
      if (ev.data) {
        patch.detail = formatStepDetail(ev.stage_id, ev.step, ev.data)   // 数字对象 → 中文文本
        if (Array.isArray(ev.data.failures)) patch.failures = ev.data.failures  // bbox 失败原因
        if (typeof ev.data.substatus === 'string') patch.substatus = ev.data.substatus  // L-10：表级验证进度
        if (ev.data.phase) patch.phase = ev.data.phase   // 2026-08-27：卡3 ① 论文提取分段（convert/extract）
      }
      // 2026-08-27：phase 运行中事件（data 只含 phase）不得覆盖 detail 摘要——
      // 此前 formatStepDetail 对 {phase} 求值 g('papers')=undefined → 分段期间
      // 主步骤 detail 被污染为 "undefined 篇论文提取完成…"（用户实测）
      if (ev.data && ev.data.phase && !('papers' in ev.data) && !('records' in ev.data)) {
        delete patch.detail
      }
      // 2026-08-27: 卡3 步骤①"论文提取"分两段（拆分 PDF / VLM 提取）——
      // 两节点共用 step='paper'，phase 区分；旧任务无 phase（单段，兼容）
      if (loc.kind === 'substeps' && loc.id === 'paper') {
        setStages((prev) => prev.map((s) => s.id !== ev.stage_id ? s : {
          ...s,
          substeps: (s.substeps || []).map((st) => {
            if (st.id !== loc.id) return st
            const phases = { ...(st.phases || {}) }
            if (ev.data && ev.data.phase) phases[ev.data.phase] = { ...(phases[ev.data.phase] || {}), ...patch }
            return { ...st, ...patch, phases }
          }),
        }))
        return
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
    } else if (type === 'flow_started' || type === 'flow_completed') {
      // quality_pipeline 子流程（normalization/conflict/export/insights，带轮次）。
      // insights flow 归属前端虚拟阶段 insight；其余按事件 stage_id（clean/deliver）。
      const isInsights = ev.flow_id === 'insights'
      const targetStage = isInsights ? 'insight' : ev.stage_id
      const status = type === 'flow_started' ? 'running' : 'completed'
      if (isInsights) insightActiveRef.current = type === 'flow_started'
      // clean/deliver/insight 无 stage_started 事件 → flow 启动即视为阶段运行中（log 归属用）
      if (type === 'flow_started') {
        activeStagesRef.current.add(targetStage)
        lastStageRef.current = targetStage   // P0-5：最近活跃阶段（无 stage_started 卡）
      }
      setStages((prev) => prev.map((s) => {
        if (s.id !== targetStage) return s
        const round = ev.round ?? 1
        const key = `${ev.flow_id}-${round}`
        const flows = [...(s.flows || [])]
        const idx = flows.findIndex((f) => f.key === key)
        if (idx >= 0) {
          flows[idx] = { ...flows[idx], status }
        } else {
          flows.push({ key, flowId: ev.flow_id, round, status })
        }
        // clean/deliver/insight 无 stage_started → 首个 flow 事件点亮阶段
        return { ...s, flows, status: (status === 'running' && s.status === 'waiting') ? 'running' : s.status }
      }))
      // insight 阶段完成：insights flow 收尾即视为洞察阶段完成（耗时后端未上报）
      if (isInsights && status === 'completed') {
        activeStagesRef.current.delete('insight')
        setStages((prev) => prev.map((s) => (s.id === 'insight' && s.status !== 'completed'
          ? { ...s, status: 'completed' } : s)))
      }
      noteCardAppeared(targetStage)
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === targetStage)
        ? prev : [...prev, { kind: 'stage', id: targetStage }]))
    } else if (type === 'agent_started' || type === 'agent_completed') {
      const status = type === 'agent_started' ? 'running' : 'completed'
      // insights flow 执行期间，stage_id='deliver' 的 agent 归属 insight 虚拟阶段
      const targetStage = (ev.stage_id === 'deliver' && insightActiveRef.current) ? 'insight' : ev.stage_id
      // 同步维护运行窗口：log 事件按 agent_started→completed 窗口归属到 Agent
      //（后端无 tool_call 事件，节点级日志是工具/检查器明细的唯一来源）
      if (type === 'agent_started') {
        activeStagesRef.current.add(targetStage)
        lastStageRef.current = targetStage   // P0-5：agent 启动即视为阶段活跃
        if (!activeAgentsRef.current.has(targetStage)) activeAgentsRef.current.set(targetStage, new Map())
        activeAgentsRef.current.get(targetStage).set(ev.agent, ev.seq || Date.now())
        // P0-5：重新运行 → 清该 agent 的 recent 记录（以最新运行窗口为准）
        recentAgentsRef.current.get(targetStage)?.delete(ev.agent)
      } else {
        activeAgentsRef.current.get(targetStage)?.delete(ev.agent)
        // P0-5：completed → 写入 recent（该 agent 完成后迟到的日志仍可归属）
        if (!recentAgentsRef.current.has(targetStage)) recentAgentsRef.current.set(targetStage, new Map())
        recentAgentsRef.current.get(targetStage).set(ev.agent, ev.seq || Date.now())
      }
      // 模块级耗时累积：各模块 agent_completed.duration 之和 = 该阶段耗时
      //（quality_check=assessment / clean=normalization+conflict / deliver=export / insight=insights）
      if (type === 'agent_completed' && MODULE_DURATION_STAGES.includes(targetStage) && ev.duration > 0) {
        modDurRef.current[targetStage] = (modDurRef.current[targetStage] || 0) + ev.duration
      }
      // 后端 agent 事件是流式的（无预置列表）——动态追加。
      // 2026-08-27：agent 唯一键 = agent 名 + flow_id + round（多轮循环同 agent 名
      // 重复出现——规划/规范化/冲突第 2 轮各自成行；此前按名合并导致轮次信息丢失）
      const agentKey = `${ev.agent}|${ev.flow_id ?? ''}|${ev.round ?? ''}`
      // quality_check 兜底取消竞争：新的 agent_started 到达 → 作废待确认的完成
      if (targetStage === 'quality_check' && type === 'agent_started' && qcDoneTimerRef.current) {
        clearTimeout(qcDoneTimerRef.current)
        qcDoneTimerRef.current = null
      }
      // 2026-08-27：quality_check 完成延迟确认（**同步层**启动 timer——
      // 严禁在 setStages updater 内 setTimeout/嵌套 setStages：updater 必须纯函数，
      // StrictMode 双调会破坏渲染一致性 → 白屏。timer 到点用 functional update
      // 检查「无 running agent」才置 completed，竞争窗口内新 agent_started 会
      // clearTimeout 作废。）
      if (targetStage === 'quality_check' && type === 'agent_completed'
          && qcDoneTimerRef.current == null) {
        qcDoneTimerRef.current = setTimeout(() => {
          qcDoneTimerRef.current = null
          setStages((prev) => prev.map((st) => {
            if (st.id !== 'quality_check' || st.status === 'completed') return st
            const ags = st.agents || []
            if (!ags.length || ags.some((a) => a.status === 'running')) return st
            return { ...st, status: 'completed' }
          }))
        }, 300)
      }
      setStages((prev) => prev.map((s) => {
        if (s.id !== targetStage) return s
        const has = (s.agents || []).some((a) => a.agentKey === agentKey)
        const agents = has
          ? (s.agents || []).map((a) => a.agentKey === agentKey
              // M-14：traces 累积而非替换（规范化多轮/回跳场景第 1 轮轨迹不丢）；
              // 按 timestamp+field+after 三元组去重（与 quality_state._merge_dict 策略一致）
              // P0-4：reason 透传（后端 agent_completed 新增字段，L3 下钻结论展示）
              ? { ...a, status, duration: type === 'agent_completed' ? (ev.duration ? fmtDuration(ev.duration) : a.duration) : a.duration, traces: mergeTraces(a.traces, ev.traces), reason: ev.reason != null ? ev.reason : a.reason }
              : a)
          : [...(s.agents || []), {
              id: agentKey, agent: ev.agent, agentKey, status,
              flow_id: ev.flow_id, round: ev.round,   // 清洗卡嵌套块归组依据（旧事件 undefined）
              duration: type === 'agent_completed' ? fmtDuration(ev.duration) : null,
              traces: ev.traces || null,
              reason: type === 'agent_completed' ? (ev.reason || null) : null,
            }]
        // insight 阶段：agent 状态同步到预置 substeps（卡片时间线展示）
        const substeps = Array.isArray(s.substeps) && s.substeps.some((st) => st.id === ev.agent)
          ? s.substeps.map((st) => (st.id === ev.agent ? { ...st, status } : st))
          : s.substeps
        const duration = modDurRef.current[targetStage] != null ? `${modDurRef.current[targetStage].toFixed(1)}s` : s.duration
        // 2026-08-27：HR→A 重评估——卡已 completed 但启动新评估 agent → 回退 running
        //（HumanReview 决策后 route_after_human_review 直连 Assessment，重评估中）
        let st = s
        if (targetStage === 'quality_check' && type === 'agent_started' && s.status === 'completed') {
          st = { ...s, status: 'running' }
        }
        return { ...st, agents, substeps, duration, status: st.status === 'waiting' ? 'running' : st.status }
      }))
      // clean/deliver/insight 卡没有 stage_started 事件 → 首个 agent 事件时弹卡
      noteCardAppeared(targetStage)
      setTimeline((prev) => (prev.some((t) => t.kind === 'stage' && t.id === targetStage) ? prev : [...prev, { kind: 'stage', id: targetStage }]))
    } else if (type === 'clarification') {
      const cl = {
        type: ev.cl_type, title: ev.title, fields: ev.fields,
        question: ev.question, error: ev.error,
        // 2026-09-02：后端 options 权威（本次合法裁决项）→ 从静态映射取标签做选项卡；
        // 无 options 时全量静态映射（final_confirm 等）；
        // human_review_batch 短路 —— 面板自己绘制选项卡，防"选项 4/选项 5"兜底芯片
        quickButtons: ev.cl_type === 'human_review_batch' ? [] : (() => {
          const all = CLARIFICATION_QUICK_BUTTONS[ev.cl_type] || []
          if (Array.isArray(ev.options) && ev.options.length) {
            const ok = new Set(ev.options)
            const pick = all.filter((b) => ok.has(b.value))
            return pick.length ? pick : ev.options.map((o) => ({ label: `选项 ${o}`, value: o }))
          }
          return all
        })(),
        // 2026-09-02: 批量协议透传（HumanReviewPanel 消费）
        conflicts: ev.conflicts,
        summary_markdown: ev.summary_markdown,
        count: ev.count,
      }
      // CR-02：快照重放中的 clarification 不置 pending（已答/已过事件不得重弹；
      // 挂起状态由 snap.pending_clarification 精确恢复，live 流正常置 pending）
      if (!replay) {
        // M-05：pendingRef 与 setPending 同构（都含 stageId）——submitAnswer
        // 历史回填依赖 cl.stageId 定位卡片，缺它则回填永不命中、answer 恒 ''
        pendingRef.current = { ...cl, stageId: ev.stage_id }
        setPending({ ...cl, stageId: ev.stage_id })
      }
      // 澄清历史追加到所属卡片（P1-8：连带存结构化 fields——展开时优先
      // 渲染键值对而非后端 CLI 原文）
      setStages((prev) => prev.map((s) => s.id !== ev.stage_id ? s : {
        ...s,
        clarifications: [...(s.clarifications || []), { type: ev.cl_type, question: ev.question, fields: ev.fields || null, answer: '' }],
      }))
    } else if (type === 'clarification_answered') {
      // P1-8：回答回填——resume 后后端落库的事件（重放时补上澄清记录的回答；
      // 实时场景 submitAnswer 已回填，这里只处理 answer 仍为空的情况）
      setStages((prev) => prev.map((s) => {
        const cls = s.clarifications || []
        if (!cls.length) return s
        const last = cls[cls.length - 1]
        if (last.answer) return s
        return { ...s, clarifications: [...cls.slice(0, -1), { ...last, answer: ev.answer }] }
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
      // P0-9：log 批量节流——只做归属计算并入缓冲，100ms 批量 flush 一次
      //（原实现每事件两次 setStages，400+ log 造成渲染风暴卡死主线程）
      const time = new Date().toTimeString().slice(0, 8)
      const entry = { id: nextId(), node: ev.node, level: ev.level, message: ev.message, time }
      // 阶段归属：同步维护的运行集合（快照重放安全），多个阶段并行时取规范
      // 顺序中最靠后的运行阶段（stagesRef 提供顺序）——工作流下钻"阶段日志"。
      // P0-5 回退：无运行阶段时挂到最近活跃阶段（阶段间隙/终态收尾日志不再丢弃）
      let stageId = null
      for (const s of stagesRef.current || []) {
        if (activeStagesRef.current.has(s.id)) stageId = s.id
      }
      if (!stageId) stageId = lastStageRef.current
      let agentName = null
      if (stageId) {
        // Agent 归属：该阶段最近启动且仍在运行的 Agent；P0-5 回退最近完成的 Agent
        const agentWindow = activeAgentsRef.current.get(stageId)
        if (agentWindow && agentWindow.size) {
          let best = -1
          for (const [name, startSeq] of agentWindow) {
            if (startSeq > best) { best = startSeq; agentName = name }
          }
        }
        if (!agentName) {
          const recent = recentAgentsRef.current.get(stageId)
          if (recent && recent.size) {
            let best = -1
            for (const [name, doneSeq] of recent) {
              if (doneSeq > best) { best = doneSeq; agentName = name }
            }
          }
        }
      }
      logBufferRef.current.push({ entry, stageId, agentName })
      scheduleLogFlush()
    } else if (type === 'task_completed' || type === 'task_cancelled') {
      flushLogsNow()   // P0-9：立即 flush 剩余 log 缓冲（防尾部丢失）
      // P0-5：终态只清运行窗口，保留 lastStageRef/recentAgentsRef——终态收尾
      // 到达的节点日志仍可归属到最后阶段/Agent（此前全部只进全局抽屉）
      activeStagesRef.current.clear()
      activeAgentsRef.current.clear()
      // H-02①③: task_cancelled（澄清超时/用户取消）清理挂起澄清 + 卡片置灰
      if (type === 'task_cancelled') {
        closeStream()
        clearPending()
      } else {
        // 不立即关流：LLM 总结（role=ai message）在 task_completed 之后异步补发，
        // 立即关会丢总结（此前需刷新才见）。等总结 message 到达后关，20s 兜底超时。
        awaitSummaryRef.current = true
        setTimeout(() => {
          if (awaitSummaryRef.current) { awaitSummaryRef.current = false; closeStream() }
        }, 20000)
      }
      setTaskDone(true)
      onTaskDone?.()
      // task_completed：final_output 此刻才落盘，insights 不在事件流里 → 重拉 /state hydrate 洞察报告
      if (type === 'task_completed' && taskId != null) {
        // P0-2：落库窗口内快照可能还没有 final_output（5MB state 写入需数百 ms）→
        // hydrate 失败时 800ms 后重试一次（taskIdRef 校验防任务切换串台）
        const tryHydrate = (attempt) => {
          api.getState(taskId).then((snap) => {
            if (taskIdRef.current !== taskId) return
            const state = (snap && snap.state) || {}
            const insOk = hydrateInsights(state)
            // 质量卡摘要（quality_report 落库窗口内可能缺失 → 与 insights 同重试；
            // 评分只在最终 state，事件流不携带）
            const quality = state?.quality_report?.report_state?.quality
            const sc = quality?.quality_scoring || {}
            if (sc.overall_score != null) {
              const qc = (stagesRef.current || []).find((s) => s.id === 'quality_check')
              const agentN = Array.isArray(qc?.agents) ? qc.agents.length : 0
              const parts = []
              if (agentN) parts.push(`${agentN} 个评估 Agent`)
              parts.push(`综合 ${Math.round(sc.overall_score * 100)} 分${sc.quality_level ? `（${sc.quality_level}）` : ''}`)
              setStages((prev) => prev.map((s) => s.id !== 'quality_check' ? s : { ...s, summary: parts.join(' · ') }))
            }
            if (!insOk && attempt < 1) {
              setTimeout(() => tryHydrate(attempt + 1), 800)
            }
          }).catch(() => { /* hydrate 失败忽略（洞察缺省走空态） */ })
        }
        tryHydrate(0)
      }
    } else if (type === 'task_failed') {
      closeStream()
      flushLogsNow()   // P0-9：立即 flush 剩余 log 缓冲
      // P0-5：同 task_completed——保留 last/recent 承接收尾日志
      activeStagesRef.current.clear()
      activeAgentsRef.current.clear()
      clearPending()
      setMessages((prev) => [...prev, { id: nextId(), role: 'ai', content: `⚠️ 任务失败：${ev.error || ''}` }])
      setTaskDone(true)
      onTaskDone?.()
    } else if (type === 'task_title_ready') {
      onTaskTitle?.(ev)   // L-01：透传完整事件（含 task_id），App 按归属更新列表
    }
  }, [onTaskDone, onTaskTitle, hydrateInsights, noteCardAppeared, pushMessage])

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
    setInsights(null)
    setSourceScores(null)
    awaitSummaryRef.current = false
    pendingRef.current = null
    insightActiveRef.current = false
    statsRef.current = {}   // D6-5：跨任务不复用步骤累积数据
    modDurRef.current = {}  // 模块级耗时跨任务不复用
    activeStagesRef.current.clear()   // log 归属窗口跨任务不复用
    activeAgentsRef.current.clear()
    lastStageRef.current = null       // P0-5：跨任务不复用
    recentAgentsRef.current.clear()   // P0-5：跨任务不复用
    logBufferRef.current = []         // P0-9：log 缓冲跨任务不复用
    cardOrderRef.current = []            // 转场旁白顺序跨任务不复用
    introDoneRef.current = false         // 开场白跨任务重置
    understandTargetRef.current = null   // 确认目标跨任务重置
    if (logTimerRef.current) { clearTimeout(logTimerRef.current); logTimerRef.current = null }
    if (qcDoneTimerRef.current) { clearTimeout(qcDoneTimerRef.current); qcDoneTimerRef.current = null }  // 2026-08-27
    esRef.current?.close()
    esRef.current = null
    lastSeqRef.current = 0   // CR-02：每次打开任务重置，快照重放确定续播锚点

    // 快照恢复（历史任务回看 / 断线恢复，契约 D6-1/D5-4）
    try {
      const snap = await api.getState(taskId)
      // H-17：快照乱序返回 → 丢弃过期响应（任务已切换）
      if (taskIdRef.current !== taskId) return
      // 后端不回显用户提问（message 事件仅最终总结）→ 从快照 task.query 重建 user 气泡，
      // 否则对话区只有阶段卡片 + 最后一条 AI 总结，用户提问永不显示
      const q = snap.task && snap.task.query
      if (q) {
        const id = nextId()
        setMessages([{ id, role: 'user', content: q }])
        setTimeline([{ kind: 'msg', id }])
      }
      const events = snap.events || []
      events.forEach((e) => applyEvent(e, taskId, true))   // replay=true：重放 clarification 不置 pending
      if (snap.pending_clarification) {
        const pc = snap.pending_clarification
        const cl = {
          ...pc, stageId: pc.stage_id,
          // 2026-09-02：options 权威 → 选项卡（标签取静态映射）；无则静态映射；batch 短路
          quickButtons: pc.cl_type === 'human_review_batch' ? [] : (() => {
            const all = CLARIFICATION_QUICK_BUTTONS[pc.cl_type] || []
            if (Array.isArray(pc.options) && pc.options.length) {
              const ok = new Set(pc.options)
              const pick = all.filter((b) => ok.has(b.value))
              return pick.length ? pick : pc.options.map((o) => ({ label: `选项 ${o}`, value: o }))
            }
            return all
          })(),
          conflicts: pc.conflicts,
          summary_markdown: pc.summary_markdown,
          count: pc.count,
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
      // D6-5：done 卡摘要 —— 快照 final_output 计数（历史任务回看时直接显示最终产出）
      const fo = (snap.state || {}).final_output
      if (fo) {
        const parts = []
        if (Array.isArray(fo.records)) parts.push(`${fo.records.length} 条记录`)
        if (Array.isArray(fo.sources)) parts.push(`${fo.sources.length} 个来源`)
        if (Array.isArray(fo.figure_evidence)) parts.push(`${fo.figure_evidence.length} 张图证`)
        if (parts.length) {
          const doneSummary = `共 ${parts.join(' · ')}`
          setStages((prev) => prev.map((s) => (s.id === 'done' ? { ...s, summary: doneSummary } : s)))
        }
      }
      // 数据洞察 hydration（历史任务回看直接呈现洞察报告）；
      // 终态任务无 insights（旧任务可能未跑洞察流程）→ insight 阶段优雅置 skipped
      const insightOk = hydrateInsights(snap.state || {})
      if (!insightOk) {
        const st = snap.task && snap.task.status
        if (st && st !== 'queued' && st !== 'running') {
          setStages((prev) => prev.map((s) => (s.id === 'insight'
            ? { ...s, status: 'skipped', summary: '该任务未生成数据洞察' }
            : s)))
        }
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
    insightActiveRef.current = false
    statsRef.current = {}
    modDurRef.current = {}
    activeStagesRef.current.clear()
    activeAgentsRef.current.clear()
    lastStageRef.current = null       // P0-5：跨任务不复用
    recentAgentsRef.current.clear()   // P0-5：跨任务不复用
    logBufferRef.current = []         // P0-9：log 缓冲跨任务不复用
    cardOrderRef.current = []            // 转场旁白顺序跨任务不复用
    introDoneRef.current = false         // 开场白跨任务重置
    understandTargetRef.current = null   // 确认目标跨任务重置
    if (logTimerRef.current) { clearTimeout(logTimerRef.current); logTimerRef.current = null }
    if (qcDoneTimerRef.current) { clearTimeout(qcDoneTimerRef.current); qcDoneTimerRef.current = null }  // 2026-08-27
    esRef.current?.close()
    esRef.current = null
    setStarted(false)
    setTaskDone(false)
    setMessages([])
    setStages(makeInitialStages())
    setTimeline([])
    setPending(null)
    setLogs([])
    setInsights(null)
    setSourceScores(null)
    awaitSummaryRef.current = false
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

  /* ── 提交新查询：建任务 → 打开流 ── */
  const submitQuery = useCallback(async (query) => {
    const task = await api.createTask(query)
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
    messages, stages, timeline, pending, started, taskDone, logs, insights, sourceScores,
    submitQuery, submitAnswer,
  }
}