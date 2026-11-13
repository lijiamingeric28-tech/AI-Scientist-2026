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
import { CandidateMaterials, MaterialPage } from './MaterialWorkbench'
import MaterialsV1 from './MaterialsV1'
import { titleText } from '@/lib/researchDisplay'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import BackToTop from '@/components/ui/BackToTop'
import { RecordsTable, OutputFiles } from './ResultTabs'
import { buildDupIndex } from '@/lib/dupMarkers'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import * as api from '@/services/api'
const AnalysisView = lazy(() => import('./AnalysisView'))
const ExportDialog = lazy(() => import('./ExportDialog'))
const WorkbenchExport = lazy(() => import('./WorkbenchExport'))

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
    ['资料', 'materials'],
    ['研究图像', 'figures'],
  ].map(([label, key]) => {
    const resource = resources[key]
    const count = counts[key] ?? (Array.isArray(resource?.data) ? resource.data.length : null)
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
          <span title={item.label === '资料' ? '同一份资料可计入多个已确认性质' : undefined}>{item.label}</span>
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
    <div data-export-pane {...panes.paneProps('files')} className="export-center-body"><ResourceState resource={resources.exports} label="任务文件" onRetry={() => reload('exports')}>{resources.exports.data?.length ? <OutputFiles files={resources.exports.data} taskId={task.task_id} /> : <p>当前修订没有已生成的输出文件</p>}</ResourceState><BackToTop active={tab === 'files'} /></div></div>
  </section></div>
}

const TABS = [
  ['candidates', '候选数据'], ['details', '全部数据'], ['overview', '任务评分'],
  ['trace', '处理溯源'], ['comparison', '对照与覆盖'],
]
const REPORTS = ['overview', 'trace', 'comparison']

function requestedTab(request) {
  if (request.section === 'candidates' || request.materialId) return 'candidates'
  if (request.recordId || request.fieldName || request.sourceId || request.figureId || request.figureSection || request.section === 'records')
    return 'details'
  if (request.section === 'analysis') return REPORTS.includes(request.analysisTab) ? request.analysisTab
    : request.analysisTab === 'insights' ? 'candidates' : 'overview'
  return TABS.some(([key]) => key === request.section) ? request.section : 'candidates'
}

export default function DataView({ memory = {}, task, data, pipeline, request, onOpenDetail, onAsk, selection, active = true }) {
  const { resources: r, reload, ensure } = data
  const taskId = task?.task_id
  const deliveryId = task?.delivery_ref?.id, revision = task?.delivery_ref?.version
  const headKey = `${taskId}:${deliveryId}:${revision}`
  const sessionKey = !pipeline.readOnly && !task?.historicalRevision && deliveryId
    ? `astroquery.workbench.${headKey}` : undefined
  const atSeq = pipeline.readOnly && !task?.historicalRevision && task?.presentation?.delivery_ref?.id === deliveryId
    && task?.presentation?.delivery_ref?.version === revision ? task.presentation.cursor : undefined
  const scope = { taskId, deliveryId, revision, atSeq }
  const [section, setSection] = useRememberedState(memory, 'workbenchSection', 'candidates', sessionKey && `${sessionKey}.tab`)
  const revisionMemory = (memory.revisions ||= {})[headKey] ||= {}
  const [entry, setEntry] = useRememberedState(revisionMemory, 'workbenchMaterial', null, sessionKey && `${sessionKey}.material`)
  const [detailsPane, setDetailsPane] = useRememberedState(memory, 'detailsPane', 'records')
  const [propertyRequest, setPropertyRequest] = useState(null)
  const [search, setSearch] = useRememberedState(memory, 'search', '')
  const [quick, setQuick] = useRememberedState(memory, 'quick', 'target')
  const [fieldRequest, setFieldRequest] = useRememberedState(memory, 'fieldRequest', null)
  const [sourceRequest, setSourceRequest] = useRememberedState(memory, 'sourceRequest', null)
  const [recordRequest, setRecordRequest] = useRememberedState(memory, 'recordRequest', null)
  const [exportOpen, setExportOpen] = useState(false)
  const [filteredRows, setFilteredRows] = useState(null)
  const [headResult, setHeadResult] = useState(null)
  const tabs = useRef(null), located = useRef(null), handledRequest = useRef(null), focusBack = useRef(null)
  const { toast } = useToast()
  const readOnly = Boolean(task?.readOnly || task?.historicalRevision || pipeline.readOnly)
  const legacy = task?.legacy_version === 1
  const selectable = !legacy && !readOnly ? selection : undefined
  const records = r.records.data || EMPTY
  const sources = r.sources.data || r.sourceList.data || EMPTY
  const figures = r.figures.data || EMPTY
  const quality = r.quality.data
  const sourceLabels = useMemo(() => new Map(sources.map(s => [s.source_id, titleText(s)])), [sources])
  const dupIndex = useMemo(() => buildDupIndex(records, quality?.report?.schema_version === 'TaskCompletionScore/1'
    ? quality.report : quality?.quality_report), [records, quality])
  const modified = useMemo(() => new Set([...(modifiedRecordIds(quality) || []),
    ...(r.changes.data || []).flatMap(c => c.measurement_ids || [])]), [quality, r.changes.data])
  const visible = useMemo(() => records.filter(record => quick === 'all' || (record.record_status !== 'not_supported' &&
    (quick === 'target' || (quick === 'modified' ? modified.has(record.record_id)
      : dupIndex.byRecordId[record.record_id]?.group.liveCount >= 2)))), [records, quick, modified, dupIndex])
  const onFilteredChange = useCallback(rows => setFilteredRows(rows), [])
  const deliveryHead = headResult?.key === headKey ? headResult.head : null
  const scroll = useScrollMemory(memory, !!deliveryId, active)
  useSlidingUnderline(tabs, `${section}:${active}`)

  useEffect(() => {
    if (!active || !deliveryId) return
    let valid = true
    queueMicrotask(() => {
      if (!valid) return
      if (legacy) ensure('materials', 'records', 'sources', 'figures', 'quality')
      if (section === 'details' && detailsPane === 'records')
        ensure('records', 'sourceList', 'quality', ...(quick === 'modified' ? ['changes'] : []))
      if (section === 'details' && detailsPane === 'figures') ensure('figures', 'sourceList')
      if (section === 'overview') ensure('quality', 'sourceList')
      if (section === 'trace') ensure('quality', 'activity', 'records', 'sourceList')
      if (section === 'comparison') ensure('quality', 'activity', 'records', 'sourceList', 'differences', 'matrix')
      if (exportOpen) ensure('exports', 'sourceList', ...(legacy ? ['records', 'sources'] : []))
    })
    return () => { valid = false }
  }, [active, deliveryId, revision, section, detailsPane, quick, exportOpen, legacy, ensure])

  useEffect(() => {
    if (!active || !deliveryId || !revision || deliveryHead || legacy) return
    const controller = new AbortController()
    api.getDelivery(taskId, revision, { deliveryId, signal: controller.signal }).then(head => {
      if (!controller.signal.aborted && head.delivery_id === deliveryId && head.revision === revision)
        setHeadResult({ key: headKey, head })
    }).catch(() => {})
    return () => controller.abort()
  }, [active, headKey, deliveryHead, legacy])

  function changeTab(next) {
    if (next === section) return
    setSection(next)
    requestAnimationFrame(() => {
      if (scroll.ref.current) scroll.ref.current.scrollTop = next === 'details' ? memory.detailsTop?.[detailsPane] || 0 : 0
    })
  }
  function changeDetailsPane(next, restore = true) {
    const container = scroll.ref.current
    if (section === 'details' && container) (memory.detailsTop ||= {})[detailsPane] = container.scrollTop
    setDetailsPane(next)
    requestAnimationFrame(() => {
      if (scroll.ref.current) scroll.ref.current.scrollTop = restore ? memory.detailsTop?.[next] || 0 : 0
    })
  }
  function openMaterial(id, property) {
    if (!id) return
    if (!entry) {
      memory.candidateScroll = scroll.ref.current?.scrollTop || 0
      focusBack.current = document.activeElement
    }
    setEntry({ id, property })
    changeTab('candidates')
    if (scroll.ref.current) scroll.ref.current.scrollTop = 0
  }
  function backToCandidates() {
    setEntry(null)
    requestAnimationFrame(() => {
      if (scroll.ref.current) scroll.ref.current.scrollTop = memory.candidateScroll || 0
      focusBack.current?.focus({ preventScroll: true })
    })
  }
  useEffect(() => {
    if (!request || !active || handledRequest.current === request) return
    handledRequest.current = request
    const next = requestedTab(request)
    changeTab(next)
    if (next === 'details') changeDetailsPane(request.figureId || request.figureSection ? 'figures' : 'records', false)
    if (next === 'candidates' && !request.materialId) {
      setEntry(null)
      if (scroll.ref.current) scroll.ref.current.scrollTop = 0
      if (request.propertyId) setPropertyRequest({ id: request.propertyId, seq: request.seq })
    }
    if (request.fieldName) setFieldRequest({ id: request.fieldName, seq: request.seq })
    if (request.sourceId) setSourceRequest({ id: request.sourceId, seq: request.seq })
    if (request.recordId) setRecordRequest({ id: request.recordId, seq: request.seq })
    if (request.materialId) openMaterial(request.materialId, request.propertyId)
    if (request.export) setExportOpen(true)
  }, [request, active])
  useEffect(() => { if (!active) setExportOpen(false) }, [active])
  useEffect(() => {
    if (!active || located.current === request?.seq) return
    if (request?.recordId && r.records.status === 'success') {
      located.current = request.seq
      const record = records.find(item => item.record_id === request.recordId)
      if (record) onOpenDetail({ type: 'record', record })
      else toast('当前成果没有这条测量', 'info')
    }
    if (request?.figureId && r.figures.status === 'success') {
      located.current = request.seq
      const figure = figures.find(item => item.figure_id === request.figureId)
      if (figure) onOpenDetail({ type: 'figure', figure })
      else toast('当前成果没有这幅图像', 'info')
    }
  }, [active, request, r.records.status, records, r.figures.status, figures])
  const locateRecord = id => {
    const record = records.find(item => item.record_id === id)
    if (record) onOpenDetail({ type: 'record', record })
    else toast('当前成果没有这条测量', 'info')
  }
  const tableMemory = memory.table ||= {}
  const materialMemory = memory.workbenchMaterials ||= {}

  if (!task) return <div className="empty-state">选择任务后查看数据结果</div>
  if (data.availability === 'waiting') return <div className="data-workbench">
    <div className="data-heading"><h2>数据结果</h2></div>
    <section className="result-pending">
      <h3>{pipeline.taskDone ? '此任务没有可查看的成果' : '等待科研数据'}</h3>
      <TemporaryPreview preview={data.preview} />
    </section>
    <BackToTop active={active} />
  </div>

  const summary = pipeline.presentation?.delivery_summary
  const counts = summary?.delivery_ref?.id === deliveryId && summary?.delivery_ref?.version === revision
    ? { ...deliveryHead?.display_counts, ...summary }
    : deliveryHead?.display_counts || {}
  const exportScope = { ...task, readOnly }
  return <div {...scroll} className="data-workbench workbench-result" data-component="data-view">
    <h2 className="sr-only">数据结果</h2>
    <div className="data-view-unified-header">
      <nav ref={tabs} className="data-tabs compact-data-tabs" aria-label="数据结果分类">
        {TABS.map(([key, label]) => <button key={key} aria-current={section === key ? 'page' : undefined}
          className={`tab-btn${section === key ? ' active' : ''}`} onClick={() => {
            if (key === 'candidates' && section === 'candidates' && entry) backToCandidates()
            else changeTab(key)
          }}>{label}</button>)}
      </nav>
      <div className="data-header-right-tools">
        <ResultSummary data={data} counts={counts} />
        <div className="research-result-actions compact-actions">
          {selectable && (selection.measurementIds.length > 0 || selection.figureIds.length > 0) &&
            <button className="text-link" onClick={() => setExportOpen(true)}>
              已选 {selection.measurementIds.length} 条数据 · {selection.figureIds.length} 幅图像
            </button>}
          {selectable && onAsk && selection.measurementIds.length > 0 && <button className="text-link"
            onClick={() => onAsk({ recordIds: selection.measurementIds.slice(0, 40), prompt: '请比较我选中的测量。' })}>就所选测量追问</button>}
          <Button variant="accent" size="sm" onClick={() => setExportOpen(true)}>导出结果</Button>
        </div>
      </div>
    </div>

    {section === 'candidates' && <div className="data-section">
      {legacy ? <Suspense fallback={<ResourceLoading label="资料" />}>
        <ResourceState resource={r.materials} label="资料" onRetry={() => reload('materials')}>
          <MaterialsV1 mode="materials" materials={r.materials.data || EMPTY} sources={sources}
            onOpenSource={source => onOpenDetail({ type: 'source', source })} />
        </ResourceState>
      </Suspense> : <>
        <CandidateMaterials scope={scope} memory={materialMemory} active={active && !entry}
          opened={!!entry} propertyRequest={propertyRequest} onOpen={openMaterial} />
        {entry && <MaterialPage key={`${entry.id}:${entry.property || ''}`} scope={scope} entry={entry}
          selection={selectable} onBack={backToCandidates} onOpenDetail={onOpenDetail} readOnly={readOnly}
          onAsk={onAsk} />}
      </>}
    </div>}
    {section === 'details' && <div className="data-section workbench-query-details">
      <nav className="workspace-chips" aria-label="全部数据分类">
        {[['records', '测量记录'], ['figures', '研究图像']].map(([key, label]) =>
          <button type="button" key={key} className={`filter-chip${detailsPane === key ? ' active' : ''}`}
            aria-pressed={detailsPane === key} onClick={() => { if (detailsPane !== key) changeDetailsPane(key) }}>{label}</button>)}
      </nav>
      {detailsPane === 'records' ? <section aria-label="测量记录">
        {request?.recordId && filteredRows && !filteredRows.some(record => record.record_id === request.recordId) &&
          <p className="notice">这条测量在当前筛选之外。<button className="text-link" onClick={() => {
            setQuick('all'); setSearch(''); setFieldRequest({ id: 'all', seq: Date.now() }); setSourceRequest({ id: 'all', seq: Date.now() })
          }}>显示此记录</button></p>}
        <ResourceState resource={r.records} label="记录" onRetry={() => reload('records')}>
          {records.length ? <RecordsTable memory={tableMemory} records={visible} filterRecords={records} allRecordCount={records.length}
            externalFiltered={quick !== 'all'} onResetFilters={() => { setSearch(''); setQuick('target') }}
            search={search} onSearchChange={setSearch} quick={quick} onQuickChange={setQuick} selection={selectable}
            onRowClick={record => onOpenDetail({ type: 'record', record })} sources={sources} dupIndex={dupIndex}
            onFilteredChange={onFilteredChange} forcedField={fieldRequest} forcedSource={sourceRequest}
            forcedRecord={recordRequest} onOpenSource={legacy ? undefined : openMaterial} />
            : <p className="hint">本次没有测量记录</p>}
        </ResourceState>
      </section> : <section aria-label="研究图像">
        <Suspense fallback={<ResourceLoading label="研究图像" />}>
          <MaterialsV1 mode="figures" active={active} figures={figures} figuresLoading={pendingResource(r.figures)}
            figuresError={r.figures.status === 'error'} onRetryFigures={() => reload('figures')}
            properties={pipeline.presentation?.properties || EMPTY} memory={memory.workbenchFigures ||= {}}
            sources={sources} selection={selectable}
            onOpenFigure={figure => onOpenDetail({ type: 'figure', figure })} />
        </Suspense>
      </section>}
    </div>}
    {REPORTS.includes(section) && <div className="data-section">
      <Suspense fallback={<ResourceLoading label="报告" />}>
        <ResourceState resource={r.quality} label="任务报告" onRetry={() => reload('quality')}>
          <AnalysisView standaloneTab={section} resourceLoading={Object.fromEntries(['matrix', 'differences', 'activity']
            .map(key => [key, pendingResource(r[key])]))} memory={memory.analysis ||= {}} requestKey={request?.seq}
            matrix={r.matrix.data || EMPTY} activity={r.activity.data || EMPTY} differences={r.differences.data}
            requestProperty={request?.propertyId} resourceErrors={Object.fromEntries(['matrix', 'differences', 'activity']
              .map(key => [key, r[key].status === 'error' ? r[key].error : null]))} onRetry={reload} quality={quality}
            records={records} sources={sources} active={active} onLocateRecord={locateRecord}
            onOpenRecords={(field, sourceId) => {
              changeTab('details'); changeDetailsPane('records', false); setQuick('all'); setSearch(''); setFieldRequest({ id: field, seq: Date.now() })
              setSourceRequest({ id: sourceId || 'all', seq: Date.now() })
            }} onOpenRecord={record => onOpenDetail({ type: 'record', record })}
            onOpenSource={source => openMaterial(source?.source_id || source?.material_id)} />
        </ResourceState>
      </Suspense>
    </div>}
    <BackToTop active={active} />
    {exportOpen && createPortal(legacy ? <ExportCenter task={exportScope} records={filteredRows || visible} resources={r}
      reload={reload} onClose={() => setExportOpen(false)} /> : <Suspense fallback={<ResourceLoading label="导出选项" />}><WorkbenchExport key={headKey} scope={scope} selection={selection}
      resources={r} sourceLabels={sourceLabels} reload={reload} readOnly={readOnly} onClose={() => setExportOpen(false)} /></Suspense>, document.body)}
  </div>
}
