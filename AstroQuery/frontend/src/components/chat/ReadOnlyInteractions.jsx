import { artifactUrl } from '@/services/api'
export default function ReadOnlyInteractions({presentation,taskId,stageId}) {
 const p=presentation
 if(!p || (stageId==='understand' ? !p.draft_question : !(p.reviews||[]).length))return null
 return <section className="readonly-interactions" aria-label="当时的问题与原回答">
  {stageId==='understand' && p.draft_question&&<div>
    <h3>{p.draft_question.kind==='target_selection'?'当时待确认的天体':'当时待确认的查询范围'}</h3>
    {p.target?.main_id&&<p>{p.target.main_id}</p>}
    {(p.request?.requests||[]).map((r,i)=>{
      const ids=r.candidate_property_ids||[]
      const names=(p.draft_question.options||[]).filter(o=>ids.includes(o.id)).map(o=>o.name)
      return names.length?<p key={i}><strong>{r.text}</strong> · {names.join('、')}</p>:null
    })}
    {!!p.properties?.length&&<p>当时已选：{p.properties.map(x=>x.name).join('、')}</p>}
  </div>}
  {stageId==='quality_check' && (p.reviews||[]).map(r=><details key={r.review_id} open={p.active_stage==='quality_check' && !p.terminal_at}><summary>{r.question} <span>{r.status==='closed_unanswered'?'已关闭':r.status==='applied'?'已复检':r.answer?'已有原回答':'历史提问'}</span></summary><p>{r.impact}</p>{r.answer?<><p>原回答：{r.choices?.find(c=>c.action===r.answer.action)?.label||r.answer.action}{r.answer.simulation?' · 模拟审核':''}</p><p>{r.answer.reason}</p><p>{p.review_receipts?.some(x=>x.review_id===r.review_id)?'已复检':'当时正在复检'}</p></>:<p>{r.status==='closed_unanswered'?'此项已关闭，无原回答':'当时尚未作答'}</p>}
   <details><summary>原审核证据</summary>{(r.evidence||[]).map(e=><div key={e.evidence_id}><blockquote className="evidence-text">{e.raw_text}</blockquote><a href={`${artifactUrl(taskId,e.artifact_ref.id)}${e.locator?.page?`#page=${e.locator.page}`:''}`} target="_blank" rel="noreferrer">打开原件{e.locator?.page?`物理第${e.locator.page}页`:''}</a></div>)}</details>
  </details>)}
 </section>
}
