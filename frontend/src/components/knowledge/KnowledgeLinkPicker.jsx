import React, { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { getKnowledge } from '@/services/api'
import { createKnowledgeLinkSearch, knowledgeLinkIds, knowledgeLinkSelection } from './knowledgeReading'
import { getCategoryInfo } from './knowledgeConstants'
import './knowledgeLinks.css'

const emptySummaries = []
const initialSearch = { status: 'idle', items: [], total: 0, error: '' }

export default function KnowledgeLinkPicker({
  value = [], summaries = emptySummaries, categories = [], excludeId,
  disabled = false, onChange, loadChoices = getKnowledge,
}) {
  const [query, setQuery] = useState('')
  const [searchState, setSearchState] = useState(initialSearch)
  const [cache, setCache] = useState(() => new Map(summaries.map(item => [item.id, item])))
  const [retry, setRetry] = useState(0)
  const searchRef = useRef(null)
  const searchId = useId(), hintId = useId()
  const ids = knowledgeLinkIds(value, excludeId)
  const selected = useMemo(() => knowledgeLinkSelection(ids, [...summaries, ...cache.values()]), [value, summaries, cache, excludeId])

  useEffect(() => {
    setCache(previous => new Map([...previous, ...summaries.filter(item => item?.id).map(item => [item.id, item])]))
  }, [summaries])
  useEffect(() => {
    const search = createKnowledgeLinkSearch(loadChoices, state => {
      setSearchState(state)
      if (state.status === 'ready') setCache(previous => new Map([...previous, ...state.items.map(item => [item.id, item])]))
    }, { excludeId })
    searchRef.current = search
    return () => { search.dispose(); searchRef.current = null }
  }, [loadChoices, excludeId])
  useEffect(() => {
    if (disabled) { searchRef.current?.dispose(); setSearchState(initialSearch); return }
    searchRef.current?.search(query)
    return () => searchRef.current?.dispose()
  }, [query, retry, disabled, loadChoices, excludeId])

  const remove = id => { if (!disabled) onChange?.(ids.filter(value => value !== id)) }
  const toggle = item => {
    if (disabled) return
    if (ids.includes(item.id)) remove(item.id)
    else if (ids.length < 100) {
      setCache(previous => new Map([...previous, [item.id, item]]))
      onChange?.([...ids, item.id])
    }
  }
  const categoryText = item => categories.find(category => category.id === item.category)?.label
    || item.category_label || (item.category ? getCategoryInfo(item.category).label : '未提供分类')
  return <div className="kr-link-picker">
    <div className="kr-link-heading"><span><Icon.Link aria-hidden="true" />建立知识之间的联系</span><span className="kr-link-count">已选 {ids.length}/100</span></div>
    <p className="kr-link-hint" id={hintId}>选择已存在的知识条目；这些关联会显示在详情与知识图谱中。</p>
    {selected.length > 0 ? <ul className="kr-link-selected" aria-label="已选关联知识">{selected.map(item => <li key={item.id} className={`kr-link-chip${item.unavailable ? ' kr-link-unavailable' : ''}`}>
      <Icon.FileText aria-hidden="true" /><span className="kr-link-chip-content"><strong>{item.unavailable ? '条目暂不可用' : item.title || item.id}</strong><small>{item.unavailable ? item.id : categoryText(item)}</small></span>
      <button className="kr-icon-button" type="button" aria-label={`移除关联：${item.title || item.id}`} disabled={disabled} onClick={() => remove(item.id)}><Icon.Close aria-hidden="true" /></button>
    </li>)}</ul> : <p className="kr-link-empty-selection">尚未选择关联知识</p>}
    <label className="kr-field kr-link-search" htmlFor={searchId}>搜索已有知识<div><Icon.Search aria-hidden="true" /><input id={searchId} className="kr-input" type="search" aria-label="搜索关联知识" aria-describedby={hintId} disabled={disabled} value={query} placeholder="输入标题、关键词或条目编号" onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') event.preventDefault() }} /></div></label>
    {ids.length >= 100 && <p className="kr-link-limit" role="status">已达到 100 项上限，可先移除已有选择。</p>}
    <div className="kr-link-results" aria-busy={searchState.status === 'loading'}>
      {searchState.status === 'loading' && <p className="kr-link-status" role="status"><Icon.Refresh aria-hidden="true" />正在搜索知识…</p>}
      {searchState.status === 'error' && <div className="kr-link-search-error" role="alert"><span><Icon.AlertCircle aria-hidden="true" />{searchState.error}</span><button className="kr-button" type="button" disabled={disabled} onClick={() => setRetry(value => value + 1)}><Icon.Refresh aria-hidden="true" />重试</button></div>}
      {searchState.status === 'ready' && (searchState.items.length ? <><ul aria-label="关联知识搜索结果">{searchState.items.map(item => {
        const checked = ids.includes(item.id)
        return <li key={item.id}><label className={`kr-link-option${checked ? ' is-selected' : ''}`}><input type="checkbox" checked={checked} disabled={disabled || (!checked && ids.length >= 100)} onChange={() => toggle(item)} /><span><strong>{item.title || item.name || item.id}</strong><small>{categoryText(item)}</small>{item.description && <p>{item.description}</p>}</span></label></li>
      })}</ul>{searchState.total > searchState.items.length && <p className="kr-link-refine">当前显示 {searchState.items.length} 项，请继续输入以缩小范围。</p>}</> : <p className="kr-link-status" role="status">未找到可关联的知识，请尝试其他关键词。</p>)}
    </div>
  </div>
}
