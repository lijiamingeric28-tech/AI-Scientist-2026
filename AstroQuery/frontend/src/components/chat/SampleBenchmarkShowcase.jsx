import React, { useState } from 'react'
import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import Markdown from '@/lib/markdown'
import CitationBadge from './CitationBadge'
import ReActTraceBlock from './ReActTraceBlock'
import benchmarkData from '@/data/benchmarkSamples.json'

/* 科研问答智能体 6 大交付样例实测成果展示展台 (Agent Harness 2.0 Benchmark Showcase)
 * - 纯矢量 monoline SVG 图标，彻底杜绝任何 Emoji
 * - 搭载 KaTeX 学术级公式渲染、ReAct 真实多步思考与六维证据链徽标
 * - 与演示样例库和右侧证据抽屉深度联动
 */

export function prepareMarkdownWithCitations(content, citations = []) {
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

  // 支持自然语言文献出处与测定记录自动转为高亮徽标
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

export default function SampleBenchmarkShowcase({ onOpenSample, onOpenData, onOpenDetail }) {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const activeSample = benchmarkData[selectedIndex] || benchmarkData[0]

  const handleCitationClick = ({ type, id, label }) => {
    if (onOpenDetail) {
      if (type === 'record') {
        onOpenDetail({
          type: 'record',
          record: {
            record_id: id,
            measurement_id: id,
            field_name: label || '科学测定值',
            details_loaded: false,
          },
        })
      } else if (type === 'source') {
        onOpenDetail({ type: 'source', source: { source_id: id.split(':')[0] } })
      } else if (type === 'figure') {
        onOpenDetail({ type: 'figure', figure: { figure_id: id } })
      } else if (type === 'theory' || type === 'knowledge') {
        onOpenDetail({ type: 'knowledge', block: { claim: { claim_id: id, text: label } } })
      } else {
        onOpenSample?.(activeSample.task_id)
      }
    } else {
      onOpenSample?.(activeSample.task_id)
    }
  }

  const renderContent = (content, citations = []) => {
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

  return (
    <section
      className="benchmark-showcase-section"
      style={{
        marginTop: 36,
        paddingTop: 28,
        borderTop: '1px solid var(--surface-border-subtle)',
      }}
    >
      {/* 模块顶部介绍 */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                background: 'color-mix(in srgb, var(--accent) 12%, transparent)',
                color: 'var(--accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Icon.Sparkle style={{ width: 14, height: 14 }} />
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 650, margin: 0, color: 'var(--content-fg)' }}>
              精选智能体学术追问与验证成果
            </h3>
          </div>
          <span
            style={{
              fontSize: 11.5,
              fontWeight: 500,
              padding: '3px 10px',
              borderRadius: 'var(--radius-pill)',
              background: 'color-mix(in srgb, var(--accent) 8%, transparent)',
              color: 'var(--accent-text)',
              border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)',
            }}
          >
            阿里云百炼 Qwen-Plus 实机推理 · 真实数据不可变快照闭环
          </span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--content-fg-secondary)', margin: 0, lineHeight: 1.5 }}>
          以下展示系统针对 6 个已交付天文学术样例的实机追问与完整推理答复。支持展开 ReAct 思考与工具调阅轨迹、公式解析与六维证据穿透。
        </p>
      </div>

      {/* 6 样例胶囊选项卡 */}
      <div
        role="tablist"
        aria-label="6 样例科研问答实测"
        style={{
          display: 'flex',
          gap: 6,
          overflowX: 'auto',
          paddingBottom: 6,
          marginBottom: 18,
          scrollbarWidth: 'none',
        }}
      >
        {benchmarkData.map((s, idx) => {
          const isSelected = idx === selectedIndex
          const shortName = s.name.split('(')[0].trim()
          return (
            <button
              key={s.task_id}
              role="tab"
              aria-selected={isSelected}
              onClick={() => setSelectedIndex(idx)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 14px',
                borderRadius: 'var(--radius-pill)',
                fontSize: 12.5,
                fontWeight: isSelected ? 600 : 480,
                background: isSelected ? 'var(--accent)' : 'var(--surface-bg)',
                color: isSelected ? '#ffffff' : 'var(--content-fg-secondary)',
                border: isSelected ? '1px solid var(--accent)' : '1px solid var(--surface-border)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all .16s ease',
              }}
            >
              <span>{idx + 1}. {shortName}</span>
              <span
                style={{
                  fontSize: 10.5,
                  padding: '1px 5px',
                  borderRadius: 4,
                  background: isSelected ? 'rgba(255,255,255,0.2)' : 'var(--surface-secondary)',
                  color: isSelected ? '#ffffff' : 'var(--content-fg-tertiary)',
                }}
              >
                {s.citations_count} 引用
              </span>
            </button>
          )
        })}
      </div>

      {/* 问答对话流模拟卡片（与实际运行效果 100% 保持一致） */}
      <div
        style={{
          background: 'var(--surface-bg)',
          border: '1px solid var(--surface-border)',
          borderRadius: 12,
          padding: '20px 22px',
          boxShadow: '0 2px 14px rgba(0,0,0,0.02)',
        }}
      >
        {/* 顶部天体信息与切换操作 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            borderBottom: '1px solid var(--surface-border-subtle)',
            paddingBottom: 14,
            marginBottom: 18,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 650, color: 'var(--content-fg)' }}>
              {activeSample.name}
            </span>
            <span
              style={{
                fontSize: 11,
                padding: '1px 7px',
                borderRadius: 4,
                background: 'var(--surface-secondary)',
                color: 'var(--content-fg-secondary)',
                fontFamily: 'var(--font-mono, monospace)',
              }}
            >
              耗时 {activeSample.elapsed ? activeSample.elapsed.toFixed(1) : 1.5}s
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onOpenData?.(activeSample.task_id)}
              style={{ fontSize: 12, padding: '4px 10px', height: 28 }}
            >
              <Icon.Database style={{ width: 12, height: 12, marginRight: 4 }} />
              查看数据结果
            </Button>
            <Button
              variant="accent"
              size="sm"
              onClick={() => onOpenSample?.(activeSample.task_id)}
              style={{ fontSize: 12, padding: '4px 12px', height: 28 }}
            >
              进入该天体对话
              <Icon.ArrowRight style={{ width: 12, height: 12, marginLeft: 4 }} />
            </Button>
          </div>
        </div>

        {/* 用户提问气泡 */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
          <div className="msg-bubble" style={{ maxWidth: '82%', fontSize: 13.5 }}>
            {activeSample.query}
          </div>
        </div>

        {/* 智能体回答 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
          <div
            style={{
              width: 30,
              height: 30,
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
            <Icon.Sparkle style={{ width: 16, height: 16 }} />
          </div>

          <div style={{ flex: 1, minWidth: 0, paddingTop: 1 }}>
            {/* ReAct 思考折叠卡 */}
            {activeSample.thought_steps && activeSample.thought_steps.length > 0 && (
              <ReActTraceBlock
                steps={activeSample.thought_steps}
                elapsedSeconds={activeSample.elapsed || 1.5}
                defaultExpanded={false}
              />
            )}

            {/* 回答正文排版（KaTeX 数学公式 + 六维徽章） */}
            <div className="answer-prose" style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--content-fg)' }}>
              {renderContent(activeSample.full_content, activeSample.citations)}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
