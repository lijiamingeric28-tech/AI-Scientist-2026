import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import { usePropertyLabel } from '@/lib/propertyLabel'
import ResourceState from './ResourceState'
import RuntimeInsights from './RuntimeInsights'
import TaskKnowledgeBasis from './TaskKnowledgeBasis'
import './task-insights.css'

const EMPTY = []
export function MaterialSummaryOverview({report,properties=EMPTY,onOpenProperty}) {
  const label=usePropertyLabel()
  const names=new Map(properties.map(item=>[item.property_id,item.name||item.label||item.property_id]))
  return <section className="research-insights-section" aria-label="资料总结与知识背景">
    <h3>资料总结与知识背景</h3>
    <p className="hint">资料解释保存在各份资料中，连同测量、图像与引用依据一起阅读。理论背景不替代原始测量与质量核验。</p>
    {report?.reason&&<p>{report.reason}</p>}
    {Object.entries(report?.counts||{}).map(([id,count])=><article className="insight-property" key={id}>
      <h4>{label(names.get(id)||id)}</h4><p>已完成 {count.ready??0} / {count.requested??0} 份 · 未完成 {count.failed??0} 份 · 仅书目信息 {count.bibliography??0} 份</p>
      <Button variant="outline" size="sm" onClick={()=>onOpenProperty?.(id)}>浏览资料</Button>
    </article>)}
    {!Object.keys(report?.counts||{}).length&&<Button variant="outline" onClick={()=>onOpenProperty?.()}>浏览资料</Button>}
  </section>
}

const STATUS = {complete:'已完成',partial:'部分完成',failed:'生成失败',pending:'正在生成',not_applicable:'无适用数据',cancelled:'已取消',budget_exhausted:'预算不足',unavailable:'不可用',skipped:'未生成'}
export default function TaskInsights({report,scope,properties=EMPTY,records=EMPTY,recordsResource,ensureRecords,onRetryRecords,onOpenProperty,onOpenRecord,onOpenKnowledge,active=true,initialTab='summary'}) {
  const [tab,setTab]=useState(initialTab)
  const nav=useRef(null),id=useId()
  useSlidingUnderline(nav,tab)
  const bundle=report?.schema_version==='InsightBundle/1'
  const material=bundle?report.material_report:report
  const property=bundle?report.property_report:null
  const component=report?.components?.property || report?.components?.property_report || report?.components?.property_insights
  useEffect(()=>{if(active&&tab==='properties'&&property)ensureRecords?.()},[active,tab,property,ensureRecords])
  const cards=<RuntimeInsights savedOnly report={property} records={records} onOpenRecord={onOpenRecord} onOpenKnowledge={block=>onOpenKnowledge?.({...block,archived:true})}/>
  return <section className="task-insights" aria-label="总结与洞察">
    <nav ref={nav} className="workspace-chips task-insight-tabs" role="tablist" aria-label="总结与洞察分区">
      {[['summary','资料总结'],['properties','性质洞察'],['knowledge','知识依据']].map(([key,label])=><button type="button" role="tab" id={`${id}-${key}`} aria-controls={`${id}-panel`} aria-selected={tab===key} tabIndex={tab===key?0:-1} key={key} className={`filter-chip${tab===key?' active':''}`} onClick={()=>setTab(key)} onKeyDown={event=>{const keys=['summary','properties','knowledge'];const next=event.key==='ArrowRight'?(keys.indexOf(tab)+1)%3:event.key==='ArrowLeft'?(keys.indexOf(tab)+2)%3:event.key==='Home'?0:event.key==='End'?2:null;if(next!=null){event.preventDefault();setTab(keys[next]);nav.current?.querySelectorAll('[role="tab"]')[next]?.focus()}}}>{label}</button>)}
    </nav>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`}>
      {tab==='summary'&&<MaterialSummaryOverview report={material} properties={properties} onOpenProperty={onOpenProperty}/>}
      {tab==='properties'&&<section className="research-insights-section" aria-label="性质洞察">
        {!bundle?<p className="hint">此历史任务未生成性质级综合洞察。已有资料总结、原文与输入知识背景仍可阅读。</p>:<>
          <p>性质洞察：{STATUS[property?.status||component?.status]||'尚未生成'}</p>
          {(property?.reason||component?.reason)&&<p className="hint">{property?.reason||component?.reason}</p>}
          {property ? recordsResource?<ResourceState resource={recordsResource} label="洞察测量依据" onRetry={onRetryRecords}>{cards}</ResourceState>:cards:<p className="hint">本部分没有已保存的报告；资料总结与科学数据可正常阅读。</p>}
        </>}
      </section>}
      {tab==='knowledge'&&<TaskKnowledgeBasis scope={scope} active={active} onOpenKnowledge={onOpenKnowledge}/>}
    </div>
  </section>
}
