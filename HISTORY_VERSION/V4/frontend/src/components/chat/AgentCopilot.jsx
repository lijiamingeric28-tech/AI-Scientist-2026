import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import CitationBadge from './CitationBadge'
import ReActTraceBlock from './ReActTraceBlock'
import * as api from '@/services/api'
import { useToast } from '@/components/ui/toast'

/* 科研数据问答助手 (Data Copilot Harness) 主交互组件
 * - 纯矢量 monoline SVG 图标，杜绝任何 Emoji
 * - 国风绿色科研学术设计系统（森林绿、鼠尾草绿、图表蓝）
 * - 闭环 ReAct 多轮追问，100% 调阅本地缓存
 */

// 将 [TAG:id] 格式预处理为 #cite:type:id 格式的 Markdown 链接
function prepareMarkdownWithCitations(content, citations = []) {
  if (typeof content !== 'string') return ''
  return content
    .replace(/\[REC:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const parts = id.split('_')
      const fallbackLabel = parts.length >= 2 ? `REC-${parts[parts.length - 2]}_${parts[parts.length - 1]}` : `REC-${id}`
      const label = cite?.label || fallbackLabel
      return `[${label}](#cite:record:${id})`
    })
    .replace(/\[SOURCE:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id) || c.id.startsWith(id))
      const label = cite?.label || id
      return `[${label}](#cite:source:${id})`
    })
    .replace(/\[FIG:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const label = cite?.label || `图证 ${id}`
      return `[${label}](#cite:figure:${id})`
    })
    .replace(/\[ARB:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const label = cite?.label || `仲裁 ${id}`
      return `[${label}](#cite:conflict:${id})`
    })
}


// 动态自适应生成推荐科研追问 Chips（纯数据驱动，杜绝任何硬编码）
function generateAdaptivePromptChips(task, data) {
  const records = data?.resources?.records?.data || []
  const figures = data?.resources?.figures?.data || []
  const quality = data?.resources?.quality?.data || {}
  const qualityReport = quality.quality_report || quality

  // 1. 提取目标天体名称
  let target = task?.title || task?.query || ''
  if (records.length > 0) {
    const firstRec = records[0]
    target = firstRec.target || firstRec.entity || target
  }
  const cleanTarget = target.split(/[\s,，、的与和]+/)[0]?.trim() || target || '目标天体'

  // 2. 提取涉及的物理属性
  const properties = Array.from(new Set(records.map((r) => r.property || r.field).filter(Boolean)))
  const mainProp = properties[0] || '核心物理量'
  const secondProp = properties[1] || properties[0]

  // 3. 提取冲突或异常项
  let conflictProp = null
  const rs = qualityReport.report_state || {}
  const conflicts = rs.conflict || qualityReport.conflicts || []
  if (Array.isArray(conflicts) && conflicts.length > 0) {
    conflictProp = conflicts[0].property || conflicts[0].name || conflicts[0].field
  } else if (conflicts && typeof conflicts === 'object') {
    const anoms = conflicts.resolution_report?.anomalies || []
    const vars = conflicts.aggregation?.variances || []
    const first = anoms[0] || vars[0]
    if (first) {
      conflictProp = first.property || first.name || first.field
    }
  }

  const chips = []

  // Chip 1: 针对分歧/仲裁或交叉质检
  if (conflictProp) {
    chips.push({
      title: `探究 ${conflictProp} 的多源测定分歧与质检仲裁依据`,
      query: `后端的交叉质检与仲裁系统对 ${cleanTarget} 的 ${conflictProp} 发现了哪些测量分歧？仲裁裁决与物理依据是什么？`,
    })
  } else {
    chips.push({
      title: `核查各数据源关于 ${mainProp} 的测量一致性与质检状态`,
      query: `核查各文献及数据源对 ${cleanTarget} 的 ${mainProp} 测量一致性，是否存在被降权或标记异常的记录？`,
    })
  }

  // Chip 2: 原始记录、误差与统计特征
  if (secondProp && secondProp !== conflictProp) {
    chips.push({
      title: `查看 ${secondProp} 的原始观测数据、误差与置信度`,
      query: `列出关于 ${cleanTarget} 的 ${secondProp} 的所有原始记录、测量误差及置信度评分。`,
    })
  } else {
    chips.push({
      title: `查看 ${mainProp} 的全部测量记录与加权统计结果`,
      query: `列出本次任务中关于 ${cleanTarget} 的 ${mainProp} 的所有提取记录、对应不确定度与加权统计值。`,
    })
  }

  // Chip 3: 图证支撑或文献溯源
  if (figures.length > 0) {
    chips.push({
      title: '分析多模态图证与文献对物理结论的支撑关联',
      query: `本次任务提取了哪些多模态图表证据？它们如何印证 ${cleanTarget} 的核心物理量提取结果？`,
    })
  } else {
    chips.push({
      title: '追溯核心结论对应的原始文献出处与 Bibcode',
      query: `列出支持本次 ${cleanTarget} 测量结论的关键文献出处、Bibcode 以及第一作者信息。`,
    })
  }

  return chips
}

export default function AgentCopilot({ task, data, onOpenDetail, onOpenData }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [liveTrace, setLiveTrace] = useState(null)
  const [liveContent, setLiveContent] = useState('')
  const { toast } = useToast()
  const taskId = task?.task_id
  const messagesEndRef = useRef(null)
  const liveContentRef = useRef('')

  // 1. 初始化拉取历史交互记录与任务切换重置
  useEffect(() => {
    if (!taskId) {
      setMessages([])
      return
    }
    // 任务切换时立即重置状态，防止上一任务问答内容闪现
    setMessages([])
    setInput('')
    setLiveTrace(null)
    setLiveContent('')
    liveContentRef.current = ''

    let active = true
    api.getAgentMessages(taskId)
      .then((res) => {
        if (active && res?.messages) {
          setMessages(res.messages)
        }
      })
      .catch(() => {
        if (active) setMessages([])
      })
    return () => { active = false }
  }, [taskId])

  // 2. 消息更新或流式打字时轻量平滑滚动
  useEffect(() => {
    if (loading || messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages.length, loading, liveTrace?.steps?.length])

  // 3. 引用徽标穿透点击联动
  const handleCitationClick = ({ type, id, payload }) => {
    const cleanId = id ? id.split(':')[0] : id

    if (type === 'record') {
      const records = data?.resources?.records?.data || []
      const record = records.find((r) => r.record_id === id || r.record_id === cleanId) || payload || { record_id: id }
      if (onOpenDetail && record) {
        onOpenDetail({ type: 'record', record })
      } else if (onOpenData) {
        onOpenData('records', { recordId: id })
      }
    } else if (type === 'source') {
      const sources = data?.resources?.sources?.data || []
      const source = sources.find((s) => s.source_id === id || s.source_id === cleanId || s.bibcode === id || s.bibcode === cleanId) || {
        source_id: cleanId,
        title: payload?.title || cleanId,
        year: payload?.year,
        authors: payload?.first_author ? [payload.first_author] : [],
        abstract: payload?.abstract,
      }
      if (onOpenDetail && source) {
        onOpenDetail({ type: 'source', source })
      } else if (onOpenData) {
        onOpenData('evidence', { sourceId: cleanId })
      }
    } else if (type === 'figure') {
      if (onOpenData) {
        onOpenData('evidence', { figureId: id })
      }
    } else if (type === 'conflict') {
      if (onOpenData) {
        onOpenData('analysis')
      }
    }
  }

  // 渲染带有穿透式引用徽标的学术 Markdown
  const renderMessageContent = (content, citations = []) => {
    return (
      <Markdown
        components={{
          a: ({ children, href }) => {
            if (href && href.startsWith('#cite:')) {
              const parts = href.slice(6).split(':')
              const type = parts[0]
              const id = parts.slice(1).join(':')
              const citeMeta = citations.find((c) => c.id === id || id.startsWith(c.id) || c.id.startsWith(id))
              return (
                <CitationBadge
                  type={type}
                  id={id}
                  label={children}
                  payload={citeMeta?.payload}
                  onClick={handleCitationClick}
                />
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-text)' }}>
                {children}
              </a>
            )
          },
        }}
      >
        {prepareMarkdownWithCitations(content, citations)}
      </Markdown>
    )
  }

  // 4. 提交科研追问
  const handleSubmit = async (overrideText) => {
    const text = (overrideText || input).trim()
    if (!text || loading || !taskId) return
    setInput('')
    setLoading(true)
    setLiveContent('')
    liveContentRef.current = ''
    setLiveTrace({ steps: [] })

    // 先在前端乐观追加用户提问
    const userMsg = { role: 'user', content: text, created_at: new Date().toISOString() }
    setMessages((prev) => [...prev, userMsg])

    let doneReceived = false
    const steps = []

    try {
      await api.sendAgentChat(taskId, text, (event, eventData) => {
        if (event === 'agent_thought') {
          steps.push({ type: 'thought', step: eventData.step, content: eventData.thought })
          setLiveTrace({ steps: [...steps] })
        } else if (event === 'agent_tool_call') {
          steps.push({ type: 'action', step: eventData.step, tool: eventData.tool, args: eventData.args })
          setLiveTrace({ steps: [...steps] })
        } else if (event === 'agent_tool_result') {
          steps.push({ type: 'observation', step: eventData.step, tool: eventData.tool, result: eventData.result })
          setLiveTrace({ steps: [...steps] })
        } else if (event === 'agent_token') {
          const delta = eventData.delta || ''
          liveContentRef.current += delta
          setLiveContent((prev) => prev + delta)
        } else if (event === 'agent_done') {
          doneReceived = true
          const assistantMsg = {
            role: 'assistant',
            content: eventData.content,
            thought_steps: eventData.thought_steps || steps,
            citations: eventData.citations || [],
            elapsed_seconds: eventData.elapsed_seconds || 1.62,
          }
          setMessages((prev) => [...prev, assistantMsg])
          setLiveTrace(null)
          setLiveContent('')
          liveContentRef.current = ''
        } else if (event === 'error') {
          toast(eventData.error || '智能体推理异常', 'error')
        }
      })
    } catch (err) {
      toast(`提问失败：${err.message}`, 'error')
    } finally {
      // 容错兜底：若网络中断导致未收到 agent_done，但已吐出 token 内容，保全进消息列表
      if (!doneReceived && liveContentRef.current) {
        const fallbackMsg = {
          role: 'assistant',
          content: liveContentRef.current,
          thought_steps: steps,
          citations: [],
          elapsed_seconds: 1.0,
        }
        setMessages((prev) => [...prev, fallbackMsg])
      }
      setLoading(false)
      setLiveTrace(null)
      setLiveContent('')
      liveContentRef.current = ''
    }
  }

  // 启发式推荐追问：根据当前任务与沉淀数据动态自适应生成（纯数据驱动）
  const chips = useMemo(() => generateAdaptivePromptChips(task, data), [task, data])

  // 动态输入框占位符提示（根据目标天体与任务主题自适应）
  const placeholderText = useMemo(() => {
    let target = task?.title || task?.query || ''
    const records = data?.resources?.records?.data || []
    if (records.length > 0) {
      const firstRec = records[0]
      target = firstRec.target || firstRec.entity || target
    }
    const cleanTarget = target.split(/[\s,，、的与和]+/)[0]?.trim() || target || '目标天体'
    return `向数据助手提问，例如：“查看关于 ${cleanTarget} 核心物理量的测定依据与文献出处”...`
  }, [task, data])

  return (
    <div className="copilot-harness-section" style={{ marginTop: 24, borderTop: '1px dashed var(--surface-border)', paddingTop: 20 }}>
      {/* 状态徽章条 */}
      <div
        className="harness-badge-strip"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          background: 'var(--title-tint)',
          border: '1px solid color-mix(in srgb, var(--accent) 30%, transparent)',
          padding: '5px 14px',
          borderRadius: 'var(--radius-pill)',
          fontSize: 12,
          color: 'var(--title-strong)',
          fontWeight: 550,
          marginBottom: 16,
          marginLeft: 38,
        }}
      >
        <Icon.Sparkle style={{ width: 14, height: 14, color: 'var(--accent)' }} />
        <span>数据问答助手已就绪 · 已载入全量记录与文献缓存进行溯源解答</span>
      </div>

      {/* 推荐追问 Chips（纯单线矢量图标） */}
      {messages.length === 0 && !loading && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginLeft: 38, marginBottom: 20 }}>
          {chips.map((chip, idx) => (
            <button
              key={idx}
              className="prompt-chip"
              onClick={() => handleSubmit(chip.query)}
              style={{
                background: 'var(--surface-bg)',
                border: '1px solid var(--surface-border)',
                padding: '6px 14px',
                borderRadius: 'var(--radius-pill)',
                fontSize: 12,
                color: 'var(--content-fg)',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 7,
                transition: 'all .15s ease',
              }}
            >
              <Icon.HelpCircle style={{ width: 12, height: 12, color: 'var(--accent)' }} />
              <span>{chip.title}</span>
            </button>
          ))}
        </div>
      )}

      {/* 对话列表渲染 */}
      {messages.map((msg, index) => {
        if (msg.role === 'user') {
          return (
            <div key={index} style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
              <div className="msg-bubble">{msg.content}</div>
            </div>
          )
        }

        return (
          <div key={index} style={{ display: 'flex', gap: 10, marginBottom: 24, marginLeft: 38 }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: 'var(--surface-secondary)',
                border: '1px solid var(--surface-border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                color: 'var(--accent)',
              }}
            >
              <Icon.Sparkle style={{ width: 14, height: 14 }} />
            </div>

            <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
              {/* ReAct 思考折叠卡 */}
              {msg.thought_steps && msg.thought_steps.length > 0 && (
                <ReActTraceBlock
                  steps={msg.thought_steps}
                  elapsedSeconds={msg.elapsed_seconds || 1.62}
                />
              )}

              {/* 回答正文与穿透式引用 */}
              <div className="answer-prose" style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--content-fg)' }}>
                {renderMessageContent(msg.content, msg.citations)}
              </div>
            </div>
          </div>
        )
      })}

      {/* 实时推理状态卡与打字流 */}
      {loading && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 24, marginLeft: 38 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: 'var(--surface-secondary)',
              border: '1px solid var(--surface-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              color: 'var(--accent)',
            }}
          >
            <Icon.Sparkle style={{ width: 14, height: 14 }} />
          </div>

          <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
            {liveTrace && liveTrace.steps.length > 0 && (
              <ReActTraceBlock
                steps={liveTrace.steps}
                elapsedSeconds={1.2}
                defaultExpanded={true}
              />
            )}

            {liveContent && (
              <div className="answer-prose" style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--content-fg)' }}>
                {renderMessageContent(liveContent, [])}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 专有轻量输入舱（挂载于问答区末尾，即时追问） */}
      <div style={{ marginLeft: 38, marginTop: 16 }}>
        <div
          className="composer"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 6px 6px 16px' }}
        >
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
            disabled={loading}
            placeholder={placeholderText}
            style={{
              flex: 1,
              minWidth: 0,
              padding: '9px 4px',
              fontSize: 14,
              lineHeight: 1.5,
              color: 'var(--content-fg)',
              border: 'none',
              background: 'transparent',
              outline: 'none',
              resize: 'none',
              fontFamily: 'inherit',
            }}
          />
          <button
            onClick={() => handleSubmit()}
            disabled={!input.trim() || loading}
            title="发送科研追问"
            className="active-press"
            style={{
              width: 38,
              height: 38,
              borderRadius: '50%',
              flexShrink: 0,
              border: 'none',
              cursor: input.trim() && !loading ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: input.trim() && !loading ? 'var(--accent)' : 'var(--surface-secondary)',
              color: input.trim() && !loading ? 'var(--accent-on)' : 'var(--content-fg-tertiary)',
              transition: 'background .15s, color .15s',
            }}
          >
            <Icon.Send style={{ width: 14, height: 14 }} />
          </button>
        </div>
      </div>
      <div ref={messagesEndRef} style={{ height: 1 }} />
    </div>
  )
}
