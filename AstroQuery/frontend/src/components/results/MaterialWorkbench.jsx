import { useDeferredValue, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useRememberedState } from '@/hooks/useViewMemory'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { titleText } from '@/lib/researchDisplay'
import * as api from '@/services/api'
import { FigureGallery, MaterialArchiveCard } from './MaterialsV1'
import ResearchMaterialDetail from './ResearchMaterialDetail'
import { RecordsTable } from './ResultTabs'
import './material-workbench.css'

const PAGE = 20
const FIGURE_PAGE = 12
const EMPTY = []

export function useWorkbenchPage(scope, resource, query, enabled = true) {
  const { taskId, deliveryId, revision } = scope
  const argumentsKey = JSON.stringify(query)
  const key = JSON.stringify([taskId, deliveryId, revision, resource, argumentsKey])
  const [state, setState] = useState({})
  const [version, setVersion] = useState(0)
  useEffect(() => {
    if (!enabled || !taskId || !deliveryId || !revision) return
    const controller = new AbortController()
    api.getWorkbenchPage(taskId, deliveryId, revision, resource, JSON.parse(argumentsKey), { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setState({ key, version, value }) })
      .catch(error => { if (!controller.signal.aborted) setState({ key, version, error: error.message }) })
    return () => controller.abort()
  }, [key, version, enabled])
  const current = state.key === key ? state : {}
  return { ...current, retry: () => setVersion(n => n + 1) }
}

function Loading({ page, label }) {
  if (page.error) return <p role="alert" className="resource-error">
    {page.error} <button className="text-link" onClick={page.retry}>重试</button>
  </p>
  return <p className="hint" role="status">正在读取{label}…</p>
}

function PageControls({ page, count, size, setPage, label }) {
  const last = Math.max(1, Math.ceil(count / size))
  if (last < 2) return null
  return <nav className="research-pagination-bar" aria-label={label}>
    <button className="research-pagination-pill" disabled={page === 1} onClick={() => setPage(page - 1)}>
      <Icon.ChevronLeft style={{ width: 13, height: 13 }} />上一页
    </button>
    <span className="research-pagination-indicator">第 {page} / {last} 页</span>
    <button className="research-pagination-pill" disabled={page >= last} onClick={() => setPage(page + 1)}>
      下一页<Icon.ChevronRight style={{ width: 13, height: 13 }} />
    </button>
  </nav>
}

export function CandidateMaterials({ scope, memory, onOpen, active = true, opened, propertyRequest }) {
  const label = usePropertyLabel()
  const [property, setProperty] = useRememberedState(memory, 'property', null)
  const [output, setOutput] = useRememberedState(memory, 'output', 'all')
  const [kind, setKind] = useRememberedState(memory, 'kind', 'all')
  const [search, setSearch] = useRememberedState(memory, 'search', '')
  const [page, setPage] = useRememberedState(memory, 'page', 1)
  const query = useDeferredValue(search.trim())
  const result = useWorkbenchPage(scope, 'materials', {
    candidates_only: true, property_id: property, output,
    material_type: kind, search: query, limit: PAGE, offset: (page - 1) * PAGE,
  }, active)
  const properties = result.value?.properties || memory.properties || EMPTY
  const selectedProperty = result.value?.selected_property_id
    || (properties.some(p => p.property_id === property) ? property : properties[0]?.property_id) || ''
  useEffect(() => {
    if (!propertyRequest) return
    setProperty(propertyRequest.id)
    setPage(1)
  }, [propertyRequest])
  useEffect(() => { if (result.value?.properties) memory.properties = result.value.properties }, [result.value, memory])
  useEffect(() => {
    if (result.value && page > 1 && result.value.total <= (page - 1) * PAGE)
      setPage(Math.max(1, Math.ceil(result.value.total / PAGE)))
  }, [result.value, page])
  const change = setter => event => { setter(event.target.value); setPage(1) }
  const selectedName = properties.find(p => p.property_id === selectedProperty)?.name
  return <div className="materials-browser research-materials workbench-candidates" hidden={opened}>
    <div className="materials-unified-toolbar">
      <div className="materials-search-box">
        <Icon.Search className="search-icon-svg" />
        <input className="workspace-search-compact" type="search" placeholder="搜索题名、作者或附表" aria-label="搜索候选资料"
          value={search} onChange={change(setSearch)} />
      </div>
      <div className="workbench-filter-selects">
        <select className="materials-select-compact" aria-label="性质" value={selectedProperty} onChange={change(setProperty)} disabled={!properties.length}>
          {properties.map(p => <option key={p.property_id} value={p.property_id}>{label(p.name)}</option>)}
        </select>
        <select className="materials-select-compact" aria-label="产出情况" value={output} onChange={change(setOutput)}>
          <option value="all">全部产出</option>
          <option value="both">有数据和图像</option>
          <option value="data">仅有数据</option>
          <option value="figures">仅有图像</option>
          <option value="none">无数据和图像</option>
        </select>
        <select className="materials-select-compact" aria-label="资料类型" value={kind} onChange={change(setKind)}>
          <option value="all">全部资料类型</option>
          <option value="paper">论文</option>
          <option value="catalog">星表</option>
          <option value="cited">引用资料</option>
        </select>
      </div>
    </div>
    {result.value ? <>
      <div className="materials-slim-stats-row">{result.value.total} 份资料</div>
      {result.value.items.length > 0 && <section className="workbench-material-group">
        <h3>{label(selectedName)}</h3>
        <div className="materials-cards-grid">
          {result.value.items.map(item => <MaterialArchiveCard key={item.group_id}
            m={{ ...item, material_id: item.group_id }}
            onOpenSource={() => onOpen(item.group_id, item.property_id)} />)}
        </div>
      </section>}
      {!result.value.total && <div className="materials-empty-box">没有符合筛选条件的资料</div>}
      <PageControls page={page} count={result.value.total} size={PAGE} setPage={setPage} label="候选资料分页" />
    </> : <Loading page={result} label="候选资料" />}
  </div>
}

function Summary({ scope, item, readOnly }) {
  const [summary, setSummary] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const stored = summary || item.summary || {}
  async function generate() {
    setBusy(true); setError('')
    try {
      setSummary(await api.generateMaterialSummary(scope.taskId, scope.deliveryId, {
        delivery_revision: scope.revision, material_id: item.group_id, property_id: item.property_id,
      }))
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return <section className="report-section workbench-material-summary" aria-label="提取总结">
    <h3>提取总结</h3>
    {stored.text && <p>{stored.text}</p>}
    {!stored.text && <div className="workbench-summary-state">
      {busy || stored.state === 'pending' ? <span role="status">正在生成资料总结…</span>
        : <span>总结暂未生成</span>}
      {!readOnly && !busy && stored.state !== 'pending' && item.property_id &&
        <Button variant="outline" size="sm" onClick={generate}>{stored.state === 'failed' ? '重试' : '生成总结'}</Button>}
    </div>}
    {error && <p className="resource-error" role="alert">{error}</p>}
  </section>
}

function MaterialRecords({ scope, item, sources, file, selection, onRecord }) {
  const section = file?.material_id ?? 'main'
  const count = file?.record_count ?? item.body_record_count
  const key = `astroquery.material.page.${scope.taskId}.${scope.deliveryId}.${scope.revision}.${item.group_id}.${item.property_id}.${section}`
  const [page, setPage] = useRememberedState(useRef({}).current, 'page', 1, key)
  const rows = useWorkbenchPage(scope, 'material_records', {
    material_id: item.group_id, property_id: item.property_id, record_section: section,
    limit: PAGE, offset: (page - 1) * PAGE,
  }, count > 0)
  const ids = rows.value?.ids || EMPTY
  const label = file ? (file.table_id || file.title) : item.kind === 'paper' ? '正文测量' : '测量记录'
  const selected = selection && ids.every(id => selection.has('records', id))
  return <div className="workbench-material-records">
    <div className="workbench-section-heading">
      {file ? <h4 tabIndex={-1}>{label} · {count} 条</h4> : <h3>{label} · {count} 条</h3>}
      {selection && ids.length > 0 && <button className="text-link" onClick={() => {
        const pageItems = new Map(rows.value.items.map(row => [row.record_id, row]))
        selection.toggle('records', ids.map(id => pageItems.get(id) || {
          record_id: id, field_name: item.property_name, source_id: file?.material_id || item.group_id,
          source_title: file?.title || item.title,
        }))
      }}>{selected ? '取消全选本组' : '全选本组测量'}</button>}
    </div>
    {count > 0 && (rows.value ? <>
      <RecordsTable key={page} records={rows.value.items} allRecordCount={rows.value.total} sources={sources}
        onRowClick={onRecord} selection={selection} externalPage />
      <PageControls page={page} count={rows.value.total} size={PAGE} setPage={setPage} label={`${label}分页`} />
    </> : <Loading page={rows} label="测量" />)}
  </div>
}

function Attachment({ file, source, scope, item, sources, selection, onRecord }) {
  const [expanded, setExpanded] = useState(false)
  const artifact = source?.artifact || source?.schema_artifact
  return <div className="workbench-attachment" data-attachment-id={file.material_id}>
    <div className="workbench-attachment-tools">
      {artifact?.artifact_id && <a className="text-link" href={api.artifactUrl(scope.taskId, artifact.artifact_id)}
        target="_blank" rel="noreferrer">打开原表</a>}
      {source && <button className="text-link" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? '收起附表信息' : '查看附表信息'}
      </button>}
    </div>
    {expanded && <ResearchMaterialDetail embeddedInfo scope={{ ...scope, deliveryRevision: scope.revision }}
      source={source} materials={sources} onOpenRecord={onRecord} />}
    <MaterialRecords scope={scope} item={item} file={file} sources={sources} selection={selection} onRecord={onRecord} />
  </div>
}

export function MaterialPage({ scope, entry, selection, onBack, onOpenDetail, onAsk, readOnly }) {
  const label = usePropertyLabel()
  const [figurePage, setFigurePage] = useState(1)
  const heading = useRef(null)
  const page = useRef(null)
  const params = { material_id: entry.id, property_id: entry.property, sealed_only: readOnly || undefined,
    at_seq: scope.atSeq }
  const result = useWorkbenchPage(scope, 'materials', params)
  const item = result.value?.items?.[0]
  useEffect(() => {
    if (readOnly || item?.summary?.state !== 'pending') return
    const timer = setInterval(result.retry, 5000)
    return () => clearInterval(timer)
  }, [readOnly, item?.summary?.state, entry.id, scope.revision])
  const figures = useWorkbenchPage(scope, 'material_figures',
    { ...params, limit: FIGURE_PAGE, offset: (figurePage - 1) * FIGURE_PAGE }, !!item?.figure_count)
  const onRecord = record => onOpenDetail({ type: 'record', record })
  const sources = item ? [item.material, ...item.related_materials] : EMPTY
  useEffect(() => {
    if (!item) return
    const file = item.attachments.find(file => file.material_id === entry.id)
    const fileHeading = file && page.current?.querySelector(`[data-attachment-id="${CSS.escape(file.material_id)}"] h4`)
    if (fileHeading) fileHeading.scrollIntoView({ block: 'nearest' })
    const title = fileHeading || heading.current
    title?.focus({ preventScroll: true })
  }, [item?.group_id, item?.property_id, entry.id])
  return <div ref={page} className="workbench-material-page">
    <button type="button" className="text-link workbench-back" onClick={onBack}>
      <Icon.ChevronLeft style={{ width: 16, height: 16 }} />返回候选数据
    </button>
    {!item ? <Loading page={result} label="资料" /> : <>
      <header className="workbench-material-heading">
        <div>
          <p>{label(item.property_name)} · {item.record_count} 条测量 · {item.figure_count} 幅图像</p>
          <h2 ref={heading} tabIndex={-1}>{item.title}</h2>
        </div>
        {onAsk && !readOnly && <Button size="sm" variant="outline"
          onClick={() => onAsk({ markers: [`SOURCE:${item.group_id}`, ...(item.property_id ? [`DEF:${item.property_id}`] : [])],
            prompt: `请解释这份资料与${label(item.property_name)}的关系。` })}>就此追问</Button>}
      </header>
      <ResearchMaterialDetail embeddedInfo scope={{ ...scope, deliveryRevision: scope.revision }}
        summary={<Summary key={scope.revision} scope={scope} item={item} readOnly={readOnly} />}
        source={item.material} sources={sources} materials={sources}
        onOpenRecord={onRecord} onOpenSource={source => onOpenDetail({ type: 'source', source })} />
      {(item.body_record_count > 0 || (item.kind === 'paper' && item.attachments.length > 0)) &&
        <section className="report-section workbench-material-data">
          <MaterialRecords scope={scope} item={item} sources={sources} selection={selection} onRecord={onRecord} />
        </section>}
      {item.attachments.length > 0 && <section className="report-section workbench-material-data">
        <h3>官方附表</h3>
        {item.attachments.map(file => <Attachment key={file.material_id} file={file}
          source={sources.find(s => s.material_id === file.material_id)} scope={scope}
          item={item} sources={sources} selection={selection} onRecord={onRecord} />)}
      </section>}
      {!!item.figure_count && <section className="report-section">
        <div className="workbench-section-heading"><h3>研究图像 · {item.figure_count} 幅</h3>
          {selection && figures.value?.ids?.length > 0 && <button className="text-link" onClick={() => selection.toggle('figures',
            figures.value.ids.map(id => figures.value.items.find(f => f.figure_id === id) ||
              { figure_id: id, source_id: item.group_id, source_title: item.title }))}>
            {figures.value.ids.every(id => selection.has('figures', id)) ? '取消本资料的全部图像' : '选择本资料的全部图像'}
          </button>}
        </div>
        {figures.value ? <>
          <FigureGallery figures={figures.value.items} galleryIds={figures.value.ids} selection={selection}
            onOpenFigure={figure => onOpenDetail({ type: 'figure', figure })} />
          <PageControls page={figurePage} count={figures.value.total} size={FIGURE_PAGE} setPage={setFigurePage} label="资料图像分页" />
        </> : <Loading page={figures} label="研究图像" />}
      </section>}
      {item.output === 'none' && <p className="hint">本次未提取到数据或图像</p>}
    </>}
  </div>
}
