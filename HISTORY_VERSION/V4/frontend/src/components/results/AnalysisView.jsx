import { Fragment, useId, useMemo, useRef, useState } from 'react'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import { useInPlaceDisclosure } from '@/hooks/useInPlaceDisclosure'
import { usePageTransition } from '@/hooks/usePageTransition'
import { QualityScoreSection } from '@/components/layout/DetailPanel'
import MeasurementDistribution from './ConsensusScatterModule'
import RelationshipGraph from './AstrophysicsNetworkModule'
import { modificationReport, executionTraceCount, percentScore, fieldDistribution } from '@/lib/resultData'
import { readableText, modificationView, sourceExplanation, sourceName, insightGroups, normalizeInsights, SOURCE_TYPES } from '@/lib/readableData'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { DefinitionNote, Prose, References } from './ReadableContent'

export function Pagination({ total, page, onPage, size = 20 }) {
  const pages = Math.max(1, Math.ceil(total / size)), current = Math.min(page, pages)
  const feedback = usePageTransition()
  const turn = (event, next) => feedback(event.currentTarget.closest('[data-page-region]'), () => onPage(next))
  return <div className="pagination-row"><span>{total} 项 · 每页 {size} 项</span><div><Button variant="outline" size="sm" disabled={current === 1} onClick={event => turn(event, current - 1)}>上一页</Button><span>{current} / {pages}</span><Button variant="outline" size="sm" disabled={current === pages} onClick={event => turn(event, current + 1)}>下一页</Button></div></div>
}
export function ModificationRecords({ quality, records = [], onLocateRecord, limit }) {
  const propertyLabel = usePropertyLabel()
  const { count, rows } = modificationReport(quality)
  const [query, setQuery] = useState(''), [field, setField] = useState('all'), [page, setPage] = useState(1)
  const adapted = useMemo(() => rows.map(row => modificationView(row, records)), [quality, records])
  const filtered = adapted.filter(row => (field === 'all' || row.field === field) && (!query || [row.entity, propertyLabel(row.field), row.operation, row.reason, ...row.ids].some(value => String(value || '').toLowerCase().includes(query.toLowerCase()))))
  const current = Math.min(page, Math.max(1, Math.ceil(filtered.length / 20)))
  const shown = limit ? filtered.slice(0, limit) : filtered.slice((current - 1) * 20, current * 20)
  return <section data-page-region className="modification-records"><h3>修改操作 {count ?? '未提供'} 项{!limit && <small> · 执行轨迹 {executionTraceCount(quality) ?? '未提供'} 条</small>}</h3>
    {!limit && <div className="filter-toolbar"><input aria-label="搜索修改记录" placeholder="搜索天体、性质或处理说明" value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} /><select aria-label="修改性质" value={field} onChange={event => { setField(event.target.value); setPage(1) }}><option value="all">全部性质</option>{[...new Set(adapted.map(row => row.field).filter(Boolean))].map(key => <option value={key} key={key}>{propertyLabel(key)}</option>)}</select></div>}
    {shown.length ? <div className="table-overflow"><table className="report-table readable-table"><thead><tr><th>天体／性质</th><th>修改前 → 修改后</th><th>处理说明</th></tr></thead><tbody data-page-content>{shown.map((row, index) => <tr key={index}><td>{row.record ? <button className="text-link" onClick={() => onLocateRecord?.(row.record.record_id)}>{row.entity} · {propertyLabel(row.field)}</button> : <span>{[row.entity, row.field ? propertyLabel(row.field) : '数据处理'].filter(Boolean).join(' · ')}</span>}</td><td>{!row.before && !row.after ? <span className="hint">未提供前后值</span> : <div className="value-change"><span>{row.before || '未提供'}</span><span>→</span><strong>{row.after || '未提供'}</strong></div>}</td><td><strong>{row.operation}</strong>{row.originals.filter(name => name !== row.operation).length > 0 && <small>{row.originals.filter(name => name !== row.operation).join(' · ')}</small>}<Prose value={row.reason} /></td></tr>)}</tbody></table></div> : <p className="hint">{rows.length ? '没有匹配的修改记录' : '该报告未提供修改记录'}</p>}
    {!limit && <Pagination total={filtered.length} page={current} onPage={setPage} />}
  </section>
}

function SourceScores({ state, sources, onOpenSource }) {
  const propertyLabel = usePropertyLabel()
  const [query, setQuery] = useState(''), [sort, setSort] = useState('asc'), [page, setPage] = useState(1), [selected, setSelected] = useState(null)
  const ids = [...new Set([...Object.keys(state.sources || {}), ...Object.keys(state.quality_scoring?.per_source_scores || {})])]
  const rows = ids.map(id => ({ id, source: state.sources?.[id] || {}, catalog: sources.find(source => source.source_id === id), score: percentScore(state.quality_scoring?.per_source_scores?.[id] ?? state.sources?.[id]?.quality_scoring?.overall_score) })).filter(row => [row.id, row.source.title, row.catalog?.title].some(value => String(value || '').toLowerCase().includes(query.toLowerCase()))).sort((a, b) => (a.score == null ? 1 : b.score == null ? -1 : sort === 'asc' ? a.score - b.score : b.score - a.score))
  const current = Math.min(page, Math.max(1, Math.ceil(rows.length / 20)))
  return <section data-page-region><div className="filter-toolbar"><input aria-label="搜索来源评分" placeholder="搜索来源或论文标题" value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} /><select aria-label="来源评分排序" value={sort} onChange={event => { setSort(event.target.value); setPage(1) }}><option value="asc">评分从低到高</option><option value="desc">评分从高到低</option></select></div>
    <div className="table-overflow"><table className="report-table readable-table"><thead><tr><th>来源</th><th>记录数</th><th>评分 / 100</th><th>评分解释</th></tr></thead><tbody data-page-content>{rows.slice((current - 1) * 20, current * 20).map(row => { const explanation = sourceExplanation(row.source, state.per_source_reasons?.[row.id], propertyLabel); return <Fragment key={row.id}><tr><td><button className="text-link source-title" onClick={() => row.catalog ? onOpenSource(row.catalog) : setSelected(selected === row.id ? null : row.id)}>{sourceName(row.catalog || row.source, row.id)}</button></td><td>{row.source.record_count ?? '未提供'}</td><td>{row.score?.toFixed(2) ?? '未提供'}</td><td><button className="text-link" aria-expanded={selected === row.id} onClick={() => setSelected(selected === row.id ? null : row.id)}>{selected === row.id ? '收起解释' : '查看解释'}</button></td></tr>{selected === row.id && <tr><td colSpan={4}><div className="source-reason"><h3>评分解释</h3>{explanation.dimensions.length > 0 && <dl className="dimension-list">{explanation.dimensions.map(dimension => <div key={dimension.key}><dt>{dimension.label}</dt><dd>{dimension.score.toFixed(1)}</dd></div>)}</dl>}<Prose value={explanation.extraction} />{explanation.impacts.length > 0 && <div className="source-impacts"><h4>具体影响</h4>{explanation.impacts.map((impact, i) => <Prose value={impact} key={i} />)}</div>}{!explanation.dimensions.length && !explanation.extraction && !explanation.impacts.length && <p className="hint">该来源未提供评分解释</p>}</div></td></tr>}</Fragment> })}</tbody></table></div>
    <Pagination total={rows.length} page={current} onPage={setPage} />
  </section>
}

function FieldInsights({ insights, records, definitions }) {
  const propertyLabel = usePropertyLabel()
  const groups = insightGroups(insights)
  const bodyId = useId()
  const toggleInPlace = useInPlaceDisclosure()
  const [selected, setSelected] = useState(null)
  const chosen = selected === null ? groups[0]?.key : selected
  const recommendations = normalizeInsights(insights).recommendations
  const usage = [['suitable_use_cases', '适用研究'], ['limitations', '使用限制'], ['recommended_caveats', '注意事项']].map(([key, label]) => ({ label, text: recommendations[key] })).filter(item => readableText(item.text))
  return <section className="field-insights"><div className="insight-introduction"><h3>研究概览</h3><p>已整理 {records.length} 条记录，覆盖 {fieldDistribution(records).length} 项性质。以下观察与解释来自本次任务的已有报告。</p></div>
    {groups.length ? groups.map(group => <section className="insight-property" key={group.key}><div className="insight-property-heading"><button aria-expanded={chosen === group.key} aria-controls={`${bodyId}-${group.key}`} onClick={event => toggleInPlace(event, () => setSelected(chosen === group.key ? '' : group.key))}><strong>{propertyLabel(group.field)}</strong>{group.entity && <span>{group.entity}</span>}<span className="disclosure-arrow">{chosen === group.key ? '−' : '+'}</span></button><DefinitionNote definition={definitions?.[group.field]} /></div>{chosen !== group.key && <p className="observation-preview">{readableText(group.rows[0]?.observation)}</p>}<div id={`${bodyId}-${group.key}`} inert={chosen === group.key ? undefined : ''} aria-hidden={chosen !== group.key} className={`smooth-collapse${chosen === group.key ? ' expanded' : ''}`}><div className="insight-observations">{group.rows.map((row, i) => <article className="field-observation" key={i}><h4>{SOURCE_TYPES[row.source_type] || row.source_type || '研究资料'}观察{group.rows.length > 1 ? ` ${i + 1}` : ''}</h4><Prose value={row.observation} />{readableText(row.interpretation) && <div className="insight-explanation"><h4>研究解释</h4><Prose value={row.interpretation} /></div>}{readableText(row.typical_range) && <div className="reference-range"><h4>已有参考范围</h4><Prose value={row.typical_range} /></div>}{readableText(row.cause_hypotheses) && <div><h4>原因假设</h4><Prose value={row.cause_hypotheses} /></div>}<References values={[...(row.kb_references || []), ...(row.evidence_sources || [])]} /></article>)}</div></div></section>) : <p className="hint">本次任务未提供字段洞察</p>}
    {readableText(insights?.overall_narrative) && <section className="usage-guidance"><h3>报告概述</h3><Prose value={insights.overall_narrative} /></section>}
    {usage.length > 0 && <section className="usage-guidance"><h3>使用建议</h3>{usage.map(item => <div key={item.label}><h4>{item.label}</h4><Prose value={item.text} /></div>)}</section>}
  </section>
}

export default function AnalysisView({ quality, records, sources, insights, onOpenRecord, onOpenSource, onLocateRecord, onOpenRecords, active = true }) {
  const [tab, setTab] = useState('overview'), [insightTab, setInsightTab] = useState('')
  const bodyId = useId()
  const toggleInPlace = useInPlaceDisclosure()
  const paneRef = useRef(null), tabsRef = useRef(null)
  const panes = useSlidingPanes(paneRef, tab, ['overview', 'sources', 'modifications', 'insights'], { active })
  useSlidingUnderline(tabsRef, `${tab}:${active}`)
  const state = quality?.quality_report?.report_state?.quality
  const resolvedInsights = insights || quality?.quality_report?.output_state?.insights || quality?.quality_report?.report_state?.insights
  const scores = useMemo(() => Object.values(state?.quality_scoring?.per_source_scores || {}).map(percentScore).filter(value => value != null), [state])
  const bins = [[0, 60], [60, 70], [70, 80], [80, 90], [90, 101]].map(([lo, hi]) => ({ label: hi === 101 ? '90–100' : `${lo}–${hi}`, count: scores.filter(score => score >= lo && score < hi).length }))
  return <div className="analysis-view"><nav ref={tabsRef} className="section-tabs reading-tabs" aria-label="质量与洞察分区">{[['overview', '总览'], ['sources', '来源评分'], ['modifications', '修改记录'], ['insights', '数据洞察']].map(([key, label]) => <button key={key} aria-current={tab === key ? 'page' : undefined} className={`tab-btn${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>{label}</button>)}</nav>
    <div ref={paneRef} className="analysis-panes slide-panes" data-sliding={panes.moving || undefined}>
    <div className="analysis-pane" {...panes.paneProps('overview')}><div className="quality-overview-grid"><section className="report-section"><h3>综合质量</h3>{state?.quality_scoring ? <QualityScoreSection qScoring={state.quality_scoring} qState={state} /> : <p className="hint">该任务未提供综合评分</p>}</section><section className="report-section"><h3>来源评分分布 <small>{scores.length} 个来源</small></h3><div className="distribution-bars">{bins.map(bin => <div key={bin.label}><span>{bin.label}</span><div><i style={{ width: `${scores.length ? bin.count / scores.length * 100 : 0}%` }} /></div><strong>{bin.count}</strong></div>)}</div><div className="processing-counts"><span>修改操作 <strong>{modificationReport(quality).count ?? '未提供'}</strong> 项</span><span>执行轨迹 <strong>{executionTraceCount(quality) ?? '未提供'}</strong> 条</span></div></section></div></div>
    <div className="analysis-pane" {...panes.paneProps('sources')}>{panes.hasVisited('sources') && (state ? <SourceScores state={state} sources={sources} onOpenSource={onOpenSource} /> : <p className="hint">该任务未提供来源评分</p>)}</div>
    <div className="analysis-pane" {...panes.paneProps('modifications')}>{panes.hasVisited('modifications') && <ModificationRecords quality={quality} records={records} onLocateRecord={onLocateRecord} />}</div>
    <div {...panes.paneProps('insights')} className="insight-sections analysis-pane">
      {[['fields', '字段洞察', '查看各性质的观察与研究解释', Icon.Sparkle], ['measurements', '测量分布', '比较不同来源的测量与已有误差', Icon.BarChart], ['relations', '字段关系', '查看性质之间的关系、公式与引用', Icon.Network]].map(([key, title, description, Glyph]) => <section className="insight-accordion" key={key} data-expanded={insightTab === key || undefined}><button className={'insight-section-toggle' + (insightTab === key ? ' selected' : '')} aria-expanded={insightTab === key} aria-controls={`${bodyId}-${key}`} onClick={event => toggleInPlace(event, () => setInsightTab(insightTab === key ? '' : key))}><span className="insight-entry-icon" aria-hidden="true"><Glyph width="18" height="18" /></span><strong>{title}</strong><span className="insight-entry-description">{description}</span><span className="insight-entry-chevron" aria-hidden="true"><Icon.ChevronDown width="16" height="16" /></span></button><div id={`${bodyId}-${key}`} inert={insightTab === key ? undefined : ''} aria-hidden={insightTab !== key} className={`smooth-collapse${insightTab === key ? ' expanded' : ''}`}><div className="collapse-clip"><div className="insight-section-body">{key === 'fields' ? <FieldInsights insights={resolvedInsights} records={records} definitions={quality?.quality_report?.output_state?.metadata?.field_definitions} /> : key === 'measurements' ? <MeasurementDistribution records={records} sources={sources} quality={quality} onOpenRecord={onOpenRecord} onOpenRecords={onOpenRecords} /> : <RelationshipGraph insights={resolvedInsights} />}</div></div></div></section>)}
    </div>
    </div>
  </div>
}
