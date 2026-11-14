import { displayText } from '@/lib/researchDisplay'
import { typedValueText } from '@/lib/valueDisplay'
import { readingConditions } from '@/lib/scienceReading'
import { citationItems, uniqueParagraphs } from '@/lib/readingLayers'
import { LatexMath, LatexText } from './LatexMath'
import { Icon } from '@/components/icons'

export function AnalysisCoverage({report}) {
 const requested=new Set(report?.coverage?.requested_ids||[])
 if(!requested.size)return null
 const completed=new Set((report.coverage.completed_ids||[]).filter(id=>requested.has(id)))
 return <p className="reading-range">已读取记录范围：<strong>{completed.size} / {requested.size}</strong><span>仅表示解读覆盖，不代表科学可信度</span></p>
}
export function AnalysisReferences({entry,blocks=[],onRecord,onKnowledge}) {
 const refs=citationItems(entry,blocks)
 if(!refs.length)return null
 const link=(ref,index)=>ref.type==='knowledge'?<button className="reading-citation" key={ref.id} onClick={()=>onKnowledge?.({...ref.blocks[0],cited_fragments:ref.blocks})}><Icon.BookOpen width="13" height="13"/>知识：{ref.blocks[0].title||'保存条目'}{ref.blocks.length>1?` · ${ref.blocks.length} 片段`:''}</button>:<button className="reading-citation" key={ref.id} onClick={()=>onRecord?.(ref.id)}><Icon.FileText width="13" height="13"/>原文与测量 {index+1}</button>
 return <div className="reading-references"><span>依据</span>{refs.slice(0,2).map(link)}{refs.length>2&&<details><summary>更多引用 · {refs.length-2}</summary><div className="reading-reference-links">{refs.slice(2).map(link)}</div></details>}</div>
}
export function ReadingText({text=''}) {
 if(text.length<=700)return <p><LatexText text={text}/></p>
 const cut=text.lastIndexOf('。',700)>200?text.lastIndexOf('。',700)+1:700
 return <details className="reading-long-text"><summary><span className="reading-eyebrow">节选 · 展开完整解读</span><LatexText text={text.slice(0,cut)+'…'}/></summary><p><LatexText text={text}/></p></details>
}
export function AnalysisSections({report,onRecord,onKnowledge,includeUses=false,compact=true}) {
 const labels={found:report?.scope?.kind==='batch'?'批内观察':report?.scope?.kind==='property_comparison'?'跨来源观察':'主要观察',comparison:'方法与条件',...(includeUses?{uses:'研究解释'}:{}),limitations:'适用边界'}
 const seen=new Set()
 return <div className="reading-analysis-sections">{Object.entries(labels).map(([key,label])=>{
  const rows=uniqueParagraphs(report?.sections?.[key]).filter(p=>{const identity=JSON.stringify([p.text.trim(),p.claim_ids,p.measurement_ids,p.evidence_ids]);if(seen.has(identity))return false;seen.add(identity);return true})
  const paragraph=(p,i)=><div className="reading-analysis-paragraph" key={i}><ReadingText text={p.text}/><AnalysisReferences entry={p} blocks={report.knowledge_blocks} onRecord={onRecord} onKnowledge={onKnowledge}/></div>
  return rows.length>0&&<section className={`reading-analysis-section reading-section-${key}`} key={key}><h4>{label}</h4>{(compact?rows.slice(0,2):rows).map(paragraph)}{compact&&rows.length>2&&<details className="reading-section-more"><summary>节选 · 展开本节完整解读（共 {rows.length} 段）</summary>{rows.slice(2).map(paragraph)}</details>}</section>
 })}</div>
}
function RecordedTheory({blocks=[],onKnowledge}) {
 if(!blocks.length)return null
 return <details className="reading-theory"><summary><Icon.BookOpen width="16" height="16"/>生成时提供的背景 · {new Set(blocks.map(b=>b.entry_id||b.claim?.claim_id)).size} 个条目</summary><p className="hint">仅作为输入，未必被上述内容逐条引用。</p><div className="reading-reference-links">{blocks.map((b,i)=><button className="reading-citation" key={i} onClick={()=>onKnowledge?.(b)}>{b.title||'保存知识片段'} ↗</button>)}</div></details>
}
function UnverifiedNotes({notes=[]}) {
 if(!notes.length)return null
 return <details className="reading-unverified"><summary>原稿与待核对 · {notes.length} 项</summary><p className="hint">原文保留供核对，缺少有效引用的说明不作为参考基准。</p>{notes.map((n,i)=><div key={i}><span className="reading-status">待核对</span><ReadingText text={n.text||''}/></div>)}</details>
}
export function MaterialAdvice({report,onRecord,onKnowledge}) {
 const blocks=report?.knowledge_blocks||[],rec=report?.recommendations||{}
 const benchmark=rec.benchmark
 const reference=benchmark?.measurement_id&&benchmark?.source_value?benchmark:null
 const allTips=uniqueParagraphs([...(rec.data_cleaning||[]).filter(v=>v.suggestion_only).map(v=>({...v,title:v.rule,text:v.text||v.action||''})),...(rec.application_guidance||[]).filter(v=>v.suggestion_only||v.claim_ids?.length).map(v=>({...v,title:v.scenario,text:v.text||v.guidance||''})),...(report?.sections?.uses||[]).map(v=>({...v,title:'研究解释'}))])
 const tips=allTips.filter(v=>citationItems(v,blocks).length)
 const tip=(item,i)=><article className="reading-tip" key={i}><strong>{item.title||'理解提示'}</strong>{item.action&&<p className="reading-tip-action"><span className="reading-status">{{exclude:'建议排除',deprioritize:'建议降权',transform:'建议核对转换条件'}[item.action_type]||'建议核对'}</span> {item.action}</p>}<ReadingText text={item.text}/>{item.formula&&<div className="reading-formula"><LatexMath formula={item.formula} displayMode/></div>}<AnalysisReferences entry={item} blocks={blocks} onRecord={onRecord} onKnowledge={onKnowledge}/></article>
 const conditions=readingConditions(reference?.conditions)
 const unbound=allTips.filter(v=>!citationItems(v,blocks).length)
 return <div className="reading-advice"><div className="reading-section-heading"><Icon.Sparkle width="17" height="17"/><h3>理解与使用提示</h3><span className="reading-status">辅助理解</span></div>
  {reference&&<article className="reading-reference-row"><div><strong>已保存参考测量</strong><span className="reading-reference-number">{typedValueText(reference.source_value.value)} {displayText(reference.source_value.unit)}</span></div><p className="hint">原报误差：{reference.source_uncertainty?.components?.map(c=>c.raw_text||displayText(c.values)).join('；')||'未记录'} · 来源：{displayText(reference.source?.title||reference.source?.source_id)}</p><ReadingText text={reference.text||''}/><p className="hint">{conditions.length?conditions.map(c=>`${c.label}：${c.value}`).join('；'):'适用条件未记录；请结合原文核对后参考。'}</p><AnalysisReferences entry={{...reference,measurement_ids:[reference.measurement_id]}} blocks={blocks} onRecord={onRecord} onKnowledge={onKnowledge}/></article>}
  {tips.slice(0,3).map(tip)}{tips.length>3&&<details className="reading-more-tips"><summary>更多提示 · {tips.length-3}</summary>{tips.slice(3).map(tip)}</details>}
  {!reference&&!tips.length&&<p className="hint">此范围未保存具有有效引用的使用提示；原文与测量仍可查阅。</p>}
  <UnverifiedNotes notes={[...(report?.unverified_advice||[]),...unbound]}/><RecordedTheory blocks={blocks} onKnowledge={onKnowledge}/>
 </div>
}
export default function MaterialAnalysisView({report,onRecord,onKnowledge,advice=false}) {
 if(!report)return null
 if(advice)return <MaterialAdvice report={report} onRecord={onRecord} onKnowledge={onKnowledge}/>
 return <><AnalysisCoverage report={report}/><AnalysisSections report={report} onRecord={onRecord} onKnowledge={onKnowledge}/>{report.saved_source_comparisons?.length>0&&<details className="reading-theory"><summary>逐来源保存解读 · {report.saved_source_comparisons.length} 份</summary>{report.saved_source_comparisons.map((s,i)=><details className="reading-source-disclosure" key={i}><summary>{s.title} · {s.record_count} 条测量</summary><AnalysisSections report={{scope:{kind:'material'},sections:s.sections,knowledge_blocks:report.knowledge_blocks}} onRecord={onRecord} onKnowledge={onKnowledge} includeUses/></details>)}</details>}{report.saved_batch_analyses?.length>0&&<details className="reading-theory"><summary>模型分批原文 · {report.saved_batch_analyses.length} 批</summary>{report.saved_batch_analyses.map((b,i)=><details key={i}><summary>批次 {b.batch_index||i+1} · {b.record_count} 条输入记录</summary><AnalysisSections report={{scope:{kind:'batch'},sections:b.sections,knowledge_blocks:report.knowledge_blocks}} onRecord={onRecord} onKnowledge={onKnowledge} includeUses/></details>)}</details>}{report.warnings?.length>0&&<details className="reading-validation-notes"><summary>校验提示 · {report.warnings.length} 项</summary><p className="hint">已保留有效内容，原稿可在版本入口查阅。</p></details>}</>
}
