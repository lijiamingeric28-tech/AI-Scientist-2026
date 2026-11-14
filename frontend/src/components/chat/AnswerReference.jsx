import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { getMaterial } from '@/services/api'
import { OriginalPage } from '@/components/results/EvidenceSource'
import { LatexText } from '@/components/results/LatexMath'
import { titleText } from '@/lib/researchDisplay'

export function adaptAnswerSource(source, taskId) {
  if (!source) return null
  const meta = source.work?.records?.find(record => record.title) || source.work?.records?.[0] || {}
  return { ...source, task_id: taskId, protocol_version: 2,
    authors: source.authors || meta.authors, title: source.title || meta.title, year: source.year || meta.year,
    abstract: source.abstract || meta.abstract }
}

function PaperPage({ citation, taskId, scope, navigate }) {
  const payload = citation.payload
  const [page, setPage] = useState(payload.page)
  const [pages, setPages] = useState(payload.page_count || null)
  const pageNav = useRef(null)
  const restorePageFocus = useRef(false)
  useLayoutEffect(() => {
    if (restorePageFocus.current) pageNav.current?.focus({ preventScroll: true })
    restorePageFocus.current = false
  }, [page])
  const source = adaptAnswerSource(payload.source, taskId)
  useEffect(() => {
    const controller = new AbortController()
    if (!payload.source_id || pages) return
    getMaterial(taskId, scope.delivery_id, scope.delivery_revision, payload.source_id, { signal: controller.signal })
      .then(item => { if (!controller.signal.aborted && item?.page_count) setPages(item.page_count) }, () => {})
    return () => controller.abort()
  }, [taskId, scope, payload.source_id, pages])
  const point = page === payload.page && payload.point ? { ...payload.point, page } : { page }
  const showPage = next => {
    restorePageFocus.current = true
    setPage(next)
  }
  return <div className="context-content research-reference">
    <h3>{titleText(source?.title, citation.label)}</h3>
    <div className="research-reference-nav">
      <button type="button" className="research-action" disabled={page <= 1} onClick={() => showPage(page - 1)} aria-label="上一页原文"><Icon.ChevronLeft />上一页</button>
      <span ref={pageNav} tabIndex={-1}>第 {page}{pages ? ' / ' + pages : ''} 页</span>
      <button type="button" className="research-action" disabled={pages != null && page >= pages} onClick={() => showPage(page + 1)} aria-label="下一页原文">下一页<Icon.ChevronRight /></button>
      {page !== payload.page && <button type="button" className="research-action" onClick={() => showPage(payload.page)}>回到引文页</button>}
      {source && <button type="button" className="research-action" data-detail-action="answer-source" onClick={() => navigate({ type: 'source', source })}>查看资料档案</button>}
    </div>
    <OriginalPage key={page} taskId={taskId} artifact={{ id: payload.artifact_id }} point={point} />
  </div>
}

function PropertyDefinition({ binding }) {
  const item = binding.definition || {}
  const profile = binding.output_profile || {}
  const unit = profile.unit?.canonical_symbol
  const body = [...new Set([item.description, item.explanation, item.scientific_purpose, item.scope].filter(text => typeof text === 'string' && text.trim()))]
  return <div className="context-content research-reference">
    <div className="research-reference-definition"><h3>{item.name_cn || '性质定义'}</h3>
      {item.symbol && <span className="research-pill"><LatexText text={item.symbol} /></span>}
      {item.name_en && <p>{item.name_en}</p>}
    </div>
    {body.map((value, i) => <p key={i}><LatexText text={value} /></p>)}
    {unit && <dl className="research-variables"><div><dt>单位</dt><dd><LatexText text={unit} /></dd></div></dl>}
    {!!item.measurement_conditions_schema?.length && <section>
      <h4>测量条件</h4>
      <ul>{item.measurement_conditions_schema.map((condition, i) => <li key={condition.key || i}>
        <strong>{condition.name_cn || condition.label || condition.key}</strong>
        {(condition.description || condition.explanation) && <span> · {condition.description || condition.explanation}</span>}
      </li>)}</ul>
    </section>}
  </div>
}

function ComparisonReference({ group, onRecord }) {
  const rows = group.rows || []
  const recordIds = [...new Set((group.measurement_ids || group.member_ids || group.member_refs || []).map(id => typeof id === 'string' ? id : id.id).filter(Boolean))]
  const summary = group.explanation || group.description || group.reason || group.question
  return <div className="context-content research-reference">
    {typeof summary === 'string' && <p>{summary}</p>}
    {recordIds.length > 0 && <section><h3>{recordIds.length} 条关联测量</h3>
      <ul className="research-reference-records">{recordIds.map((id, i) => {
        const row = rows.find(item => item.measurement_id === id)
        return <li key={id}><button className="research-action" type="button" data-detail-action={id}
          onClick={() => onRecord(id)}>{[row?.raw_value, row?.native_unit].filter(Boolean).join(' ') || '测量 ' + (i + 1)}<Icon.ArrowRight /></button></li>
      })}</ul>
    </section>}
    {(group.author_statements || []).map((statement, i) => <blockquote key={i}>
      <LatexText text={statement.raw_quote} />{statement.page && <footer>原文第 {statement.page} 页</footer>}
    </blockquote>)}
  </div>
}

export default function AnswerReference({ detail, navigate, onClose, onRecord }) {
  const { citation, taskId, scope, error, retry } = detail
  const header = detail.type === 'agent-ref-loading' ? '正在读取引用' :
    error ? '引用暂不可用' :
    citation.type === 'definition' ? '性质定义' :
    citation.type === 'conflict' ? '测量对照' : citation.label
  return <>
    <header className="context-drawer-header">
      <h2 data-detail-heading tabIndex={-1} className="drawer-header-title">{header}</h2>
      <button type="button" className="drawer-close-circle active-press" onClick={onClose} aria-label="关闭详情"><Icon.Close /></button>
    </header>
    {detail.type === 'agent-ref-loading' ? <div className="context-content research-reference" role="status">正在读取同版数据…</div> :
      error ? <div className="context-content research-reference" role="status"><p>{error}</p>
        <button type="button" className="research-action" onClick={retry}>重试</button></div> :
        citation.type === 'definition' ? <PropertyDefinition binding={citation.payload.binding} /> :
        citation.type === 'conflict' ? <ComparisonReference group={citation.payload.group} onRecord={onRecord} /> :
        <PaperPage key={citation.citation_id} citation={citation} taskId={taskId} scope={scope} navigate={navigate} />}
  </>
}
