import { useState } from 'react'
import { artifactUrl } from '@/services/api'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { rawCells, reviewRows, reviewWording } from '@/lib/scienceReading'
import { NativeCells, OriginalPage } from '../results/EvidenceSource'
import FormattedExcerpt from '../results/FormattedExcerpt'

function evidencePages(items, issue) {
  const result = new Map()
  const ids = new Set(items.filter(e=>e.kind === 'paper' && e.artifact_ref?.id).map(e=>e.artifact_ref.id))
  const add = (item, page, excerpt, role) => {
    if (!item?.artifact_ref?.id || !Number.isInteger(page) || page < 1) return
    const key = item.artifact_ref.id + ':' + page
    const entry = result.get(key) || {key, item, page, anchors:[]}
    if (excerpt && !entry.anchors.some(a=>a.excerpt === excerpt)) entry.anchors.push({page, excerpt, role})
    result.set(key,entry)
  }
  for (const e of items) if (e.kind === 'paper') add(e,e.locator?.page,e.raw_text,'main_excerpt')
  if (ids.size === 1) {
    const item = items.find(e=>e.artifact_ref?.id === [...ids][0])
    for (const [key,role] of [['scope_evidence','scope_evidence'],['support_evidence','local_evidence'],['counter_evidence','counter_evidence']]) {
      for (const anchor of issue?.[key] || []) add(item,anchor.page,anchor.quote,role)
    }
  }
  return [...result.values()]
}

export default function ReviewReading({review,taskId,children,hideTitle = false}) {
  const propertyLabel = usePropertyLabel()
  const items = review.evidence_bundle || review.evidence || []
  const rows = reviewRows(review), wording = reviewWording(review)
  const [selectedRow,setRow] = useState(0), [selectedPage,setPage] = useState(0)
  const entry = rows[selectedRow]
  const linked = entry?.evidence?.length ? items.filter(e=>entry.evidence.includes(e.evidence_id)) : items
  const pages = evidencePages(linked, items.length === linked.length ? review.scientific_issue : null)
  const page = pages[selectedPage] || pages[0]
  const propertyName = entry?.propertyId && propertyLabel(entry.propertyId)
  const files = linked.filter(e=>e.kind !== 'paper' || !e.artifact_ref?.id || !Number.isInteger(e.locator?.page))
  const additional = items.filter(e=>rows.length && !rows.some(r=>r.evidence.includes(e.evidence_id)))
  const special = rows.length && selectedRow === rows.length
  const showSupplement = additional.length > 0 && rows.some(r=>r.evidence.length)
  const alternatives = special ? additional : files
  const columnDefinitions = Object.entries(review.scientific_issue?.column_evidence || {})
  return <div className="review-reading modern-review-reading">
    {!hideTitle && wording.original && propertyName && propertyName !== entry?.propertyId && <strong className="review-prop-label">{propertyName}</strong>}
    {!hideTitle && <h4>{wording.title}</h4>}
    {!hideTitle && wording.original && <details className="review-original-question"><summary>查看当时的完整问题</summary><p>{wording.original}</p></details>}
    {rows.length > 0 && <div className="review-values" aria-label="待核实的测量">{rows.map((r,i)=>
      <button type="button" key={r.id || i} aria-pressed={i===selectedRow} onClick={()=>{setRow(i);setPage(0)}}>
        {rows.length>1 && <span>记录 {i+1}</span>}<strong>{r.value ?? '原值未记录'} <small>{r.unit}</small></strong>
        {r.role && r.role !== '文中报告结果' && <span>{r.role}</span>}{r.errors.length>0 && <span>{r.errors.join('；')}</span>}
      </button>)}{showSupplement && <button type="button" aria-pressed={special} onClick={()=>{setRow(rows.length);setPage(0)}}>其他审核依据</button>}</div>}
    {entry?.method && <p className="review-method"><strong>方法与模型</strong> {entry.method}</p>}
    <div className={'review-decision-layout'+(children?' has-options':'')}><div className="review-documents">
    {!special && page && <div className="review-source-page">
      {page.item.source_title && <h5>{page.item.source_title}</h5>}
      {pages.length>1 && <label>原文位置 <select value={page.key} onChange={ev=>setPage(pages.findIndex(p=>p.key===ev.target.value))}>{pages.map((p,i)=><option key={p.key} value={p.key}>原件 {i+1} · 第 {p.page} 页</option>)}</select></label>}
      <OriginalPage key={page.key} taskId={taskId} artifact={page.item.artifact_ref}
        point={{page:page.page,anchors:page.anchors,excerpt:page.item.raw_text,preview_artifact:page.page===page.item.locator?.page ? page.item.page_preview : null}} />
    </div>}
    {alternatives.map(e=>{
      const cells = rawCells(e), main = cells?.filter(c=>c.is_main)
      if (special && e.kind === 'paper' && e.locator?.page && e.artifact_ref?.id)
        return <OriginalPage key={e.evidence_id} taskId={taskId} artifact={e.artifact_ref} point={{page:e.locator.page,excerpt:e.raw_text}} />
      return <section key={e.evidence_id} className="review-table-source">
        {e.source_title && <h5>{e.source_title}</h5>}
        <strong>{e.locator?.table || (cells ? '星表原行' : '保存的出处')}</strong>
        {Number.isInteger(e.locator?.row) && <span> · 第 {e.locator.row+1} 个数据行</span>}
        {main?.length > 0 && <NativeCells cells={main}/>}
        {cells ? <details><summary>查看整行（{cells.length} 列）</summary><NativeCells cells={cells}/></details> :
          e.raw_text && <FormattedExcerpt excerpt={e.raw_text} role="审核出处摘录" />}
        {e.artifact_ref?.id && <a className="text-link" href={artifactUrl(taskId,e.artifact_ref.id)} target="_blank" rel="noreferrer">打开原件</a>}
      </section>
    })}
    {!page && !alternatives.length && <p>这条判断没有保存可打开的原件位置。</p>}
    {columnDefinitions.length > 0 && <details><summary>审核所依据的列定义</summary>
      <dl className="research-fields">{columnDefinitions.map(([name,c])=><div className="research-field-pair" key={name}>
        <dt>{name}{c.unit_text || c.unit ? ' ('+(c.unit_text || c.unit)+')' : ''}</dt><dd>{c.description}</dd>
      </div>)}</dl>
    </details>}
    {(review.scientific_issue?.undecided_fact || review.basis?.shared_premise || review.impact) &&
      <details><summary>判断依据与影响</summary>{[review.scientific_issue?.undecided_fact,review.basis?.shared_premise,review.impact].filter(Boolean).map((text,i)=><p key={i}>{text}</p>)}</details>}
    </div>{children && <div className="review-decision">{children}</div>}</div>
  </div>
}
