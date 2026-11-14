import React, { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { createKnowledgeCategory, createSaveGate } from './knowledgeReading'
import { useReadingFocus } from './knowledgeReadingParts'
import { moveCategoryId, normalizeCategoryColor, rebaseCategoryDraft } from '@/lib/knowledgeCategories'
import './knowledgeCategories.css'

const PALETTE = [
  ['森林绿','#24583b'], ['翡翠绿','#10b981'], ['湖蓝','#06b6d4'], ['学术蓝','#3b82f6'],
  ['紫罗兰','#8b5cf6'], ['琥珀','#f59e0b'], ['玫红','#e05278'], ['石墨灰','#64748b'],
]
const validColor = value => /^#[0-9a-f]{6}$/i.test(value || '')

export default function KnowledgeCategoryManager({ categories = [], catalogRevision, readOnly = false, loading = false, loadError,
  onCreate, onRename, onUpdate, onReorder, onDelete, onReload, onClose }) {
  const [newName, setNewName] = useState('')
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [color, setColor] = useState('#24583b')
  const [query, setQuery] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [target, setTarget] = useState('user_private')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [discard, setDiscard] = useState(null)
  const [orderView, setOrderView] = useState(null)
  const [draggingId, setDraggingId] = useState(null)
  const drag = useRef(null), dragCleanup = useRef(null), orderAck = useRef(null)
  const gate = useRef(createSaveGate()), ref = useRef(null), discardRef = useRef(null)
  const createInput = useRef(null), renameInput = useRef(null), targetSelect = useRef(null)
  const latest = categories.find(category => category.id === editing?.id)
  const changedExternally = !loading && editing && (!latest || (latest.revision ?? 0) !== (editing.revision ?? 0))
  const renameDirty = Boolean(editing?.is_custom && name.trim() !== editing.label)
  const colorDirty = Boolean(editing && color.toLowerCase() !== editing.color?.toLowerCase())
  const settingsDirty = renameDirty || colorDirty
  const locked = busy || readOnly || loading
  const requestClose = () => {
    if (gate.current.pending) return
    if (newName.trim() || settingsDirty) setDiscard({ kind: 'close' })
    else onClose?.()
  }
  useReadingFocus(ref, true, requestClose, true)
  useReadingFocus(discardRef, Boolean(discard), () => setDiscard(null), true)
  useEffect(() => {
    if (busy || loading || discard || ref.current?.contains(document.activeElement)) return
    const target = deleteOpen ? targetSelect.current : editing?.is_custom ? renameInput.current : createInput.current
    ;(target && !target.disabled ? target : ref.current)?.focus({ preventScroll: true })
  }, [busy, loading, discard, deleteOpen, editing?.id])
  useEffect(() => () => dragCleanup.current?.(), [])
  useEffect(() => {
    if (!drag.current && !busy && !loading && orderView && (orderAck.current == null || catalogRevision >= orderAck.current)) setOrderView(null)
  }, [categories, catalogRevision, busy, loading])
  const select = category => {
    if (busy) return
    if (settingsDirty) { setDiscard({ kind: 'select', category }); return }
    applySelection(category)
  }
  const applySelection = category => { setEditing(category); setName(category?.label || ''); setColor(category?.color || '#24583b'); setDeleteOpen(false); setTarget('user_private'); setError(''); setMessage('') }
  const acceptLatest = () => { const draft = rebaseCategoryDraft(editing, { name, color }, latest); setName(draft.name); setColor(draft.color); setEditing(latest); setError('') }
  const run = async operation => {
    if (locked || gate.current.pending) return
    setBusy(true); setError(''); setMessage('')
    try { await gate.current.run(operation) }
    catch (failure) { setError(failure.status === 409 ? '分类配置已被更新，本次修改尚未保存。请重新读取后核对，输入内容已保留。' : failure.message || '分类保存失败，输入内容已保留') }
    finally { setBusy(false) }
  }
  const create = event => {
    event.preventDefault()
    run(async () => {
      const label = createKnowledgeCategory(newName, categories).label
      if (!onCreate) throw new Error('分类保存服务不可用')
      const result = await onCreate(label)
      setNewName(''); if (!settingsDirty) applySelection(result.category); setMessage('分类已独立创建，可以立即在知识工作台中使用。')
    })
  }
  const rename = event => {
    event.preventDefault()
    if (!editing || changedExternally) return
    run(async () => {
      const changes = { color: normalizeCategoryColor(color) }
      if (editing.is_custom) changes.label = createKnowledgeCategory(name, categories.filter(category => category.id !== editing.id)).label
      if (!onUpdate && !onRename) throw new Error('分类保存服务不可用')
      const result = onUpdate ? await onUpdate(editing, changes) : await onRename(editing, changes.label)
      applySelection(result.category); setMessage('分类设置已保存，目录与图谱将同步更新。')
    })
  }
  const remove = () => {
    if (!editing?.is_custom || changedExternally) return
    run(async () => {
      if (!onDelete) throw new Error('分类保存服务不可用')
      const result = await onDelete(editing, target)
      const label = categories.find(category => category.id === result.target_category)?.label || '目标分类'
      applySelection(null)
      setMessage(result.moved_count ? `分类已删除，${result.moved_count} 条知识已迁移至「${label}」。` : '空分类已删除。')
    })
  }
  const byId = new Map(categories.map(category => [category.id, category]))
  const ordered = orderView ? [...orderView.map(id => byId.get(id)).filter(Boolean), ...categories.filter(category => !orderView.includes(category.id))] : categories
  const canOrder = !locked && !query.trim() && typeof onReorder === 'function' && Number.isInteger(catalogRevision)
  const persistOrder = (ids, expectedRevision) => {
    if (locked || gate.current.pending) { setOrderView(null); return }
    setOrderView(ids)
    run(async () => {
      try {
        const result = await onReorder(ids, expectedRevision)
        orderAck.current = result.revision
        setMessage('分类顺序已保存，左侧目录与图谱已同步。')
      } catch (failure) { setOrderView(null); throw failure }
    })
  }
  const beginDrag = (event, category) => {
    if (event.button !== 0 || !canOrder) return
    event.preventDefault(); event.currentTarget.focus({ preventScroll: true })
    dragCleanup.current?.()
    drag.current = { id: category.id, startY: event.clientY, ids: ordered.map(item => item.id), original: ordered.map(item => item.id), revision: catalogRevision, moved: false }
    const move = pointer => {
      const current = drag.current
      if (!current || (!current.moved && Math.abs(pointer.clientY - current.startY) < 5)) return
      current.moved = true; setDraggingId(current.id)
      const row = document.elementFromPoint(pointer.clientX, pointer.clientY)?.closest('[data-category-id]')
      const targetId = row?.getAttribute('data-category-id')
      if (!targetId || targetId === current.id) return
      current.ids = moveCategoryId(current.ids, current.id, targetId); setOrderView(current.ids)
    }
    const finish = (cancel = false) => {
      const current = drag.current
      dragCleanup.current?.(); drag.current = null; setDraggingId(null)
      if (!current || cancel || !current.moved || current.ids.every((id, index) => id === current.original[index])) { setOrderView(null); return }
      persistOrder(current.ids, current.revision)
    }
    const up = () => finish(), cancel = () => finish(true)
    const escape = key => { if (key.key === 'Escape') { key.preventDefault(); key.stopPropagation(); cancel() } }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', cancel); window.addEventListener('keydown', escape, true)
    dragCleanup.current = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', cancel); window.removeEventListener('keydown', escape, true) }
  }
  const shift = (category, step) => {
    if (!canOrder) return
    const ids = ordered.map(item => item.id), index = ids.indexOf(category.id), targetId = ids[index + step]
    if (targetId) persistOrder(moveCategoryId(ids, category.id, targetId), catalogRevision)
  }
  const rows = ordered.filter(category => !query.trim() || category.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(category => {
    const index = ordered.findIndex(item => item.id === category.id)
    return <div key={category.id} data-category-id={category.id} className={`kcm-row${draggingId === category.id ? ' is-dragging' : ''}`}>
      <button type="button" className="kcm-drag-handle" disabled={!canOrder} aria-label={`拖动排序「${category.label}」`} aria-describedby="kcm-order-hint" onPointerDown={event => beginDrag(event, category)} onKeyDown={event => { if (['ArrowUp','ArrowDown'].includes(event.key)) { event.preventDefault(); shift(category, event.key === 'ArrowUp' ? -1 : 1) } }}><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M5 4h.01M11 4h.01M5 8h.01M11 8h.01M5 12h.01M11 12h.01" /></svg></button>
      <button type="button" className={`kcm-category${editing?.id === category.id ? ' is-selected' : ''}`} onClick={() => select(category)} disabled={busy || Boolean(draggingId)} aria-pressed={editing?.id === category.id}><i style={{ background: category.color || 'var(--seed-accent)' }} /><span>{category.label}{!category.is_custom && <em>内置</em>}</span><small>{category.count || 0}</small></button>
      <div className="kcm-order-actions"><button type="button" disabled={!canOrder || index === 0} aria-label={`上移「${category.label}」`} onClick={() => shift(category,-1)}><Icon.ChevronDown className="kcm-arrow-up" /></button><button type="button" disabled={!canOrder || index === ordered.length-1} aria-label={`下移「${category.label}」`} onClick={() => shift(category,1)}><Icon.ChevronDown /></button></div>
    </div>
  })
  return <div className="kcm-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) requestClose() }}>
    <section className="kcm-dialog" ref={ref} role="dialog" aria-modal="true" aria-labelledby="kcm-title" tabIndex={-1} aria-busy={busy || loading}>
      <div className="kcm-surface" inert={discard ? '' : undefined} aria-hidden={discard ? true : undefined}>
        <header className="kcm-header"><div><span className="kr-eyebrow">知识工作台</span><h3 id="kcm-title"><Icon.Grid />分类管理</h3><p>独立保存分类，统一整理科研知识。</p></div><button type="button" className="kr-icon-button" disabled={busy} aria-label="关闭分类管理" onClick={requestClose}><Icon.Close /></button></header>
        {((readOnly && !loading) || loadError) && <div className="kcm-notice" role="status"><span>{loadError || '当前为只读状态，请连接知识库后再修改分类。'}</span><button className="kr-button" type="button" disabled={busy || loading} onClick={onReload}>重新读取分类</button></div>}
        <form className="kcm-create" onSubmit={create}><label className="kr-field">新分类名称<input ref={createInput} className="kr-input" data-initial-focus value={newName} maxLength={40} disabled={locked} onChange={event => setNewName(event.target.value)} placeholder="例如：星系演化笔记" /></label><button type="submit" className="kr-button kr-button-accent" disabled={locked || !newName.trim()}><Icon.Plus />创建分类</button><small>创建后立即保存，空分类也会保留。</small></form>
        <div className="kcm-body">
          <aside className="kcm-directory" aria-label="分类管理目录"><label className="kcm-search"><Icon.Search /><input aria-label="搜索分类" placeholder="搜索分类名称" value={query} onChange={event => setQuery(event.target.value)} /></label>
            <h4>分类顺序 <span>{categories.length}</span></h4><p className="kcm-order-hint" id="kcm-order-hint">{query.trim() ? '清空搜索后可调整顺序' : '拖动手柄排序，也可使用上下移动按钮'}</p>{rows}
          </aside>
          <main className="kcm-detail">{error && <div className="kr-error" role="alert">{error}<button type="button" className="kr-button" disabled={busy || loading} onClick={onReload}>重新读取分类</button></div>}{message && <p className="kcm-success" role="status"><Icon.Check />{message}</p>}
            {!editing ? <div className="kcm-empty"><Icon.Grid /><h4>建立清晰的科研分类</h4><p>在上方创建新分类，或选择左侧分类进行维护。</p></div> : <>
              <div className="kcm-detail-title"><i style={{ background: validColor(color) ? color : editing.color }} /><h4>{latest?.label || editing.label}</h4><span className="kr-badge">{editing.is_custom ? '自定义分类' : '内置分类'}</span></div>
              <p className="kcm-count">{latest?.count ?? editing.count ?? 0} 条有效知识{(latest?.entry_count ?? editing.entry_count ?? 0) > (latest?.count ?? editing.count ?? 0) ? ' · 包含隐藏条目的归属记录' : ''}</p>
              {!editing.is_custom && <p className="kcm-notice">内置分类支持设置颜色与顺序，名称和删除由系统维护。</p>}
              {changedExternally && <section className="kcm-conflict" role="status"><strong>分类信息已发生变化</strong><p>{latest ? `最新名称为「${latest.label}」。当前输入已保留，请核对后继续。` : '该分类已不可用，请选择其他分类。'}</p>{latest && <button type="button" className="kr-button" disabled={locked} onClick={acceptLatest}>保留修改并使用最新版本</button>}<button type="button" className="kr-button" disabled={busy || loading} onClick={onReload}>重新读取分类</button></section>}
              <form className="kcm-rename" onSubmit={rename}>{editing.is_custom && <label className="kr-field">分类名称<input ref={renameInput} className="kr-input" value={name} maxLength={40} disabled={locked} onChange={event => setName(event.target.value)} /></label>}
                <fieldset className="kcm-color-field" disabled={locked}><legend>分类颜色</legend><div className="kcm-palette" role="group" aria-label="预设分类颜色">{PALETTE.map(([label,value]) => <button key={value} type="button" style={{ '--swatch': value }} aria-label={`${label} ${value}`} aria-pressed={color.toLowerCase() === value} onClick={() => setColor(value)}>{color.toLowerCase() === value && <Icon.Check />}</button>)}</div><div className="kcm-color-inputs"><input type="color" aria-label="选择分类颜色" value={validColor(color) ? color : '#24583b'} onChange={event => setColor(event.target.value)} /><label>自定义颜色<input className="kr-input" aria-label="分类颜色 Hex 码" value={color} maxLength={7} spellCheck={false} aria-invalid={!validColor(color)} onChange={event => setColor(event.target.value)} /></label><i style={{ background: validColor(color) ? color : editing.color }} /></div>{!validColor(color) && <p className="kr-category-error">请输入完整的颜色值，例如 #24583b</p>}</fieldset>
                <button type="submit" className="kr-button kr-button-accent" disabled={locked || !settingsDirty || !validColor(color) || (editing.is_custom && !name.trim()) || Boolean(changedExternally)}><Icon.Check />保存分类设置</button><p>保存后，左侧目录、知识卡片与图谱颜色同步更新。</p>
              </form>
              {editing.is_custom && <>
                <section className="kcm-delete"><div><h4>删除分类</h4><p>先迁移分类中的知识，再移除分类。</p></div>{!deleteOpen ? <button type="button" className="kr-button kr-danger-button" disabled={locked || Boolean(changedExternally)} onClick={() => setDeleteOpen(true)}><Icon.Trash />删除分类</button> : <div className="kcm-delete-confirm">
                  <p>即将删除「{latest?.label || editing.label}」。关联的 {latest?.entry_count ?? editing.entry_count ?? 0} 条知识（含隐藏条目）将迁移到下方分类，知识内容与派生关系会保留。</p>
                  <label className="kr-field">知识迁移到<select ref={targetSelect} className="kr-select" value={target} disabled={locked} onChange={event => setTarget(event.target.value)}>{categories.filter(category => category.id !== editing.id).map(category => <option key={category.id} value={category.id}>{category.label}</option>)}</select></label>
                  <div><button type="button" className="kr-button" disabled={busy} onClick={() => setDeleteOpen(false)}>取消删除</button><button type="button" className="kr-button kr-danger-button" disabled={locked || Boolean(changedExternally) || !categories.some(category => category.id === target && category.id !== editing.id)} onClick={remove}>迁移知识并删除分类</button></div>
                </div>}</section>
              </>}
            </>}
          </main>
        </div>
        <footer className="kcm-footer"><span>{busy ? '正在保存分类…' : loading ? '正在更新分类目录…' : '分类独立保存 · 知识内容完整保留'}</span><button type="button" className="kr-button" disabled={busy} onClick={requestClose}>完成</button></footer>
      </div>
      {discard && <div className="kr-discard-backdrop"><div className="kr-confirm" ref={discardRef} role="alertdialog" aria-modal="true" aria-labelledby="kcm-discard-title" tabIndex={-1}><h3 id="kcm-discard-title">放弃未保存的分类修改？</h3><p>已保存的分类会保留，当前名称或颜色尚未保存。</p><div className="kr-confirm-actions"><button className="kr-button" type="button" data-initial-focus onClick={() => setDiscard(null)}>继续编辑</button><button className="kr-button kr-danger-button" type="button" onClick={() => { const action = discard; setDiscard(null); if (action.kind === 'close') onClose?.(); else applySelection(action.category) }}>放弃修改</button></div></div></div>}
    </section>
  </div>
}
