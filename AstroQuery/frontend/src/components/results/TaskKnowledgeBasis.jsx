import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { LatexText } from './LatexMath'
import * as api from '@/services/api'

const STATES={matched:'已固定输入背景',available:'已固定输入背景',ready:'已固定输入背景',no_match:'尚无匹配的知识解释',missing:'尚无匹配的知识解释',unavailable:'知识不可用',conditions_unknown:'条件未确认',conditional:'条件未确认',unknown_conditions:'条件未确认',historical_saved_basis:'历史已保存依据'}
const ORIGINS={user:'用户知识',user_knowledge:'用户知识',user_override:'用户修改知识',theory:'一般理论背景',theory_background:'一般理论背景',formal_release:'正式解释依据',user_background:'用户知识',released:'正式解释依据',formal:'正式解释依据',knowledge_release:'正式解释依据',historical_saved_basis:'历史已保存依据'}
export function KnowledgeBasisContent({context,origin,onOpenKnowledge}) {
  if(!context)return <p className="hint">本交付未保存可读取的知识依据。</p>
  const entries=context.entries||[],properties=context.properties||[]
  const grouped=properties.map(property=>({property,entries:entries.filter(entry=>
    (property.entry_ids||[]).includes(entry.entry_id)&&Array.isArray(entry.property_ids)&&entry.property_ids.includes(property.property_id))}))
  const used=new Set(grouped.flatMap(group=>group.entries))
  const ungrouped=entries.filter(entry=>!used.has(entry))
  const renderEntry=(entry,index)=><article className="task-knowledge-entry" key={`${entry.entry_id||entry.claim?.claim_id}:${index}`}>
    <div className="workbench-section-heading"><h4>{entry.title||entry.entry_id||'已保存知识'}</h4><Button variant="outline" size="sm" onClick={()=>onOpenKnowledge?.({...entry,archived:true,task_context_ref:{context_id:context.context_id,content_sha256:context.content_sha256,library_version:context.library_version}})}>查看当时依据</Button></div>
    <p className="hint">{ORIGINS[entry.origin]||'任务已保存背景'}{entry.revision!=null?` · 条目版本 ${entry.revision}`:''}</p>
    {entry.claim?.text&&<p><LatexText text={entry.claim.text}/></p>}
  </article>
  return <section className="task-knowledge-basis" aria-label="任务知识依据">
    <h3>{origin==='historical_saved_basis'?'历史已保存依据':'任务固定知识依据'}</h3>
    <p className="hint">以下是提供给生成模型的输入背景，不能据此认定每句话均实际引用。仅列出已保存的明确性质绑定。</p>
    <p className="hint">{new Set(entries.map(entry=>entry.entry_id||entry.claim?.claim_id).filter(Boolean)).size} 个去重知识条目 · {grouped.filter(group=>group.entries.length).length} 项性质有已保存背景{context.library_version!=null?` · 知识库版本 ${context.library_version}`:''}</p>
    {grouped.map(({property,entries:boundEntries})=><section className="task-knowledge-property" key={property.property_id}><h4>{property.name||property.property_id}</h4><p className="hint">{STATES[property.state]||property.state||'状态未记录'}{property.reason?` · ${property.reason}`:''}</p>
      {(property.entry_ids||[]).map(entryId=>{const matches=boundEntries.filter(item=>item.entry_id===entryId);return matches.length?matches.map(renderEntry):<p className="resource-error" key={entryId}>{entries.some(item=>item.entry_id===entryId)?'该性质未保存明确绑定的知识片段':'已记录的知识条目不可读'}：{entryId}</p>})}
    </section>)}
    {!!ungrouped.length&&<section><h4>未归入性质分组的已保存背景</h4><p className="hint">这些归档片段没有同时满足本目录的条目标识与显式性质绑定，不分配给任一性质。</p>{ungrouped.map(renderEntry)}</section>}
    {!entries.length&&!properties.length&&<p className="hint">本交付没有已保存的知识背景；不会用当前知识库补写历史依据。</p>}
  </section>
}
export default function TaskKnowledgeBasis({scope={},active=true,onOpenKnowledge}) {
  const {taskId,deliveryId,revision,atSeq,sealedOnly}=scope
  const key=JSON.stringify([taskId,deliveryId,revision,atSeq,sealedOnly])
  const [state,setState]=useState({}),[attempt,setAttempt]=useState(0)
  useEffect(()=>{
    if(!active||!taskId||!deliveryId||!revision)return
    const controller=new AbortController()
    api.getTaskKnowledgeContext(taskId,deliveryId,revision,{atSeq,sealedOnly,signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted)setState({key,value})})
      .catch(error=>{if(!controller.signal.aborted)setState({key,error:error.message})})
    return()=>controller.abort()
  },[key,active,attempt])
  const current=state.key===key?state:{}
  if(current.error)return <div className="resource-error" role="alert">知识依据读取失败：{current.error}<Button size="sm" variant="outline" onClick={()=>setAttempt(n=>n+1)}>重试</Button></div>
  if(!current.value)return <p className="hint" role="status">正在读取本交付的知识依据…</p>
  return <KnowledgeBasisContent context={current.value.context} origin={current.value.origin} onOpenKnowledge={onOpenKnowledge}/>
}
