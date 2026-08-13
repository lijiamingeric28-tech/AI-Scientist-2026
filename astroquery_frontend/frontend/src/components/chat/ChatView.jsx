import { Fragment, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import StageCard from './StageCard'
import ClarificationCard from './ClarificationCard'
import ResultTabs from '@/components/results/ResultTabs'
import LogDrawer from '@/components/log/LogDrawer'
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
  const { messages, stages, timeline, pending, started, taskDone, logs, submitQuery, submitAnswer } = pipeline
  const [input, setInput] = useState('')
  const [files, setFiles] = useState([])   // 已选 PDF chips [{name, size}]
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef(null)
  const { toast } = useToast()
  // 卡片默认展开，用户手动收起才收起（collapsed 记录用户收起过的卡）
  const [collapsedIds, setCollapsedIds] = useState(() => new Set())
  const scrollRef = useRef(null)
  // 贴底跟随：用户在底部附近才自动滚动，向上翻阅时不被拽回
  const stickToBottomRef = useRef(true)

  const toggleStage = (id) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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

  // 贴底跟随滚动：仅在用户位于底部附近时自动滚到底
  useEffect(() => {
    if (stickToBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, stages, pending])

  /* 运行中 = 任务已启动且未完成；澄清期 = 澄清卡挂起（寒暄除外，寒暄走主栏对话） */
  const running = started && !taskDone
  const clarifying = !!pending && pending.type !== 'greeting'

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
                {/* 卡片（默认展开，用户可收起）；data-stage-id 供工作流联动定位 */}
                <div className="stage-indent" data-stage-id={stage.id} style={{ marginLeft: 38, marginBottom: 8 }}>
                  <StageCard
                    stage={stage}
                    expanded={!collapsedIds.has(stage.id)}
                    onToggle={() => toggleStage(stage.id)}
                    onOpenInsights={onOpenInsights}
                  />
                </div>
                {/* 澄清卡：挂起时渲染在所属卡片下方（greeting 走普通对话不渲染） */}
                {pending && pending.stageId === stage.id && pending.type !== 'greeting' && (
                  <ClarificationCard payload={pending} onSubmit={submitAnswer} />
                )}
                {/* 兜底：stageId 缺失时渲染在时间线末尾（下方统一处理） */}
                {/* 任务完成：主区全宽结果区（记录表格/来源/质量/下载） */}
                {stage.id === 'done' && stage.status === 'completed' && <ResultTabs taskId={task?.task_id} />}
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
    </div>
  )
}
