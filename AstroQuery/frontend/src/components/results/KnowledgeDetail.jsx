import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from './LatexMath'
import { setKnowledgePreference } from '@/services/api'
import KnowledgeEditorModal from '@/components/knowledge/KnowledgeEditorModal'

export default function KnowledgeDetail({ block, onClose, onEditOrFork, onPreferenceChange }) {
  if (!block) return null

  const entryId = block.id || block.entry_id || block.title
  const [isPreferred, setIsPreferred] = useState(
    Boolean(block.preferred || block.user_preference === 'preferred')
  )
  const [editorOpen, setEditorOpen] = useState(false)
  const [prefLoading, setPrefLoading] = useState(false)

  const text = block.claim?.text || block.claim?.statement || block.description || block.text
  const formulas = [block.formula, block.claim?.formula, ...(block.formulas || [])].filter(Boolean)
  const basisLabel =
    block.authoring_basis === 'source_checked'
      ? '来源已核读'
      : block.authoring_basis === 'standard_theory'
      ? '权威标准理论与物理定律'
      : '作者知识整理'

  const handleTogglePreference = async () => {
    const next = !isPreferred
    setIsPreferred(next)
    setPrefLoading(true)
    try {
      if (entryId) {
        await setKnowledgePreference(entryId, next ? 'preferred' : 'neutral', next ? 1.5 : 1.0)
      }
      onPreferenceChange?.(entryId, next)
    } catch (e) {
      // Optimistic update retained
    } finally {
      setPrefLoading(false)
    }
  }

  const handleEditClick = () => {
    if (onEditOrFork) {
      onEditOrFork(block)
    } else {
      setEditorOpen(true)
    }
  }

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

      {/* In-situ 理论操作按钮组 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 20px',
          borderBottom: '1px solid var(--surface-border)',
          background: 'var(--surface-secondary, rgba(255,255,255,0.02))',
          flexWrap: 'wrap',
        }}
      >
        <Button
          variant={isPreferred ? 'default' : 'outline'}
          size="sm"
          onClick={handleTogglePreference}
          disabled={prefLoading}
          style={isPreferred ? { background: '#eab308', color: '#000', borderColor: '#eab308' } : {}}
        >
          {isPreferred ? (
            <Icon.StarFilled style={{ width: 14, height: 14 }} />
          ) : (
            <Icon.Star style={{ width: 14, height: 14 }} />
          )}
          <span>{isPreferred ? '已设为科研优选' : '设为科研优选'}</span>
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={handleEditClick}
        >
          <Icon.Fork style={{ width: 14, height: 14 }} />
          <span>编辑/派生该理论</span>
        </Button>
      </div>

      <div className="context-content source-reading">
        <p className="hint">
          {basisLabel}
          {block.category && ` · 分类：${block.category}`}
          {isPreferred && ' · 优先参考'}
        </p>

        {text && (
          <blockquote className="evidence-text" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.65 }}>
            <LatexText text={text} />
          </blockquote>
        )}

        {formulas.map((formula, i) => (
          <LatexMath
            key={i}
            math={typeof formula === 'string' ? formula : formula.latex}
            displayMode
          />
        ))}

        {(block.conditions || []).map((c, i) => (
          <p key={i} className="theory-condition-line">
            <LatexText text={typeof c === 'string' ? c : c.text || c.description} />
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

      {editorOpen && (
        <KnowledgeEditorModal
          isOpen={editorOpen}
          mode="fork"
          initialData={block}
          onSave={() => setEditorOpen(false)}
          onClose={() => setEditorOpen(false)}
        />
      )}
    </>
  )
}
