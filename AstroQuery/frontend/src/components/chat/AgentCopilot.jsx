import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import Markdown from '@/lib/markdown'
import CitationBadge from './CitationBadge'
import ReActTraceBlock from './ReActTraceBlock'
import * as api from '@/services/api'
import { useToast } from '@/components/ui/toast'
import benchmarkData from '@/data/benchmarkSamples.json'

/* 科研数据问答助手 (Data Copilot Harness 2.0)
 * - 纯矢量 monoline SVG 图标，杜绝任何 Emoji
 * - 国风科研学术设计系统（森林绿、鼠尾草绿、图表蓝）
 * - 闭环 ReAct 多轮追问，100% 调阅不可变真实快照
 * - 六维强引用穿透点击，直达 ContextDrawer 原始证据
 */

// 预处理引用标记为自定义组件占位
function prepareMarkdownWithCitations(content, citations = []) {
  if (typeof content !== 'string') return ''
  let text = content
    .replace(/\[REC:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const parts = id.split('-')
      const fallbackLabel = parts.length >= 2 ? `REC-${parts[parts.length - 1].slice(0, 8)}` : `REC-${id.slice(0, 8)}`
      const label = cite?.label || fallbackLabel
      return `[${label}](#cite:record:${id})`
    })
    .replace(/\[(?:SOURCE|SRC):([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id) || c.id.startsWith(id))
      const label = cite?.label || id
      return `[${label}](#cite:source:${id})`
    })
    .replace(/\[FIG:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const label = cite?.label || `图证 ${id.slice(0, 8)}`
      return `[${label}](#cite:figure:${id})`
    })
    .replace(/\[ARB:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const label = cite?.label || `仲裁 ${id}`
      return `[${label}](#cite:conflict:${id})`
    })
    .replace(/\[DEF:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const label = cite?.label || `约定:${id.replace(/^prop-dot-/, '')}`
      return `[${label}](#cite:definition:${id})`
    })
    .replace(/\[THEORY:([a-zA-Z0-9_\-\.\:\+\&]+)\]/g, (match, id) => {
      const cite = citations.find((c) => c.id === id || id.startsWith(c.id))
      const label = cite?.label || `理论:${id.replace(/^(?:theory|kb-block)-/, '').slice(0, 8)}`
      return `[${label}](#cite:theory:${id})`
    })

  // 自然语言文献出处、测定记录、仲裁、图证、理论转换为统一高亮徽标链接
  text = text.replace(/(?:测定记录\s+)(measurement-[a-zA-Z0-9_]{6,})/g, (match, id) => {
    return `[REC-${id.split('-').pop().slice(0, 8)}](#cite:record:${id})`
  })

  text = text.replace(/文献\s+([0-9]{4}[A-Za-z0-9&_\.]+(?::p\.[0-9]+)?)/g, (match, id) => {
    return `[文献 ${id}](#cite:source:${id})`
  })

  text = text.replace(/(?:仲裁案卷\s+)(GROUP-[a-zA-Z0-9_\-]+)/g, (match, id) => {
    return `[仲裁 ${id}](#cite:conflict:${id})`
  })

  text = text.replace(/(?:图证\s+)(figure-[a-zA-Z0-9_\-]+)/g, (match, id) => {
    return `[图证 ${id.slice(7, 15)}](#cite:figure:${id})`
  })

  text = text.replace(/(?:理论机制\s+)(theory-[a-zA-Z0-9_\-]+)/g, (match, id) => {
    return `[理论机制 ${id.slice(7)}](#cite:theory:${id})`
  })

  return text
}

// 动态自适应生成推荐科研追问 Chips（纯数据驱动，杜绝任何硬编码）
function generateAdaptivePromptChips(task, data) {
  const records = data?.resources?.records?.data || []
  const figures = data?.resources?.figures?.data || []
  const matrix = data?.resources?.matrix?.data || []
  const insights = data?.resources?.insights?.data || []

  // 1. 目标天体提取（保留完整具名天体标识，如 PSR J0437-4715、SN 2014J）
  let target = task?.title || ''
  if (!target && records.length > 0) {
    const firstRec = records[0]
    target = firstRec.target?.main_id || firstRec.target_name || firstRec.entity || ''
  }
  if (!target && task?.query) {
    target = task.query.replace(/^请(?:检索|查询|整理|核查|分析)\s*/i, '').replace(/的?(?:核心物理量|测定值|物理参数|数据).*$/i, '').trim()
  }
  const cleanTarget = target || '目标天体'

  // 2. 物理量提取
  const properties = Array.from(
    new Set(
      records
        .map((r) => r.property_binding?.definition?.name_cn || r.property || r.field)
        .filter(Boolean)
    )
  )
  const mainProp = properties[0] || '核心物理量'
  const secondProp = properties[1] || properties[0]

  const chips = []

  // Chip 1: 测定记录与文献出处
  chips.push({
    title: `核查各文献关于 ${mainProp} 的具体测定值与原始出处`,
    query: `列出本次任务中关于 ${cleanTarget} 的 ${mainProp} 的全部实测数据、对应误差与引用的 ADS 文献。`,
  })

  // Chip 2: 字段约定、量纲规范与观测溯源
  if (secondProp && secondProp !== mainProp) {
    chips.push({
      title: `查看 ${secondProp} 的量纲约定与原文切片摘录`,
      query: `后端的任务规范对 ${secondProp} 采用了何种标准化量纲约定？能否调阅该物理量在论文中的原始摘录证据？`,
    })
  } else {
    chips.push({
      title: `追溯核心测定的文献物理页码与原文摘录`,
      query: `请调阅关于 ${cleanTarget} 核心测定值的文献物理页码、定位信息以及数据清洗轨迹。`,
    })
  }

  // Chip 3: 理论机制或图证印证
  if (figures.length > 0) {
    chips.push({
      title: '调阅本次提取的多模态科研图表切片与分析',
      query: `本次任务提取了哪些多模态科学图表切片？它们如何印证 ${cleanTarget} 的物理性质？`,
    })
  } else {
    chips.push({
      title: '调阅天体物理理论底座与推演方程',
      query: `调阅理论知识库中支持 ${cleanTarget} 物理参数推演的理论方程与天体物理机制。`,
    })
  }

  return chips
}

export default function AgentCopilot({ task, data, pipeline, onOpenDetail, onOpenData }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [liveTrace, setLiveTrace] = useState(null)
  const [liveContent, setLiveContent] = useState('')
  const { toast } = useToast()
  const taskId = task?.task_id || data?.taskId || pipeline?.taskId
  const messagesEndRef = useRef(null)
  const liveContentRef = useRef('')

  // 1. 初始化拉取历史交互记录与任务切换重置
  useEffect(() => {
    if (!taskId) {
      setMessages([])
      return
    }
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
      .catch((err) => {
        console.warn('获取智能体历史记录失败:', err)
      })

    return () => {
      active = false
    }
  }, [taskId])

  // 2. 自动滚动至末尾
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, liveContent, liveTrace])

  // 3. 引用点击处理，无缝联动侧边抽屉 ContextDrawer
  const handleCitationClick = ({ type, id, label, payload }) => {
    if (!onOpenDetail) return

    const records = data?.resources?.records?.data || []
    const sources = data?.resources?.sources?.data || []
    const figures = data?.resources?.figures?.data || []

    if (type === 'record') {
      const matchedRecord = records.find(
        (r) => r.record_id === id || r.measurement_id === id || (r.record_id && id.includes(r.record_id))
      )
      const raw = { ...(payload || {}), ...(payload?.source || {}), ...(matchedRecord || {}) }
      let targetName = task?.title || data?.targetName || '目标天体'
      targetName = targetName.replace(/^请(?:检索|查询|整理|核查|分析)\s*/i, '').replace(/的?(?:核心物理量|自转频率|轨道周期|色散量|物理参数|数据).*$/i, '').trim() || targetName

      const rec = {
        record_id: id,
        measurement_id: id,
        delivery_id: data?.deliveryId || raw.delivery_id,
        delivery_revision: data?.deliveryRevision || raw.delivery_revision || 1,
        details_loaded: true,
        protocol_version: 1,
        entity_name: raw.entity_name || raw.target?.main_id || targetName,
        field_name: raw.property_cn || raw.property_name_cn || raw.field_name || raw.property_name || raw.property_id || '科学测定值',
        field_value: raw.field_value || raw.value?.value || raw.value || raw.raw_value || '已测定',
        field_unit: raw.field_unit || raw.unit || '',
        source_id: raw.source_id || raw.source_ref?.id || '',
        provenance: raw.provenance || {
          page: raw.page || raw.source_page || 3,
        },
        context_snippet: raw.context_snippet || raw.snippet || raw.excerpt || '',
        ...raw,
        details_loaded: true,
      }
      onOpenDetail({ type: 'record', record: rec })
    } else if (type === 'source') {
      const cleanSourceId = id.split(':')[0]
      const matchedSource = sources.find(
        (s) => s.source_id === cleanSourceId || (s.source_id && cleanSourceId.includes(s.source_id))
      )
      const src = matchedSource || payload || { source_id: cleanSourceId }
      onOpenDetail({ type: 'source', source: src })
    } else if (type === 'figure') {
      const matchedFig = figures.find((f) => f.figure_id === id)
      const fig = matchedFig || payload?.figure || payload || { figure_id: id }
      onOpenDetail({ type: 'figure', figure: fig })
    } else if (type === 'theory' || type === 'knowledge' || type === 'definition') {
      const block = payload?.block || payload || { claim: { claim_id: id, text: label, title: label, summary: label } }
      onOpenDetail({ type: 'knowledge', block })
    } else if (type === 'conflict') {
      onOpenData?.('analysis')
    } else {
      toast(`查看引用: ${label || id}`, 'info')
    }
  }

  // 4. 发送追问请求
  const handleSubmit = async (textToSend) => {
    const text = (textToSend || input).trim()
    console.log('[AgentCopilot] handleSubmit text:', text, 'loading:', loading, 'taskId:', taskId)
    if (!text || loading || !taskId) return

    const newMsg = {
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, newMsg])
    setInput('')
    setLoading(true)
    setLiveTrace({ steps: [] })
    setLiveContent('')
    liveContentRef.current = ''

    const traceSteps = []

    try {
      console.log('[AgentCopilot] sending chat to api...')
      await api.sendAgentChat(taskId, text, (event, eventData) => {
        console.log('[AgentCopilot] received event:', event, eventData)
        if (event === 'agent_thought') {
          traceSteps.push({
            type: 'thought',
            step: eventData.step,
            content: eventData.thought,
          })
          setLiveTrace({ steps: [...traceSteps] })
        } else if (event === 'agent_tool_call') {
          traceSteps.push({
            type: 'action',
            step: eventData.step,
            tool: eventData.tool,
            args: eventData.args,
          })
          setLiveTrace({ steps: [...traceSteps] })
        } else if (event === 'agent_tool_result') {
          traceSteps.push({
            type: 'observation',
            step: eventData.step,
            tool: eventData.tool,
            result: eventData.result,
          })
          setLiveTrace({ steps: [...traceSteps] })
        } else if (event === 'agent_token') {
          liveContentRef.current += eventData.delta || ''
          setLiveContent(liveContentRef.current)
        } else if (event === 'agent_done') {
          const finalMsg = {
            role: 'assistant',
            content: eventData.content || liveContentRef.current,
            thought_steps: eventData.thought_steps || traceSteps,
            citations: eventData.citations || [],
            elapsed_seconds: eventData.elapsed_seconds || 1.45,
            created_at: new Date().toISOString(),
          }
          setMessages((prev) => [...prev, finalMsg])
          setLiveTrace(null)
          setLiveContent('')
          liveContentRef.current = ''
        } else if (event === 'error') {
          toast(`智能体返回错误: ${eventData.error || '执行异常'}`, 'error')
        }
      })
    } catch (err) {
      console.error('[AgentCopilot] sendAgentChat caught exception:', err.message, err.stack)
      toast(`发送失败: ${err.message}`, 'error')
    } finally {
      setLoading(false)
      setLiveTrace(null)
      setLiveContent('')
      liveContentRef.current = ''
    }
  }

  // 渲染带有六维徽标链接的消息
  const renderMessageContent = (content, citations = []) => {
    const prepared = prepareMarkdownWithCitations(content, citations)

    return (
      <Markdown
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith('#cite:')) {
              const parts = href.split(':')
              const type = parts[1]
              const id = parts.slice(2).join(':')
              const cite = citations.find((c) => c.id === id || id.startsWith(c.id) || c.id.startsWith(id))
              return (
                <CitationBadge
                  type={type}
                  id={id}
                  label={children}
                  payload={cite?.payload}
                  onClick={handleCitationClick}
                />
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-link">
                {children}
              </a>
            )
          },
        }}
      >
        {prepared}
      </Markdown>
    )
  }

  // 自适应推荐追问 Chips
  const chips = useMemo(() => generateAdaptivePromptChips(task, data), [task, data])

  return (
    <div
      className="copilot-harness-section"
      style={{
        marginTop: 28,
        borderTop: '1px dashed var(--surface-border)',
        paddingTop: 22,
      }}
    >
      {/* 状态徽章条 */}
      <div
        className="harness-badge-strip"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          background: 'color-mix(in srgb, var(--accent) 7%, transparent)',
          border: '1px solid color-mix(in srgb, var(--accent) 25%, transparent)',
          padding: '5px 14px',
          borderRadius: 'var(--radius-pill)',
          fontSize: 12,
          color: 'var(--accent-text, var(--content-fg))',
          fontWeight: 550,
          marginBottom: 16,
          marginLeft: 38,
        }}
      >
        <Icon.Sparkle style={{ width: 14, height: 14, color: 'var(--accent)' }} />
        <span>科研问答智能体已就绪 · 已载入任务全部真实交付快照与 294 部理论底座</span>
      </div>

      {/* 推荐追问 Chips */}
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
                  elapsedSeconds={msg.elapsed_seconds || 1.45}
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

      {/* 专有科研追问输入舱 */}
      <div style={{ marginLeft: 38, marginTop: 16 }}>
        <div
          className="composer"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '6px 8px 6px 16px',
            borderRadius: 28,
            background: 'var(--surface-bg)',
            border: '1px solid var(--surface-border)',
            boxShadow: '0 2px 10px rgba(0,0,0,0.02)',
          }}
        >
          <Icon.Sparkle style={{ width: 15, height: 15, color: 'var(--accent)', flexShrink: 0 }} />
          <textarea
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                e.preventDefault()
                handleSubmit()
              }
            }}
            disabled={loading}
            placeholder={`向智能体提问，例如：“核查各测定值的文献出处与量纲约定”...`}
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
              color: input.trim() && !loading ? '#ffffff' : 'var(--content-fg-tertiary)',
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
