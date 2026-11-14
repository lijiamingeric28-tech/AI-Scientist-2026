import React, { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { LatexMath, LatexText } from '@/components/results/LatexMath'
import { getCategoryInfo, translateProperty } from './knowledgeConstants'
import { conditionText, entryOrigin, sourceRecords } from './knowledgeReading'

export function useReadingFocus(ref, enabled, onClose, modal = false) {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!enabled || !ref.current) return undefined
    const previous = document.activeElement
    const panel = ref.current
    const initial = [...panel.querySelectorAll('[data-initial-focus]:not(:disabled)')].find(element => element.getClientRects().length > 0 && !element.closest('[inert]'))
    ;(initial || panel).focus({ preventScroll: true })
    const handleKey = event => {
      if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); closeRef.current?.() }
      const trap = modal || window.matchMedia('(max-width: 1200px)').matches
      if (event.key !== 'Tab' || !trap) return
      const focusable = [...panel.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, a[href], [tabindex="0"]')]
        .filter(element => element.getClientRects().length > 0 && !element.closest('[inert]') && element.tabIndex >= 0)
      if (!focusable.length) { event.preventDefault(); panel.focus(); return }
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    panel.addEventListener('keydown', handleKey)
    return () => { panel.removeEventListener('keydown', handleKey); if (previous?.isConnected) previous.focus() }
  }, [enabled, modal, ref])
}

export function EntryBadges({ item, categories = [], showCategory = true }) {
  const category = getCategoryInfo(item.category, categories)
  const origin = entryOrigin(item)
  return <div className="kr-badges">
    {showCategory && <span className="kr-badge kr-category"><i style={{ background: category.color }} />{category.label}</span>}
    <span className={`kr-badge kr-origin-${origin.id}`}>{origin.label}</span>
  </div>
}

export function Formula({ formula, compact = false }) {
  return <div className={`kr-formula ${compact ? 'kr-formula-compact' : ''}`}>
    {formula ? <LatexMath math={String(formula)} displayMode /> : <span className="kr-missing">未提供公式</span>}
  </div>
}

export function PropertyTags({ values = [], limit = Infinity, onMore }) {
  return values.length ? <div className="kr-tags">{values.slice(0, limit).map((property, index) => {
    const label = typeof property === 'string' ? property : property.label || property.name || property.property_id || property.id
    const unbound = typeof property === 'object' && (property.binding_state === 'unreviewed' || property.bound === false)
    return <span className={`kr-tag ${unbound ? 'kr-unbound' : ''}`} key={`${label}-${index}`}>{translateProperty(label)}{unbound ? ' · 未绑定' : ''}</span>
  })}{values.length > limit && <button type="button" className="kr-tag kr-tag-more" aria-label={`查看其余 ${values.length - limit} 项关联物理量`} onClick={event => { event.stopPropagation(); onMore?.() }}>+{values.length - limit} 项</button>}</div> : <span className="kr-missing">未提供关联物理量</span>
}

export function SourcesList({ sources }) {
  const records = sourceRecords(sources)
  const format = value => Array.isArray(value) ? value.map(format).join('; ') : typeof value === 'object' && value ?
    Object.entries(value).map(([key, data]) => `${key}: ${format(data)}`).join('; ') : String(value ?? '')
  const labels = { doi: 'DOI', url: '链接', authors: '作者', year: '年份', venue: '期刊', journal: '期刊', pages: '页码', source_id: '来源编号', provenance: '依据' }
  return records.length ? <ol className="kr-source-list">{records.map((source, index) => <li key={index}>
    <div className="kr-source-title">{source.title || source.name || '来源记录'}</div>
    <dl>{Object.entries(source).filter(([key]) => key !== 'title' && key !== 'name').map(([key, value]) => <div key={key}>
      <dt>{labels[key] || key}</dt><dd>{key === 'url' && /^https?:\/\//i.test(String(value)) ?
        <a href={value} target="_blank" rel="noreferrer">{format(value)}<Icon.ExternalLink /></a> : format(value)}</dd>
    </div>)}</dl>
  </li>)}</ol> : <p className="kr-missing">未提供来源</p>
}

export function EntryOverview({ item }) {
  const conditions = conditionText(item.conditions).split('\n').filter(Boolean)
  return <div className="kr-overview">
    <section><h4>科学公式</h4><Formula formula={item.formula} /></section>
    <section><h4>核心阐述</h4><p className="kr-prose">{item.description || item.content ? <LatexText text={item.description || item.content} /> : <span className="kr-missing">未提供描述</span>}</p></section>
    <section><h4>适用条件与假定</h4>{conditions.length ? <ul className="kr-conditions">{conditions.map((condition, index) => <li key={index}><LatexText text={condition} /></li>)}</ul> : <p className="kr-missing">未提供适用条件</p>}</section>
    <section><h4>参数与取值范围</h4>{item.parameters?.length ? <dl className="kr-parameters">{item.parameters.map((raw, index) => {
      const parameter = typeof raw === 'string' ? { name: raw } : raw
      return <div key={index}>
      <dt>{parameter.symbol ? <LatexMath math={parameter.symbol} /> : parameter.name || '未提供参数名'}</dt>
      <dd>{parameter.desc || parameter.description || parameter.name || ''}<span>{parameter.range ? <LatexText text={String(parameter.range)} /> : '未提供范围'}{parameter.unit ? <> · <LatexText text={parameter.unit} /></> : ''}</span></dd>
    </div>})}</dl> : <p className="kr-missing">未提供参数</p>}</section>
    <section><h4>关联物理量</h4><PropertyTags values={item.relations?.properties || item.properties} /></section>
  </div>
}

export function EntryActions({ item, readOnly = false, pending = false, onTogglePreference, onEdit, onFork, onDelete, onRestore, onError }) {
  const [busy, setBusy] = useState(false)
  const menuRef = useRef(null)
  const preferred = Boolean(item.preferred || item.user_preference === 'preferred')
  const disabled = readOnly || pending || busy
  const action = async callback => {
    if (disabled || !callback) return
    if (menuRef.current) menuRef.current.open = false
    setBusy(true)
    try { await callback() } catch (error) { onError?.(error.message || '操作失败，请重试') }
    finally { setBusy(false) }
  }
  return <div className="kr-actions" onClick={event => event.stopPropagation()}>
    <button type="button" className={`kr-icon-button ${preferred ? 'kr-preferred' : ''}`} disabled={disabled || !onTogglePreference}
      aria-label={preferred ? '取消科研优选' : '设为科研优选'} title={preferred ? '取消科研优选' : '设为科研优选'} aria-pressed={preferred}
      onClick={() => action(() => onTogglePreference(item.id, !preferred))}>{preferred ? <Icon.StarFilled /> : <Icon.Star />}</button>
    <details className="kr-more" ref={menuRef} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus() } }}>
      <summary className="kr-icon-button" aria-label="更多条目操作" title="更多操作"><Icon.Ellipsis /></summary>
      <div className="kr-menu">
        <button type="button" disabled={disabled || !onEdit} onClick={() => action(() => onEdit(item))}><Icon.Edit />编辑理论</button>
        <button type="button" disabled={disabled || !onFork} onClick={() => action(() => onFork(item))}><Icon.Fork />派生理论</button>
        {item.is_override && <button type="button" disabled={disabled || !onRestore} onClick={() => action(() => onRestore(item.id))}><Icon.History />恢复默认</button>}
        <button type="button" className="kr-danger" disabled={disabled || !onDelete} onClick={() => { menuRef.current.open = false; onDelete(item) }}><Icon.Trash />删除条目</button>
      </div>
    </details>
  </div>
}

export function DeleteConfirmation({ item, onCancel, onConfirm, pending = false }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const ref = useRef(null)
  const locked = busy || pending
  useReadingFocus(ref, Boolean(item), () => { if (!locked) onCancel?.() }, true)
  if (!item) return null
  const submit = async () => {
    if (locked) return
    setBusy(true); setError('')
    try { await onConfirm?.(item.id); onCancel?.() }
    catch (failure) { setError(failure.message || '删除失败，请重试') }
    finally { setBusy(false) }
  }
  return <div className="kr-confirm-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !locked) onCancel?.() }}>
    <div ref={ref} className="kr-confirm" role="alertdialog" aria-modal="true" aria-labelledby="kr-delete-title" aria-describedby="kr-delete-description" tabIndex={-1}>
      <h3 id="kr-delete-title">删除知识条目</h3>
      <p id="kr-delete-description">确定删除「{item.title || item.name || item.label}」？{item.is_user ? '此条目的派生条目将保留。' : '内置条目及其用户修改将从当前知识库中隐藏。'}</p>
      {error && <p className="kr-error" role="alert">{error}</p>}
      <div className="kr-confirm-actions"><button type="button" className="kr-button" data-initial-focus disabled={locked} onClick={onCancel}>取消</button>
        <button type="button" className="kr-button kr-danger-button" disabled={locked} onClick={submit}>{locked ? '正在删除…' : '确认删除'}</button></div>
    </div>
  </div>
}
