import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import * as api from '@/services/api'
import StageCard from './StageCard'
import ClarificationCard from './ClarificationCard'
import ResultTabs from '@/components/results/ResultTabs'
import LogDrawer from '@/components/log/LogDrawer'
import StageDetailPanel from '@/components/workflow/StageDetailPanel'
import { useToast } from '@/components/ui/toast'
import SampleGallery from './SampleGallery'
// 演示样例画廊清单（scripts/rebuild_sample_pack.py 生成：质量分/计数与结果端点同源）
import SAMPLE_MANIFEST from '@/data/samples.json'

/* 对话视图（块 3 定案）：
 * - 消息流 / 阶段卡片 / HITL 澄清 / 输入栏（块 6）
 * 数据源：App 层上提的 usePipeline（SSE 事件流 + REST，契约 API_CONTRACT.md），
 * 与工作流视图共享同一份实时状态。
 */

/* AI 消息（文档流）：Sparkle 图标 + markdown —— 用于对话消息与卡片下方总结 */
function AiMessage({ content }) {
  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 6,
          background: 'var(--surface-secondary)',
          border: '1px solid var(--surface-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          color: 'var(--content-fg-secondary)',
        }}
      >
        <Icon.Sparkle />
      </div>
      <div style={{ paddingTop: 3, flex: 1, minWidth: 0 }}>
        <Markdown>{content}</Markdown>
      </div>
    </div>
  )
}

function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
        <div className="msg-bubble">{msg.content}</div>
      </div>
    )
  }
  return <AiMessage content={msg.content} />
}

/* 空状态示例提问（引导新用户，点击填入输入框） */
const EXAMPLE_PROMPTS = [
  '查询 M13 的距离、年龄与金属丰度',
  '提取蟹状星云中心脉冲星的自转参数',
  '收集 M31 球状星团系统的金属丰度数据',
]

/* 顶部信息带：运行耗时（completed_at-created_at）+ 数据源/记录计数（完成时一次性拉取）
 * 2026-09-01 用户重设计 */
function fmtDuration(sec) {
  if (!Number.isFinite(sec) || sec < 0) return null
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export default function ChatView({ task, pipeline, onNewTask, logOpen, onToggleLog, focusStage, onOpenInsights,
  mode = 'user', samplesExpanded = false, onOpenSample, onReplaySample, onSwitchToUser }) {
  const { messages, stages, timeline, pending, started, taskDone, logs, sourceScores, submitQuery, submitAnswer } = pipeline
  const [input, setInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { toast } = useToast()
  // 2026-09-02：演示样例本体（source=sample 且非回放副本）——记录只读；
  // 回放副本与普通任务保留全部编辑能力
  const sampleLocked = !!task && task.source === 'sample' && !task.replay_of
  // 卡片默认展开，用户手动收起才收起（collapsed 记录用户收起过的卡）。
  // P1-8：done 卡无展开内容（完成摘要已在卡头）→ 默认折叠
  const [collapsedIds, setCollapsedIds] = useState(() => new Set(['done']))
  // P1-2：Agent 侧抽屉下钻（对话卡点击 Agent 行 → StageDetailPanel L3）
  const [agentDrill, setAgentDrill] = useState(null)   // { stage, agent } | null
  const scrollRef = useRef(null)
  // 贴底跟随：用户在底部附近才自动滚动，向上翻阅时不被拽回
  const stickToBottomRef = useRef(true)

  // 顶部信息带统计（任务完成时一次性拉取并缓存；taskId 键防重复请求）
  const [summaryStats, setSummaryStats] = useState(null)
  const statsCacheRef = useRef({})
  useEffect(() => {
    if (!task?.task_id || task.status !== 'completed') return
    const cached = statsCacheRef.current[task.task_id]
    if (cached) { setSummaryStats(cached); return }
    let alive = true
    Promise.all([
      api.getSources(task.task_id).catch(() => []),
      api.getRecords(task.task_id).catch(() => []),
    ]).then(([s, r]) => {
      const d = { sources: (Array.isArray(s) ? s : []).length, records: (Array.isArray(r) ? r : []).length }
      statsCacheRef.current[task.task_id] = d
      if (alive) setSummaryStats(d)
    })
    return () => { alive = false }
  }, [task?.task_id, task?.status])

  // 2026-08-27：useCallback 稳定引用——StageCard 已 memo，onToggle/onOpenAgent/
  // onOpenInsights 若不稳定（每次 render 新函数），memo 恒失效，高频 setStages
  // 场景全量重渲（主区滚动卡顿的元凶）
  const toggleStage = useCallback((id) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // 稳定引用（StageCard memo 依赖）：Agent 行点击 → L3 下钻抽屉
  const handleOpenAgent = useCallback((agent, stage) => {
    setAgentDrill(stage ? { stage, agent } : null)
  }, [])

  // 工作流视图"在对话中查看" → 展开目标卡并滚动定位
  useEffect(() => {
    if (!focusStage?.id) return
    setCollapsedIds((prev) => {
      if (!prev.has(focusStage.id)) return prev
      const next = new Set(prev)
      next.delete(focusStage.id)
      return next
    })
    // 等卡片展开渲染后再滚动
    const timer = setTimeout(() => {
      const el = scrollRef.current?.querySelector(`[data-stage-id="${focusStage.id}"]`)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 60)
    return () => clearTimeout(timer)
  }, [focusStage])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  /* 运行中 = 任务已启动且未完成；澄清期 = 澄清卡挂起（寒暄除外，寒暄走主栏对话） */
  const running = started && !taskDone
  const clarifying = !!pending && pending.type !== 'greeting'

  // 贴底跟随滚动：仅在用户位于底部附近时自动滚到底
  // 2026-08-27：滚动性能——每 event 同步写 scrollTop 会强制浏览器同步 layout
  // 完整子树（卡顿来源）。改为 rAF 合并：一个动画帧内至多一次 scrollTop 赋值，
  // 且只有内容高度变化（增量 >0）才滚（避免用户上拉回看时被拽回）。
  // 2026-08-27 v2：运行中（running）**强制跟随**——无论用户滚动位置，每次内容
  // 更新都滚到底（保证最新阶段/AI 消息/进度条始终可见，真实查询与回放一致）；
  // 完成瞬间滚一次（看到结果表格）；任务完成后恢复"贴近底部才跟随"（自由回看）。
  const lastScrollHRef = useRef(0)
  const wasRunningRef = useRef(false)   // 运行→完成瞬间检测（滚一次到底）
  useEffect(() => {
    if (!scrollRef.current) return
    const el = scrollRef.current
    // 完成瞬间：上一状态运行中、现在已完成 → 强制滚一次（结果表格/总结入视野）
    const finishedNow = wasRunningRef.current && !running && taskDone
    wasRunningRef.current = running
    const force = running || finishedNow
    if (!force && !stickToBottomRef.current) return
    const delta = el.scrollHeight - lastScrollHRef.current
    // 运行中/完成瞬间：无视高度增量（时间线可能只替换卡片高度不变，但内容更新了）
    // 非运行中：仅内容真正增长才滚（用户回看不被拽回）
    if (!force && delta <= 0) return
    lastScrollHRef.current = el.scrollHeight
    let raf = 0
    const tick = () => {
      if (force || stickToBottomRef.current) el.scrollTop = el.scrollHeight
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [messages, stages, pending, running, taskDone])

  const handleSubmit = async () => {
    const text = input.trim()
    if (!text || running || clarifying || submitting) return
    setSubmitting(true)
    try {
      if (pending) {
        // greeting 等澄清期：主栏输入即回答
        await submitAnswer(text)
        setInput('')
      } else {
        // 新查询：建任务 → 打开事件流
        const taskId = await submitQuery(text)
        onNewTask?.(taskId)
        // 失败（400）保留输入
        setInput('')
      }
    } catch (err) {
      toast(`提交失败：${err.message}`, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* 内容区：统一时间线 —— 消息与卡片按产生顺序交错排列 */}
      <div ref={scrollRef} onScroll={handleScroll} className="chat-gutter" style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 16px' }}>
        <div className="chat-column">
          {/* 顶部信息带（用户重设计）：耗时 · 数据源 · 记录数 + 质量总结 */}
          {task?.status === 'completed' && summaryStats && (
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, color: 'var(--content-fg-secondary)', marginBottom: 8 }}>
                运行耗时 {fmtDuration((new Date(task.completed_at || 0) - new Date(task.created_at)) / 1000) || '—'}
                {' · '}{summaryStats.sources} 个数据源 · {summaryStats.records} 条记录
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                <span style={{
                  width: 20, height: 20, borderRadius: '50%', background: 'var(--status-success)',
                  color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  <Icon.Check style={{ width: 10, height: 10 }} />
                </span>
                <span style={{ fontSize: 14, color: 'var(--content-fg)' }}>
                  数据提取已完成，整体质量良好，可直接用于后续天文数据分析。
                </span>
              </div>
            </div>
          )}
          {timeline.map((entry) => {
            if (entry.kind === 'msg') {
              const msg = messages.find((m) => m.id === entry.id)
              return msg ? <Message key={`m-${entry.id}`} msg={msg} /> : null
            }
            const stage = stages.find((s) => s.id === entry.id)
            if (!stage) return null
            return (
              <Fragment key={`s-${entry.id}`}>
                {stage.id === 'done' ? (
                  /* 「任务完成」卡不渲染卡片本体——结果区表格直接展示在时间线对应位置；
                     LLM 总结已由 usePipeline 排到 done entry 之前（数据洞察卡与表格之间） */
                  stage.status === 'completed' && (
                    <div className="stage-indent" data-stage-id={stage.id} style={{ marginLeft: 38, marginBottom: 8 }}>
                      <ResultTabs taskId={task?.task_id} status={task?.status} readOnly={sampleLocked} />
                    </div>
                  )
                ) : (
                  <>
                    {/* 卡片（默认展开，用户可收起）；data-stage-id 供工作流联动定位 */}
                    <div className="stage-indent" data-stage-id={stage.id} style={{ marginLeft: 38, marginBottom: 8 }}>
                      <StageCard
                        stage={stage}
                        expanded={!collapsedIds.has(stage.id)}
                        onToggle={toggleStage}
                        onOpenInsights={onOpenInsights}
                        onOpenAgent={handleOpenAgent}
                        sourceScores={sourceScores}
                      />
                    </div>
                    {/* 澄清卡：挂起时渲染在所属卡片下方（greeting 走普通对话不渲染） */}
                    {pending && pending.stageId === stage.id && pending.type !== 'greeting' && (
                      <ClarificationCard payload={pending} onSubmit={submitAnswer} />
                    )}
                  </>
                )}
              </Fragment>
            )
          })}

          {/* 兜底：澄清卡 stageId 未匹配时渲染在时间线末尾 */}
          {pending && pending.type !== 'greeting' && !timeline.some((t) => t.kind === 'stage' && t.id === pending.stageId) && (
            <ClarificationCard payload={pending} onSubmit={submitAnswer} />
          )}

          {/* 空状态：无任务或时间线为空 → 演示样例画廊 / 引导 + 示例提问 */}
          {!started && timeline.length === 0 && (
            task ? (
              /* 有选中任务但时间线未起（排队/事件未流到）→ 准备中 */
              <div className="empty-state" style={{ paddingTop: 72, gap: 10 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-text)', marginBottom: 4 }}>
                  <Icon.Sparkle style={{ width: 18, height: 18 }} />
                </div>
                <div style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)' }}>任务准备中…</div>
                <div style={{ maxWidth: 420, lineHeight: 1.6 }}>
                  描述目标天体与想查询的物理性质，智能体将自动完成意图确认、文献检索、数据提取与质检。
                </div>
              </div>
            ) : mode === 'sample' ? (
              /* 演示样例模式：默认空白（折叠态只露侧栏置顶 3 条）；点「展开全部」才显画廊 */
              samplesExpanded && (
                <div style={{ padding: '24px 4px 8px' }}>
                  <SampleGallery
                    samples={SAMPLE_MANIFEST.samples || []}
                    onOpen={onOpenSample}
                    onReplay={onReplaySample}
                    onSwitchToUser={onSwitchToUser}
                  />
                </div>
              )
            ) : (
              <div className="empty-state" style={{ paddingTop: 72, gap: 10 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-text)', marginBottom: 4 }}>
                  <Icon.Sparkle style={{ width: 18, height: 18 }} />
                </div>
                <div style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)' }}>开始一次天文数据提取</div>
                <div style={{ maxWidth: 420, lineHeight: 1.6 }}>
                  描述目标天体与想查询的物理性质，智能体将自动完成意图确认、文献检索、数据提取与质检。
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
                  {EXAMPLE_PROMPTS.map((p) => (
                    <button
                      key={p}
                      onClick={() => setInput(p)}
                      className="filter-chip"
                      style={{ borderRadius: 8, padding: '7px 14px' }}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            )
          )}
        </div>
      </div>

      {/* 输入栏（块 6 定案：附件 chips / 状态禁用；玻璃输入舱）
          2026-09-02：演示样例模式 → 禁发提示条（防误触发起真实计费查询） */}
      {mode === 'sample' ? (
        <div style={{ padding: '12px 24px 20px', flexShrink: 0 }}>
          <div className="chat-column">
            <div
              className="composer"
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 16px' }}
            >
              <Icon.Sparkle style={{ width: 15, height: 15, color: 'var(--accent-text)', flexShrink: 0 }} />
              <span style={{ flex: 1, fontSize: 12.5, color: 'var(--content-fg-secondary)', lineHeight: 1.5 }}>
                演示样例模式仅供浏览与回放——重演的是已内嵌的真实运行过程，不消耗查询额度。
              </span>
              <button
                onClick={onSwitchToUser}
                title="切回『我的查询』发起新的真实查询"
                style={{
                  border: '1px solid color-mix(in srgb, var(--accent) 45%, transparent)',
                  background: 'var(--accent-light)', color: 'var(--accent-text)',
                  fontSize: 12, fontWeight: 500, padding: '5px 12px', borderRadius: 'var(--radius-pill)',
                  cursor: 'pointer', flexShrink: 0, whiteSpace: 'nowrap',
                }}
              >
                发起真实查询
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ padding: '12px 24px 20px', flexShrink: 0 }}>
          <div className="chat-column">
            <div
              className="composer"
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 6px 6px 16px', opacity: running || clarifying ? 0.6 : 1 }}
            >
              {/* 用户重设计：左图标 + 大圆角输入舱 + 圆形绿色发送钮 */}
              <Icon.Sparkle style={{ width: 15, height: 15, color: 'var(--accent-text)', flexShrink: 0 }} />
              <textarea
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSubmit()
                  }
                }}
                disabled={running || clarifying}
                placeholder={clarifying ? '请在上方澄清卡中回答' : running ? '任务进行中…' : '查询数据、筛选记录或继续分析…'}
                style={{
                  flex: 1,
                  minWidth: 0,
                  // 一行布局：上下对称 padding，文字与星标/发送钮同轴垂直居中
                  padding: '9px 4px 9px',
                  fontSize: 14,
                  lineHeight: 1.5,
                  color: 'var(--content-fg)',
                  minHeight: 21,
                  ...((running || clarifying) ? { cursor: 'not-allowed' } : {}),
                }}
              />
              <button
                onClick={handleSubmit}
                disabled={!input.trim() || running || clarifying}
                title="发送"
                style={{
                  width: 40, height: 40, borderRadius: '50%', flexShrink: 0,
                  border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: running || clarifying ? 'var(--surface-secondary)' : !input.trim() ? 'var(--surface-secondary)' : 'var(--accent)',
                  color: running || clarifying ? 'var(--content-fg-tertiary)' : !input.trim() ? 'var(--content-fg-tertiary)' : 'var(--accent-on)',
                  transition: 'background .15s, color .15s',
                }}
              >
                <Icon.Send />
              </button>
            </div>
            <div style={{ textAlign: 'center', marginTop: 8, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
              AI Scientist 可能产生误差，请核实关键信息
            </div>
          </div>
        </div>
      )}

      {/* 底部日志抽屉（块 7，真实事件流日志） */}
      <LogDrawer open={logOpen} onClose={onToggleLog} liveLogs={logs} />

      {/* P1-2：Agent 明细侧抽屉（对话卡点击 Agent 行 → L3 下钻） */}
      {agentDrill && (
        <StageDetailPanel
          stage={agentDrill.stage}
          initialAgentKey={agentDrill.agent.id || agentDrill.agent.agent}
          onClose={() => setAgentDrill(null)}
        />
      )}
    </div>
  )
}
