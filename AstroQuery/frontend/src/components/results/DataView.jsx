import ResourceState from './ResourceState'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import TemporaryPreview from './TemporaryPreview'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import { createPortal } from 'react-dom'
import { useRememberedState, useScrollMemory } from '@/hooks/useViewMemory'
import { fieldDistribution, modifiedRecordIds } from '@/lib/resultData'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { sourceName } from '@/lib/readableData'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { RecordsTable, OutputFiles } from './ResultTabs'
import { buildDupIndex } from '@/lib/dupMarkers'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import * as api from '@/services/api'
const MaterialsV1 = lazy(() => import('./MaterialsV1'))
const AnalysisView = lazy(() => import('./AnalysisView'))
const ExportDialog = lazy(() => import('./ExportDialog'))

const EMPTY = []
const ResourceLoading = ({label}) => <p className="hint" role="status">正在读取{label}…</p>
const pendingResource = resource => !['success', 'error'].includes(resource.status)


function ControlledCoverage({ rows = EMPTY }) {
  const catalogs = rows.filter(c => c.outcome === 'not_checked_time_control')
  const versions = [...new Map(rows.flatMap(c => (c.skipped_versions || []).map(v =>
    [v.artifact?.artifact_id || `${v.work_id}:${v.url}`, { ...v, titles: c.titles }])).map(v => v)).values()]
  if (!catalogs.length && !versions.length) return null
  const skipped = [...new Set(catalogs.flatMap(c => [c.table_id, ...(c.not_checked_table_ids || []), ...(c.unscreened_table_ids || [])]).filter(Boolean))]
  const count = catalogs.find(c => c.deep_tables != null)?.deep_tables
  return <section className="report-section">
    {!!catalogs.length && <><p>{count != null ? ` 本次深入处理${count}张表。` : ''}</p>
      {!!skipped.length && <details><summary>{skipped.length}张表因本次筛选或耗时控制未查完</summary>{skipped.map(t => <p key={t}>{t}</p>)}</details>}</>}
    {!!versions.length && <details><summary>{versions.length}份PDF超过50个物理页，整份跳过；避免排入{versions.reduce((n,v) => n + v.page_count, 0)}页</summary>{versions.map((v,i) => <p key={i}>{v.titles?.join('；') || v.work_id} · {v.page_count}页 · 未安排正文、图证或回读。{v.url && <a href={v.url} target="_blank" rel="noreferrer">该稿来源</a>}</p>)}</details>}
  </section>
}

function FigureCoverage({ figures, sources = EMPTY }) {
  const coverage = figures.coverage || []
  if (!coverage.length) return null
  const incomplete = coverage.filter(c => ['failed', 'uncertain'].includes(c.state))
  const absent = coverage.filter(c => c.state === 'checked_no_relevant')
  const layoutOnly = coverage.filter(c => c.state === 'no_candidates')
  const reason = c => ({FIGURE_CAPTION_UNSUPPORTED: '图注未能与当前页原文核对', FIGURE_RESPONSE_INVALID: '模型未返回一致的图证结论', FIGURE_ASSOCIATION_UNSUPPORTED: '目标关联依据未能与原文核对', unclassified_scan_pages: '扫描页缺少图页定位线索，尚未确认是否有相关图'})[c.reason] || c.meaning || '图证处理未完成，原始论文仍保留'
  return <details className="figure-coverage"><summary>图像检查范围</summary><p>{absent.length ? ` ${absent.length} 个候选页已检查，没有相关图。` : ''}{layoutOnly.length ? ` ${layoutOnly.length} 篇论文的版面未发现候选图。` : ''}</p>{incomplete.length > 0 && <details><summary>{incomplete.length} 处图像关联待核实</summary>{incomplete.map((c, i) => <p key={i}>{sourceName(sources.find(s => s.source_id === c.source_id), c.source_id, true)}{c.page ? ` · 第 ${c.page} 页` : ''}：{reason(c)}</p>)}</details>}</details>
}

export function ResultSummary({ data, counts = {} }) {
  const { resources } = data
  const quality = resources.quality?.data
  const qualityReport = quality?.protocol_version === 2 ? quality.report : quality?.quality_report
  const score = quality?.score ?? quality?.body?.score ?? qualityReport?.score ?? qualityReport?.overall_score ?? counts.score

  const items = [
    ['记录', 'records'],
    ['来源资料', 'sources'],
    ['研究图像', 'figures'],
  ].map(([label, key]) => {
    const resource = resources[key]
    const count = Array.isArray(resource?.data) ? resource.data.length : counts[key]
    return {
      label,
      value: count ?? (resource?.status === 'error' ? '待查' : '…'),
    }
  })

  if (score != null) {
    items.push({
      label: '综合质量',
      value: `${score}`,
      suffix: '/100',
    })
  }

  return (
    <div className="result-summary result-stat-strip">
      {items.map(item => (
        <div key={item.label} className="result-stat-item">
          <strong>
            {item.value}
            {item.suffix && <small>{item.suffix}</small>}
          </strong>
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  )
}
export function CompletionOutcome({ data, onOpenData }) {
  const propertyLabel = usePropertyLabel()
  const r = data.resources, records = r.records.data
  const distribution = fieldDistribution(records), total = records?.length || 0
  const sourcesCount = Array.isArray(r.sources.data) ? r.sources.data.length : null
  const figuresCount = Array.isArray(r.figures.data) ? r.figures.data.length : null
  const quality = r.quality.data
  const qualityReport = quality?.protocol_version === 2 ? quality.report : quality?.quality_report
  const score = qualityReport?.score ?? qualityReport?.overall_score ?? (quality ? 100 : null)

  return (
    <section className="completion-outcome" data-component="completion-outcome">
      <header>
        <div>
          <span className="eyebrow">天体物理数据交付</span>
          <h2>数据提取与质检完成</h2>
        </div>
        <Button variant="accent" size="sm" onClick={() => onOpenData('records')}>
          查看数据结果 →
        </Button>
      </header>

      <div className="completion-metrics-grid">
        <div className="metric-card">
          <span className="metric-num">{total}</span>
          <span className="metric-label">条有效测量</span>
        </div>
        <div className="metric-card">
          <span className="metric-num">{sourcesCount ?? (r.sources.status === 'error' ? '待查' : '…')}</span>
          <span className="metric-label">份来源文献/星表</span>
        </div>
        <div className="metric-card">
          <span className="metric-num">{figuresCount ?? (r.figures.status === 'error' ? '待查' : '0')}</span>
          <span className="metric-label">幅学术图像</span>
        </div>
        <div className="metric-card">
          <span className="metric-num">{score != null ? `${score}分` : '已核验'}</span>
          <span className="metric-label">综合质检评分</span>
        </div>
      </div>

      <p className="outcome-description">
        {Array.isArray(records)
          ? `已整理 ${total} 条科研记录，覆盖 ${distribution.length} 项物理性质。可直接查阅各测量值、出处段落与天体图像。`
          : '正在整理本次任务的最终记录与证据。'}
      </p>

      <ResourceState resource={r.records} label="记录分布" onRetry={() => data.reload('records')}>
        <div className="outcome-distribution">
          {distribution.map(item => (
            <button key={item.field} onClick={() => onOpenData('records', { fieldName: item.field })}>
              <span>{propertyLabel(item.field)}</span>
              <div><i style={{ width: `${total ? (item.count / total) * 100 : 0}%` }} /></div>
              <strong>{item.count}<small> 条 ›</small></strong>
            </button>
          ))}
        </div>
      </ResourceState>
    </section>
  )
}

function ExportCenter({ task, records, resources, onClose, reload }) {
  const [tab, setTab] = useState(task.readOnly||task.historicalRevision?'files':'filtered')
  const dismissal = useDismissTransition(onClose)
  const ref = useDialogFocus(true, dismissal.close)
  const contentRef = useRef(null), navRef = useRef(null)
  const panes = useSlidingPanes(contentRef, tab, ['filtered', 'files'])
  useSlidingUnderline(navRef, tab)
  return <div className="settings-overlay" data-closing={dismissal.closing || undefined} onClick={dismissal.close}><section ref={ref} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal="true" aria-labelledby="export-center-title" tabIndex={-1} className="export-center selecting export-direct animate-modal-in" onClick={event => event.stopPropagation()}>
    <header className="settings-header"><h2 id="export-center-title">导出结果</h2><Button aria-label="关闭导出" variant="outline" size="sm" onClick={dismissal.close}>关闭</Button></header>
    <div ref={navRef} className="workspace-chips export-tabs" aria-label="导出范围">{[['filtered', '选择记录与格式'], ['files', '已生成文件']].map(([key, label]) => <button className={`filter-chip${tab === key ? ' active' : ''}`} aria-pressed={tab === key} key={key} disabled={key==='filtered'&&(task.readOnly||task.historicalRevision)} onClick={() => setTab(key)}>{label}</button>)}</div>
    <div ref={contentRef} className="export-panes slide-panes" data-sliding={panes.moving || undefined}><div data-export-pane {...panes.paneProps('filtered', 'flex')} className="export-filtered-pane"><Suspense fallback={<ResourceLoading label="导出选项" />}><ExportDialog embedded open readOnly={task.readOnly||task.historicalRevision} readOnlyReason={task.historicalRevision?'此处为历史修订。可下载本修订已有文件，创建新导出请切换到最新修订。':undefined} taskId={task.task_id} records={records} sources={resources.sources.data || EMPTY} onClose={dismissal.close} /></Suspense></div>
    <div data-export-pane {...panes.paneProps('files')} className="export-center-body"><ResourceState resource={resources.exports} label="任务文件" onRetry={() => reload('exports')}>{resources.exports.data?.length ? <OutputFiles files={resources.exports.data} taskId={task.task_id} /> : <p>当前修订没有已生成的输出文件</p>}</ResourceState></div></div>
  </section></div>
}

export default function DataView({ memory = {}, task, data, pipeline, request, onOpenDetail, onSelectRevision, active = true }) {
  const propertyLabel = usePropertyLabel()
  const { resources: r, reload } = data
  const order=pipeline.presentation?.properties?.map(p=>p.property_id)||[]
  const records = useMemo(()=>Array.isArray(r.records.data)?[...r.records.data].sort((a,b)=>{const x=order.indexOf(a.property_id),y=order.indexOf(b.property_id);return (x<0?999:x)-(y<0?999:y)}):EMPTY,[r.records.data,order.join(',')])
  const sources = r.sources.data || r.sourceList.data || EMPTY
  const figures = Array.isArray(r.figures.data) ? r.figures.data : EMPTY
  const quality = r.quality.data
  const [section, setSection] = useRememberedState(memory, 'section', 'records'), [search, setSearch] = useRememberedState(memory, 'search', ''), [quick, setQuick] = useRememberedState(memory, 'quick', 'target')
  const [filteredRows, setFilteredRows] = useState(null)
  const [fieldRequest, setFieldRequest] = useRememberedState(memory, 'fieldRequest', null)
  const [sourceRequest, setSourceRequest] = useRememberedState(memory, 'sourceRequest', null), [recordRequest, setRecordRequest] = useRememberedState(memory, 'recordRequest', null)
  const [exportOpen, setExportOpen] = useState(false)
  const [evidenceTab, setEvidenceTab] = useState(() => memory.materials?.tab || 'materials')
  const [analysisTab, setAnalysisTab] = useState(() => memory.analysis?.tab || 'overview')
  const { ensure } = data
  useEffect(() => {
    if (!active || !task?.delivery_ref?.id) return
    let visible = true
    queueMicrotask(() => {
      if (!visible) return
      if (section === 'records') ensure('records', task?.legacy_version ? 'sources' : 'sourceList', 'quality', ...(quick === 'modified' ? ['changes'] : []))
      if (section === 'evidence') {
        ensure('materials', 'coverage')
        if (evidenceTab === 'figures') ensure('figures', 'sources')
      }
      if (section === 'analysis') {
        ensure('quality')
        if (analysisTab === 'trace' || analysisTab === 'comparison') ensure('activity', 'records', 'sources')
        if (analysisTab === 'comparison') ensure('differences', 'matrix')
        if (analysisTab === 'insights') ensure('insights', 'records', 'sources')
      }
      if (exportOpen) ensure('records', 'sources', 'exports')
    })
    return () => { visible = false }
  }, [active, task?.delivery_ref?.id, task?.legacy_version, section, quick, exportOpen, evidenceTab, analysisTab, ensure])
  const locatedRequest = useRef(null)
  const { toast } = useToast()
  const dupIndex = useMemo(() => buildDupIndex(records, quality?.report?.schema_version === 'TaskCompletionScore/1' ? quality.report : quality?.quality_report), [r.records.data, quality])
  const modified = useMemo(() => new Set([...(modifiedRecordIds(quality)||[]),...(r.changes?.data||[]).flatMap(c=>c.measurement_ids||[])]), [quality,r.changes?.data])
  const ownerExcluded = records.filter(record => record.record_status === 'not_supported').length
  const visible = useMemo(() => records.filter(record => quick === 'all' || (record.record_status !== 'not_supported' && (quick === 'target' || (quick === 'modified' ? modified.has(record.record_id) : dupIndex.byRecordId[record.record_id]?.group.liveCount >= 2)))), [r.records.data, quick, modified, dupIndex])
  const onFilteredChange = useCallback(rows => setFilteredRows(rows), [])
  useEffect(() => { setFilteredRows(null) }, [task?.task_id, task?.delivery_ref?.version, quick])
  const insights = r.insights.data
  const [headResult, setHeadResult] = useState(null)
  const deliveryId = task?.delivery_ref?.id, deliveryRevision = task?.delivery_ref?.version
  const headKey = `${task?.task_id}:${deliveryId}:${deliveryRevision}`
  const deliveryHead = headResult?.key === headKey ? headResult.head : null
  useEffect(() => {
    if (!active || !deliveryId || !deliveryRevision || deliveryHead || task?.legacy_version) return
    const controller = new AbortController()
    api.getDelivery(task.task_id, deliveryRevision, { signal: controller.signal }).then(head => {
      if (!controller.signal.aborted && head.delivery_id === deliveryId && head.revision === deliveryRevision) setHeadResult({key: headKey, head})
    }).catch(() => {})
    return () => controller.abort()
  }, [active, headKey, deliveryHead, task?.legacy_version])
  useEffect(() => { if (!active) setExportOpen(false) }, [active])
  useEffect(() => {
    if (!request) return
    setSection(request.section || 'records')
    if (request.fieldName) { setFieldRequest({ id: request.fieldName, seq: request.seq }) }
    if (request.export) setExportOpen(true)
    if (request.sourceId) { setSourceRequest({ id: request.sourceId, seq: request.seq }) }
    if (request.recordId) { setRecordRequest({ id: request.recordId, seq: request.seq }) }
  }, [request])
  useEffect(() => {
    if (!request?.recordId || locatedRequest.current === request.seq || r.records.status !== 'success') return
    locatedRequest.current = request.seq
    const record = records.find(item => item.record_id === request.recordId)
    if (record) onOpenDetail({ type: 'record', record })
    else toast('报告关联的记录在当前结果中未提供', 'info')
  }, [request, r.records.status, r.records.data])
  const locateRecord = id => {
    const record = records.find(item => item.record_id === id)
    if (!record) { toast('报告关联的记录在当前结果中未提供，可查看其他已提供的报告内容', 'info'); return }
    onOpenDetail({ type: 'record', record })
  }
  const locatedMaterial=useRef(null)
  useEffect(()=>{
    if(!request?.materialId||locatedMaterial.current===request.seq||r.materials.status!=='success')return
    locatedMaterial.current=request.seq
    const source=r.materials.data.find(item=>[item.material_id,item.source_id,item.work_id,item.work?.work_id].includes(request.materialId))
      ||sources.find(item=>[item.source_id,item.work_id].includes(request.materialId))
    if(source)onOpenDetail({type:'source',source:{...source,task_id:task.task_id}})
    else toast('此资料未包含在当前交付档案中','info')
  },[request,r.materials.status,r.materials.data])
  const scroll = useScrollMemory(memory, r.records.data != null, active)
  const panesRef = useRef(null), tabsRef = useRef(null)
  const panes = useSlidingPanes(panesRef, section, ['records', 'evidence', 'analysis'], { active, identity: task?.task_id })
  useSlidingUnderline(tabsRef, `${section}:${data.availability}:${active}`)
  const tableMemory = memory.table ||= {}
  if (!task) return <div className="empty-state">选择任务后查看数据结果</div>
  if (data.availability === 'waiting') return <div className="data-workbench"><div className="data-heading"><h2>数据结果</h2></div><section className="result-pending">
    {!pipeline.started ? <p role="status">正在读取任务成果…</p> : <><h3>{pipeline.taskDone ? (task.status === 'cancelled' ? '任务已取消' : task.status === 'completed' ? '此任务未保存可查看的成果' : '任务未完成') : pipeline.stages.find(stage => stage.status === 'running')?.name || '等待最终结果'}</h3><p>{pipeline.taskDone ? '已有过程见执行明细。' : '任务完成后，可在此查看记录、资料和报告。'}</p><TemporaryPreview preview={data.preview} />
    {!pipeline.snapshot?.workspace_only && !pipeline.taskDone && <div className="pending-stage-list">{pipeline.stages.filter(stage => stage.id !== 'done').map(stage => <div key={stage.id}><span>{stage.name}</span><strong>{({completed:'已完成',running:'执行中',waiting:'未开始',pending:'未开始',skipped:'已跳过',error:'失败',cancelled:'已取消'})[stage.status] || stage.status}</strong></div>)}</div>}</>}
  </section></div>
  return <div {...scroll} className={`data-workbench${section === 'records' ? ' records-workbench' : ''}`} data-component="data-view">
    <h2 className="sr-only">数据结果</h2>{task.legacy_version===1&&<p className="notice">旧版历史：按原归档展示，未按新科学规则复检；缺失字段不补造。</p>}{request?.recordId && filteredRows && !filteredRows.some(r=>r.record_id===request.recordId) && <p className="notice">此记录被当前筛选隐藏。<button className="text-link" onClick={()=>{setQuick('all');setSearch('');setFieldRequest({id:'all',seq:Date.now()});setSourceRequest({id:'all',seq:Date.now()})}}>显示此记录（清除相关筛选）</button></p>}<div className="data-view-unified-header">
      <nav ref={tabsRef} className="data-tabs compact-data-tabs" aria-label="数据结果分类">
        {[['records', '记录'], ['evidence', '资料与图像'], ['analysis', '质量与洞察']].map(([key, label]) => (
          <button key={key} className={`tab-btn${section === key ? ' active' : ''}`} onClick={() => setSection(key)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="data-header-right-tools">
        <ResultSummary
          data={data}
          counts={
            (pipeline.presentation?.delivery_summary &&
            pipeline.presentation.delivery_summary.delivery_ref?.version === task.delivery_ref?.version
              ? pipeline.presentation.delivery_summary
              : deliveryHead && deliveryHead.revision === task.delivery_ref?.version
              ? deliveryHead.display_counts
              : null) || {}
          }
        />
        <div className="research-result-actions compact-actions">
          {task.legacy_version !== 1 && (
            <label className="result-version">
              交付修订{' '}
              <select
                aria-label="交付修订"
                value={task.delivery_ref?.version || ''}
                disabled={task.readOnly || !deliveryHead}
                onChange={(event) => onSelectRevision?.(Number(event.target.value))}
              >
                {(deliveryHead?.available_revisions || [task.delivery_ref?.version])
                  .filter(Boolean)
                  .filter((v) => !task.readOnly || v <= task.delivery_ref.version)
                  .map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <Button variant="accent" size="sm" onClick={() => setExportOpen(true)}>
            导出结果
          </Button>
        </div>
      </div>
    </div>
    {data.availability === 'partial' && <p className="notice">任务未完成，以下为接口提供的部分结果。</p>}
    {ownerExcluded > 0 && <p className="notice">{ownerExcluded} 条原报未归入当前目标，可在“全部原报”查看。</p>}
    <div ref={panesRef} className="data-panes slide-panes" data-sliding={panes.moving || undefined}>
    <div {...panes.paneProps('records')} className="records-section data-section">
      {panes.hasVisited('records') && <ResourceState resource={r.records} label="记录" onRetry={() => reload('records')}>

        {r.quality.status === 'error' && <ResourceState resource={r.quality} label="修改与重复标记" onRetry={() => reload('quality')} />}
        {r.sourceList.status === 'error' && !r.sources.data && <ResourceState resource={r.sourceList} label="来源名称" onRetry={() => reload('sourceList')} />}
        {records.length ? <RecordsTable memory={tableMemory} active={active && section === 'records'} filterRecords={records} allRecordCount={records.length} filterKey={quick} externalFiltered={quick !== 'all'} onResetFilters={() => { setSearch(''); setQuick('target') }} search={search} onSearchChange={setSearch} quick={quick} onQuickChange={setQuick} records={visible} onRowClick={record => onOpenDetail({ type: 'record', record })} searchText={search} sources={sources} dupIndex={dupIndex} onFilteredChange={onFilteredChange} forcedField={fieldRequest} forcedSource={sourceRequest} forcedRecord={recordRequest} /> : <p className="hint">本次任务未产生记录</p>}
      </ResourceState>}
    </div>
    <div {...panes.paneProps('evidence')} className="data-section">
      {panes.hasVisited('evidence') && <Suspense fallback={<ResourceLoading label="资料与图像" />}>
      <ResourceState resource={r.materials} label="资料档案" onRetry={()=>reload('materials')}><MaterialsV1 onVisibleTab={setEvidenceTab} figuresLoading={pendingResource(r.figures)} figuresError={r.figures.status==='error'} onRetryFigures={()=>reload('figures')} active={active && section === 'evidence'} properties={r.matrix.data?.length?r.matrix.data:(pipeline.presentation?.properties||[])} onOpenFigure={figure=>onOpenDetail({type:'figure',figure})} memory={memory.materials ||= {}} materials={(r.materials?.data||sources).map(m=>({...m,task_id:task?.task_id}))} figures={figures.map(f=>({...f,task_id:f.task_id||task?.task_id}))} sources={sources} onOpenSource={source=>source&&onOpenDetail({type:'source',source})}/></ResourceState>
      <ResourceState resource={r.coverage} label="处理范围" onRetry={()=>reload('coverage')}>{(r.coverage?.data||[]).some(row=>row.outcome==='not_checked_time_control' || row.skipped_versions?.length) && <details className="figure-coverage"><summary>资料获取范围</summary><ControlledCoverage rows={r.coverage?.data||EMPTY}/></details>}</ResourceState>
      <FigureCoverage figures={figures} sources={sources}/>
      </Suspense>}
    </div>
    <div className="data-section" {...panes.paneProps('analysis')}>{panes.hasVisited('analysis') && <Suspense fallback={<ResourceLoading label="质量报告" />}><ResourceState resource={r.quality} label="质量报告" onRetry={() => reload('quality')}><AnalysisView onVisibleTab={setAnalysisTab} resourceLoading={Object.fromEntries(['insights','matrix','differences','activity'].map(key=>[key,pendingResource(r[key])]))} memory={memory.analysis ||= {}} requestKey={request?.seq} matrix={r.matrix?.data||[]} activity={r.activity?.data||[]} differences={r.differences?.data} requestProperty={request?.propertyId} resourceErrors={Object.fromEntries(['insights','matrix','differences','activity'].map(key=>[key,r[key]?.status==='error'?r[key].error:null]))} onRetry={reload} onOpenKnowledge={block=>onOpenDetail({type:'knowledge',block})} changes={r.changes?.data||[]} requestTab={request?.analysisTab} quality={quality} records={records} sources={sources} insights={insights} active={active && section === 'analysis'} onLocateRecord={locateRecord} onOpenRecords={(field,sourceId) => { setSection('records'); setQuick('all'); setSearch(''); setFieldRequest({ id: field, seq: Date.now() }); setSourceRequest({id:sourceId||'all',seq:Date.now()}) }} onOpenRecord={record => onOpenDetail({ type: 'record', record })} onOpenSource={source => onOpenDetail({ type: 'source', source })} /></ResourceState></Suspense>}</div>
    </div>
    {exportOpen && createPortal(<ExportCenter task={{...task,readOnly:task.readOnly||pipeline.readOnly}} records={filteredRows || visible} resources={r} reload={reload} onClose={() => setExportOpen(false)} />, document.body)}
  </div>
}
