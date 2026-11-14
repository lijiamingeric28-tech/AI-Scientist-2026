import SnapshotKnowledgeDetail from './SnapshotKnowledgeDetail'
import React, { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from './LatexMath'
import { createKnowledge, getKnowledgeItem, setKnowledgePreference, updateKnowledge } from '@/services/api'
import { useToast } from '@/components/ui/toast'
import { createSaveGate, loadKnowledgeReportEditor, prepareKnowledgeReportCopy, saveKnowledgeReportDraft, saveKnowledgeReportPreference } from '@/components/knowledge/knowledgeReading'
import KnowledgeEditorModal from '@/components/knowledge/KnowledgeEditorModal'

export default function KnowledgeDetail({ block, onClose, onEditOrFork, onPreferenceChange, onOpenCurrent, referenceScope }) {
  const { toast } = useToast()
  const archived = Boolean(block?.archived)
  const entryId = block?.entry_id || block?.id || block?.title
  const [isPreferred, setIsPreferred] = useState(
    Boolean(block?.preferred || block?.user_preference === 'preferred')
  )
  const [editorOpen, setEditorOpen] = useState(false)
  const [prefLoading, setPrefLoading] = useState(false)
  const [editorData, setEditorData] = useState(null)
  const [editorMode, setEditorMode] = useState('edit')
  const [editorLoading, setEditorLoading] = useState(false)
  const [baseUnavailable, setBaseUnavailable] = useState(false)
  const [actionError, setActionError] = useState('')
  const preferenceGate = useRef(createSaveGate())
  const editorSequence = useRef(0)
  useEffect(() => {
    setIsPreferred(Boolean(block?.preferred || block?.user_preference === 'preferred'))
    setActionError(''); setEditorOpen(false); setEditorLoading(false); setBaseUnavailable(false)
    return () => { editorSequence.current += 1 }
  }, [entryId])
  if (!block) return null
  if (archived) return <SnapshotKnowledgeDetail block={block} scope={referenceScope} onClose={onClose} onOpenCurrent={onOpenCurrent}/>

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
    if (preferenceGate.current.pending) return
    setPrefLoading(true)
    setActionError('')
    try {
      await preferenceGate.current.run(() => saveKnowledgeReportPreference(block, next, { getKnowledgeItem, setKnowledgePreference }, () => {
        setIsPreferred(next)
        onPreferenceChange?.(entryId, next)
        toast(next ? '已设为科研优选' : '已取消科研优选', 'success')
      }))
    } catch (error) {
      setActionError(error.message || '偏好保存失败，请重试')
    } finally {
      setPrefLoading(false)
    }
  }

  const handleEditClick = async () => {
    if (onEditOrFork) {
      try { await onEditOrFork(block) } catch (error) { setActionError(error.message || '无法打开编辑器') }
    } else {
      const sequence = ++editorSequence.current
      setEditorLoading(true); setActionError('')
      try {
        const editor = await loadKnowledgeReportEditor(block, { getKnowledgeItem })
        if (sequence === editorSequence.current) { setEditorData(editor.item); setEditorMode(editor.mode); setBaseUnavailable(false); setEditorOpen(true) }
      } catch (error) { if (sequence === editorSequence.current) { setBaseUnavailable(true); setActionError(`无法读取当前条目：${error.message || '请重试'}。仍可从报告复制为新知识。`) } }
      finally { if (sequence === editorSequence.current) setEditorLoading(false) }
    }
  }
  const handleReportCopy = async () => {
    const sequence = ++editorSequence.current
    setEditorLoading(true); setActionError('')
    try {
      const prepared = await prepareKnowledgeReportCopy(block, { getKnowledgeItem })
      if (sequence === editorSequence.current) { setEditorData(prepared.item); setEditorMode(prepared.mode); setBaseUnavailable(prepared.baseUnavailable); setEditorOpen(true) }
    } catch (error) { if (sequence === editorSequence.current) setActionError(error.message || '无法准备报告内容，请重试') }
    finally { if (sequence === editorSequence.current) setEditorLoading(false) }
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
      {!archived && <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 20px',
          borderBottom: '1px solid var(--surface-border)',
          background: 'var(--surface-secondary)' ,
          flexWrap: 'wrap',
        }}
      >
        <Button
          variant={isPreferred ? 'default' : 'outline'}
          size="sm"
          onClick={handleTogglePreference}
          disabled={prefLoading}
          style={isPreferred ? { background: 'var(--accent-light)', color: 'var(--accent-text)', borderColor: 'var(--accent)' } : {}}
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
          disabled={editorLoading}
        >
          <Icon.Fork style={{ width: 14, height: 14 }} />
          <span>{editorLoading ? '正在读取完整条目…' : '编辑/派生该理论'}</span>
        </Button>
        {!onEditOrFork && <Button variant="ghost" size="sm" disabled={editorLoading} onClick={handleReportCopy}><Icon.Fork style={{ width: 14, height: 14 }} />{baseUnavailable ? '从报告复制为新知识' : '以报告内容派生'}</Button>}
      </div>}
      {archived && <div className="task-archive-meta" style={{padding:'12px 20px'}}>
        <p>任务当时版本 · 归档只读</p>
        {(block.is_override||block.raw_entry?.is_override)&&<p>用户修改的知识背景</p>}
        <p className="hint">{block.origin==='theory_background'||block.claim?.role==='theory_background'?'仅用于一般理论背景':block.claim?.role==='method'?'本资料的方法背景；适用范围以保存条件为准':'输入解释背景；不取得科学采用或换算权限'}</p>
        {(block.revision??block.entry_revision??block.raw_entry?.revision)!=null&&<p>条目版本：{block.revision??block.entry_revision??block.raw_entry?.revision}</p>}
        {(block.release_ref?.version??block.task_context_ref?.library_version)!=null&&<p>知识版本：{block.release_ref?.version??block.task_context_ref?.library_version}</p>}
        {block.content_sha256&&<p>条目内容哈希：{block.content_sha256}</p>}
        {block.release_ref?.content_sha256&&<p>知识发布哈希：{block.release_ref.content_sha256}</p>}
        {block.task_context_ref?.content_sha256&&<p>任务上下文哈希：{block.task_context_ref.content_sha256}</p>}
        <p className="hint">按本任务保存的正文、条件和来源展示；当前知识库可能已有修改。</p>
        {block.entry_id && <Button variant="outline" size="sm" disabled={editorLoading} onClick={async()=>{
          const sequence=++editorSequence.current;setEditorLoading(true);setActionError('')
          try{const item=await getKnowledgeItem(block.entry_id);if(sequence===editorSequence.current)onOpenCurrent?.({...item,entry_id:item.id||block.entry_id,claim:{text:item.description||item.text||item.claim?.text},archived:false})}
          catch(error){if(sequence===editorSequence.current)setActionError(`当前知识库条目不可读：${error.message}。归档依据仍保留。`)}
          finally{if(sequence===editorSequence.current)setEditorLoading(false)}
        }}>{editorLoading?'正在读取当前条目…':'打开当前知识库条目'}</Button>}
      </div>}
      {actionError && <div className="kr-error" role="alert">{actionError}</div>}

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
                  {s.title || s.identity?.title || s.source_id}
                </a>
              ) : (
                s.title || s.identity?.title || s.source_id
              )}
            </h3>
            {s.locator && <p className="locator-text">定位出处：{s.locator}</p>}
            {s.support_note && <p className="support-note-text">{s.support_note}</p>}
            {archived && (s.evidence||[]).map((piece,index)=><blockquote key={piece.evidence_id||index}><LatexText text={piece.excerpt||piece.raw_text}/>{piece.locator&&<p>{typeof piece.locator==='string'?piece.locator:JSON.stringify(piece.locator)}</p>}</blockquote>)}
          </section>
        ))}
      </div>

      {editorOpen && (
        <KnowledgeEditorModal
          isOpen={editorOpen}
          mode={editorMode}
          initialData={editorData}
          onSave={(payload, mode) => saveKnowledgeReportDraft(payload, mode, { createKnowledge, updateKnowledge }, () => {
            toast(mode === 'fork' ? '知识已派生入库' : mode === 'create' ? '报告内容已复制为新知识' : '知识条目已更新', 'success')
          })}
          onClose={() => setEditorOpen(false)}
        />
      )}
    </>
  )
}
