import { Button } from '@/components/ui/button'
import { LatexText } from './LatexMath'

export default function KnowledgeDetail({ block, onClose }) {
  if (!block) return null
  const basisLabel =
    block.authoring_basis === 'source_checked'
      ? '来源已核读'
      : block.authoring_basis === 'standard_theory'
      ? '权威标准理论与物理定律'
      : '作者知识整理'

  return (
    <>
      <header className="settings-header">
        <h2 data-detail-heading tabIndex={-1}>
          {block.title || '天体物理理论依据'}
        </h2>
        <Button variant="ghost" onClick={onClose}>
          关闭
        </Button>
      </header>
      <div className="context-content source-reading">
        <p className="hint">
          {basisLabel}
          {block.category && ` · 分类：${block.category}`}
        </p>
        <blockquote className="evidence-text" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.65 }}>
          <LatexText text={block.claim?.text || ''} />
        </blockquote>
        {(block.conditions || []).map((c, i) => (
          <p key={i} className="theory-condition-line">
            <strong>{c.startsWith('适用') ? '' : '适用条件：'}</strong>
            <LatexText text={c} />
          </p>
        ))}
        {(block.sources || []).map((s, i) => (
          <section key={s.source_id || i} className="source-support-item">
            <h3>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.title}
                </a>
              ) : (
                s.title
              )}
            </h3>
            {s.locator && <p className="locator-text">定位出处：{s.locator}</p>}
            {s.support_note && <p className="support-note-text">{s.support_note}</p>}
          </section>
        ))}
      </div>
    </>
  )
}
