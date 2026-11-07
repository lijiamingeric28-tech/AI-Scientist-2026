import { useState } from 'react'
import { Icon } from '@/components/icons'
import { StatusDot } from '@/components/status'
import { reviewReceipt } from '@/lib/reviewReceipt'
import { ReviewQuestion } from './RuntimeQuestion'
import ReviewReading from './ReviewReading'

const states = {
  pending: '等待判断',
  accepted: '原回答已接收',
  applied: '已应用并复检',
  application_failed: '应用未完成',
  closed_unanswered: '问题已撤回',
  resolved: '审核已处理',
}

function extractReviewTitle(question, idx) {
  if (!question) return `审核项 ${idx + 1}`
  // Extract property or concise core question snippet
  if (question.includes('E(B-V)') || question.includes('消光') || question.includes('红化')) return '视线消光 E(B−V) 尘埃模型'
  if (question.includes('Na I D') || question.includes('等值宽度') || question.includes('吸收线')) return 'Na I D 吸收线等值宽度'
  if (question.includes('峰值') || question.includes('星等')) return '光变曲线峰值星等'
  if (question.includes('距离') || question.includes('模数')) return '距离模数与视差基准'
  if (question.includes('金属丰度') || question.includes('[Fe/H]')) return '金属丰度 [Fe/H] 标定'
  if (question.includes('质量') || question.includes('半径')) return '天体物理质量与几何半径'
  // Fallback to first clause
  const firstSentence = question.split(/[，。？！\n]/)[0]
  return firstSentence.length > 24 ? firstSentence.slice(0, 24) + '…' : firstSentence
}

export default function AggregatedReviewCard({
  reviews = [],
  taskId,
  readOnly,
  gate,
  onSubmit,
  onReplaySubmit,
  receipts = [],
}) {
  const pendingReviews = reviews.filter((r) => r.status === 'pending')
  const hasPending = pendingReviews.length > 0
  const [open, setOpen] = useState(hasPending)
  const [inspectId, setInspectId] = useState(null)
  const [sendingId, setSendingId] = useState(null)
  const [error, setError] = useState('')

  if (!reviews.length) return null

  const submitSingle = async (review, value) => {
    if (sendingId) return
    setSendingId(review.review_id)
    setError('')
    try {
      const locked =
        readOnly &&
        gate?.available &&
        gate.review_id === review.review_id &&
        gate.review_revision === review.revision &&
        gate.basis_hash === review.basis_hash
      if (locked) onReplaySubmit?.(value)
      else await onSubmit?.({ ...value, review_id: review.review_id })
    } catch (e) {
      setError(e.message)
    } finally {
      setSendingId(null)
    }
  }

  return (
    <section
      data-component="aggregated-review-card"
      className="stage-card aggregated-review-card"
      data-state={hasPending ? 'waiting' : 'completed'}
      style={{
        background: 'var(--surface-bg)',
        border: hasPending
          ? '1.5px solid var(--status-waiting)'
          : '1px solid var(--surface-border)',
        borderRadius: 14,
        overflow: 'hidden',
        marginBottom: 16,
        transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
      }}
    >
      {/* 头部：单行摘要胶囊 */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={(e) => {
          const sel = window.getSelection()
          if (sel && sel.toString().trim().length > 0) return
          setOpen(!open)
        }}
        onKeyDown={(e) => {
          if (['Enter', ' '].includes(e.key)) {
            e.preventDefault()
            setOpen(!open)
          }
        }}
        className="card-header-clickable chat-stage-head"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 18px',
          cursor: 'pointer',
          background: hasPending
            ? 'var(--status-waiting-bg, #fffbf0)'
            : 'linear-gradient(to right, color-mix(in srgb, var(--accent) 5%, transparent), transparent)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          {hasPending ? (
            <StatusDot status="waiting" size={8} />
          ) : (
            <Icon.Check className="stage-check" aria-hidden="true" />
          )}
          <strong style={{ fontSize: 'var(--text-section)', fontWeight: 600, color: 'var(--title-strong, #44785b)' }}>
            人机协同审核 (HITL)
          </strong>
          <span
            className="font-mono"
            style={{
              fontSize: 11.5,
              color: 'var(--content-fg-tertiary)',
              background: 'var(--surface-secondary)',
              padding: '1.5px 7px',
              borderRadius: 4,
              flexShrink: 0,
            }}
          >
            {hasPending ? `${pendingReviews.length} 项待决断` : `${reviews.length} 项审核已决断`}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          <span
            className="stage-summary-pill"
            style={{
              fontSize: 12.5,
              padding: '4px 12px',
              borderRadius: 999,
              background: hasPending ? 'var(--status-waiting-bg, #fef7ed)' : 'var(--accent-light, #eff5f0)',
              color: hasPending ? 'var(--status-waiting, #c67d16)' : 'var(--accent-text, #345844)',
              border: `1px solid ${hasPending ? 'rgba(198,125,22,0.3)' : 'rgba(68,120,91,0.22)'}`,
              fontWeight: 550,
            }}
          >
            {hasPending
              ? `需要你的判断 · ${pendingReviews.length} 项待处理`
              : `${reviews.length} 项文献分歧已决断 · 全数通过`}
          </span>
          <Icon.ChevronDown
            className="chat-chevron"
            style={{
              transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
              transition: 'transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
            }}
            aria-hidden="true"
          />
        </div>
      </div>

      {/* 展开内容区：结构化审核矩阵 */}
      <div
        aria-hidden={!open}
        className={`smooth-collapse${open ? ' expanded' : ''}`}
      >
        <div className="collapse-clip">
          <div
            className="chat-stage-body"
            style={{
              padding: '16px 20px 20px',
              borderTop: '1px solid var(--surface-border-subtle)',
              background: 'var(--surface-secondary, #fafcfb)',
            }}
          >
          {error && (
            <div role="alert" style={{ color: 'var(--status-error)', marginBottom: 12, fontSize: 13 }}>
              {error}
            </div>
          )}

          <p style={{ fontSize: 12.5, color: 'var(--content-fg-secondary)', marginBottom: 12 }}>
            为确保科学研究严谨性，智能体在多源数据对照时将分歧提交专家协同判定，以下为本次任务审核决断记录：
          </p>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
              gap: 12,
            }}
          >
            {reviews.map((r, idx) => {
              const isPending = r.status === 'pending'
              const receipt = receipts.find((x) => x.review_id === r.review_id)?.receipt
              const rc = reviewReceipt(r)
              const actionOutcome = rc?.outcome || rc?.answer || states[r.status] || '已决断'
              const title = extractReviewTitle(r.question, idx)
              const isInspecting = inspectId === r.review_id

              const locked =
                readOnly &&
                gate?.available &&
                gate.review_id === r.review_id &&
                gate.review_revision === r.revision &&
                gate.basis_hash === r.basis_hash
              const simulation =
                gate?.answer?.simulation ||
                gate?.answer?.actor === 'simulated_test_operator' ||
                r.answer?.simulation ||
                r.answer?.actor === 'simulated_test_operator'

              const evidence = r.evidence_bundle || r.evidence || []
              const prepared = {
                ...r,
                task_id: taskId,
                evidence_bundle: evidence,
                evidence_refs: r.evidence_refs || evidence.map((e) => ({ id: e.evidence_id })),
                correction_types: r.correction_types || [],
                allowed_actions: r.allowed_actions || (r.choices || []).map((c) => c.action),
              }

              return (
                <div
                  key={r.review_id || idx}
                  data-review-id={r.review_id}
                  style={{
                    background: '#ffffff',
                    border: `1px solid ${isPending ? 'var(--status-waiting)' : 'var(--surface-border)'}`,
                    borderRadius: 10,
                    padding: '12px 14px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    boxShadow: '0 1px 4px rgba(0,0,0,0.02)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', flexShrink: 0 }}>
                        #{idx + 1}
                      </span>
                      <strong
                        style={{
                          fontSize: 13.5,
                          fontWeight: 600,
                          color: 'var(--content-fg)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                        title={title}
                      >
                        {title}
                      </strong>
                    </div>

                    <span
                      style={{
                        fontSize: 11.5,
                        padding: '2px 8px',
                        borderRadius: 4,
                        background: isPending ? 'var(--status-waiting-bg, #fef7ed)' : 'var(--accent-light, #eff5f0)',
                        color: isPending ? 'var(--status-waiting, #c67d16)' : 'var(--accent-text, #345844)',
                        fontWeight: 550,
                        flexShrink: 0,
                      }}
                    >
                      {actionOutcome}
                    </span>
                  </div>

                  <p
                    style={{
                      fontSize: 12,
                      color: 'var(--content-fg-secondary)',
                      lineHeight: 1.55,
                      margin: 0,
                      display: '-webkit-box',
                      WebkitLineClamp: isInspecting ? 100 : 2,
                      WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }}
                  >
                    {r.question}
                  </p>

                  {r.answer?.reason && (
                    <div
                      style={{
                        fontSize: 11.5,
                        color: 'var(--content-fg)',
                        background: 'var(--surface-secondary)',
                        padding: '6px 10px',
                        borderRadius: 6,
                        borderLeft: '2px solid var(--accent)',
                      }}
                    >
                      <strong>裁决理由：</strong>
                      {r.answer.reason}
                    </div>
                  )}

                  {/* 运行时若处于待回答状态，则直接内嵌回答组件 */}
                  {isPending && (!readOnly || locked) && (
                    <div style={{ marginTop: 8 }}>
                      <ReviewQuestion
                        review={prepared}
                        disabled={sendingId === r.review_id}
                        simulation={simulation}
                        replayGate={locked ? gate : null}
                        onSubmit={(val) => submitSingle(r, val)}
                      />
                    </div>
                  )}

                  {/* 查看原件/依据切换按钮 */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => setInspectId(isInspecting ? null : r.review_id)}
                      style={{ fontSize: 11.5 }}
                    >
                      {isInspecting ? '收起文献依据与原页' : '查看文献依据与原页'}
                    </button>
                    {receipt && (
                      <span style={{ fontSize: 11, color: 'var(--status-success)' }}>
                        {receipt.postcheck === 'passed' ? '复检已通过' : '已复核'}
                      </span>
                    )}
                  </div>

                  {isInspecting && (
                    <div style={{ marginTop: 8, borderTop: '1px solid var(--surface-border-subtle)', paddingTop: 8 }}>
                      <ReviewReading review={prepared} taskId={taskId} hideTitle={true} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  </section>
  )
}
