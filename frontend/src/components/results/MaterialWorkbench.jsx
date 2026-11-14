import './task-insights.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useRememberedState } from '@/hooks/useViewMemory'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { titleText, displayText } from '@/lib/researchDisplay'
import * as api from '@/services/api'
import { workbenchQuery, workbenchReadKey } from '@/services/workbenchReads'
import { FigureGallery, MaterialArchiveCard } from './MaterialsV1'
import ResearchMaterialDetail from './ResearchMaterialDetail'
import MaterialReading,{MaterialIdentity,MaterialOverview,READING_SECTIONS,useReadingVisibility} from './MaterialReading'
import { RecordsTable } from './ResultTabs'
import './material-workbench.css'

const PAGE = 20
const FIGURE_PAGE = 12
const EMPTY = []
const EMPTY_SUMMARY = {}

function useDebouncedSearch(value) {
  const [query, setQuery] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setQuery(value), 250)
    return () => clearTimeout(timer)
  }, [value])
  return query
}

export function useWorkbenchPage(scope, resource, query, enabled = true) {
  const { taskId, deliveryId, revision } = scope
  const argumentsKey = JSON.stringify(workbenchQuery(scope, query))
  const key = workbenchReadKey(scope, resource, query)
  const [state, setState] = useState({})
  const [version, setVersion] = useState(0)
  useEffect(() => {
    if (!enabled || !taskId || !deliveryId || !revision) return
    const controller = new AbortController()
    api.getWorkbenchPage(taskId, deliveryId, revision, resource, JSON.parse(argumentsKey), { signal: controller.signal, protocol:scope.protocol })
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

export function PageControls({ page, count, size, setPage, label }) {
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
  const query = useDebouncedSearch(search.trim())
  const result = useWorkbenchPage(scope, 'materials', {
    candidates_only: true, group_by: 'material', property_id: property, output,
    material_type: kind, search: query, limit: PAGE, offset: (page - 1) * PAGE,
  }, active && query === search.trim())
  const properties = result.value?.properties || memory.properties || EMPTY
  const selectedProperty = property || ''
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
        <input className="workspace-search-compact" type="search" placeholder="搜索题名、作者或附表" aria-label="搜索资料"
          value={search} onChange={change(setSearch)} />
      </div>
      <div className="workbench-filter-selects">
        <select className="materials-select-compact" aria-label="性质" value={selectedProperty} onChange={change(setProperty)} disabled={!properties.length}>
          <option value="">全部性质</option>{properties.map(p => <option key={p.property_id} value={p.property_id}>{label(p.name)}</option>)}
        </select>
        <select className="materials-select-compact" aria-label="产出情况" value={output} onChange={change(setOutput)}>
          <option value="all">全部产出</option>
          <option value="both">有数据和图像</option>
          <option value="data">仅有数据</option>
          <option value="figures">仅有图像</option>
          <option value="none">无数据和图像</option>
        </select>
        <select className="materials-select-compact" aria-label="资料类型" value={kind} onChange={change(setKind)}>
          <option value="all">论文与星表</option>
          <option value="paper">论文</option>
          <option value="catalog">星表</option>
          <option value="cited">引用线索（单独查看）</option>
        </select>
      </div>
    </div>
    {result.value ? <>
      <div className="materials-slim-stats-row">当前筛选：{result.value.total} {kind==='cited'?'项引用线索':'份去重资料'}<span className="hint">{kind==='cited'?'尚未解析的引文保持原标识，不按相同题名猜测合并。':'论文与明确关联的附表合为一份；引用线索可单独查看。'}</span></div>
      {result.value.items.length > 0 && <section className="workbench-material-group">
        <h3>{selectedName?label(selectedName):'全部资料'}</h3>
        <div className="materials-cards-grid">
          {result.value.items.map(item => <div className="grouped-material-card" key={item.group_id}><MaterialArchiveCard
            m={{ ...item, material_id: item.group_id }}
            onOpenSource={() => onOpen(item.group_id, item.property_id)} /><div className="reading-properties">{item.available_properties?.map(p=><button className="filter-chip" key={p.property_id} onClick={()=>onOpen(item.group_id,p.property_id)}>{label(p.name)} <small>{p.record_count}</small></button>)}</div></div>)}
        </div>
      </section>}
      {!result.value.total && <div className="materials-empty-box">没有符合筛选条件的资料</div>}
      <PageControls page={page} count={result.value.total} size={PAGE} setPage={setPage} label="候选资料分页" />
    </> : <Loading page={result} label="候选资料" />}
  </div>
}

export function Summary({ scope, item, readOnly, active, onOpenDetail, onSummary }) {
  const [summary, setSummary] = useState(() => item.summary || null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const visited = useRef(false)
  const stored = summary || item.summary || EMPTY_SUMMARY
  useEffect(()=>onSummary?.(stored),[stored,onSummary])
  const historical = readOnly || scope.atSeq != null || scope.sealedOnly
  const summaryQuery = workbenchQuery(scope, { material_id:item.group_id, property_id:item.property_id, projection:'summary' })
  const summaryKey = workbenchReadKey(scope, 'materials', summaryQuery)
  const confirm = useCallback(signal => api.getWorkbenchPage(scope.taskId, scope.deliveryId, scope.revision,
    'materials', summaryQuery, {signal,protocol:scope.protocol})
    .then(value => { if (!signal.aborted) { setSummary(value.summary || {}); setError('') } })
    .catch(e => { if (!signal.aborted) setError(e.message) }), [summaryKey])
  useEffect(() => {
    if (!active || historical) return
    const controller = new AbortController()
    // The first full read already includes the current summary. Static cache
    // hits and later activations confirm only this small dynamic projection.
    if (visited.current || !item.summary) confirm(controller.signal)
    visited.current = true
    return () => controller.abort()
  }, [active, historical, confirm])
  useEffect(() => {
    if (!active || historical || stored.state !== 'pending') return
    const controller = new AbortController()
    let pending = false
    const timer = setInterval(() => {
      if (pending) return
      pending = true
      confirm(controller.signal).finally(() => { pending = false })
    }, 5000)
    return () => { clearInterval(timer); controller.abort() }
  }, [active, historical, stored.state, confirm])
  async function generate() {
    if (historical) return
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
      {false && !busy && stored.state !== 'pending' && item.property_id &&
        <Button variant="outline" size="sm" onClick={generate}>{stored.state === 'failed' ? '重试' : '生成总结'}</Button>}
    </div>}
    {stored.basis && <>
      <div className="summary-basis-links">
        <button className="text-link" type="button" onClick={()=>onOpenDetail?.({type:'summary-basis',tab:'evidence',basis:stored.basis,taskId:scope.taskId,answerScope:{delivery_id:scope.deliveryId,delivery_revision:scope.revision,at_seq:scope.atSeq,sealed_only:scope.sealedOnly}})}>原文依据（{stored.basis.evidence?.length||0}）</button>
        <button className="text-link" type="button" onClick={()=>onOpenDetail?.({type:'summary-basis',tab:'knowledge',basis:stored.basis,taskId:scope.taskId,answerScope:{delivery_id:scope.deliveryId,delivery_revision:scope.revision,at_seq:scope.atSeq,sealed_only:scope.sealedOnly}})}>输入知识背景（{stored.basis.knowledge?.length||0}）</button>
      </div>
      <p className="hint">知识条目是提供给生成模型的背景，不代表总结逐句实际引用。</p>
    </>}
    {stored.state==='failed'&&<p className="hint">资料总结未完成：{stored.reason||'生成失败'}。已保存的依据仍可查阅。</p>}
    {error && <p className="resource-error" role="alert">{error}</p>}
  </section>
}

function MaterialRecords({ scope, item, sources, file, selection, onRecord, active = true }) {
  const section = file?.material_id ?? 'main'
  const count = file?.record_count ?? item.body_record_count
  const key = `astroquery.material.page.${scope.taskId}.${scope.deliveryId}.${scope.revision}.${item.group_id}.${item.property_id}.${section}`
  const [page, setPage] = useRememberedState(useRef({}).current, 'page', 1, key)
  const rows = useWorkbenchPage(scope, 'material_records', {
    material_id: item.group_id, property_id: item.property_id, record_section: section,
    limit: PAGE, offset: (page - 1) * PAGE,
  }, active && count > 0)
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

function Attachment({ file, source, scope, item, sources, selection, onRecord, active = true }) {
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
    <MaterialRecords scope={scope} item={item} file={file} sources={sources} selection={selection} onRecord={onRecord} active={active} />
  </div>
}

export function MaterialPage({ scope, entry, memory = {}, selection, onBack, onOpenDetail, onAsk, onCompare, readOnly, active = true }) {
  const entryMemory = useRef(memory[entry.id] ||= {}).current
  const [property,setProperty] = useRememberedState(entryMemory,`property:${entry.property||'default'}`,entry.property)
  const [dataTab,setDataTab] = useRememberedState(entryMemory,'dataTab','records')
  const [figurePage,setFigurePage] = useRememberedState(entryMemory,'figurePage',1)
  const [anchor,setAnchor] = useRememberedState(entryMemory,'readingTab','reading')
  const heading = useRef(null),page = useRef(null),attachmentEntered=useRef(false),pendingAnchor=useRef(null)
  const [dataRef,dataEnabled] = useReadingVisibility(active)
  const params = { material_id: entry.id, property_id: property, sealed_only: scope.sealedOnly || undefined, at_seq: scope.atSeq }
  const result = useWorkbenchPage(scope,'materials',params,active)
  const item = result.value?.items?.[0]
  const summaryScopeKey=workbenchReadKey(scope,'materials',params)
  const [summaryState,setSummaryState]=useState({})
  const shareSummary=useCallback(summary=>setSummaryState(previous=>previous.key===summaryScopeKey&&previous.summary===summary?previous:{key:summaryScopeKey,summary}),[summaryScopeKey])
  const readingItem=item&&{...item,summary:summaryState.key===summaryScopeKey?summaryState.summary:item.summary}
  const figures = useWorkbenchPage(scope,'material_figures',{...params,limit:FIGURE_PAGE,offset:(figurePage-1)*FIGURE_PAGE},active&&anchor==='data'&&dataTab==='figures'&&!!item?.figure_count)
  const answerScope={delivery_id:scope.deliveryId,delivery_revision:scope.revision,at_seq:scope.atSeq,sealed_only:scope.sealedOnly}
  const onRecord = record => onOpenDetail({type:'record',record,taskId:scope.taskId,answerScope})
  const sources = item ? [item.material,...item.related_materials] : EMPTY
  useEffect(()=>{
    if(!active||!item)return
    const attachment=item.attachments?.find(file=>file.material_id===entry.id)
    if(attachment&&!attachmentEntered.current){attachmentEntered.current=true;setDataTab('attachments');setAnchor('data');setTimeout(()=>page.current?.querySelector(`[data-attachment-id="${CSS.escape(entry.id)}"] h4`)?.scrollIntoView({block:'nearest'}),0)}
    heading.current?.focus({preventScroll:true})
  },[active,item?.group_id,item?.property_id])
  const settleNavigation=useCallback(id=>{if(pendingAnchor.current!==id)return;requestAnimationFrame(()=>{if(pendingAnchor.current!==id)return;pendingAnchor.current=null;page.current?.querySelector(`#reading-${id}`)?.scrollIntoView({block:'start',behavior:'instant'})})},[])
  const jump=id=>setAnchor(id)
  return <div ref={page} className="workbench-material-page material-reading-page" onWheel={()=>{pendingAnchor.current=null}} onTouchStart={()=>{pendingAnchor.current=null}}>
    <button type="button" className="text-link workbench-back" onClick={onBack}><Icon.ChevronLeft style={{width:16,height:16}}/>返回资料目录</button>
    {!item?<Loading page={result} label="资料"/>:<>
      <MaterialIdentity scope={scope} item={item} headingRef={heading} onSources={()=>setAnchor('sources')} onProperty={pid=>{setProperty(pid);setFigurePage(1)}} onAsk={onAsk&&!readOnly?()=>onAsk({markers:[`SOURCE:${item.group_id}`,`DEF:${item.property_id}`],prompt:`请解释这份资料与${item.property_name}的关系。`}):undefined}/>
      <nav className="reading-local-nav" aria-label="资料详情目录">{READING_SECTIONS.map(([id,name])=><button key={id} type="button" aria-current={anchor===id?'true':undefined} onClick={()=>jump(id)}>{name}</button>)}</nav>
      <MaterialReading onCompare={onCompare} key={`${item.group_id}:${item.property_id}`} scope={scope} item={readingItem} active={active&&anchor==='reading'} onOpenDetail={onOpenDetail} onAsk={onAsk&&!readOnly?onAsk:undefined} summary={<Summary key={workbenchReadKey(scope,'materials',params)} scope={scope} item={item} readOnly={readOnly} active={active&&anchor==='reading'} onOpenDetail={onOpenDetail} onSummary={shareSummary}/>}/>
      <section id="reading-data" hidden={anchor!=='data'} ref={dataRef} className="reading-section" aria-label="数据与图像">
        <div className="reading-section-heading"><Icon.Database width="17" height="17"/><h3>数据与图像</h3></div>
        <nav className="workspace-chips reading-data-tabs" aria-label="本资料产出分类">{[['records',`测量记录 ${item.body_record_count}`],['attachments',`官方附表 ${item.attachments.length}`],['figures',`研究图像 ${item.figure_count}`]].map(([key,name])=><button type="button" key={key} className={`filter-chip${dataTab===key?' active':''}`} aria-pressed={dataTab===key} onClick={()=>setDataTab(key)}>{name}</button>)}</nav>
        <div className="reading-data-panel" hidden={dataTab!=='records'}><MaterialRecords key={`${item.group_id}:${item.property_id}:main`} scope={scope} item={item} sources={sources} selection={selection} onRecord={onRecord} active={active&&anchor==='data'&&dataTab==='records'}/>{!item.body_record_count&&<p className="hint">正文未保存当前性质的测量；可查阅关联附表与图像。</p>}</div>
        <div className="reading-data-panel" hidden={dataTab!=='attachments'}>{item.attachments.map(file=><Attachment key={`${file.material_id}:${item.property_id}`} file={file} source={sources.find(s=>s.material_id===file.material_id)} scope={scope} item={item} sources={sources} selection={selection} onRecord={onRecord} active={active&&anchor==='data'&&dataTab==='attachments'}/>)}{!item.attachments.length&&<p className="hint">未保存明确关联的官方附表。</p>}</div>
        <div className="reading-data-panel" hidden={dataTab!=='figures'}>
          {selection&&figures.value?.ids?.length>0&&<button className="text-link" onClick={()=>selection.toggle('figures',figures.value.ids.map(id=>figures.value.items.find(f=>f.figure_id===id)||{figure_id:id,source_id:item.group_id,source_title:item.title}))}>{figures.value.ids.every(id=>selection.has('figures',id))?'取消本资料的全部图像':'选择本资料的全部图像'}</button>}
          {!!item.figure_count?(figures.value?<><FigureGallery figures={figures.value.items} galleryIds={figures.value.ids} selection={selection} onOpenFigure={figure=>onOpenDetail({type:'figure',figure,taskId:scope.taskId,answerScope})}/><PageControls page={figurePage} count={figures.value.total} size={FIGURE_PAGE} setPage={setFigurePage} label="资料图像分页"/></>:<Loading page={figures} label="研究图像"/>):<p className="hint">当前性质未保存明确关联的研究图像。</p>}
        </div>
      </section>
      <section id="reading-sources" hidden={anchor!=='sources'} className="reading-section" aria-label="完整题录与来源"><div className="reading-section-heading"><Icon.BookOpen width="17" height="17"/><h3>完整题录与来源</h3></div>{anchor==='sources'&&<div className="reading-source-disclosure">{item.material?.authors?.length>0&&<details><summary>完整作者 · {item.material.authors.length} 位</summary><p>{item.material.authors.map(displayText).join('；')}</p></details>}<ResearchMaterialDetail embeddedInfo scope={{...scope,deliveryRevision:scope.revision}} source={item.material} sources={sources} materials={sources} onOpenRecord={onRecord} onOpenSource={source=>onOpenDetail({type:'source',source,taskId:scope.taskId,answerScope})}/></div>}</section>
    </>}
  </div>
}
