import { useEffect, useState } from 'react'
import { useRememberedState } from '@/hooks/useViewMemory'
import { displayText } from '@/lib/researchDisplay'
import { useWorkbenchPage, PageControls } from './MaterialWorkbench'
import { useAnalysis, AnalysisControls, useReadingVisibility } from './MaterialReading'
import MaterialAnalysisView, {MaterialAdvice} from './MaterialAnalysisView'

const coordinates=(rows,field)=>[...new Set((rows||[]).map(v=>displayText(typeof v==='object'?v[field]||v.value||v.definition||v.column:v)).filter(Boolean))].join('、')||'未记录'
export default function PropertyComparison({scope,active,memory={},property,onProperty,onOpenMaterial,onOpenDetail,onBack}) {
 const [tab,setTab]=useRememberedState(memory,'tab','reading'),[page,setPage]=useRememberedState(memory,'page',1)
 const [visibleRef,visible]=useReadingVisibility(active)
 const catalog=useWorkbenchPage(scope,'materials',{group_by:'material',property_id:property||undefined,limit:1},active)
 const properties=catalog.value?.properties||memory.properties||[]
 useEffect(()=>{if(catalog.value?.properties)memory.properties=catalog.value.properties},[catalog.value,memory])
 const selected=properties.some(p=>p.property_id===property)?property:properties[0]?.property_id
 useEffect(()=>{if(selected&&selected!==property)onProperty(selected)},[selected,property])
 const name=properties.find(p=>p.property_id===selected)?.name||'当前性质'
 const state=useAnalysis(scope,{property_id:selected},'property_comparison',visible&&!!selected&&tab==='reading')
 const sources=useWorkbenchPage(scope,'materials',{group_by:'material',property_id:selected,limit:10,offset:(page-1)*10},active&&!!selected&&tab==='sources')
 const report=state.value?.report||(state.value?.existing_comparison?{...state.value.existing_comparison.card,scope:{kind:'property_comparison'},knowledge_blocks:state.value.existing_comparison.knowledge_blocks}:null)
 const answerScope={delivery_id:scope.deliveryId,delivery_revision:scope.revision,at_seq:scope.atSeq,sealed_only:scope.sealedOnly}
 const onRecord=id=>onOpenDetail?.({type:'record',taskId:scope.taskId,answerScope,record:{record_id:id,task_id:scope.taskId,delivery_id:scope.deliveryId,delivery_revision:scope.revision,details_loaded:false}})
 const onKnowledge=block=>onOpenDetail?.({type:'knowledge',taskId:scope.taskId,answerScope,block:{...block,archived:true}})
 return <div className="property-comparison-page" ref={visibleRef}>
  {onBack&&<button className="text-link workbench-back" onClick={onBack}>← 返回刚才资料</button>}
  <header className="property-comparison-heading"><div><span className="reading-eyebrow">本任务 · 跨来源综合</span><h2>{name}</h2><p className="hint">{state.value?.scope?.record_count??'…'} 条测量 · {(catalog.value?.selected_property_id===selected?catalog.value?.total:null)??'…'} 份资料<span> · 同一性质复用同一份已保存报告</span></p></div><select aria-label="对照性质" value={selected||''} onChange={e=>{onProperty(e.target.value);setPage(1)}}>{properties.map(p=><option key={p.property_id} value={p.property_id}>{p.name}</option>)}</select></header>
  <nav className="workspace-chips" aria-label="性质对照分类">{[['reading','综合解读'],['sources','来源对照']].map(([key,label])=><button className={`filter-chip${tab===key?' active':''}`} aria-pressed={tab===key} key={key} onClick={()=>setTab(key)}>{label}</button>)}</nav>
  {catalog.error&&<p role="alert">{catalog.error}</p>}
  {tab==='reading'&&<section className="reading-section reading-main"><AnalysisControls state={state} kind="property_comparison"/>{report?<><MaterialAnalysisView report={report} onRecord={onRecord} onKnowledge={onKnowledge}/><MaterialAdvice report={report} onRecord={onRecord} onKnowledge={onKnowledge}/></>:state.value&&<p className="hint">该性质尚无已保存的综合解读。可在“来源对照”查看实际资料与测量。</p>}</section>}
  {tab==='sources'&&<section className="property-source-table"><p className="hint">仅展示已保存的条件；未记录的字段不推测补齐。</p>{sources.error?<p role="alert">{sources.error} <button className="text-link" onClick={sources.retry}>重试</button></p>:sources.value?<><p className="reading-range">本任务 · {name} · {sources.value.total} 份去重资料</p><div className="local-table-scroll"><table><thead><tr>{['资料名称','测量数','波段','历元定义','表示方式 / 单位','查看'].map(v=><th key={v}>{v}</th>)}</tr></thead><tbody>{sources.value.items.map(item=><tr key={item.group_id}><td><button className="text-link" onClick={()=>onOpenMaterial(item.group_id,selected)}>{item.title}</button></td><td>{item.record_count}</td><td>{coordinates(item.coordinates?.bands)}</td><td>{coordinates(item.coordinates?.epochs,'definition')}</td><td>{coordinates(item.coordinates?.representations)} / {coordinates(item.coordinates?.units)}</td><td><button className="text-link" onClick={()=>onOpenMaterial(item.group_id,selected)}>本篇资料 →</button></td></tr>)}</tbody></table></div><PageControls page={page} count={sources.value.total} size={10} setPage={setPage} label="性质来源对照分页"/></>:<p className="hint" role="status">正在读取来源对照…</p>}</section>}
 </div>
}
