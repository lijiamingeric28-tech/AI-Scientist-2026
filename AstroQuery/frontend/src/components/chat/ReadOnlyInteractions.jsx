import { artifactUrl } from '@/services/api'
import { Icon } from '@/components/icons'

export default function ReadOnlyInteractions({ presentation, taskId, stageId }) {
  const p = presentation
  if (!p || (stageId === 'understand' ? !p.draft_question : !(p.reviews || []).length)) return null

  return (
    <section className="readonly-interactions" aria-label="人机协同确认记录">
      {stageId === 'understand' && p.draft_question && (
        <div className="historical-confirmation-card">
          <div className="historical-confirm-header">
            <div className="historical-confirm-title">
              <span className="section-indicator-bar" />
              <span>{p.draft_question.kind === 'target_selection' ? '人机协同 · 天体身份确认' : '人机协同 · 查询范围核定'}</span>
            </div>
            <span className="historical-confirm-badge">
              <Icon.Check style={{ width: 11, height: 11 }} />
              <span>已核定范围</span>
            </span>
          </div>

          {p.target?.main_id && (
            <div className="confirm-target-row">
              <span className="confirm-target-label">核定目标天体</span>
              <span className="confirm-target-value font-mono">{p.target.main_id}</span>
            </div>
          )}

          {(p.request?.requests || []).length > 0 && (
            <div className="confirm-mapping-list">
              <div className="confirm-sub-label">提问意图与标准物理性质对应</div>
              {(p.request?.requests || []).map((r, i) => {
                const ids = r.candidate_property_ids || []
                const names = (p.draft_question.options || []).filter((o) => ids.includes(o.id)).map((o) => o.name)
                if (!names.length) return null
                return (
                  <div key={i} className="confirm-mapping-item">
                    <span className="confirm-intent-chip">{r.text}</span>
                    <span className="confirm-mapping-arrow">→</span>
                    <div className="confirm-property-tags">
                      {names.map((name) => (
                        <span key={name} className="confirm-prop-tag font-mono">
                          {name}
                        </span>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {!!p.properties?.length && (
            <div className="confirm-selected-box">
              <div className="confirm-selected-header">
                <Icon.Check style={{ width: 13, height: 13, color: 'var(--seed-accent)' }} />
                <span>执行时选定进入流水线的标准性质（{p.properties.length} 项）</span>
              </div>
              <div className="confirm-selected-pills">
                {p.properties.map((x) => (
                  <span key={x.property_id || x.name} className="confirm-selected-pill font-mono">
                    {x.name}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {stageId === 'quality_check' &&
        (p.reviews || []).map((r) => (
          <details key={r.review_id} open={p.active_stage === 'quality_check' && !p.terminal_at} className="legacy-review-details">
            <summary>
              {r.question}{' '}
              <span>
                {r.status === 'closed_unanswered'
                  ? '已关闭'
                  : r.status === 'applied'
                    ? '已覆核'
                    : r.answer
                      ? '原回答'
                      : '历史未覆核'}
              </span>
            </summary>
            <p>{r.impact}</p>
            {r.answer ? (
              <>
                <p>
                  原回答：
                  {r.choices?.find((c) => c.action === r.answer.action)?.label || r.answer.action}
                  {r.answer.simulation ? ' · 模拟' : ''}
                </p>
                <p>{r.answer.reason}</p>
                <p>{p.review_receipts?.some((x) => x.review_id === r.review_id) ? '已覆核' : '当时正在覆核'}</p>
              </>
            ) : (
              <p>{r.status === 'closed_unanswered' ? '已关闭，无原回答' : '当时未回答'}</p>
            )}
            <details>
              <summary>原著证据</summary>
              {(r.evidence || []).map((e) => (
                <div key={e.evidence_id}>
                  <blockquote className="evidence-text">{e.raw_text}</blockquote>
                  <a
                    href={`${artifactUrl(taskId, e.artifact_ref.id)}${e.locator?.page ? `#page=${e.locator.page}` : ''}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    查阅原文{e.locator?.page ? `第 ${e.locator.page} 页` : ''}
                  </a>
                </div>
              ))}
            </details>
          </details>
        ))}
    </section>
  )
}
