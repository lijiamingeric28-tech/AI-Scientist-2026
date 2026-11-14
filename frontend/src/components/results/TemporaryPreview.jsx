import EvidenceSource from './EvidenceSource'
const STATES = { under_review: '待人工判断或复检', collected: '已采集，尚未最终封口', withheld_or_linked_mention: '暂不交付或同源重复提及' }
const ROLES = { stat: '统计误差', sys: '系统误差', total: '原文总误差', unspecified: '未说明类别' }

export default function TemporaryPreview({ preview }) {
  if (!preview) return null
  if (preview.status === 'error') return <p role="status">临时数据暂不可读：{preview.error}</p>
  if (preview.status !== 'success') return <p role="status">正在读取临时数据…</p>
  const { items, counts } = preview.data
  return <section aria-label="临时只读数据">
    <h3>临时只读数据</h3>
    <p>已采集{counts.source_records}条记录；待回答{counts.pending_questions}项，已答待落实{counts.accepted_answers_awaiting_application}项。以下保留原报值与证据，最终评分、导出和洞察将在质检完成后提供。</p>
    {items.map(item => <details data-preview-measurement-id={item.source.measurement_id} key={item.source.measurement_id}>
      <summary>{item.property_binding.definition.name_cn}：{item.source.raw_value} {item.source.unit} · {STATES[item.provisional_state]}</summary>
      <p>{item.source_document.title || item.source_document.work?.records?.[0]?.title || item.source_document.source_id}</p>
      <p>限值：{({ none: '非限值', upper: '上限', lower: '下限' })[item.source.limit] || item.source.limit}</p>
      {item.source.uncertainty.components.length ? item.source.uncertainty.components.map(component => <div key={component.component_id}>
        <p>{ROLES[component.role] || component.role}：{component.raw_text}</p>
        <p>{component.interpretation_state === 'parsed' ? Object.entries(component.values || {}).map(([key, value]) => `${key}=${value ?? '未给出'}`).join('；') : '误差解释尚未核实，保留原文'}</p>
        {component.level?.raw_text && <p>{component.level.raw_text}</p>}
      </div>) : <p>{item.source.uncertainty.state === 'not_reported' ? '已检查范围未报告不确定度' : '不确定度状态尚未核实'}</p>}
      {item.saved_processing?.main_state==='ready'&&<p>已有局部处理回执（尚未封口）：{item.source.raw_value} {item.source.unit} → {item.saved_processing.value_typed?.value} {item.saved_processing.coordinate_units?.target}。原报不变。</p>}
      {item.evidence.map(e=><EvidenceSource key={e.evidence_id} evidence={e} taskId={item.source.task_id} view={item.evidence_views?.find(v=>v.evidence_id===e.evidence_id)}/>)}
      {item.source_statements.map(statement => <p key={statement.statement_id}>来源上下文：{statement.raw_quote || statement.text}</p>)}
    </details>)}
    {preview.onPage && <div className="records-pagination"><button className="pager-btn" disabled={!preview.data.offset} onClick={()=>preview.onPage(Math.max(0,(preview.data.offset||0)-50))}>上一页</button><span>{Math.floor((preview.data.offset||0)/50)+1} / {Math.max(1,Math.ceil(preview.data.total/50))} 页 · {preview.data.total} 条</span><button className="pager-btn" disabled={(preview.data.offset||0)+items.length>=preview.data.total} onClick={()=>preview.onPage((preview.data.offset||0)+50)}>下一页</button></div>}
  </section>
}
