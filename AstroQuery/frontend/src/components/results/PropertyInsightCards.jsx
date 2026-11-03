import EvidenceSource from './EvidenceSource'
import {stateText} from '@/lib/researchDisplay'
import { usePropertyLabel } from '@/lib/propertyLabel'
import { useState } from 'react'

const HEADINGS = { found: '本轮发现', comparison: '比较条件', uses: '可以怎样使用', limitations: '值得复查与适用限制' }
const FINDINGS = { explicit_counterevidence: '有明确反证', needs_check: '需要复核', ordinary_difference: '普通测量差异' }

function OriginalEvidence({ record, evidence }) {
  const [open, setOpen] = useState(false)
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{Number.isInteger(evidence.locator?.page) ? `打开PDF物理第${evidence.locator.page}页原文` : '打开原表行列与原文'}</summary>
    {open && <EvidenceSource evidence={evidence} taskId={record.source.task_id}
      view={record.evidence_views?.find(v => v.evidence_id === evidence.evidence_id)} />}
  </details>
}

function OriginalReferences({ paragraph, facts, onOpenRecord }) {
  const direct = paragraph.measurement_ids || []
  const ids = direct.length ? direct : paragraph.evidence_record_ids || []
  return ids.map(mid => {
    const record = facts[mid]
    if (!record) return <p key={mid}>原记录未随当前筛选显示；请到完整结果查看。</p>
    const selected = paragraph.evidence_ids || []
    const evidence = (record.evidence || []).filter(e => !selected.length || selected.includes(e.evidence_id))
    return <section key={mid}>
      {!direct.length && <p className="hint">以下是所选原文位置关联的记录，不表示模型对每条另作判断。</p>}
      <p>{record.field_name} · 原报 {record.source.raw_value}
        {onOpenRecord && <button className="text-link" onClick={() => onOpenRecord(record)}>查看记录、不确定度与上下文</button>}
      </p>
      <p className="hint">原单位：{record.source.unit || '未核明，见原文'}</p>
      <p>{Array.isArray(record.source_title) ? record.source_title.join('；') : record.source_title || '本次来源'}{record.source_version_grade && ` · ${record.source_version_grade}`}</p>
      {evidence.map(e => <OriginalEvidence key={e.evidence_id} record={record} evidence={e} />)}
      {(record.source_statements || []).filter(s => selected.includes(s.statement_id)).map(s => <section key={s.statement_id}>
        <p>{Number.isInteger(s.page) ? `PDF物理第${s.page}页` : '原表位置见记录详情'}</p>
        <blockquote style={{ whiteSpace: 'pre-wrap' }}>{s.raw_quote}</blockquote>
      </section>)}
    </section>
  })
}

function KnowledgeReferences({ ids, blocks, onOpenKnowledge }) {
  return (ids || []).map(cid => {
    const block = blocks[cid]
    if (!block) return null
    return <section key={cid}>
      <button className="text-link" onClick={()=>onOpenKnowledge?.(block)}>{block.title} · 查看知识依据</button>
      <p className="hint">{block.authoring_basis === 'source_checked' ? '来源已核读' : '作者知识整理'}</p>
      <blockquote>{block.claim.text}</blockquote>
      {(block.conditions || []).map((text, i) => <p key={i}>适用条件：{text}</p>)}
      {(block.sources || []).map(source => <p key={source.source_id}>
        {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : source.title}
        <br />{source.locator}<br />{source.support_note}
      </p>)}
    </section>
  })
}

function NumericCard({ record, onOpenRecord }) {
  const errors = record.source.uncertainty?.components || []
  return <section>
    <p>原报：{record.source.raw_value}</p>
    <p className="hint">原单位：{record.source.unit || '未核明，见原文'}</p>
    {record.derived?.main_state === 'ready' && <p>当前表示：{typeof record.field_value === 'object' ? JSON.stringify(record.field_value) : String(record.field_value)} {record.field_unit || ''}</p>}
    {errors.length ? errors.map(error => {
      const actualUnit = record.uncertainty_units?.[error.component_id]
      const label = typeof actualUnit === 'object' ? actualUnit?.canonical_symbol : actualUnit
      return <p key={error.component_id}>
        原报{{ stat: '统计误差', sys: '系统误差', total: '总误差', unspecified: '未说明类别的误差' }[error.role] || '独立误差分量'}：{error.raw_text}（{label || '单位及含义见原文'}）
        {error.interpretation_state === 'unresolved' && '；含义尚未核实，保留原报'}
      </p>
    }) : <p className="hint">{record.source.uncertainty?.state === 'not_reported' ? '原记录未报告误差。' : '当前记录未有可解释误差分量，状态及原文见详情。'}</p>}
    {onOpenRecord && <button className="text-link" onClick={() => onOpenRecord(record)}>完整数值、独立分量和原文</button>}
  </section>
}

export default function PropertyInsightCards({ report, records, onOpenRecord, onOpenKnowledge, relations }) {
  const propertyLabel = usePropertyLabel()
  const facts = Object.fromEntries(records.map(record => [record.record_id, record]))
  const names = Object.fromEntries(records.map(record => [record.property_id, record.field_name]))
  const blocks = Object.fromEntries((report.knowledge_blocks || []).map(block => [block.claim.claim_id, block]))
  if (relations) return <section>
    <KnowledgeReferences ids={Object.keys(blocks)} blocks={blocks} onOpenKnowledge={onOpenKnowledge} />
  </section>
  return <section>
    {report.status === 'pending' && <p className="hint">数据已可查看，正在按性质整理解释。</p>}
    {(report.cards || []).map(card => <article className="insight-card" key={card.card_id}>
      <section className="insight-property"><header><h4>{names[card.property_id] || propertyLabel(card.property_id)}</h4><span>{stateText(card.status)}</span>
      <p className="insight-scope">{card.coverage.target_record_count} 条关联测量 · {card.coverage.contributing_source_count} 份实际贡献来源</p></header>
      {card.coverage.owner_excluded_count > 0 && <p>其中 {card.coverage.owner_excluded_count} 条经责任复检，不再用于目标对象的示例结论；原报和审查历史仍保留。</p>}
      {Object.entries(HEADINGS).map(([key, heading]) => (card.sections[key] || []).length > 0 && <section key={key}>
        <h5>{heading}</h5>
        {card.sections[key].map((paragraph, i) => <section key={i}>
          <p>{paragraph.text}</p>
          <details><summary>原文与知识依据</summary>
            <OriginalReferences paragraph={paragraph} facts={facts} onOpenRecord={onOpenRecord} />
            <KnowledgeReferences ids={paragraph.claim_ids} blocks={blocks} onOpenKnowledge={onOpenKnowledge} />
          </details>
        </section>)}
      </section>)}
      {!(card.sections.found || []).length && <p className="hint">此性质暂无已保存的事实解释。</p>}

      {card.findings?.length > 0 && <section><h5>值得复核的记录</h5>{card.findings.map(finding => <section key={finding.finding_id}>
        <strong>{FINDINGS[finding.classification]}</strong><p>{finding.paragraph.text}</p>
        <p className="hint">{finding.owner_state === 'not_supported' ? '责任复检已确认：不作为目标示例。' : finding.owner_state === 'passed' ? '责任复检未确认该反证，保留原记录。' : finding.classification === 'ordinary_difference' ? '保留不同结果，不据此判错。' : '尚未有足够复检结论；保留原报及待核标记。'}</p>
        <details><summary>查看实际反证位置</summary>
          <OriginalReferences paragraph={{ measurement_ids: finding.measurement_ids, evidence_ids: finding.anchors.map(a => a.evidence_id) }} facts={facts} onOpenRecord={onOpenRecord} />
        </details>
      </section>)}</section>}
      {card.suppressed_examples?.length > 0 && <details><summary>示例修订与责任复检记录</summary>
        {card.suppressed_examples.map((item, i) => <p key={i}>原示例已因责任复检结论停止用于目标汇总：{item.paragraph.text}</p>)}

      </details>}
    </section></article>)}
  </section>
}
