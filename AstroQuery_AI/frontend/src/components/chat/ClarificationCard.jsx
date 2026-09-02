import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { cleanCliQuestion } from '@/lib/format'
import HumanReviewPanel from './HumanReviewPanel'

/* HITL 澄清卡（结构化渲染版）
 *
 * 不再原样显示后端终端文本（分隔符/框线/"您的选择："），改为按 type 渲染
 * 结构化 UI。后端 interrupt 原始 question 文本保留在 payload，点击"详情"可回溯。
 *
 * 结构化字段（mock 先行，API 契约阶段与后端对齐）：
 *   ask_properties     → title + description + [全部] + 输入框
 *   final_confirm      → title + fields[{label, value}] + [确认/修改/取消]
 *   final_confirm_modify → title + description + 输入框
 *   ask_entity         → title + description + 输入框
 */

export default function ClarificationCard({ payload, onSubmit }) {
  const [text, setText] = useState('')
  const [showRaw, setShowRaw] = useState(false)

  const submit = async (value) => {
    try {
      await onSubmit(value === undefined ? text : value)
      setText('')
    } catch {
      // H-18: resume 失败已由 usePipeline 恢复 pending 并写入 payload.error，
      // 卡内红字提示；保留输入内容允许直接重发
    }
  }

  const isConfirm = payload.type === 'final_confirm'
  const isBatch = payload.type === 'human_review_batch'

  return (
    <div
      style={{
        marginLeft: 38,
        background: 'var(--surface-bg)',
        border: '1px solid var(--status-progress)',
        borderRadius: 8,
        overflow: 'hidden',
        boxShadow: '0 2px 8px rgba(0,0,0,0.05)',
      }}
    >
      {/* 头部 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '9px 14px',
          background: 'var(--status-progress-bg)',
          fontSize: 13,
          fontWeight: 510,
          color: 'var(--status-progress)',
        }}
      >
        <span className="animate-pulse-dot">●</span>
        <span style={{ flex: 1 }}>{payload.title || '澄清请求'}</span>
        {payload.question && (
          <button
            onClick={() => setShowRaw(!showRaw)}
            style={{
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              fontSize: 11,
              color: 'var(--content-fg-tertiary)',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            {showRaw ? '隐藏原文' : '原文'}
            <Icon.ChevronDown style={{ width: 10, height: 10, transform: showRaw ? 'rotate(0)' : 'rotate(-90deg)' }} />
          </button>
        )}
      </div>

      <div style={{ padding: '12px 14px 14px' }}>
        {/* M-09 无效输入重发提示 */}
        {payload.error && (
          <div
            style={{
              marginBottom: 12,
              padding: '8px 12px',
              background: 'var(--status-error-bg)',
              border: '1px solid var(--status-error)',
              borderRadius: 6,
              fontSize: 12,
              color: 'var(--status-error)',
            }}
          >
            {payload.error}
          </div>
        )}

        {/* 2026-09-02: 人工审核批量面板（忠实于冲突数据的 markdown + 逐项 1-5 选项卡 + 可选理由） */}
        {isBatch ? (
          <HumanReviewPanel payload={payload} onSubmit={submit} />
        ) : (
          <>
        {/* final_confirm：结构化字段；human_review 系列 fields（历史任务重放）也可渲染——
            2026-09-02 fix：原 isConfirm gate 挡住 human_review_verdict 的冲突字段 */}
        {payload.fields && payload.fields.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            {payload.fields.map((f) => (
              <div key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ width: 64, flexShrink: 0, fontSize: 12, color: 'var(--content-fg-tertiary)', fontWeight: 510 }}>
                  {f.label}
                </span>
                <span
                  style={{
                    flex: 1,
                    fontSize: 13,
                    color: 'var(--content-fg)',
                    fontWeight: 510,
                    padding: '6px 10px',
                    background: 'var(--surface-secondary)',
                    borderRadius: 6,
                  }}
                >
                  {f.value}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 描述文本（P1-7：pre-wrap 整段改为分段段落，不再整块原始平铺） */}
        {payload.description && !isConfirm && (
          <div style={{ fontSize: 13, color: 'var(--content-fg)', lineHeight: 1.7, marginBottom: 12 }}>
            {String(payload.description).split(/\n+/).filter(Boolean).map((para, i) => (
              <p key={i} style={{ margin: '0 0 6px' }}>{para}</p>
            ))}
          </div>
        )}

        {/* 快捷按钮 */}
        {payload.quickButtons && payload.quickButtons.length > 0 && (
          <div style={{ display: 'flex', gap: 8, marginBottom: isConfirm ? 0 : 12, flexWrap: 'wrap' }}>
            {payload.quickButtons.map((b) => (
              <Button
                key={b.value}
                variant="outline"
                size="sm"
                onClick={() => submit(b.value)}
                style={{ color: 'var(--accent-text)', borderColor: 'var(--accent-light)' }}
              >
                {b.label}
              </Button>
            ))}
          </div>
        )}

        {/* 输入框（final_confirm 只需按钮） */}
        {!isConfirm && (
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
              placeholder={payload.type === 'final_confirm_modify' ? '输入新的查询…' : '输入答案…（回车发送）'}
              style={{
                flex: 1,
                padding: '7px 10px',
                fontSize: 13,
                border: '1px solid var(--surface-border)',
                borderRadius: 6,
                outline: 'none',
                background: 'var(--surface-secondary)',
                color: 'var(--content-fg)',
              }}
            />
            <Button variant="accent" size="icon" onClick={() => submit()}>
              <Icon.Send />
            </Button>
          </div>
        )}
          </>
        )}

        {/* 后端原文（可回溯；P1-7：套引用块样式，不再裸 pre-wrap 平铺） */}
        {showRaw && payload.question && (
          <div
            style={{
              marginTop: 12,
              padding: '8px 12px',
              background: 'var(--surface-secondary)',
              borderRadius: 6,
              fontSize: 11,
              color: 'var(--content-fg-tertiary)',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.6,
              maxHeight: 160,
              overflowY: 'auto',
              borderLeft: '3px solid var(--accent-light)',
            }}
          >
            {cleanCliQuestion(payload.question)}
          </div>
        )}
      </div>
    </div>
  )
}
