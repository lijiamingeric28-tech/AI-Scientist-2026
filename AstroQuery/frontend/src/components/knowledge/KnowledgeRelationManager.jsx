import React, { useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import KnowledgeLinkPicker from './KnowledgeLinkPicker'
import { createSaveGate } from './knowledgeReading'
import { useReadingFocus } from './knowledgeReadingParts'
import { buildRelationPayload, createRelationDraft, incomingKnowledgeRelations, rebaseRelationDraft, relationDraftChanged, relationMutationResult } from './knowledgeRelationManagement'
import './knowledgeReading.css'
import './knowledgeLinks.css'

export default function KnowledgeRelationManager({ item, categories = [], readOnly = false, connecting = false, onSave, onClose, onReloadLatest, onReconnect }) {
  const [base, setBase] = useState(item)
  const [draft, setDraft] = useState(() => createRelationDraft(item))
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [conflict, setConflict] = useState(false), [latest, setLatest] = useState(null)
  const [reloading, setReloading] = useState(false), [discard, setDiscard] = useState(false)
  const [notice, setNotice] = useState('')
  const panel = useRef(null), confirmation = useRef(null), gate = useRef(createSaveGate())
  const dirty = relationDraftChanged(base, draft), locked = busy || readOnly || reloading
  const requestClose = () => { if (gate.current.pending || reloading) return; if (dirty) setDiscard(true); else onClose?.() }
  useReadingFocus(panel, true, requestClose, true)
  useReadingFocus(confirmation, discard, () => setDiscard(false), true)
  const incoming = incomingKnowledgeRelations(base)
  const toggleIncoming = id => setDraft(current => ({ ...current, unlinkIncomingIds: current.unlinkIncomingIds.includes(id)
    ? current.unlinkIncomingIds.filter(value => value !== id) : [...current.unlinkIncomingIds, id] }))
  const save = async event => {
    event.preventDefault()
    if (locked || conflict || !dirty || gate.current.pending) return
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = buildRelationPayload(base, draft)
      await gate.current.run(async () => {
        if (!onSave) throw new Error('关联保存服务不可用')
        relationMutationResult(await onSave(base.id, payload), base.id)
        onClose?.()
      })
    } catch (failure) {
      setError(failure.status === 409 ? '知识库已有更新，关联修改尚未保存。请读取最新关联后核对。' : failure.message || '关联保存失败，请重试')
      if (failure.status === 409) { setConflict(true); setLatest(null) }
    } finally { setBusy(false) }
  }
  const reloadLatest = async () => {
    if (reloading || busy) return
    setReloading(true); setError('')
    try {
      if (!onReloadLatest) throw new Error('无法读取最新关联，请重新连接知识库')
      const result = await onReloadLatest(base.id)
      rebaseRelationDraft(base, draft, result)
      setLatest(result)
    } catch (failure) { setError(failure.message || '读取失败，请重试') }
    finally { setReloading(false) }
  }
  const acceptLatest = () => {
    try {
      setDraft(rebaseRelationDraft(base, draft, latest)); setBase(latest); setConflict(false); setLatest(null); setError('')
      setNotice('已合并最新关联并保留你的增删，核对后可保存。')
    } catch (failure) { setError(failure.message) }
  }
  const titles = entry => (entry.relations?.related || []).map(relation => relation.title || relation.id).join('、') || '暂无关联'
  return <div className="kr-editor-backdrop kr-link-manager-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) requestClose() }}>
    <section className="kr-editor kr-link-manager" ref={panel} role="dialog" aria-modal="true" aria-labelledby="kr-relations-title" tabIndex={-1} aria-busy={busy || reloading}>
      <div className="kr-link-manager-surface" inert={discard ? '' : undefined} aria-hidden={discard ? true : undefined}>
        <header className="kr-editor-header"><div><span className="kr-eyebrow">知识工作台</span><h3 id="kr-relations-title"><Icon.Link />管理知识关联</h3></div><button type="button" className="kr-icon-button" aria-label="关闭关联管理" disabled={busy || reloading} onClick={requestClose}><Icon.Close /></button></header>
        <div className="kr-link-context"><strong>{base.title || base.name || base.id}</strong><p>搜索添加知识关联，或移除已建立的绑定。修改将在保存后统一生效。</p>{!base.is_user && <small>内置知识的关联修改保存在用户版本中。</small>}</div>
        {readOnly && !connecting && <div className="kr-editor-notice" role="status">当前为只读状态，关联草稿已保留。<button type="button" className="kr-button" disabled={busy} onClick={onReconnect}>重新连接知识库</button></div>}
        <form className="kr-editor-form" onSubmit={save}>
          <div className="kr-link-manager-body">
            {error && <div className="kr-error" role="alert">{error}<span>当前选择已保留。</span></div>}
            {notice && <p className="kr-link-success" role="status"><Icon.Check />{notice}</p>}
            {conflict && <section className="kr-link-conflict" aria-label="关联冲突恢复"><strong>核对最新关联</strong><p>保留当前增删，并合并其他新增的关联后再保存。</p><button type="button" className="kr-button" disabled={busy || reloading} onClick={reloadLatest}>{reloading ? '正在读取…' : latest ? '重新读取最新关联' : '读取最新关联'}</button>{latest && <><dl><div><dt>最新关联</dt><dd>{titles(latest)}</dd></div><div><dt>待保存的修改</dt><dd>本条目关联 {draft.relatedIds.length} 项，解除传入关联 {draft.unlinkIncomingIds.length} 项。</dd></div></dl><button type="button" className="kr-button kr-button-accent" disabled={locked} onClick={acceptLatest}>保留修改并合并最新关联</button></>}</section>}
            <section aria-labelledby="kr-outgoing-title"><h4 id="kr-outgoing-title">本条目关联的知识</h4><KnowledgeLinkPicker value={draft.relatedIds} summaries={[...(base.relations?.related || []), ...(latest?.relations?.related || [])]} categories={categories} excludeId={base.id} disabled={locked} onChange={relatedIds => setDraft(current => ({ ...current, relatedIds }))} /></section>
            <section className="kr-incoming-section" aria-labelledby="kr-incoming-title"><h4 id="kr-incoming-title">关联到本条目的知识 <span>{incoming.length}</span></h4><p className="kr-link-hint">这些知识建立了指向本条目的关联。解除后会同步更新对应知识；双向关系的另一方向可在上方移除。</p>
              {incoming.length ? <ul className="kr-incoming-list">{incoming.map(relation => {
                const removed = draft.unlinkIncomingIds.includes(relation.id)
                return <li key={relation.id} className={removed ? 'is-removed' : undefined}><span><strong>{relation.title || relation.id}</strong><small>{removed ? '待解除 · 保存后生效' : relation.direction === 'both' ? '双向关联' : '由该知识关联到本条目'}</small></span><button type="button" className="kr-button" aria-label={`${removed ? '撤销解除' : '解除传入关联'}：${relation.title || relation.id}`} disabled={locked} onClick={() => toggleIncoming(relation.id)}>{removed ? <Icon.History /> : <Icon.Close />}{removed ? '撤销解除' : '解除绑定'}</button></li>
              })}</ul> : <p className="kr-missing">暂无其他知识关联到本条目</p>}
            </section>
          </div>
          <footer className="kr-editor-footer"><span className="kr-muted">{busy ? '正在保存关联…' : dirty ? '有未保存的关联修改' : '详情与知识图谱同步更新'}</span><div><button className="kr-button" type="button" disabled={busy || reloading} onClick={requestClose}>取消</button><button className="kr-button kr-button-accent" type="submit" disabled={locked || conflict || !dirty}><Icon.Check />{busy ? '正在保存…' : '保存关联'}</button></div></footer>
        </form>
      </div>
      {discard && <div className="kr-discard-backdrop"><div className="kr-confirm" ref={confirmation} role="alertdialog" aria-modal="true" aria-labelledby="kr-discard-relations" tabIndex={-1}><h3 id="kr-discard-relations">放弃未保存的关联修改？</h3><p>已保存的知识关联会保留。</p><div className="kr-confirm-actions"><button type="button" className="kr-button" data-initial-focus onClick={() => setDiscard(false)}>继续编辑</button><button type="button" className="kr-button kr-danger-button" onClick={onClose}>放弃修改</button></div></div></div>}
    </section>
  </div>
}
