import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import { createPortal } from 'react-dom'
import { useRememberedState, useScrollMemory } from '@/hooks/useViewMemory'
import AnalysisView, { ModificationRecords, Pagination } from './AnalysisView'
import { fieldDistribution, percentScore } from '@/lib/resultData'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { sourceName } from '@/lib/readableData'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { RecordsTable, SourcesList, OutputFiles } from './ResultTabs'
import { FigureThumb, FigureLightboxModal, QualityReport, InsightsReport } from '@/components/layout/DetailPanel'
import ExportDialog from './ExportDialog'
import MeasurementDistribution from './ConsensusScatterModule'
import RelationshipGraph from './AstrophysicsNetworkModule'
import { buildDupIndex } from '@/lib/dupMarkers'
import { exactRecordIds, modificationReport, modifiedRecordIds, qualitySummary, riskMessages, executionTraces, executionTraceCount } from '@/lib/resultData'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import * as api from '@/services/api'
const EMPTY = []

export function ResourceState({ resource, label, onRetry, children }) {
  if (!resource || resource.status === 'waiting') return <p className="hint" role="status">{resource?.ended ? `本次任务未生成${label}，可查看已有执行内容。` : `${label}将在任务完成后统一展示`}</p>
  const hasData = resource.data != null
  if (!hasData && ['idle', 'loading', 'settling'].includes(resource.status)) return <p className="hint" role="status">{label}整理中…</p>
  return <>{resource.status === 'error' && <div className="resource-error" role="alert">{label}读取失败：{resource.error}<Button variant="outline" size="sm" onClick={onRetry}>重试</Button></div>}{resource.refreshing && hasData && <p className="hint" role="status">正在刷新{label}…</p>}{hasData && children}</>
}
export function ResultSummary({ data }) {
  const { resources: r } = data
  const score = percentScore(qualitySummary(r.quality.data)?.overall_score ?? r.quality.data?.quality_report?.report_state?.quality?.quality_scoring?.overall_score)
  return <div className="result-summary result-stat-strip">{[['记录', r.records], ['来源', r.sources], ['研究图像', r.figures]].map(([label, resource]) => <div key={label}><span>{label}</span><strong className={!Array.isArray(resource.data) ? 'stat-state' : undefined}>{Array.isArray(resource.data) ? resource.data.length : resource.status === 'error' ? '读取失败' : '整理中'}</strong></div>)}<div><span>综合质量</span><strong className={score == null ? 'stat-state' : undefined}>{score == null ? r.quality.status === 'error' ? '读取失败' : r.quality.status === 'success' ? '未提供' : '整理中' : score.toFixed(2)}{score != null && <small> /100</small>}</strong></div></div>
}
export function CompletionOutcome({ data, onOpenData }) {
  const propertyLabel = usePropertyLabel()
  const r = data.resources, records = r.records.data
  const distribution = fieldDistribution(records), total = records?.length || 0
  return <section className="completion-outcome" data-component="completion-outcome"><header><div><span className="eyebrow">任务成果</span><h2>数据提取已完成</h2></div><Button variant="accent" size="sm" onClick={() => onOpenData('records')}>查看数据结果 →</Button></header><ResultSummary data={data} /><p className="outcome-description">{Array.isArray(records) ? `已整理 ${total} 条记录，覆盖 ${distribution.length} 项性质。可查看测量记录、出处和研究图像。` : '正在整理本次任务的最终记录与证据。'}</p><ResourceState resource={r.records} label="记录分布" onRetry={() => data.reload('records')}><div className="outcome-distribution">{distribution.map(item => <button key={item.field} onClick={() => onOpenData('records', { fieldName: item.field })}><span>{propertyLabel(item.field)}</span><div><i style={{ width: `${total ? item.count / total * 100 : 0}%` }} /></div><strong>{item.count}<small> 条 ›</small></strong></button>)}</div></ResourceState></section>
}
// Kept as an export for older imports; raw flags live only in report details.
export function RiskNotice() { return null }
export function ModificationTable(props) { return <ModificationRecords {...props} /> }

function ExportCenter({ task, records, resources, onClose, reload }) {
  const [tab, setTab] = useState('filtered')
  const dismissal = useDismissTransition(onClose)
  const ref = useDialogFocus(true, dismissal.close)
  const contentRef = useRef(null), navRef = useRef(null)
  const panes = useSlidingPanes(contentRef, tab, ['filtered', 'files'])
  useSlidingUnderline(navRef, tab)
  return <div className="settings-overlay" data-closing={dismissal.closing || undefined} onClick={dismissal.close}><section ref={ref} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} role="dialog" aria-modal="true" aria-labelledby="export-center-title" tabIndex={-1} className="export-center selecting export-direct animate-modal-in" onClick={event => event.stopPropagation()}>
    <header className="settings-header"><h2 id="export-center-title">导出结果</h2><Button variant="outline" size="sm" onClick={dismissal.close}>关闭</Button></header>
    <div ref={navRef} className="workspace-chips export-tabs" aria-label="导出范围">{[['filtered', '当前筛选数据'], ['files', '既有任务文件与数据包']].map(([key, label]) => <button className={`filter-chip${tab === key ? ' active' : ''}`} aria-pressed={tab === key} key={key} onClick={() => setTab(key)}>{label}</button>)}</div>
    <div ref={contentRef} className="export-panes slide-panes" data-sliding={panes.moving || undefined}><div data-export-pane {...panes.paneProps('filtered', 'flex')} className="export-filtered-pane"><ExportDialog embedded open taskId={task.task_id} records={records} sources={resources.sources.data || EMPTY} onClose={dismissal.close} /></div>
    <div data-export-pane {...panes.paneProps('files')} className="export-center-body"><ResourceState resource={resources.exports} label="任务文件" onRetry={() => reload('exports')}>{resources.exports.data?.length ? <OutputFiles files={resources.exports.data} taskId={task.task_id} /> : <p>该任务未提供输出文件</p>}</ResourceState></div></div>
  </section></div>
}

export default function DataView({ memory = {}, task, data, pipeline, request, onOpenDetail, active = true }) {
  const propertyLabel = usePropertyLabel()
  const { resources: r, reload } = data
  const records = Array.isArray(r.records.data) ? r.records.data : EMPTY
  const sources = Array.isArray(r.sources.data) ? r.sources.data : EMPTY
  const figures = Array.isArray(r.figures.data) ? r.figures.data : EMPTY
  const quality = r.quality.data
  const [section, setSection] = useRememberedState(memory, 'section', 'records'), [search, setSearch] = useRememberedState(memory, 'search', ''), [quick, setQuick] = useRememberedState(memory, 'quick', 'all')
  const [filteredRows, setFilteredRows] = useState(null)
  const [fieldRequest, setFieldRequest] = useRememberedState(memory, 'fieldRequest', null)
  const [sourceRequest, setSourceRequest] = useRememberedState(memory, 'sourceRequest', null), [recordRequest, setRecordRequest] = useRememberedState(memory, 'recordRequest', null)
  const [exportOpen, setExportOpen] = useState(false), [deleteTarget, setDeleteTarget] = useState(null), [deleting, setDeleting] = useState(false)
  const deleteDismissal = useDismissTransition(() => { if (!deleting) setDeleteTarget(null) }, { active: !!deleteTarget, identity: deleteTarget })
  const deleteRef = useDialogFocus(!!deleteTarget, () => { if (!deleting) deleteDismissal.close() })
  const [figure, setFigure] = useState(null), [figurePage, setFigurePage] = useState(1)
  const locatedRequest = useRef(null)
  const { toast } = useToast()
  const dupIndex = useMemo(() => buildDupIndex(records, quality?.quality_report), [r.records.data, quality])
  const modified = useMemo(() => modifiedRecordIds(quality), [quality])
  const visible = useMemo(() => records.filter(record => quick === 'all' || (quick === 'modified' ? modified.has(record.record_id) : dupIndex.byRecordId[record.record_id]?.group.liveCount >= 2)), [r.records.data, quick, modified, dupIndex])
  const onFilteredChange = useCallback(rows => setFilteredRows(rows), [])
  const insights = pipeline.insights || quality?.quality_report?.output_state?.insights || quality?.quality_report?.report_state?.insights
  useEffect(() => { if (!active) { setExportOpen(false); setDeleteTarget(null); setFigure(null) } }, [active])
  useEffect(() => {
    if (!request) return
    setSection(request.section || 'records')
    if (request.fieldName) { setQuick('all'); setSearch(''); setFieldRequest({ id: request.fieldName, seq: request.seq }) }
    if (request.export) setExportOpen(true)
    if (request.sourceId) { setQuick('all'); setSearch(''); setSourceRequest({ id: request.sourceId, seq: request.seq }) }
    if (request.recordId) { setQuick('all'); setSearch(''); setRecordRequest({ id: request.recordId, seq: request.seq }) }
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
  const deleteRecord = async () => {
    if (deleting) return
    setDeleting(true)
    try { await api.deleteRecord(task.task_id, deleteTarget.record_id); setDeleteTarget(null); await reload(); toast('记录已删除', 'success') } catch (err) { toast(`删除失败：${err.message}`, 'error') } finally { setDeleting(false) }
  }
  const scroll = useScrollMemory(memory, r.records.data != null, active)
  const panesRef = useRef(null), tabsRef = useRef(null)
  const panes = useSlidingPanes(panesRef, section, ['records', 'evidence', 'analysis'], { active, identity: task?.task_id })
  useSlidingUnderline(tabsRef, `${section}:${data.availability}:${active}`)
  const tableMemory = memory.table ||= {}
  if (!task) return <div className="empty-state">选择任务后查看数据结果</div>
  if (data.availability === 'waiting') return <div className="data-workbench"><div className="data-heading"><h2>数据结果</h2></div><section className="result-pending"><span className="eyebrow">{pipeline.taskDone ? '任务已结束' : '结果生成中'}</span><h3>{pipeline.taskDone ? (task.status === 'cancelled' ? '任务已取消' : '任务未完成') : pipeline.stages.find(stage => stage.status === 'running')?.name || (pipeline.started ? '等待最终结果' : '任务尚未开始')}</h3><p>{pipeline.taskDone ? '可在对话与工作流中查看已有执行内容。' : '任务完成后，此处统一展示记录、来源、研究图像和报告。'}</p><div className="pending-stage-list">{pipeline.stages.filter(stage => stage.id !== 'done').map(stage => <div key={stage.id}><span>{stage.name}</span><strong>{({completed:'已完成',running:'执行中',waiting:'未开始',skipped:'已跳过',error:'失败',cancelled:'已取消'})[stage.status] || stage.status}</strong></div>)}</div></section></div>
  const qState = quality?.quality_report?.report_state?.quality
  const conflicts = quality?.quality_report?.report_state?.conflict
  const normalization = quality?.quality_report?.report_state?.normalization
  const issueItems = [ ...(Array.isArray(normalization?.modifications?.errors) ? normalization.modifications.errors : []), ...(Array.isArray(conflicts?.resolution_report?.annotations) ? conflicts.resolution_report.annotations : []) ]
  return <div {...scroll} className={`data-workbench${section === 'records' ? ' records-workbench' : ''}`} data-component="data-view">
    <h2 className="sr-only">数据结果</h2><div className="data-result-tools"><ResultSummary data={data} /><Button variant="accent" size="sm" onClick={() => setExportOpen(true)}>导出结果</Button></div>{data.availability === 'partial' && <p className="notice">任务未完成，以下为接口提供的部分结果。</p>}
    <nav ref={tabsRef} className="data-tabs" aria-label="数据结果分类">{[['records', '记录'], ['evidence', '来源与图像'], ['analysis', '质量与洞察']].map(([key, label]) => <button key={key} className={`tab-btn${section === key ? ' active' : ''}`} onClick={() => setSection(key)}>{label}</button>)}</nav>
    <div ref={panesRef} className="data-panes slide-panes" data-sliding={panes.moving || undefined}>
    <div {...panes.paneProps('records')} className="records-section data-section">
      <ResourceState resource={r.records} label="记录" onRetry={() => reload('records')}>

        {r.quality.status === 'error' && <ResourceState resource={r.quality} label="修改与重复标记" onRetry={() => reload('quality')} />}
        {records.length ? <RecordsTable memory={tableMemory} active={active && section === 'records'} filterRecords={records} filterKey={quick} externalFiltered={quick !== 'all'} onResetFilters={() => { setSearch(''); setQuick('all') }} toolbarExtra={<div className="records-toolbar-extra"><input aria-label="搜索记录" className="workspace-search" placeholder="搜索天体、性质、值或来源" value={search} onChange={event => setSearch(event.target.value)} /><div className="workspace-chips">{[['all', '全部'], ['modified', '有修改记录'], ['duplicate', '疑似重复']].map(([key, label]) => <button key={key} aria-pressed={quick === key} className={`filter-chip${quick === key ? ' active' : ''}`} disabled={key !== 'all' && r.quality.status !== 'success'} onClick={() => setQuick(key)}>{label}</button>)}</div></div>} records={visible} onRowClick={record => onOpenDetail({ type: 'record', record })} searchText={search} sources={sources} dupIndex={dupIndex} onFilteredChange={onFilteredChange} forcedField={fieldRequest} forcedSource={sourceRequest} forcedRecord={recordRequest} onDeleteRecord={task.source === 'sample' || task.replay_of ? undefined : setDeleteTarget} /> : <p className="hint">本次任务未产生记录</p>}
      </ResourceState>
    </div>
    <div {...panes.paneProps('evidence')} className="evidence-layout data-section">
      <section className="report-section"><h3>来源清单</h3><ResourceState resource={r.sources} label="来源" onRetry={() => reload('sources')}>{sources.length ? <SourcesList sources={sources} onOpenSource={source => onOpenDetail({ type: 'source', source })} /> : <p className="hint">该任务未提供来源</p>}</ResourceState></section>
      <section data-page-region className="report-section"><h3>研究图像</h3><ResourceState resource={r.figures} label="研究图像" onRetry={() => reload('figures')}>{figures.length ? <><div data-page-content className="figure-grid">{figures.slice((Math.min(figurePage, Math.ceil(figures.length / 12)) - 1) * 12, Math.min(figurePage, Math.ceil(figures.length / 12)) * 12).map((fig, index) => <article className="figure-card" key={fig.id || index}><button className="figure-button" onClick={() => setFigure(fig)} aria-label={`查看研究图像 ${index + 1}`}><FigureThumb fig={fig} height={160} /></button><p>{fig.caption || '该记录未提供图注'}</p><span className="hint">{fig.page != null ? `第 ${fig.page} 页 · ` : ''}{sourceName(sources.find(source => source.source_id === fig.source_id), fig.source_id, true)}</span>{fig.source_id && <button className="text-link" onClick={() => { const source = sources.find(item => item.source_id === fig.source_id); if (source) onOpenDetail({ type: 'source', source }); else toast('该研究图像来源未在来源清单中提供', 'info') }}>查看来源</button>}</article>)}</div><Pagination total={figures.length} page={figurePage} onPage={setFigurePage} size={12} /></> : <p className="hint">该任务未提供研究图像</p>}</ResourceState></section>
    </div>
    <div className="data-section" {...panes.paneProps('analysis')}><ResourceState resource={r.quality} label="质量报告" onRetry={() => reload('quality')}><AnalysisView quality={quality} records={records} sources={sources} insights={insights} active={active && section === 'analysis'} onLocateRecord={locateRecord} onOpenRecords={field => { setSection('records'); setQuick('all'); setSearch(''); setFieldRequest({ id: field, seq: Date.now() }) }} onOpenRecord={record => onOpenDetail({ type: 'record', record })} onOpenSource={source => onOpenDetail({ type: 'source', source })} /></ResourceState></div>
    </div>
    {figure && createPortal(<FigureLightboxModal fig={figure} onClose={() => setFigure(null)} />, document.body)}
    {exportOpen && createPortal(<ExportCenter task={task} records={filteredRows || visible} resources={r} reload={reload} onClose={() => setExportOpen(false)} />, document.body)}
    {deleteTarget && createPortal(<div className="settings-overlay" data-closing={deleteDismissal.closing || undefined}><section ref={deleteRef} data-closing={deleteDismissal.closing || undefined} onAnimationEnd={deleteDismissal.onAnimationEnd} onKeyDownCapture={deleteDismissal.onKeyDownCapture} tabIndex={-1} role="dialog" aria-modal="true" aria-label="确认删除记录" className="confirm-dialog"><h3>删除这条实操记录？</h3><p>{deleteTarget.field_name} = {String(deleteTarget.field_value)} {deleteTarget.field_unit}</p><p>删除不可恢复，将影响后续导出。</p><div className="workspace-chips"><Button variant="outline" disabled={deleting} onClick={deleteDismissal.close}>取消</Button><Button variant="destructive" disabled={deleting} onClick={deleteRecord}>{deleting ? '删除中…' : '确认删除'}</Button></div></section></div>, document.body)}
  </div>
}
