import React, { lazy, Suspense, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import { useKnowledgeWorkbench } from '@/hooks/useKnowledgeWorkbench'
import { resolveKnowledgeNavigation, searchKnowledgeProperties, selectedKnowledgeShell } from '@/lib/knowledgeWorkbench'
import { mergeCategoryFacets } from '@/lib/knowledgeCategories'
import KnowledgeGraphView from './KnowledgeGraphView'
import KnowledgeListView from './KnowledgeListView'
const KnowledgeEditorModal = lazy(() => import('./KnowledgeEditorModal'))
import KnowledgeDrawer from './KnowledgeDrawer'
const KnowledgeCategoryManager = lazy(() => import('./KnowledgeCategoryManager'))
const KnowledgeRelationManager = lazy(() => import('./KnowledgeRelationManager'))
import { getCustomCategoryColor } from './knowledgeConstants'
import './knowledge.css'
import './knowledgeWorkspace.css'

const sourceLabels = { all: '全部来源', builtin: '内置理论', user: '用户知识', override: '内置覆写' }
const number = value => Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—'
const restoreFocus = element => requestAnimationFrame(() => { if (element?.isConnected && !element.closest('[inert]')) element.focus({ preventScroll: true }) })

function KnowledgePropertyPicker({ properties, value, disabled, onChange, className = '' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const control = useRef(null), trigger = useRef(null), input = useRef(null)
  const listId = useId()
  const results = useMemo(() => searchKnowledgeProperties(properties, query, value), [properties, query, value])
  const options = [{ id: '', label: '全部物理量' }, ...results.items]
  const selected = properties.find(property => property.id === value)
  const close = (restoreFocus = false) => { setOpen(false); if (restoreFocus) trigger.current?.focus() }
  const choose = id => { onChange(id); close(true) }
  useEffect(() => {
    if (!open) return
    input.current?.focus()
    const outside = event => { if (!control.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => { if (open) control.current?.querySelector('[data-active]')?.scrollIntoView({ block: 'nearest' }) }, [active, open])
  return <div ref={control} className={`kwb-property-control ${className}`} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }} onKeyDownCapture={event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); close(true) }
  }}>
    <button ref={trigger} type="button" className="kwb-property-trigger" disabled={disabled} aria-label="按绑定物理量筛选" aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? listId : undefined} onClick={() => { setOpen(!open); setQuery(''); setActive(0) }}><span>{selected?.label || value || '全部物理量'}</span><Icon.ChevronDown /></button>
    {open && <div className="kwb-property-popover">
      <label className="kwb-property-search"><Icon.Search /><input ref={input} value={query} role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={`${listId}-${Math.min(active, options.length - 1)}`} placeholder="搜索名称或精确 ID" aria-label="搜索绑定物理量" onChange={event => { setQuery(event.target.value); setActive(0) }} onKeyDown={event => {
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) { event.preventDefault(); setActive(index => event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length) }
        if (event.key === 'Enter') { event.preventDefault(); choose(options[Math.min(active, options.length - 1)].id) }
      }} /></label>
      <div className="kwb-property-options" id={listId} role="listbox" aria-label="物理量筛选结果">{options.map((property, index) => <button id={`${listId}-${index}`} key={property.id} type="button" role="option" aria-selected={property.id === value} data-active={index === active || undefined} onMouseMove={() => setActive(index)} onClick={() => choose(property.id)}><span>{property.label || property.id}<small>{property.id}</small></span>{property.id === value ? <Icon.Check /> : <b>{property.count ?? ''}</b>}</button>)}</div>
      <p className="kwb-property-hint">{results.total ? `${number(results.total)} 项匹配${results.hasMore ? ' · 显示前 30 项' : ''}` : '没有匹配的物理量'}<span>可搜索全部 {number(properties.length)} 项</span></p>
    </div>}
  </div>
}

export default function KnowledgeWorkspace({ task, pipeline, active = true, memory, initialMode = null, renderHeader }) {
  const { toast } = useToast()
  const localMemory = useRef({})
  const workspaceRef = useRef(null), detailOrigin = useRef(null), editorOrigin = useRef(null), managerOrigin = useRef(null), relationOrigin = useRef(null)
  const editorSequence = useRef(0)
  const taskProperties = useMemo(() => [...new Set([
    ...(pipeline?.presentation?.properties || []), ...(task?.properties || []),
  ].map(property => typeof property === 'string' ? property : property.id || property.property_id).filter(Boolean))], [pipeline?.presentation?.properties, task?.properties])
  const data = useKnowledgeWorkbench({ memory: memory || localMemory.current, initialMode, active, taskProperties })
  const { state, dispatch, summary, list, graph, detail, main, readOnly, items, graphData, selectedItem, pendingIds } = data
  const [editor, setEditor] = useState(null)
  const [editorLoading, setEditorLoading] = useState(false)
  const [categoryManagerOpen, setCategoryManagerOpen] = useState(false)
  const [relationEditor, setRelationEditor] = useState(null)
  const previousSummary = useRef(null)
  const previousCatalog = useRef(null)
  if (summary.data) previousSummary.current = summary.data
  const summaryMetadata = summary.data || previousSummary.current
  if (data.categoryResource.data) previousCatalog.current = data.categoryResource.data
  const catalogMetadata = data.categoryResource.data || previousCatalog.current
  const categoryCatalog = useMemo(() => catalogMetadata?.items || [], [catalogMetadata])
  const summaryPending = summary.status === 'loading' || summary.status === 'idle'
  const summaryMetadataStale = summary.status === 'stale' || summary.status === 'error'
  const categories = useMemo(() => mergeCategoryFacets(categoryCatalog.length ? categoryCatalog : summaryMetadata?.categories || [], summaryMetadata?.categories || []).filter(category => category.id !== 'all').map(category => ({ ...category, color: category.color || getCustomCategoryColor(category.id) })), [summaryMetadata, categoryCatalog])
  const total = summaryMetadata?.total
  const matchedTotal = summary.data?.matched_total
  const facetTotal = categories.reduce((count, category) => count + (category.count || 0), 0)
  const selectedCategory = categories.find(category => category.id === state.filters.category)
  const filter = (key, value) => {
    if (key === 'category' && state.mode === 'graph') dispatch({ type: 'navigate', scene: { view: value === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false }, filters: { category: value } })
    else dispatch({ type: 'filter', key, value })
  }
  const create = () => { if (!readOnly) { editorOrigin.current = document.activeElement; setEditor({ mode: 'create', item: null }) } }
  const closeEditor = () => { setEditor(null); restoreFocus(editorOrigin.current) }
  const openCategoryManager = () => { managerOrigin.current = document.activeElement; setCategoryManagerOpen(true) }
  const closeCategoryManager = () => { setCategoryManagerOpen(false); restoreFocus(managerOrigin.current) }
  const openRelationManager = item => { if (!readOnly && !detail.readOnly) { relationOrigin.current = document.activeElement; setRelationEditor(item) } }
  const closeRelationManager = () => { setRelationEditor(null); restoreFocus(relationOrigin.current) }
  const dismissDetail = () => { dispatch({ type: 'dismissDetail' }); restoreFocus(detailOrigin.current) }
  const focusCanvas = () => requestAnimationFrame(() => workspaceRef.current?.querySelector('.kg-canvas')?.focus({ preventScroll: true }))
  const notifyMutation = async (operation, success) => {
    try { const result = await operation(); toast(success, 'success'); return result }
    catch (error) { toast(error.status === 409 ? '条目已被更新，草稿已保留。请重新读取后核对修改。' : error.message || '保存失败，请重试', 'error'); throw error }
  }
  const actions = {
    onTogglePreference: (id, preferred) => notifyMutation(() => data.preference(id, preferred), preferred ? '已设为科研优选' : '已取消科研优选'),
    onDelete: id => notifyMutation(() => data.remove(id), '条目已删除'),
    onRestore: id => notifyMutation(() => data.restore(id), '已恢复内置条目'),
  }
  const openEditor = async (item, mode) => {
    if (readOnly || !item?.id || item.kind === 'category' || item.kind === 'property' || item.is_property) return
    const sequence = ++editorSequence.current
    const origin = document.activeElement
    setEditorLoading(true)
    try {
      const full = await data.loadEntry(item.id)
      if (sequence === editorSequence.current) { editorOrigin.current = origin; setEditor({ mode, item: full }) }
    } catch (error) { if (sequence === editorSequence.current) toast(error.message || '无法读取条目，请重试', 'error') }
    finally { if (sequence === editorSequence.current) setEditorLoading(false) }
  }
  const editActions = { onEdit: item => openEditor(item, 'edit'), onFork: item => openEditor(item, 'fork') }
  const openMatrix = () => dispatch({ type: 'view', mode: 'matrix' })
  const enterCategory = category => {
    if (!category) { openMatrix(); return }
    dispatch({ type: 'navigate', scene: { view: category === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false }, filters: { category } })
  }
  const enterProperty = property => dispatch({ type: 'navigate', scene: { view: 'overview', focus_id: null, allAssociations: false }, filters: { property_ids: [property] } })
  const select = node => {
    const navigation = resolveKnowledgeNavigation(node, { nodes: graphData.nodes, properties: data.properties || [], relations: selectedItem?.relations })
    if (navigation.kind === 'matrix') { openMatrix(); return }
    if (navigation.kind === 'category') { enterCategory(navigation.id); if (state.detailOpen) focusCanvas(); return }
    if (navigation.kind === 'property') { enterProperty(navigation.id); if (state.detailOpen) focusCanvas(); return }
    if (!state.detailOpen) detailOrigin.current = document.activeElement
    dispatch({ type: 'select', id: navigation.id })
  }
  const focus = id => { const entryId = typeof id === 'string' ? id : id?.id || state.selectedId; if (entryId) { dispatch({ type: 'select', id: entryId }); dispatch({ type: 'navigate', scene: { view: 'focus', focus_id: entryId, allAssociations: false } }); focusCanvas() } }
  const showAllRelations = id => { const entryId = typeof id === 'string' ? id : id?.id || state.selectedId; if (entryId) { dispatch({ type: 'navigate', scene: { view: 'focus', focus_id: entryId, allAssociations: true } }); focusCanvas() } }
  const staleResources = [summary, data.directory, main, data.categoryResource, ...(state.selectedId ? [detail] : [])].filter(resource => resource.status === 'stale')
  const errorResources = [summary, data.directory, main, data.categoryResource].filter(resource => resource.status === 'error')
  const isLoading = summary.status === 'loading' || main.status === 'loading' || data.categoryResource.status === 'loading'
  const headerControls = { total, matchedTotal, readOnly, pending: summaryPending, stale: summaryMetadataStale, onCreate: create }
  const selectedShell = selectedKnowledgeShell(state.selectedId, { detail: selectedItem, items, nodes: graphData.nodes })
  const detailVisible = state.detailOpen && Boolean(state.selectedId)

  return (
    <div className="knowledge-workspace kwb-workspace" ref={workspaceRef} role="region" aria-label="天体物理知识图谱与理论库" aria-busy={isLoading}>
      <div className="kwb-surface" inert={detailVisible || editor || categoryManagerOpen || relationEditor ? '' : undefined} aria-hidden={detailVisible || editor || categoryManagerOpen || relationEditor ? true : undefined}>
      {renderHeader ? renderHeader(headerControls) : (
        <header className="kwb-studio-header">
          <div className="kwb-title-group"><Icon.Network /><h2>知识图谱与理论库</h2><span className="kwb-header-count">{number(total)} 条{summaryPending ? ' · 更新中' : summaryMetadataStale ? ' · 上次读取' : ''}</span></div>
          <Button variant="accent" size="sm" onClick={create} disabled={readOnly}><Icon.Plus />新增知识</Button>
        </header>
      )}
      <div className="kwb-toolbar" role="toolbar" aria-label="知识库检索与视图">
        <div className="kwb-views" role="tablist" aria-label="知识呈现视图">
          <button type="button" role="tab" aria-selected={state.mode === 'graph'} onClick={() => dispatch({ type: 'view', mode: 'graph' })}><Icon.Network /><span>图谱</span></button>
          <button type="button" role="tab" aria-selected={state.mode === 'matrix'} onClick={() => dispatch({ type: 'view', mode: 'matrix' })}><Icon.Grid /><span>矩阵</span></button>
        </div>
        <label className="kwb-search"><Icon.Search /><input value={state.keyword} onChange={event => dispatch({ type: 'keyword', value: event.target.value })} placeholder="检索理论、公式、物理量…" aria-label="搜索理论知识" />{state.keyword && <button type="button" aria-label="清空搜索" onClick={() => dispatch({ type: 'keyword', value: '' })}><Icon.Close /></button>}</label>
        <select className="kwb-category-select" aria-label="知识分类" value={state.filters.category} onChange={event => filter('category', event.target.value)}><option value="all">全部分类 ({number(facetTotal)})</option>{categories.map(category => <option key={category.id} value={category.id}>{category.label} ({category.count})</option>)}</select>
        <select className="kwb-source-select" aria-label="知识来源" value={state.filters.source} onChange={event => filter('source', event.target.value)}>{Object.entries(sourceLabels).map(([source, label]) => <option key={source} value={source}>{label}{source !== 'all' && Number.isFinite(summaryMetadata?.sources?.[source]) ? ` (${summaryMetadata.sources[source]})` : ''}</option>)}</select>
        <KnowledgePropertyPicker className="kwb-property-mobile" properties={data.properties || []} value={state.filters.property_ids[0] || ''} disabled={state.taskScoped} onChange={id => filter('property_ids', id ? [id] : [])} />
        <button type="button" className="kwb-filter-button" aria-pressed={state.filters.preferred_only} onClick={() => filter('preferred_only', !state.filters.preferred_only)}>{state.filters.preferred_only ? <Icon.StarFilled /> : <Icon.Star />}<span>科研优选</span></button>
        {taskProperties.length > 0 && <button type="button" className="kwb-filter-button kwb-task-button" aria-pressed={state.taskScoped} onClick={() => dispatch({ type: 'taskScoped', value: !state.taskScoped })} title="按当前任务中明确绑定的物理量筛选"><Icon.Filter /><span>当前任务</span></button>}
        <button type="button" className="kwb-filter-button kwb-manage-categories" onClick={openCategoryManager}><Icon.Grid /><span>分类管理</span></button>
      </div>
      <div className="kwb-body">
        <aside className="kwb-taxonomy" aria-label="知识分类目录" aria-busy={summaryPending}>
          <div className="kwb-rail-heading">知识分类 <span>{summaryPending ? '更新中' : summaryMetadataStale ? '上次读取' : categories.length}</span></div>
          <nav><button type="button" className={state.filters.category === 'all' ? 'is-active' : ''} onClick={() => filter('category', 'all')}><Icon.Grid /><span>全部知识</span><b>{number(facetTotal)}</b></button>{categories.map(category => <button key={category.id} type="button" className={state.filters.category === category.id ? 'is-active' : ''} onClick={() => filter('category', category.id)} title={category.label}><i style={{ background: category.color }} /><span>{category.label}</span><b>{number(category.count)}</b></button>)}</nav>
          <div className="kwb-rail-heading kwb-properties-heading">绑定物理量</div>
          <KnowledgePropertyPicker className="kwb-property-rail" properties={data.properties || []} value={state.filters.property_ids[0] || ''} disabled={state.taskScoped} onChange={id => filter('property_ids', id ? [id] : [])} />
          {state.taskScoped && <p className="kwb-rail-note">当前按任务中 {taskProperties.length} 项明确物理量筛选。</p>}
          <div className="kwb-rail-foot"><Icon.Atom /><span>科研知识工作台<small>理论 · 物理量 · 关联证据</small></span></div>
        </aside>
        <main className="kwb-main" aria-label={state.mode === 'graph' ? '知识图谱' : '知识分类矩阵'}>
          {(staleResources.length > 0 || errorResources.length > 0) && <div className="kwb-connection-banner" role="status"><Icon.AlertCircle /><span>{staleResources.length ? `正在显示上次成功读取的缓存 · 只读${staleResources[0].savedAt ? ` · ${new Date(staleResources[0].savedAt).toLocaleTimeString('zh-CN')}` : ''}` : '无法连接知识库，当前内容不可编辑'}<small>{(errorResources[0]?.error || staleResources[0]?.error)?.message}</small></span><button type="button" onClick={data.reload}>重新连接</button></div>}
          {state.scene.allAssociations && state.mode === 'graph' && <div className="kwb-scope-banner"><span>全部关联 · 图谱暂时扩展到当前筛选范围之外</span><button type="button" onClick={() => dispatch({ type: 'back' })}>返回原范围</button></div>}
          {state.mode === 'graph' && data.filters.keyword && <div className="kwb-scope-banner"><span>{summaryPending ? '检索结果正在更新…' : `当前筛选匹配 ${number(matchedTotal)} 条知识`} · 可逐条查看完整检索结果</span><button type="button" onClick={openMatrix}>逐条查看结果</button></div>}
          {state.mode === 'graph' ? <KnowledgeGraphView
            graphData={graphData} loading={graph.status === 'loading'} graphReady={Boolean(graph.data)} selectedCategory={state.filters.category}
            selectedNodeId={state.selectedId} onSelectNode={select} onEnterCategory={enterCategory} onEnterProperty={enterProperty}
            onFocus={focus} onShowAllRelations={showAllRelations} onOpenMatrix={openMatrix} onBack={() => dispatch({ type: 'back' })} canGoBack={state.history.length > 0}
            nodeBudget={state.graphLimit} onBudgetChange={limit => dispatch({ type: 'graphBudget', limit })}
            sceneKey={data.sceneKey} viewState={state.cameras[data.sceneKey]} onViewStateChange={value => dispatch({ type: 'camera', key: data.sceneKey, value })}
            readOnly={readOnly} pendingIds={pendingIds} {...actions} {...editActions}
          /> : <KnowledgeListView
            items={items} categories={categories} selectedCategory={state.filters.category} mode={state.listMode} onModeChange={mode => dispatch({ type: 'listMode', mode })}
            selectedId={state.selectedId} total={list.data?.total || 0} offset={state.offset} limit={state.listMode === 'table' ? state.tableLimit : 24}
            onPageChange={offset => dispatch({ type: 'page', offset })} onPageSizeChange={limit => dispatch({ type: 'pageSize', limit })}
            sort={state.filters.sort} onSortChange={sort => filter('sort', sort)} loading={list.status === 'loading'} readOnly={readOnly} pendingIds={pendingIds}
            onSelectNode={select} {...actions} {...editActions}
          />}
          {main.status === 'error' && !main.data && <div className="kwb-load-error" role="alert"><Icon.Network /><h3>暂时无法读取知识库</h3><p>{main.error?.message}</p><button type="button" onClick={data.reload}>重新读取</button></div>}
          {editorLoading && <div className="kwb-editor-loading" role="status">正在读取完整条目…</div>}
        </main>
      </div>
      <footer className="kwb-statusbar" role="status" aria-live="polite">
        <span className="kwb-status-summary"><span className={`kwb-status-dot ${staleResources.length || errorResources.length ? 'is-offline' : isLoading ? 'is-loading' : ''}`} />{isLoading ? '正在读取知识库…' : `${number(matchedTotal)} 条匹配 / ${number(total)} 条知识`}{selectedCategory && <span className="kwb-status-category"> · {selectedCategory.label}</span>}</span>
        <span className="kwb-status-context">{state.mode === 'graph' && graph.data?.meta ? `${graph.data.meta.view === 'overview' && Number.isFinite(graph.data.meta.represented_entries) ? `聚合覆盖 ${number(graph.data.meta.represented_entries)} 条知识` : `显示 ${number(graph.data.meta.shown_entries)} 条知识`} · ${number(graph.data.meta.node_count)} 个节点${graph.data.meta.truncated && graph.data.meta.view !== 'overview' ? ' · 已限制图谱规模，可搜索定位其余条目' : ''}` : state.mode === 'matrix' && list.data ? `当前 ${number(items.length)} / ${number(list.data.total)} 条` : ''}</span>
        <span>{pendingIds.size ? `正在保存 ${pendingIds.size} 项…` : staleResources.length ? '缓存只读' : errorResources.length ? '连接中断' : Number.isFinite(summary.data?.revision) ? `修订 ${summary.data.revision}` : '等待连接'}</span>
      </footer>
      </div>
      {detailVisible && <div className="kwb-detail-slot" inert={editor || categoryManagerOpen || relationEditor ? '' : undefined} aria-hidden={editor || categoryManagerOpen || relationEditor ? true : undefined}>
        <KnowledgeDrawer item={selectedShell} categories={categories} allNodes={graphData.nodes} topologyLinks={graphData.edges}
          loading={detail.status === 'loading' || detail.status === 'idle'} readOnly={readOnly || detail.readOnly} pending={pendingIds.has(state.selectedId)}
          loadError={detail.status === 'error' ? detail.error?.message : null} onRetry={data.reload}
          onClose={dismissDetail} onSelectNode={select} onFocus={focus} onShowAllRelations={showAllRelations} {...actions} {...editActions}
          onManageRelations={openRelationManager}
        />
      </div>}
      {editor && <Suspense fallback={<div className="kwb-connection-banner" role="status">正在读取知识编辑器…</div>}><KnowledgeEditorModal isOpen={Boolean(editor)} mode={editor?.mode || 'create'} initialData={editor?.item || null} existingCategories={categoryCatalog} categoryCatalogReady={Boolean(catalogMetadata)}
        readOnly={readOnly} connecting={isLoading} onReconnect={data.reload} onCreateCategory={data.createCategory} knownProperties={data.properties || []} onSave={async (payload, mode) => { const result = await notifyMutation(() => data.save(payload, mode), mode === 'fork' ? '知识已派生入库' : mode === 'edit' ? '知识条目已更新' : '知识已入库'); closeEditor(); return result }} onClose={closeEditor} /></Suspense>}
      {categoryManagerOpen && <Suspense fallback={<div className="kwb-connection-banner" role="status">正在读取分类管理…</div>}><KnowledgeCategoryManager categories={categoryCatalog} catalogRevision={catalogMetadata?.revision} readOnly={data.categoryResource.readOnly} loading={data.categoryResource.status === 'loading'} loadError={data.categoryResource.error?.message}
        onCreate={data.createCategory} onRename={data.renameCategory} onUpdate={data.updateCategory} onReorder={data.reorderCategories} onDelete={data.removeCategory} onReload={data.reload} onClose={closeCategoryManager} /></Suspense>}
      {relationEditor && <Suspense fallback={<div className="kwb-connection-banner" role="status">正在读取关联管理…</div>}><KnowledgeRelationManager key={relationEditor.id} item={relationEditor} categories={categoryCatalog} readOnly={readOnly || detail.readOnly} connecting={isLoading}
        onReloadLatest={data.loadEntry} onReconnect={data.reload} onClose={closeRelationManager}
        onSave={(id, payload) => notifyMutation(() => data.manageRelations(id, payload), '知识关联已更新')} /></Suspense>}
    </div>
  )
}
