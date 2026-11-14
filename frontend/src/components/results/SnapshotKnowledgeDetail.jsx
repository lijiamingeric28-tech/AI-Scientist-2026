import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { displayText } from '@/lib/researchDisplay'
import { LatexMath, LatexText } from './LatexMath'
import { getTaskKnowledgeContext, getKnowledgeItem } from '@/services/api'

export default function SnapshotKnowledgeDetail({block,scope,onClose,onOpenCurrent,initialTab='overview'}) {
 const [tab,setTab]=useState(initialTab),[state,setState]=useState({}),[currentError,setCurrentError]=useState('')
 const key=JSON.stringify([scope,block.entry_id,block.claim?.claim_id,block.content_sha256])
 useEffect(()=>{
  if(block.current_library||!scope?.taskId||!scope.deliveryId||!scope.revision||!block.entry_id||!block.claim?.claim_id||!block.content_sha256)return
  const controller=new AbortController()
  getTaskKnowledgeContext(scope.taskId,scope.deliveryId,scope.revision,{atSeq:scope.atSeq,sealedOnly:scope.sealedOnly,entryId:block.entry_id,claimId:block.claim.claim_id,entryHash:block.content_sha256,signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setState({key,value:value.reference})}).catch(error=>{if(!controller.signal.aborted)setState({key,error:error.message})})
  return()=>controller.abort()
 },[key])
 const current=state.key===key?state:{},view=current.value,entry=view?.entry||block.raw_entry||block
 const fragments=block.cited_fragments||[block]
 const formula=entry.formula||block.formula||block.claim?.formula
 const conditions=entry.conditions||block.conditions||[]
 const sources=entry.sources||block.sources||[]
 const list=value=>Array.isArray(value)?value:[value]
 const field=(name,value)=><section className="snapshot-field"><h4>{name}</h4>{value?<p>{displayText(value)}</p>:<p className="hint">未提供</p>}</section>
 async function openCurrent(){setCurrentError('');try{const item=await getKnowledgeItem(block.entry_id);onOpenCurrent?.({entry_id:item.id||block.entry_id,title:item.title||item.name,claim:{text:item.description||item.text||''},raw_entry:item,archived:true,current_library:true})}catch(error){setCurrentError(error.message)}}
 return <><header className="snapshot-knowledge-header"><div><span className="reading-eyebrow">{block.current_library?'当前知识库版本 · 只读':'任务当时版本 · 只读'}</span><h2 data-detail-heading tabIndex={-1}>{block.title||entry.title||entry.name||'知识依据'}</h2></div><Button variant="ghost" aria-label="关闭知识依据" onClick={onClose}>×</Button></header><nav className="snapshot-knowledge-tabs" aria-label="知识依据分类">{[['overview','概览'],['relations','关联'],['sources','来源']].map(([id,label])=><button key={id} aria-pressed={tab===id} className={tab===id?'active':''} onClick={()=>setTab(id)}>{label}</button>)}</nav><div className="context-content snapshot-knowledge-body">
 {!block.current_library&&!current.value&&!current.error&&scope?.deliveryId&&block.content_sha256&&<p className="hint" role="status">正在读取该引用的保存版本…</p>}
 {current.error&&<p className="hint">同版本扩展暂不可读：{current.error}。以下保留本次已保存的引用片段。</p>}
 {tab==='overview'&&<><section className="snapshot-cited-fragment"><h4>{block.current_library?'当前条目正文':'本次引用片段'}</h4>{block.current_library&&<p className="hint">这是当前知识库内容，与任务当时的引用版本分别展示。</p>}{fragments.map((f,i)=><p key={i}><LatexText text={f.claim?.text||''}/></p>)}</section><section className="snapshot-field"><h4>科学公式</h4>{formula?<div className="reading-formula"><LatexMath formula={formula} displayMode/></div>:<p className="hint">该版本未保存公式；正文中的数学关系仍按原文展示。</p>}</section>{field('知识正文与物理含义',entry.description||entry.text||entry.blocks?.map(b=>b.text).join('\n'))}<section className="snapshot-field"><h4>适用条件与限定</h4>{conditions.length?list(conditions).map((v,i)=><p key={i}>{displayText(v)}</p>):<p className="hint">未提供适用条件</p>}</section>{field('参数与取值范围',entry.parameters?.length?entry.parameters:null)}</>}
 {tab==='relations'&&<><h3>当时保存的关联</h3><p className="hint">仅展示本版本明确记录的性质与关系。</p><div className="reading-properties">{(entry.properties||block.property_ids||[]).map((v,i)=><span className="filter-chip" key={i}>{displayText(v)}</span>)}</div>{!(entry.properties||block.property_ids)?.length&&<p className="hint">此版本未保存性质关联。</p>}{view?.block?.applicable_mappings?.length>0&&<details><summary>正式绑定依据</summary>{view.block.applicable_mappings.map((v,i)=><p key={i}>{displayText(v)}</p>)}</details>}</>}
 {tab==='sources'&&<><h3>来源与版本</h3>{list(sources).filter(Boolean).map((source,i)=><div className="snapshot-field" key={i}><p>{source.url?<a className="text-link" href={source.url} target="_blank" rel="noreferrer">{displayText(source.title||source.identity?.title||source.source_id||source)} ↗</a>:displayText(source.title||source.identity?.title||source.source_id||source)}</p>{source.support_note&&<p>{source.support_note}</p>}{source.evidence?.map((piece,j)=><blockquote key={j}><LatexText text={piece.excerpt||piece.raw_text||''}/>{piece.locator&&<p className="hint">{displayText(piece.locator)}</p>}</blockquote>)}{source.locator&&<p className="hint">定位：{displayText(source.locator)}</p>}</div>)}{!sources.length&&<p className="hint">此版本未保存资料出处。</p>}<p className="hint">{entry.is_override?'用户修改的知识背景':entry.is_user?'用户自建知识':'任务保存的知识依据'}</p><details><summary>版本详情</summary><p>知识版本：{view?.knowledge_release_ref?.id||view?.library_version||'保存片段'}</p><p>条目版本：{entry.revision??'未记录'}</p>{(view?.entry_hash||block.content_sha256)&&<p>条目内容哈希：{view?.entry_hash||block.content_sha256}</p>}{(block.release_ref?.content_sha256||view?.knowledge_release_ref?.content_sha256)&&<p>知识发布哈希：{block.release_ref?.content_sha256||view?.knowledge_release_ref?.content_sha256}</p>}{block.task_context_ref?.content_sha256&&<p>任务上下文哈希：{block.task_context_ref.content_sha256}</p>}</details>{!block.current_library&&<><Button variant="outline" size="sm" onClick={openCurrent}>查看当前知识库版本</Button><p className="hint">当前版本单独打开，可能与任务当时引用不同。</p></>}{currentError&&<p role="alert">{currentError}</p>}</>}
 </div></>
}
