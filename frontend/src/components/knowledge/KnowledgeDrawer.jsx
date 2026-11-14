import React, { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { translateEdgeLabel, translateProperty } from './knowledgeConstants'
import { knowledgeRelationEvidence } from './knowledgeReading'
import { EntryActions, EntryBadges, EntryOverview, SourcesList, DeleteConfirmation, useReadingFocus } from './knowledgeReadingParts'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import './knowledgeReading.css'

export default function KnowledgeDrawer({
  item, categories = [], allNodes = [], topologyLinks = [], loading = false, readOnly = false, pending = false,
  onClose, onSelectNode, onTogglePreference, onEdit, onFork, onDelete, onRestore, onFocus, onShowAllRelations,
  loadError, onRetry, onManageRelations,
}) {
  const [tab, setTab] = useState('overview')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [error, setError] = useState('')
  const ref = useRef(null)
  const tabsRef = useRef(null)
  const dismissal = useDismissTransition(onClose, { duration: 180, active: Boolean(item), identity: item?.id })
  useReadingFocus(ref, Boolean(item), dismissal.close, true)
  useEffect(() => { setTab('overview'); setDeleteOpen(false); setError('') }, [item?.id])
  if (!item) return null
  const hub = item.is_property || ['category', 'property', 'aggregate'].includes(item.kind)
  const relation = item.relations
  const properties = relation?.properties || []
  const derived = relation?.derived || []
  const related = relation?.related || []
  const base = relation?.base
  const legacy = !relation ? topologyLinks.filter(link => (link.source?.id || link.source) === item.id || (link.target?.id || link.target) === item.id).map(link => {
    const source = link.source?.id || link.source, target = link.target?.id || link.target
    const id = source === item.id ? target : source
    return { ...(allNodes.find(node => node.id === id) || { id, label: id }), relationLabel: translateEdgeLabel(link.label), provenance: link.provenance }
  }) : []
  const title = item.title || item.name || item.label || item.id
  const relationButton = (node, prefix = '') => {
    const normalized = typeof node === 'string' ? { id: node, label: node } : node
    const id = normalized.id || normalized.entry_id || normalized.property_id
    const entry = ['related','base','derived'].includes(prefix)
    return <button key={`${prefix}-${id}`} type="button" className="kr-relation" disabled={normalized.unavailable} onClick={() => onSelectNode?.(entry ? { ...normalized, id, kind:'entry' } : id)}>
      <span><strong>{normalized.title || normalized.label || normalized.name || translateProperty(id)}</strong>{normalized.unavailable && <small>当前不可用 · {id}</small>}{normalized.binding_state === 'unreviewed' && <small>未绑定</small>}{normalized.relationLabel && <small>{normalized.relationLabel}</small>}<small>{knowledgeRelationEvidence(normalized, prefix, { isOverride: item.is_override })}{prefix === 'related' && normalized.direction === 'incoming' ? ' · 由该知识关联到本条目' : prefix === 'related' && normalized.direction === 'both' ? ' · 双向关联' : ''}</small></span><Icon.ChevronRight />
    </button>
  }
  const tabs = [['overview', '概览'], ['relations', '关联'], ['sources', '来源']]
  return <>
    <button type="button" className="kr-drawer-backdrop" data-closing={dismissal.closing || undefined} onClick={dismissal.close} aria-label="关闭详情遮罩" tabIndex={-1} />
    <aside className="kr-drawer" ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} aria-busy={loading}
      data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture}>
      <header className="kr-drawer-header"><div>{hub ? <span className="kr-badge">{item.kind === 'category' ? '分类导航' : '物理量导航'}</span> : !item.loading_only && <EntryBadges item={item} categories={categories} showCategory={Boolean(item.category)} />}
        <h3>{title}</h3></div><button type="button" className="kr-icon-button" data-initial-focus aria-label="关闭详情" onClick={dismissal.close}><Icon.Close /></button></header>
      <div className="kr-drawer-command">{hub ? <p className="kr-muted">浏览关联条目，保持当前筛选和返回路径。</p> : <>
        <span className="kr-muted">条目详情</span><EntryActions item={item} readOnly={readOnly || loading} pending={pending} onTogglePreference={onTogglePreference}
          onEdit={onEdit} onFork={onFork} onDelete={onDelete ? () => setDeleteOpen(true) : undefined} onRestore={onRestore} onError={setError} />
      </>}</div>
      {error && <p className="kr-error" role="alert">{error}</p>}
      {loadError && <div className="kwb-detail-error" role="alert"><span>无法读取条目详情：{loadError}</span><button type="button" onClick={onRetry}>重试</button></div>}
      <div className="kr-detail-tabs" role="tablist" aria-label="知识详情" ref={tabsRef} onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        let index = tabs.findIndex(([id]) => id === tab)
        index = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3
        setTab(tabs[index][0]); tabsRef.current.children[index].focus()
      }}>{tabs.map(([id, label]) => <button key={id} type="button" role="tab" id={`kr-tab-${id}`} aria-controls={`kr-panel-${id}`} aria-selected={tab === id} tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)}>{label}</button>)}</div>
      <div className="kr-drawer-body">
        {loading && <p className="kr-muted" role="status">正在载入完整详情…</p>}
        {!loading && <><section hidden={tab !== 'overview'} role="tabpanel" id="kr-panel-overview" aria-labelledby="kr-tab-overview">
          {hub ? <div className="kr-overview"><p>此节点汇集相关知识条目。请选择关联条目阅读完整科学内容。</p><button type="button" className="kr-button kr-button-accent" onClick={() => onShowAllRelations?.(item.id)}>浏览关联条目<Icon.ChevronRight /></button>{item.count != null && <p className="kr-muted">关联 {item.count} 条</p>}</div> : <>
            {item.is_override && <div className="kr-notice">当前内容包含用户修改。下方来源记录不代表修改内容已经过学术审校。</div>}
            {item.is_user && !item.is_override && <div className="kr-notice">用户条目 · 来源与物理量绑定请自行核验。</div>}
            <EntryOverview item={item} />
          </>}
        </section>
        <section hidden={tab !== 'relations'} role="tabpanel" id="kr-panel-relations" aria-labelledby="kr-tab-relations" className="kr-relations">
          <div className="kr-relation-tools">{onFocus && !hub && <button type="button" className="kr-button" onClick={() => onFocus(item.id)}><Icon.Focus />聚焦图谱</button>}
            {onShowAllRelations && <button type="button" className="kr-button" onClick={() => onShowAllRelations(item.id)}>查看全部关联</button>}</div>
          <h4>关联物理量</h4>{properties.length ? properties.map(node => relationButton(node, 'property')) : <p className="kr-missing">未提供已绑定物理量</p>}
          <div className="kr-related-heading"><h4>关联知识</h4>{!hub && onManageRelations && <button type="button" className="kr-button" disabled={readOnly || pending || loading || item.loading_only} onClick={() => onManageRelations(item)}><Icon.Link />管理关联</button>}</div>{related.length ? related.map(node => relationButton(node, 'related')) : <p className="kr-missing">未建立知识条目关联</p>}
          <h4>基础条目</h4>{base ? relationButton(base, 'base') : <p className="kr-missing">{relation?.base_unavailable ? '基础条目当前不可用；派生内容已保留。' : '未提供基础条目'}</p>}
          <h4>派生条目</h4>{derived.length ? derived.map(node => relationButton(node, 'derived')) : <p className="kr-missing">未提供派生条目</p>}
          {legacy.length > 0 && <><h4>图中关联</h4>{legacy.map(node => relationButton(node, 'graph'))}</>}
        </section>
        <section hidden={tab !== 'sources'} role="tabpanel" id="kr-panel-sources" aria-labelledby="kr-tab-sources">
          <h4>{item.is_override || item.is_user ? '当前用户内容的来源' : '内置条目来源'}</h4>
          {(item.is_override || item.is_user) && <p className="kr-muted">用户填写的引用与内置审校记录分别展示。</p>}<SourcesList sources={item.sources || item.source} />
          {item.reviewed_sources && <><h4>内置审校来源</h4><SourcesList sources={item.reviewed_sources} /></>}
          {!item.reviewed_sources && item.is_override && base?.sources && <><h4>内置条目来源（修改前）</h4><SourcesList sources={base.sources} /></>}
          <dl className="kr-entry-meta"><div><dt>条目编号</dt><dd>{item.id}</dd></div><div><dt>条目修订</dt><dd>{item.revision ?? '未提供'}</dd></div><div><dt>更新时间</dt><dd>{item.updated_at || '未提供'}</dd></div></dl>
        </section></>}
      </div>
    </aside>
    {deleteOpen && <DeleteConfirmation item={item} pending={pending} onCancel={() => setDeleteOpen(false)} onConfirm={async id => {
      if (readOnly) throw new Error('当前知识库为只读状态')
      await onDelete?.(id); onClose?.()
    }} />}
  </>
}
