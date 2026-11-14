import RelationshipGraph from './AstrophysicsNetworkModule'
import { usePropertyLabel } from '@/lib/propertyLabel'
import PropertyInsightCards from './PropertyInsightCards'

function TheoryBasis({ ids, theory }) {
  return theory.filter(item => ids.includes(item.claim.claim_id)).map(item => <section key={item.claim.claim_id}>
    <strong>{item.claim.basis_label || (item.claim.authoring_basis === 'author_knowledge' ? '作者知识整理' : '来源已核查')}：{item.title_zh || item.claim.claim_id}</strong>
    <p>{item.claim.statement_zh}</p>
    {item.scope === 'conditional_background' && <p className="hint">适用条件尚未确认，作为有条件的背景。</p>}
    {item.conditions_zh && <p>适用条件：{item.conditions_zh}</p>}
    {item.limitations?.map((text, i) => <p key={i}>限制：{text}</p>)}
    {item.uncertainty_notes && <p>不确定度说明：{item.uncertainty_notes}</p>}
    {item.sources?.map(source => <section key={source.source_id}><p>{source.identity?.title || source.source_id}</p>{source.evidence?.map(piece => <blockquote key={piece.evidence_id}>{piece.excerpt}<br />{piece.locator}</blockquote>)}</section>)}
    {item.author_review && <p className="hint">内容包含模型作者复核；不代表独立专家或人工科学审定。</p>}
  </section>)
}

export default function RuntimeInsights({ report, records, relations = false, onOpenRecord, onOpenKnowledge, savedOnly = false }) {
  if (!report) return <p className="hint">洞察尚未生成；已交付的数据可正常查看和导出。</p>
  if (report.status === 'disabled_pending_content') return <p className="hint">新洞察待知识内容接入，本轮未启用。数据、原文及导出可正常查看；没有调用旧洞察模型。</p>
  if (report.schema_version === 'InsightReport/4') return <PropertyInsightCards savedOnly={savedOnly} report={report} records={records} onOpenRecord={onOpenRecord} onOpenKnowledge={onOpenKnowledge} relations={relations} />
  if (report.schema_version === 'InsightReport/3') return <AuthorInsights report={report} records={records} />
  const labels = Object.fromEntries(records.map(record => [record.property_id, record.field_name]))
  if (relations) return <section><p>以下为有条件的一般理论背景，不表示本任务已验证相关性。</p><RelationshipGraph insights={report} /></section>
  return <section><p>解释状态：{{ complete: '已生成', partial: '部分完成', not_applicable: '无可解释数据' }[report.status] || report.status}</p>
    {report.units?.map(unit => <article key={unit.unit_id}><h4>{labels[unit.property_id] || unit.property_id}</h4>{unit.paragraphs.length ? unit.paragraphs.map((paragraph, i) => <section key={i}><strong>{{ source_fact: '来源事实', theory_background: '一般理论背景', usage_limit: '使用限制' }[paragraph.kind]}</strong><p>{paragraph.text}</p><details><summary>依据</summary><p>测量：{paragraph.measurement_ids.join('、') || '无'}</p><p>理论声明：{paragraph.claim_ids.join('、') || '无'}</p><TheoryBasis ids={paragraph.claim_ids} theory={report.theory || []} /></details></section>) : <p>该部分尚未完成解释：{unit.reason || '未取得可用解释'}。原始测量和不确定度仍保留。</p>}</article>)}
    {report.limitations?.map((limitation, i) => <p className="hint" key={i}>{limitation}</p>)}
  </section>
}

function AuthorInsights({ report, records }) {
  const propertyLabel = usePropertyLabel()
  const names = Object.fromEntries(records.map(r => [r.property_id, r.field_name]))
  const facts = Object.fromEntries(records.map((r, index) => [r.record_id, { ...r, readable: `记录${index + 1} · ${r.field_name}` }]))
  const blocks = Object.fromEntries((report.knowledge_blocks || []).map(b => [b.claim.claim_id, b]))
  return <section><p>解释状态：{{ pending: '正在生成，数据已可查看', complete: '已生成', partial: '部分完成', not_applicable: '无可解释的测量结果' }[report.status] || '尚未完成'}</p>
    {report.property_states?.filter(item => item.knowledge_coverage?.state === 'missing').map(item =>
      <p className="hint" key={item.property_id}>{names[item.property_id] || propertyLabel(item.property_id)}：{item.knowledge_coverage.message}</p>)}
    {report.units?.map(unit => <article key={unit.unit_id}><h4>{names[unit.property_id] || propertyLabel(unit.property_id)}</h4>
      {unit.paragraphs.length ? unit.paragraphs.map((p, index) => <section key={index}><strong>{{ source_fact: '本次来源事实', property_definition: '性质含义', theory_background: '知识背景', usage_limit: '条件与使用限制' }[p.kind]}</strong><p>{p.text}</p>
        <details><summary>原文与知识依据</summary>{p.measurement_ids.map(mid => <p key={mid}>{facts[mid]?.readable || '本次原记录'}：原报 {facts[mid]?.source?.raw_value} {facts[mid]?.source?.unit}；原页/行列见该记录详情。</p>)}
          {p.claim_ids.map(cid => { const block = blocks[cid]; return block && <section key={cid}><strong>{block.title}</strong><p className="hint">{block.authoring_basis === 'source_checked' ? '来源已核读（按作者包保留标签）' : '作者知识整理（不代表独立科学审定）'}</p><blockquote>{block.claim.text}</blockquote>{block.conditions?.map((c, i) => <p key={i}>适用条件：{c}</p>)}{block.sources?.map(s => <p key={s.source_id}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> · {s.verification === 'reference_only' ? '进一步阅读' : '已核读或复用证据'}<br />{s.locator}<br />{s.support_note}</p>)}</section> })}
        </details></section>) : <p className="hint">该部分未完成解释，数据和原件已保留。{unit.reason}</p>}
    </article>)}{report.limitations?.map((text, index) => <p className="hint" key={index}>{text}</p>)}
  </section>
}
