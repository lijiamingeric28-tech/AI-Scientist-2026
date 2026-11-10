import React, { useState } from 'react'
import { Icon } from '@/components/icons'

/* ReAct 思考与工具调用轨迹折叠卡片 (ReActTraceBlock 2.0)
 * - 纯矢量单线图标示意，杜绝 Emoji
 * - 精确复刻国风绿色科研风格与轻量边框
 */

export default function ReActTraceBlock({ steps = [], elapsedSeconds = 1.62, defaultExpanded = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  if (!steps || steps.length === 0) return null

  // 聚合步骤统计
  const stepCount = steps.filter((s) => s.type === 'action').length || steps.length

  return (
    <div
      className="react-trace-card"
      style={{
        marginBottom: 14,
        borderRadius: 8,
        border: '1px solid var(--surface-border)',
        overflow: 'hidden',
        background: 'var(--surface-bg)',
      }}
    >
      <div
        className={`react-trace-header ${expanded ? 'expanded' : ''}`}
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '9px 14px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          userSelect: 'none',
          background: 'color-mix(in srgb, var(--seed-accent) 4%, transparent)',
          borderBottom: expanded ? '1px solid var(--surface-border-subtle)' : '1px solid transparent',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, fontWeight: 600, color: 'var(--title-section, var(--content-fg))' }}>
          <Icon.Check style={{ width: 12, height: 12, color: 'var(--accent)' }} />
          <span>ReAct 思考与工具调用轨迹 (Thought / Action / Observation)</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            className="react-trace-pill"
            style={{
              fontSize: 11,
              padding: '2px 9px',
              borderRadius: 'var(--radius-pill)',
              background: 'var(--status-success-bg, rgba(46, 125, 50, 0.1))',
              color: 'var(--status-success, #2e7d32)',
              fontWeight: 500,
            }}
          >
            {stepCount} 步执行 · 耗时 {elapsedSeconds}s · 100% 真实缓存
          </span>
          <span style={{ fontSize: 11, color: 'var(--content-fg-tertiary)', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            <span>{expanded ? '收起明细' : '展开明细'}</span>
            {expanded ? <Icon.ChevronDown style={{ width: 10, height: 10 }} /> : <Icon.ChevronRight style={{ width: 10, height: 10 }} />}
          </span>
        </div>
      </div>

      {expanded && (
        <div
          className="react-trace-body show"
          style={{ padding: '12px 14px', fontSize: 12, lineHeight: 1.6, background: 'var(--surface-bg)' }}
        >
          {steps.map((st, idx) => {
            const isThought = st.type === 'thought'
            const isAction = st.type === 'action'
            const isObs = st.type === 'observation'

            return (
              <div
                key={idx}
                className="trace-step"
                style={{
                  padding: '8px 10px',
                  borderRadius: 6,
                  background: 'var(--surface-secondary)',
                  marginBottom: idx === steps.length - 1 ? 0 : 8,
                  borderLeft: isAction ? '3px solid var(--accent)' : isObs ? '3px solid var(--chart-blue, #4a6cf7)' : '3px solid var(--surface-border)',
                }}
              >
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10.5,
                    fontWeight: 600,
                    marginBottom: 3,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    color: isAction ? 'var(--accent)' : isObs ? 'var(--chart-blue, #4a6cf7)' : 'var(--content-fg-secondary)',
                  }}
                >
                  {isThought && <span>THOUGHT {st.step || idx + 1}</span>}
                  {isAction && <span>ACTION: {st.tool}</span>}
                  {isObs && <span>OBSERVATION</span>}
                </div>
                <div style={{ color: 'var(--content-fg)', wordBreak: 'break-all', fontSize: 12 }}>
                  {isAction && (
                    <code style={{ fontFamily: "'JetBrains Mono', monospace", color: 'var(--content-fg-secondary)' }}>
                      {JSON.stringify(st.args || {})}
                    </code>
                  )}
                  {isObs && (
                    <pre
                      style={{
                        margin: 0,
                        whiteSpace: 'pre-wrap',
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: 11,
                        color: 'var(--content-fg)',
                        maxHeight: 180,
                        overflowY: 'auto',
                      }}
                    >
                      {typeof st.result === 'string' ? st.result : JSON.stringify(st.result, null, 2)}
                    </pre>
                  )}
                  {isThought && <div>{st.content || st.thought}</div>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
