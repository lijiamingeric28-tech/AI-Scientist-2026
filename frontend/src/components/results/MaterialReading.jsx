import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { primaryReading, analysisVersion } from '@/lib/readingLayers'
import { displayText } from '@/lib/researchDisplay'
import { usePropertyLabel } from '@/lib/propertyLabel'
import * as api from '@/services/api'
import MaterialAnalysisView,{MaterialAdvice} from './MaterialAnalysisView'
import './material-reading.css'

const KINDS={paper:'论文',catalog:'星表',official_attachment:'官方补充材料',cited:'引用资料'}
const VERSIONS={published:'正式版',accepted:'接受稿',preprint:'预印本',unknown:'版本等级未确认'}
const STATUS={queued:'等待生成',running:'正在生成',complete:'已完成',partial:'部分完成',failed:'生成失败',cancelled:'已停止',interrupted:'运行中断'}
const ACTIVE=new Set(['queued','running'])
export const READING_SECTIONS=[['reading','本篇解读'],['data','测量与图像'],['sources','原文与来源']]

export function MaterialIdentity({scope,item,onProperty,onAsk,onSources,headingRef}) {
 const label=usePropertyLabel()
 const source=item.material||{},meta=source.work?.records?.[0]||{},authors=source.authors||item.authors||meta.authors||[]
 const artifact=source.artifact||source.schema_artifact
 return <header className="material-reading-header">
  <div className="reading-identity-meta"><span className="reading-type"><Icon.FileText width="14" height="14"/>{KINDS[item.kind]||'科研资料'}</span>{(item.year||source.year||meta.year)&&<span>{item.year||source.year||meta.year}</span>}{source.version_grade&&<span>{VERSIONS[source.version_grade]||source.version_grade}</span>}<span>{item.availability||source.availability||'原件状态未记录'}</span></div>
  <h2 ref={headingRef} tabIndex={-1}>{item.title}</h2>
  {!!authors.length&&<div className="reading-authors">{authors.slice(0,3).map(displayText).join('，')}{authors.length>3&&<button className="text-link" type="button" onClick={onSources}>等 {authors.length} 位作者 · 查看来源</button>}</div>}
  <div className="reading-header-bottom"><div className="reading-scope-counts">本篇资料 · {item.property_name} · <strong>{item.record_count??0}</strong> 条测量<span>·</span><strong>{item.figure_count??0}</strong> 幅关联图像</div><div className="reading-header-actions">{artifact?.artifact_id&&<a className="reading-original-link" href={api.artifactUrl(scope.taskId,artifact.artifact_id)} target="_blank" rel="noreferrer">查阅原件 <Icon.ExternalLink width="13" height="13"/></a>}{onAsk&&<Button size="sm" variant="outline" onClick={onAsk}>就此追问</Button>}</div></div>
  <div className="reading-properties" aria-label="本资料关联性质">{(item.available_properties||[{property_id:item.property_id,name:item.property_name}]).map(p=><button type="button" key={p.property_id} className={`filter-chip${p.property_id===item.property_id?' active':''}`} aria-pressed={p.property_id===item.property_id} onClick={()=>onProperty?.(p.property_id)}>{label(p.name||p.property_id)}{p.record_count!=null&&<small>{p.record_count}</small>}</button>)}</div>
 </header>
}

export function MaterialOverview({profile={},item={}}) {
 const fields=[['研究对象',profile.target?.main_id||profile.target?.canonical_name],['当前性质',item.property_name||profile.property_name],['原报单位',(profile.units||[]).map(displayText).join('；')],['原报表示',(profile.representations||[]).map(displayText).join('；')],['波段',[...new Set((profile.bands||[]).map(v=>displayText(v.value)).filter(Boolean))].join('；')],['历元定义',[...new Set((profile.epochs||[]).map(v=>v.definition||v.column).filter(Boolean))].join('；')]]
 return <div className="reading-overview"><dl className="reading-fact-grid">{fields.map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value||'未记录'}</dd></div>)}</dl><div className="reading-overview-foot"><span>本资料全部性质 <strong>{profile.material_record_count??item.record_count??0}</strong> 条测量</span><span>当前性质 <strong>{profile.record_count??item.record_count??0}</strong> 条</span><span>正文 <strong>{item.body_record_count??0}</strong> 条 · 附表 <strong>{item.attachments?.length??0}</strong> 份</span></div>{profile.conditions?.length>0?<details className="reading-condition-list"><summary>已保存适用条件 · {profile.conditions.length}</summary>{profile.conditions.map((c,i)=><p key={i}>{c.key||c.name||'条件'}：{displayText(c.value??c.raw_text)}{c.state&&c.state!=='known'?'（状态未确认）':''}</p>)}</details>:<p className="hint">适用条件未记录；不据此视为无条件适用。</p>}</div>
}

export function useReadingVisibility(active) {
 const [node,setNode]=useState(null),[near,setNear]=useState(false),[visible,setVisible]=useState(()=>typeof document==='undefined'||document.visibilityState!=='hidden')
 useEffect(()=>{const change=()=>setVisible(document.visibilityState!=='hidden');document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change)},[])
 useEffect(()=>{if(!active||!node||near)return;if(typeof IntersectionObserver==='undefined'){setNear(true);return}const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setNear(true);observer.disconnect()}},{rootMargin:'240px'});observer.observe(node);return()=>observer.disconnect()},[active,node,near])
 return [setNode,Boolean(active&&near&&visible)]
}

export function useAnalysis(scope,item,kind,active) {
 const key=JSON.stringify([scope.taskId,scope.deliveryId,scope.revision,scope.atSeq,scope.sealedOnly,item.group_id,item.property_id,kind])
 const [versions,setVersions]=useState({}),[epoch,setEpoch]=useState(0),[state,setState]=useState({}),[busy,setBusy]=useState(false)
 const version=analysisVersion(versions,key),setVersion=value=>setVersions(old=>({...old,[key]:value}))
 const current=state.key===key&&state.version===version?state:{},value=current.value
 useEffect(()=>{if(!active||state.key===key&&state.version===version&&state.epoch===epoch&&state.value)return;const controller=new AbortController();api.getMaterialAnalysis(scope,{materialId:item.group_id,propertyId:item.property_id,kind,reportVersion:version||undefined},{signal:controller.signal}).then(result=>{if(!controller.signal.aborted)setState({key,version,epoch,value:result})}).catch(error=>{if(!controller.signal.aborted)setState({key,version,error:error.message})});return()=>controller.abort()},[key,active,version,epoch])
 useEffect(()=>{if(!active||!value?.run||!ACTIVE.has(value.run.status))return;let pending=false;const controller=new AbortController();const timer=setInterval(async()=>{if(pending)return;pending=true;try{const run=await api.getMaterialAnalysisRun(scope.taskId,value.run.run_id,{signal:controller.signal});if(!controller.signal.aborted){if(ACTIVE.has(run.status))setState(old=>old.key===key?{...old,value:{...old.value,run}}:old);else setEpoch(n=>n+1)}}catch(error){if(!controller.signal.aborted)setState(old=>({...old,error:error.message}))}finally{pending=false}},5000);return()=>{clearInterval(timer);controller.abort()}},[active,key,value?.run?.run_id,value?.run?.status])
 async function generate(){if(busy||!value?.generation?.allowed)return;setBusy(true);try{const run=await api.createMaterialAnalysis(scope,{materialId:item.group_id,propertyId:item.property_id,kind});setState({key,value:{...value,run}});setVersion('');setEpoch(n=>n+1)}catch(error){setState(old=>({...old,key,error:error.message}))}finally{setBusy(false)}}
 async function stop(){if(!value?.run)return;try{await api.stopMaterialAnalysis(scope.taskId,value.run.run_id);setEpoch(n=>n+1)}catch(error){setState(old=>({...old,error:error.message}))}}
 const selected=value?.versions?.find(ref=>ref.version===(version?Number(version):value.versions[0]?.version))
 return {key,value,loading:active&&!value&&!current.error,error:current.error,busy,version,setVersion,generate,stop,selected,retry:()=>setEpoch(n=>n+1)}
}

export function AnalysisControls({state,kind,onAsk}) {
 if(!state.value&&!state.error)return <p className="reading-loading" role="status"><Icon.Clock/>{state.loading?'正在读取已保存解读…':'进入此区域后读取补充解读。'}</p>
 const {value,busy}=state,run=value?.run,running=run&&ACTIVE.has(run.status),retryable=run&&['failed','partial','cancelled','interrupted'].includes(run.status)
 const status=running?STATUS[run.status]:value?.report?(value.report.generation_method==='saved_source_comparison'?'来源并列对照':value.report.generation_method==='saved_batch_and_summary'?'分批解读与原总结':STATUS[value.report.status]):kind==='material'?'原资料总结':'跨来源综合'
 return <>
  <div className="reading-analysis-controls">
   <span className={`reading-status${running?' is-running':''}`}>{running?<Icon.Clock/>:value?.report?<Icon.Check/>:<Icon.FileText/>}{status}</span>
   <div>{value?.versions?.length>0&&<select aria-label={kind==='material'?'本资料补充版本':'同性质对照版本'} value={state.version} onChange={e=>state.setVersion(e.target.value)}><option value="">最新补充版本</option>{value.versions.map(ref=><option key={ref.version} value={ref.version}>版本 {ref.version} · {ref.generated_at}</option>)}</select>}
    {running?<Button size="sm" variant="outline" onClick={state.stop}>停止补充分析</Button>:false&&(retryable||value?.report?.status!=='complete')&&<Button size="sm" variant="outline" disabled={busy} onClick={state.generate}>{busy?'提交中…':kind==='material'?(retryable?'重试本资料解读':'生成本资料解读'):(retryable?'重试本性质对照':'生成本性质对照')}</Button>}
    {onAsk&&state.selected&&<Button variant="outline" size="sm" onClick={()=>onAsk(state.selected)}><Icon.Sparkle/> 基于此解读追问</Button>}
   </div>
  </div>
  {(value?.report?.generated_at||value?.generation?.message)&&<details className="reading-report-meta"><summary>版本与运行信息{value?.report?.generated_at&&<time dateTime={value.report.generated_at}>{new Date(value.report.generated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}</time>}</summary>{value?.report?.generated_at&&<p>独立补充版本 · {value.report.generated_at} · 原交付保持不变</p>}{value?.generation?.message&&<p>{value.generation.message}</p>}</details>}
  {running&&<p className="hint" role="status">{run.stage||'等待生成'}{run.total_records!=null?` · 已完成 ${run.completed_records} / ${run.total_records} 条记录范围`:''}</p>}
  {run&&!running&&!['complete','partial'].includes(run.status)&&<p className="hint">{STATUS[run.status]||run.status}：{run.message||run.reason||'保留已完成批次'}</p>}
  {state.error&&<p className="resource-error" role="alert">读取或生成失败：{state.error} <button className="text-link" onClick={state.retry}>重新读取</button></p>}
 </>
}

export function readingNavigationReady(section,own,comparison) {
 if(section==='comparison')return Boolean((comparison.value||comparison.error)&&!comparison.loading&&!own.loading)
 return ['reading','advice'].includes(section)&&Boolean((own.value||own.error)&&!own.loading)
}

export default function MaterialReading({scope,item,summary,onOpenDetail,onAsk,active,onCompare}) {
 const [ref,enabled]=useReadingVisibility(active)
 const own=useAnalysis(scope,item,'material',enabled)
 const answerScope={delivery_id:scope.deliveryId,delivery_revision:scope.revision,at_seq:scope.atSeq,sealed_only:scope.sealedOnly}
 const onRecord=id=>onOpenDetail?.({type:'record',taskId:scope.taskId,answerScope,record:{record_id:id,task_id:scope.taskId,delivery_id:scope.deliveryId,delivery_revision:scope.revision,details_loaded:false}})
 const onKnowledge=block=>onOpenDetail?.({type:'knowledge',taskId:scope.taskId,answerScope,block:{...block,archived:true}})
 const ask=reference=>onAsk?.({markers:[`SOURCE:${item.group_id}`,`DEF:${item.property_id}`],materialAnalysisRef:{id:reference.id,version:reference.version,content_sha256:reference.content_sha256},prompt:`请依据这份已保存的解读，说明${item.property_name}的适用条件。`})
 const main=primaryReading(own.value?.report,item.summary)
 return <section ref={ref} className="reading-section reading-main" aria-label="本篇解读" hidden={!active}>
  <div className="reading-section-heading"><h3>本篇解读</h3><span className="reading-status">本资料 · {item.property_name}</span></div>
  <details className="reading-overview-disclosure"><summary>资料概况 · 单位、波段与历元</summary><MaterialOverview profile={item.profile||{}} item={item}/></details>
  <AnalysisControls state={own} kind="material" onAsk={onAsk?ask:null}/>
  {main.report?<MaterialAnalysisView report={main.report} onRecord={onRecord} onKnowledge={onKnowledge}/>:summary}
  <MaterialAdvice report={main.report||{knowledge_blocks:item.summary?.basis?.knowledge||[]}} onRecord={onRecord} onKnowledge={onKnowledge}/>
  <details className="reading-originals"><summary>原稿与版本</summary><p className="hint">原总结和补充版本均独立保存；此处不改写原交付。</p>{main.report&&summary}{own.value?.report&&<details><summary>本补充版本完整保存内容</summary><MaterialAnalysisView report={own.value.report} onRecord={onRecord} onKnowledge={onKnowledge}/><MaterialAdvice report={own.value.report} onRecord={onRecord} onKnowledge={onKnowledge}/></details>}</details>
  <button className="reading-comparison-link" onClick={()=>onCompare?.(item.property_id)}>查看本任务该性质的跨来源对照 →</button>
 </section>
}
