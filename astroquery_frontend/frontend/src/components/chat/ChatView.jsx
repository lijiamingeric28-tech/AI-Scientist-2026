import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import StageCard from './StageCard'
import ClarificationCard from './ClarificationCard'
import ResultTabs from '@/components/results/ResultTabs'
import LogDrawer from '@/components/log/LogDrawer'
import StageDetailPanel from '@/components/workflow/StageDetailPanel'
import { useToast } from '@/components/ui/toast'

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

export default function ChatView({ task, pipeline, onNewTask, logOpen, onToggleLog, focusStage, onOpenInsights }) {
  const { messages, stages, timeline, pending, started, taskDone, logs, sourceScores, submitQuery, submitAnswer } = pipeline
  const [input, setInput] = useState('')
  const [files, setFiles] = useState([])   // 已选 PDF chips [{name, size}]
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef(null)
  const { toast } = useToast()
  // 卡片默认展开，用户手动收起才收起（collapsed 记录用户收起过的卡）。
  // P1-8：done 卡无展开内容（完成摘要已在卡头）→ 默认折叠
  const [collapsedIds, setCollapsedIds] = useState(() => new Set(['done']))
  // P1-2：Agent 侧抽屉下钻（对话卡点击 Agent 行 → StageDetailPanel L3）
  const [agentDrill, setAgentDrill] = useState(null)   // { stage, agent } | null
  const scrollRef = useRef(null)
  // 贴底跟随：用户在底部附近才自动滚动，向上翻阅时不被拽回
  const stickToBottomRef = useRef(true)

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

  const formatSize = (bytes) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)

  const handleFiles = (e) => {
    const list = Array.from(e.target.files || [])
    const valid = list.filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    const rejected = list.length - valid.length
    if (rejected > 0) toast(`仅支持 PDF 文件（${rejected} 个已忽略）`, 'error')
    setFiles((prev) => [...prev, ...valid.map((f) => ({ name: f.name, size: f.size, file: f }))])
    e.target.value = ''
  }

  const removeFile = (name) => setFiles((prev) => prev.filter((f) => f.name !== name))

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
        // 新查询：上传 PDF → 建任务 → 打开事件流
        const taskId = await submitQuery(text, files.map((f) => f.file))
        onNewTask?.(taskId)
        // L-02：清理移入成功分支——失败（400/上传错误）保留输入与已选 PDF
        setInput('')
        setFiles([])
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
                      <ResultTabs taskId={task?.task_id} status={task?.status} />
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

          {/* 空状态：无任务或时间线为空 → 引导 + 示例提问（点击填入输入框） */}
          {!started && timeline.length === 0 && (
            <div className="empty-state" style={{ paddingTop: 72, gap: 10 }}>
              <div style={{ width: 44, height: 44, borderRadius: 12, background: 'var(--surface-bg)', border: '1px solid var(--surface-border)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-text)', marginBottom: 4 }}>
                <Icon.Sparkle style={{ width: 18, height: 18 }} />
              </div>
              <div style={{ fontSize: 15, fontWeight: 510, color: 'var(--content-fg)' }}>
                {task ? '任务准备中…' : '开始一次天文数据提取'}
              </div>
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
          )}
        </div>
      </div>

      {/* 输入栏（块 6 定案：附件 chips / 状态禁用；玻璃输入舱） */}
      <div style={{ padding: '12px 24px 20px', flexShrink: 0 }}>
        <div className="chat-column">
          <div
            className="composer"
            style={{ opacity: running || clarifying ? 0.6 : 1 }}
          >
            {/* 已选 PDF chips */}
            {files.length > 0 && (
              <div style={{ display: 'flex', gap: 6, padding: '10px 14px 0', flexWrap: 'wrap' }}>
                {files.map((f) => (
                  <span
                    key={f.name}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      padding: '3px 8px',
                      fontSize: 12,
                      borderRadius: 6,
                      background: 'var(--surface-secondary)',
                      border: '1px solid var(--surface-border)',
                      color: 'var(--content-fg)',
                    }}
                  >
                    <Icon.FileText style={{ width: 12, height: 12, color: 'var(--content-fg-tertiary)' }} />
                    {f.name} <span style={{ color: 'var(--content-fg-tertiary)', fontSize: 11 }}>{formatSize(f.size)}</span>
                    <button
                      onClick={() => removeFile(f.name)}
                      style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--content-fg-tertiary)', padding: 0, display: 'flex' }}
                      title="移除"
                    >
                      <Icon.Close style={{ width: 10, height: 10 }} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <textarea
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSubmit()
                }
              }}
              disabled={running || clarifying}
              placeholder={clarifying ? '请在上方澄清卡中回答' : running ? '任务进行中…' : '描述您的天文查询需求，智能体将自动检索文献（也可上传 PDF）…'}
              style={{
                width: '100%',
                padding: '14px 16px 8px',
                fontSize: 14,
                lineHeight: 1.5,
                color: 'var(--content-fg)',
                minHeight: 48,
                ...((running || clarifying) ? { cursor: 'not-allowed' } : {}),
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', gap: 4 }}>
              {/* 附件上传（运行/澄清期禁用） */}
              <input ref={fileInputRef} type="file" accept=".pdf" multiple hidden onChange={handleFiles} />
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 text-xs"
                disabled={running || clarifying}
                onClick={() => fileInputRef.current?.click()}
              >
                <Icon.Paperclip />上传 PDF
              </Button>
              <div style={{ flex: 1 }} />
              <Button variant="accent" size="icon" className="rounded-full" onClick={handleSubmit} disabled={!input.trim() || running || clarifying}>
                <Icon.Send />
              </Button>
            </div>
          </div>
          <div style={{ textAlign: 'center', marginTop: 8, fontSize: 11, color: 'var(--content-fg-tertiary)' }}>
            AI Scientist 可能产生误差，请核实关键信息
          </div>
        </div>
      </div>

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
