import { useId, useState } from 'react'
import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/status'
import { chatStageState, elapsedTime } from '@/lib/chatStageState'
import { useInPlaceDisclosure } from '@/hooks/useInPlaceDisclosure'
import { PropertyDefinition } from './PropertyChoices'
import './chatStage.css'

const stateLabels = {pending:'待开始',running:'进行中',waiting:'等待处理',completed:'已完成',
  partial:'已结束',cancelled:'已取消',cancelling:'正在取消',skipped:'未启用',failed:'未完成',paused:'已暂停'}
const jobLabels = {succeeded:'已结束',running:'正在处理',ready:'等待处理',waiting_dependency:'等待前序',
  failed:'此项未完成',cancelled:'已取消',not_run:'未执行',discovered:'已发现',eligible:'待获取',
  acquiring:'正在获取',attempted:'已尝试获取',evaluated:'已评估',readable:'可读',acquired:'已取得',
  changed:'已处理',unchanged:'核实无需改变',retained:'保留原报',recheck_pending:'等待复检',
  no_target_result:'重提已结束，无目标结果',review_candidate:'待核验',collected:'已采集，交给质检',
  supported:'核验支持',not_applicable:'核验不适用',not_passed:'核验未通过',raw_retained:'已核验，保留原报',
  technical_failure:'核验未完成',needs_human:'需要人工判断',reextracted:'已完成局部重提',
  reextraction_requested:'已送局部重提',rechecked:'复检已结束',recheck_incomplete:'复检未完成',
  not_completed:'已结束，未完成核验',registered:'已登记',conclusion_unrecorded:'已交接，未保存后续结论',
  backup_unused:'本轮未使用',ended_incomplete:'已结束，此项未完成'}
const decisionLabels = {supported:'原文支持',not_applicable:'不适用',not_passed:'未通过',
  reextraction_requested:'需要重提',technical_failure:'未能完成核验',needs_human:'待人工判断',raw_retained:'保留原报'}
function Count({value,unit}) {
  return Number.isFinite(value)?<span className="process-count"><b>{value}</b> {unit}</span>:null
}
function shownValue(value) {
  return value==null?'原式已保留':typeof value==='object'?JSON.stringify(value):String(value)
}
function Progress({value,total,label}) {
  if(!Number.isFinite(value)||!Number.isFinite(total)||total<=0) return null
  return <progress className="chat-meter" value={Math.min(value,total)} max={total} aria-label={label}/>
}
function ProgressText({progress,unit}) {
  if(!progress?.total)return null
  return <span className="process-progress">{progress.finished} / {progress.total} {unit||progress.unit}已结束</span>
}
function WorkList({items=[],children,empty}) {
  return items.length?<ul className="process-list">{items.map(item=><li key={item.id} data-work-state={item.display_state||item.state}>
    <div className="process-item-title"><strong title={item.label}>{item.label}</strong>
      <span>{jobLabels[item.display_state||item.state]||'状态已记录'}</span></div>{children?.(item)}
  </li>)}</ul>:empty?<p className="process-muted">{empty}</p>:null
}
function Heading({children,detail}) {
  return <div className="process-heading"><h3>{children}</h3>{detail}</div>
}
function PropertyNames({ids,stage}) {
  const names=(ids||[]).map(id=>stage.properties.find(p=>p.property_id===id)?.name).filter(Boolean)
  return names.length?<span className="process-property">{names.join(' · ')}</span>:null
}

function Understanding({stage}) {
  const request=stage.request||{}, target=stage.target
  const ended=['completed','cancelled','failed','error','budget_exhausted','definition_invalidated'].includes(stage.lifecycle)
  return <div className="understand-flow">
    <section><Heading>理解你的问题</Heading>
      {request.original_query&&<p className="understand-original">{request.original_query}</p>}
      <div className="intent-fragments">{(request.requests||[]).map((r,i)=><span key={i}>{typeof r==='string'?r:r.text||r.request_text||r.raw_text}</span>)}</div>
    </section>
    <section><Heading detail={target&&<span className="object-type">{target.primary_otype}</span>}>核实天体与性质</Heading>
      {target?<><div className="understand-target"><Icon.Sparkle/><strong>{target.main_id}</strong></div>
        <details className="object-details"><summary>别名与坐标</summary>
          <p>{(target.aliases||[]).slice(0,12).join(' · ')}</p>
          {target.coordinates&&<p>赤经 {target.coordinates.ra_deg}°　赤纬 {target.coordinates.dec_deg}°</p>}
        </details></>:<p className="process-muted">{ended?'本次尚未核实天体身份':'正在核实天体身份'}</p>}
    </section>
    {request.confirmed && <section><Heading>已确认的性质</Heading>
      <div className="confirmed-choices">{(request.bindings||[]).map(b=><div key={b.property_id}>
        <strong>{b.definition.name_cn}</strong><PropertyDefinition binding={b}/></div>)}</div>
    </section>}
    {!request.confirmed && ended && <p className="process-muted">任务结束时尚未确认查询范围。</p>}
  </div>
}

function Retrieval({stage}) {
  const activity=stage.activity||{}, catalog=activity.catalog, papers=activity.papers, attachments=activity.attachments
  const [opened,setOpened]=useState(null)
  const ended=chatStageState(stage)==='completed'||['cancelled','failed','error'].includes(stage.lifecycle)
  return <div className="retrieval-workspace">
    <section className="process-section resource-explorer">
      <Heading detail={<ProgressText progress={catalog?.deep_checks||stage.progress.catalog} unit="张表"/>}>数据库探索</Heading>
      <div className="process-counts"><Count value={catalog?.resources} unit="个资源"/><Count value={catalog?.tables} unit="张发现表"/><Count value={catalog?.deep_checks.total} unit="张深入检查"/></div>
      {catalog?.outcomes&&<div className="property-feedback">{Object.entries(catalog.outcomes).map(([key,n])=><span key={key}>{n} 张 · {({no_verified_rows:'未核验目标行',identity_unresolved:'对象身份待核',no_property_columns:'无所问性质列',access_incomplete:'访问未完成',candidates:'已形成待核候选'})[key]}</span>)}</div>}
      <WorkList items={catalog?.items} empty={stage.blocks[0]?.state==='pending'?'等待检索星表':null}>
        {item=>Number.isFinite(item.candidate_count)&&<p>{item.candidate_count} 项待核候选</p>}
      </WorkList>
      {catalog?.closed&&<p className="process-muted">星表检查已结束。具体对象匹配和未取得的范围可在执行明细查看。</p>}
    </section>
    <section className="process-section literature-workspace">
      <Heading detail={<Count value={stage.uniqueReadable} unit="篇不同可读作品"/>}>论文检索与获取</Heading>
      <div className="property-workflows">{stage.materials.map(rawProperty=>{
        const property=ended&&['running','waiting'].includes(rawProperty.state)?{...rawProperty,state:'partial'}:rawProperty
        const steps=['检索','相关性评估','正文获取','可读作品']
        const step=property.state==='completed'?3:property.action_step==='acquire'?2:property.action_step==='evaluate'?1:property.action_step==='search'?0:-1
        return <article key={property.property_id} className="property-workflow">
          <button className="property-workflow-title" aria-expanded={opened===property.property_id} onClick={()=>setOpened(opened===property.property_id?null:property.property_id)}>
            <strong>{property.name}</strong><span>{property.state==='completed'?'已备齐':property.state==='partial'?'已结束，仍有缺口':property.state==='unknown'?'此历史未保存分项进度':property.batch?'第 '+property.batch+' 批':'准备检索'}</span>
            {Number.isFinite(property.readable)&&<b>{property.readable}{Number.isFinite(property.target)?' / '+property.target:''} 篇</b>}
          </button>
          <ol className="property-track" aria-label={property.name+'检索进展'}>{steps.map((label,i)=><li key={label}
            className={i===step&&property.state==='running'?'is-current':i<step||property.state==='completed'?'is-settled':''}>{label}</li>)}</ol>
          <Progress label={property.name+'可读作品'} value={property.readable} total={property.target}/>
          {opened===property.property_id&&property.recorded!==false&&<div className="property-feedback">
            <span>已评估 {property.evaluated} 篇</span><span>候选 {property.eligible} 篇</span>
            <span>尝试获取 {property.attempted} 篇</span><span>候补 {property.waiting} 篇</span>
            {property.long_downloaded>0&&<span>超长略过 {property.long_downloaded} 篇</span>}
            {property.close_reason&&<span>{property.action}</span>}
          </div>}
        </article>
      })}</div>
      <div className="shared-pool"><Heading>共享研究材料池</Heading>
        <div className="process-counts"><Count value={papers?.evaluated} unit="篇已评估"/><Count value={papers?.eligible} unit="篇候选"/><Count value={papers?.readable??stage.uniqueReadable} unit="篇可读"/></div>
        <WorkList items={papers?.items}>{item=><PropertyNames ids={item.property_ids} stage={stage}/>}</WorkList>
      </div>
    </section>
    <section className="process-section attachment-associations">
      <Heading detail={<ProgressText progress={stage.progress.attachments} unit="篇父论文"/>}>官方补充材料</Heading>
      {attachments?.files>0&&<Count value={attachments.files} unit="份已取得附件"/>}
      <WorkList items={attachments?.items} empty={attachments?.parents?.total?
        attachments.parents.finished===attachments.parents.total?'本轮官方附件检查已结束，未取得可读附件。':'正在按已取得的论文检查官方附件。':ended?'本轮未记录官方附件检查。':'等待已取得论文。'}>
        {item=>item.parent_title&&<p className="attachment-parent">所属论文 · {item.parent_title}</p>}
      </WorkList>
    </section>
  </div>
}

function Extraction({stage}) {
  const a=stage.activity||{}, reading=a.reading, candidates=a.candidates
  const position={region:'区域位置已保存',page:'原句与物理页已保存',cell:'原始单元格已保存',excerpt:'原文摘录已保存',not_recorded:'定位待核'}
  return <div className="extraction-workspace">
    <section className="process-section"><Heading detail={<ProgressText progress={stage.progress.papers}/>}>并行阅读工作台</Heading>
      <WorkList items={reading?.items} empty={reading?.availability==='not_recorded'?'等待正文阅读批次。':null}>{item=><>
        <PropertyNames ids={item.property_ids} stage={stage}/>
        {!!item.pages?.length&&<div className="physical-pages" aria-label="PDF物理页段">{item.pages.map(page=><span key={page}>第 {page} 页</span>)}</div>}
        {!item.pages?.length&&<p className="process-muted">此批次未保存页段。</p>}
      </>}</WorkList>
    </section>
    <section className="process-section candidate-collection"><Heading detail={<Count value={candidates?.total??stage.blocks[1]?.count} unit="项候选对象"/>}>候选与证据采集</Heading>
      {candidates?.by_property&&<div className="candidate-property-counts">{stage.properties.map(p=><div key={p.property_id}>
        <span>{p.name}</span><strong>{candidates.by_property[p.property_id]??0} 项</strong></div>)}</div>}
      <WorkList items={candidates?.items}>{item=><p>{item.page?'PDF 物理第 '+item.page+' 页 · ':''}{position[item.position]}{item.batch_id?' · 已关联阅读批次':''}</p>}</WorkList>

    </section>
    <div className="extended-collection">
      <div><strong>官方附表</strong><ProgressText progress={a.attachments?.reading||stage.progress.tables} unit="张表"/></div>
      <div><strong>研究图像</strong><Count value={a.figures?.saved??stage.counts.figures} unit="幅已保存"/></div>
      <div><strong>引用资料</strong><span>{a.references? a.references.relations+' 条引用关系 · '+a.references.works+' 篇被引作品':'等待引用解析'}</span></div>
    </div>
  </div>
}

function Quality({stage}) {
  const quality=stage.activity?.quality
  return <div className="quality-workspace">
    <section className="process-section"><Heading detail={<Count value={quality?.availability==='available'?quality.roots:null} unit="个初始候选"/>}>按原件核验</Heading>
      <ProgressText progress={stage.progress.verify}/>
      {quality?.roots>0&&<p>{quality.concluded_roots} / {quality.roots} 个初始候选已有明确结论</p>}
      <div className="quality-outcomes">{Object.entries(quality?.states||{}).map(([key,count])=><div key={key}><strong>{count}</strong><span>{decisionLabels[key]||'尚无结论'}</span></div>)}</div>
      {quality?.states?.technical_failure>0 && Object.keys(quality.unfinished_reasons||{}).length>0 &&
        <details className="object-details"><summary>哪些候选没能核完？</summary>
          {Object.entries(quality.unfinished_reasons).map(([key,count])=><p key={key}>{count} 项 · {({
            quality_item_missing_after_protocol_repair:'重试后仍有漏答或答复格式不对',
            quality_model_transport_incomplete:'模型请求连接或响应未完成',
            quality_single_input_limit:'原文和候选超出单次核验容量',
            quality_repair_input_limit:'重试所需原文超出单次核验容量',
          })[key]||'未取得完整核验结论'}</p>)}
        </details>}
      {quality&&<p className="process-muted">共 {quality.decisions} 次核验决定，含重新提取后的候选。</p>}
    </section>
    <section className="process-section reextract-loop"><Heading detail={<Count value={quality?.reextractions} unit="次局部重提"/>}>局部修正与复检</Heading>
      {quality?.items?.length?<ol className="reextract-items">{quality.items.map(item=><li key={item.id}>
        <PropertyNames ids={[item.property_id]} stage={stage}/><div className="repair-path"><span>发现问题</span><span>局部重提</span>
          <span>{item.candidate_count!=null?item.candidate_count+' 个后继候选':item.state==='running'?'处理中':'未形成后继候选'}</span><strong>{jobLabels[item.state]||'结果已记录'}</strong></div>
      </li>)}</ol>:<p className="process-muted">{stage.blocks[1]?.state==='skipped'?'本次无需局部重提。':'出现有据可修的问题时，在这里显示修正过程。'}</p>}
    </section>
  </div>
}

function Cleaning({stage}) {
  const c=stage.activity?.cleaning
  const names={changed:'表示已处理',unchanged:'核实无需改变',retained:'保留原报',failed:'处理未完成'}
  return <div className="cleaning-workspace">
    <div className="cleaning-counts">{Object.entries(c?.states||{}).map(([state,n])=><div key={state}><b>{n}</b><span>{names[state]}</span></div>)}</div>
    {(c?.items||[]).slice(0,3).map(item=><div className="normalization-item" key={item.id}>
      <div><PropertyNames ids={[item.property_id]} stage={stage}/><span>{names[item.state]}</span></div>
      <div className="value-transformation"><span>{shownValue(item.before)} <small>{item.before_unit}</small></span>
        <Icon.ArrowRight aria-hidden="true"/><span>{shownValue(item.after??item.before)} <small>{item.after_unit||item.before_unit}</small></span></div>
    </div>)}
    {!c?.items?.length&&<p>{stateLabels[stage.blocks[1]?.state]||'等待主值表示与单位处理'}</p>}
    <p className="process-muted">独立误差、限值及各分量的处理结果可在记录详情查阅。</p>
  </div>
}
function Comparison({stage,onOpenData}) {
  return <div className="comparison-workspace">{stage.properties.map(property=>{
    const report=stage.comparisonByProperty[property.property_id]
    return <div className="comparison-property" key={property.property_id}>
      <strong>{property.name}</strong><span>{report?(report.state==='checked'?'已核对':'核对未完成'):'尚无完整核对报告'}</span>
      {report&&<div><span>{report.groups} 个重复归档组</span><span>{report.differences} 项疑点</span></div>}
    </div>
  })}<button className="text-link" onClick={()=>onOpenData?.('analysis',{analysisTab:'overview'})}>查看归档成员与差异依据</button></div>
}
function Delivery({stage,onOpenData}) {
  const summary=stage.deliverySummary
  return <div className="delivery-workspace">
    <ol className="delivery-checkpoints"><li data-ready={!!summary}><Icon.Check/><span>科学数据封存</span></li>
      <li data-ready={!!summary}><Icon.Check/><span>{summary?'交付修订 '+summary.delivery_ref.version+' 已发布':'整理交付内容'}</span></li></ol>
    {summary&&<><p>{summary.records} 条测量 · {summary.sources} 份来源 · {summary.figures} 幅研究图像</p>
      <Button onClick={()=>onOpenData?.('records')}>查看当前科研数据 <Icon.ArrowRight/></Button>
      <div className="export-capabilities"><span>可导出</span><span>CSV 长表</span><span>CSV 宽表</span><span>JSON</span><span>按性质 JSON</span><span>ZIP</span></div></>}
  </div>
}
function Insights({stage,onOpenData}) {
  const ended=chatStageState(stage)==='completed'||['cancelled','failed','error'].includes(stage.lifecycle)
  return <div className="insight-generation">
    {stage.properties.map(p=><div key={p.property_id}><strong>{p.name}</strong><span>{stage.status==='skipped'?'本次未启用':
      ended&&!stage.insightStates[p.property_id]?'未保存生成记录':
      ended&&['pending','running'].includes(stage.insightStates[p.property_id])?'本轮未完成':
      ({generated:'已生成',not_completed:'未完成',not_applicable:'不适用',pending:'待生成',running:'正在生成'})[stage.insightStates[p.property_id]]||'等待生成记录'}</span></div>)}
    {!!stage.deliverySummary?.insights&&<button className="text-link" onClick={()=>onOpenData?.('analysis',{analysisTab:'insights'})}>阅读科研洞察</button>}
  </div>
}
function Outcome({stage,onOpenData,onReplay}) {
  const s=stage.deliverySummary
  return <div className="chat-outcome">
    <div className="query-outcome-identity"><strong>{stage.target?.main_id||'本次查询'}</strong><span>{stage.properties.length} 项性质 · {elapsedTime(stage.wallSeconds)}</span></div>
    {s?<><div className="chat-totals">{[[s.records,'条测量'],[s.sources,'份来源'],[s.figures,'幅研究图像'],[s.insights,'项性质洞察']].map(([n,label])=>
      Number.isFinite(n)&&<div key={label}><b>{n}</b><span>{label}</span></div>)}</div>
      <div className="outcome-score">{Number.isFinite(s.score)&&<span>任务流程评分 <strong>{s.score}<small> / 100</small></strong></span>}
        {s.comparison_checked<s.properties&&<span>{s.comparison_checked} / {s.properties} 项性质完成对照</span>}</div></>:
      <p>{stage.lifecycle==='cancelled'?'任务已取消':stage.lifecycle==='completed'?'任务已结束':'任务未完成'}，此时没有已发布的交付。</p>}
    <div className="outcome-actions"><Button disabled={!s} onClick={()=>onOpenData?.('records')}>查看科研数据 <Icon.ArrowRight/></Button>
      <Button variant="outline" disabled={!s} onClick={()=>onOpenData?.('evidence')}>浏览论文资料</Button>
      <Button variant="outline" disabled={!s?.insights} onClick={()=>onOpenData?.('analysis',{analysisTab:'insights'})}>阅读科研洞察</Button>
      <Button variant="outline" disabled={!s} onClick={()=>onOpenData?.('records',{export:true})}>导出研究成果</Button>
      {onReplay&&<button className="text-link" onClick={onReplay}>回放查询</button>}</div>
  </div>
}
function StageBody({stage,onOpenData,onReplay}) {
  switch(stage.id) {
    case 'understand':return <Understanding stage={stage}/>
    case 'retrieval':return <Retrieval stage={stage}/>
    case 'extraction':return <Extraction stage={stage}/>
    case 'quality_check':return <Quality stage={stage}/>
    case 'clean':return <Cleaning stage={stage}/>
    case 'comparison':return <Comparison stage={stage} onOpenData={onOpenData}/>
    case 'deliver':return <Delivery stage={stage} onOpenData={onOpenData}/>
    case 'insight':return <Insights stage={stage} onOpenData={onOpenData}/>
    case 'done':return <Outcome stage={stage} onOpenData={onOpenData} onReplay={onReplay}/>
    default:return null
  }
}
function summary(stage) {
  const a=stage.activity, s=stage.deliverySummary
  if(stage.id==='done')return s?s.records+' 条测量':''
  if(stage.id==='understand')return [stage.target?.main_id,stage.properties.length?stage.properties.length+' 项性质':null].filter(Boolean).join(' · ')
  if(stage.id==='retrieval'&&stage.uniqueReadable>0)return stage.uniqueReadable+' 篇不同可读作品'
  if(stage.id==='extraction'&&a?.candidates)return a.candidates.total+' 项候选'
  if(stage.id==='quality_check'&&a?.quality?.availability==='available')return a.quality.roots+' 项候选'
  if(stage.id==='clean'&&Number.isFinite(a?.cleaning?.states?.changed))return a.cleaning.states.changed+' 项表示变更'
  if(stage.id==='comparison')return Object.values(stage.comparisonByProperty).filter(x=>x.state==='checked').length+' 项性质已核对'
  if(stage.id==='deliver'&&s)return s.records+' 条测量已发布'
  if(stage.id==='insight'&&Object.keys(stage.insightStates).length)return Object.values(stage.insightStates).filter(x=>x==='generated').length+' 项已生成'
  return ''
}
export default function ChatStage({stage,expanded,onToggle,onOpenData,onReplay,historyContent}) {
  const state=chatStageState(stage), id=useId(), toggle=useInPlaceDisclosure()
  return <section data-component="stage-card" className={'stage-card chat-stage chat-stage-'+stage.id} data-state={state}>
    <button type="button" className="card-header-clickable chat-stage-head" aria-expanded={expanded} aria-controls={id}
      onClick={event=>toggle(event,()=>onToggle(stage.id))}>
      {state==='completed'?<Icon.Check className="stage-check" aria-hidden="true"/>:<StatusDot status={state} size={8}/>}
      <strong>{stage.name}</strong><span className="chat-stage-summary">{summary(stage)}</span>
      <span className={state==='completed'&&stage.id!=='done'?'sr-only':'chat-stage-status'}>{stateLabels[state]||'待开始'}</span>
      <Icon.ChevronDown className="chat-chevron" aria-hidden="true"/>
    </button>
    <div id={id} hidden={!expanded} className="chat-stage-body">{expanded&&<StageBody stage={stage} onOpenData={onOpenData} onReplay={onReplay}/>}
      {expanded&&historyContent}</div>
  </section>
}
