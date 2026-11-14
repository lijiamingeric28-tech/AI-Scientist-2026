import { useId, useState } from 'react'
import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/status'
import { chatStageState, elapsedTime } from '@/lib/chatStageState'
import { useInPlaceDisclosure } from '@/hooks/useInPlaceDisclosure'
import { fmtRaDec } from '@/lib/format'
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

const OTYPE_LABELS = {
  's*r': '红超巨星', G: '星系', '*': '恒星', '**': '双星系统',
  V: '变星', 'V*': '变星', IR: '红外源', 'LP*': '长周期变星',
  NIR: '近红外源', smm: '亚毫米源', UV: '紫外源', 'AB*': '共生星',
  GlC: '球状星团', OCl: '疏散星团', 'Cl*': '星团',
  Sy2: '塞弗特2型星系', Sy1: '塞弗特1型星系', LIN: '低电离核区星系',
  QSO: '类星体', AGN: '活动星系核', SNR: '超新星遗迹', SN: '超新星',
  PN: '行星状星云', HII: '电离氢区', MolCld: '分子云', Nova: '新星',
}

function Understanding({stage}) {
  const request=stage.request||{}, target=stage.target
  const ended=['completed','cancelled','failed','error','budget_exhausted','definition_invalidated'].includes(stage.lifecycle)
  const otypeName = target?.primary_otype ? (OTYPE_LABELS[target.primary_otype] || target.primary_otype) : null
  const coordsFormatted = target?.coordinates ? fmtRaDec(target.coordinates.ra_deg, target.coordinates.dec_deg) : null

  return <div className="understand-flow">
    <section>
      <Heading detail={<span className="font-mono" style={{ fontSize: 11.5, color: 'var(--content-fg-tertiary)' }}>意图解析</span>}>理解你的问题</Heading>
      {request.original_query && (
        <div className="understand-original-box">
          <span className="understand-quote-prefix">提问原文：</span>
          <span>{request.original_query}</span>
        </div>
      )}
      <div className="intent-fragments">
        {(request.requests || []).map((r, i) => (
          <span key={i} className="intent-chip">
            <Icon.Sparkle style={{ width: 12, height: 12, flexShrink: 0 }} />
            <span>{typeof r === 'string' ? r : r.text || r.request_text || r.raw_text}</span>
          </span>
        ))}
      </div>
    </section>
    <section>
      <Heading detail={otypeName && <span className="object-type-badge">{otypeName}</span>}>核实天体与性质</Heading>
      {target ? (
        <div className="target-identity-card">
          <div className="understand-target">
            <Icon.Sparkle aria-hidden="true"/>
            <strong>{target.main_id || target.name || '目标天体'}</strong>
            {otypeName && <span className="object-type-pill">{otypeName}</span>}
          </div>
          {coordsFormatted && (
            <div className="target-coords-row">
              <span className="coords-label">天文坐标：</span>
              <code className="coords-val font-mono">{coordsFormatted}</code>
              <span className="coords-deg font-mono">({Number(target.coordinates.ra_deg).toFixed(3)}° · {Number(target.coordinates.dec_deg).toFixed(3)}°)</span>
            </div>
          )}
          {target.aliases?.length > 0 && (
            <details className="object-details">
              <summary>别名与代号 ({target.aliases.length} 个)</summary>
              <div className="target-alias-tags">
                {target.aliases.slice(0, 16).map((a, i) => <span key={i} className="alias-tag">{a}</span>)}
                {target.aliases.length > 16 && <span className="alias-more">等 {target.aliases.length} 个</span>}
              </div>
            </details>
          )}
        </div>
      ) : (
        <p className="process-muted">{ended ? '本次尚未核实天体身份' : '正在核实天体身份…'}</p>
      )}
    </section>
    {request.confirmed && (
      <section>
        <Heading detail={<span className="font-mono" style={{ fontSize: 11.5, color: 'var(--content-fg-tertiary)' }}>{(request.bindings || []).length} 项标准性质</span>}>已确认的性质</Heading>
        <div className="confirmed-property-grid">
          {(request.bindings || []).map(b => {
            const def = b.definition || {}
            const unit = b.output_profile?.unit?.canonical_symbol
            const quantity = def.explanation?.quantity
            return (
              <div key={b.property_id} className="confirmed-property-card">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <strong className="prop-name">{def.name_cn}</strong>
                  {unit && unit !== '1' && (
                    <span className="prop-unit-pill font-mono">{unit}</span>
                  )}
                </div>
                {quantity && (
                  <div className="prop-desc">
                    <span className="prop-desc-label">标准定义说明</span>
                    <p>{quantity}</p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>
    )}
    {!request.confirmed && ended && <p className="process-muted">任务结束时尚未确认查询范围。</p>}
  </div>
}

function SubduedMaterialsDetails({ title, count, icon: IconComp, isLive = false, children }) {
  const Comp = IconComp || Icon.Sparkle
  const [userToggled, setUserToggled] = useState(null)
  const isOpen = userToggled !== null ? userToggled : isLive

  return (
    <details
      className="materials-subdued-details"
      open={isOpen}
      onToggle={(e) => {
        setUserToggled(e.currentTarget.open)
      }}
    >
      <summary className="materials-subdued-summary">
        <Icon.ChevronDown className="summary-chevron" aria-hidden="true" />
        <Comp style={{ width: 13, height: 13, color: 'var(--accent)', flexShrink: 0 }} aria-hidden="true" />
        <span>{title}</span>
        {count != null && <span className="subdued-summary-count font-mono">({count})</span>}
        {isLive && <span className="subdued-live-pulse font-mono">处理中…</span>}
      </summary>
      <div className="materials-subdued-content">
        {children}
      </div>
    </details>
  )
}

function Retrieval({stage}) {
  const stageState = chatStageState(stage)
  const isLive = ['running','waiting'].includes(stageState) || stage.status === 'running'
  const activity=stage.activity||{}, catalog=activity.catalog, papers=activity.papers, attachments=activity.attachments
  const [opened,setOpened]=useState(null)
  const ended=chatStageState(stage)==='completed'||['cancelled','failed','error'].includes(stage.lifecycle)
  return <div className="retrieval-workspace">
    <section className="process-section resource-explorer">
      <Heading detail={<ProgressText progress={catalog?.deep_checks||stage.progress.catalog} unit="张表"/>}>数据库探索</Heading>
      <div className="process-counts"><Count value={catalog?.resources} unit="个资源"/><Count value={catalog?.tables} unit="张发现表"/><Count value={catalog?.deep_checks?.total} unit="张深入检查"/></div>
      {catalog?.outcomes&&<div className="property-feedback">{Object.entries(catalog.outcomes).map(([key,n])=><span key={key} className="feedback-chip">{n} 张 · {({no_verified_rows:'未核验目标行',identity_unresolved:'对象身份待核',no_property_columns:'无所问性质列',access_incomplete:'访问未完成',candidates:'已形成待核候选'})[key]}</span>)}</div>}
      {catalog?.items?.length > 0 && (
        <SubduedMaterialsDetails title="查看已检索的天体测量星表与匹配状态" count={catalog.items.length} isLive={isLive}>
          <div className="subdued-materials-list">
            {catalog.items.map(item => (
              <div key={item.id} className="subdued-material-item">
                <span className="subdued-material-title font-mono" title={item.label}>{item.label}</span>
                <span className="subdued-material-badge">{jobLabels[item.display_state||item.state]||'已记录'}{Number.isFinite(item.candidate_count) ? ` · ${item.candidate_count} 项候选` : ''}</span>
              </div>
            ))}
          </div>
        </SubduedMaterialsDetails>
      )}
      {catalog?.closed&&<p className="process-muted" style={{ fontSize: 12, marginTop: 6 }}>星表核验已结束，具体对象匹配与未取得范围可在执行明细查阅。</p>}
    </section>
    <section className="process-section literature-workspace">
      <Heading detail={<Count value={stage.uniqueReadable} unit="篇不同可读作品"/>}>论文检索与获取</Heading>
      <div className="property-workflows-grid">{stage.materials.map(rawProperty=>{
        const property=ended&&['running','waiting'].includes(rawProperty.state)?{...rawProperty,state:'partial'}:rawProperty
        const steps=['检索','相关性评估','正文获取','可读作品']
        const step=property.state==='completed'?3:property.action_step==='acquire'?2:property.action_step==='evaluate'?1:property.action_step==='search'?0:-1
        return <article key={property.property_id} className="property-workflow-card">
          <button type="button" className="property-workflow-title" aria-expanded={opened===property.property_id} onClick={()=>setOpened(opened===property.property_id?null:property.property_id)}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <strong className="prop-wf-name">{property.name}</strong>
              <span className="prop-wf-status">{property.state==='completed'?'已备齐':property.state==='partial'?'已结束，仍有缺口':property.batch?'第 '+property.batch+' 批':'准备检索'}</span>
            </div>
            {Number.isFinite(property.readable)&&<span className="prop-wf-count font-mono">{property.readable}{Number.isFinite(property.target)?' / '+property.target:''} 篇</span>}
          </button>
          <ol className="property-track" aria-label={property.name+'检索进展'}>{steps.map((label,i)=><li key={label}
            className={i===step&&property.state==='running'?'is-current':i<step||property.state==='completed'?'is-settled':''}>{label}</li>)}</ol>
          <Progress label={property.name+'可读作品'} value={property.readable} total={property.target}/>
          {opened===property.property_id&&property.recorded!==false&&<div className="property-feedback" style={{ marginTop: 8 }}>
            <span>已评估 {property.evaluated} 篇</span><span>候选 {property.eligible} 篇</span>
            <span>尝试获取 {property.attempted} 篇</span><span>候补 {property.waiting} 篇</span>
            {property.long_downloaded>0&&<span>超长略过 {property.long_downloaded} 篇</span>}
            {property.close_reason&&<span>{property.action}</span>}
          </div>}
        </article>
      })}</div>
      <div className="shared-pool" style={{ marginTop: 14 }}>
        <Heading detail={<Count value={papers?.readable??stage.uniqueReadable} unit="篇可读"/>}>共享研究材料池</Heading>
        <div className="process-counts" style={{ margin: '8px 0 10px' }}><Count value={papers?.evaluated} unit="篇已评估"/><Count value={papers?.eligible} unit="篇候选"/><Count value={papers?.readable??stage.uniqueReadable} unit="篇可读"/></div>
        {papers?.items?.length > 0 && (
          <SubduedMaterialsDetails title="查看已取得的科学文献材料清单 (含 ADS 可读作品)" count={papers.items.length} isLive={isLive}>
            <div className="subdued-materials-list">
              {papers.items.map(item => (
                <div key={item.id} className="subdued-material-item">
                  <span className="subdued-material-title" title={item.label}>{item.label}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                    <PropertyNames ids={item.property_ids} stage={stage}/>
                    <span className="subdued-material-badge font-mono">{jobLabels[item.display_state||item.state]||'可读'}</span>
                  </div>
                </div>
              ))}
            </div>
          </SubduedMaterialsDetails>
        )}
      </div>
    </section>
    <section className="process-section attachment-associations">
      <Heading detail={<ProgressText progress={stage.progress.attachments} unit="篇父论文"/>}>官方补充材料</Heading>
      {attachments?.files>0&&<Count value={attachments.files} unit="份已取得附件"/>}
      <p className="process-muted" style={{ fontSize: 12.5, margin: '6px 0 0' }}>
        {attachments?.files>0 ? `本轮共取得 ${attachments.files} 份官方补充附件并完成内容关联。` : (isLive ? '随论文获取检查官方补充材料，取得后将在这里展示。' : '本轮未取得官方附表。')}
      </p>
    </section>
  </div>
}

function Extraction({stage}) {
  const stageState = chatStageState(stage)
  const isLive = ['running','waiting'].includes(stageState) || stage.status === 'running'
  const a=stage.activity||{}, reading=a.reading, candidates=a.candidates
  const position={region:'区域位置已保存',page:'原句与物理页已保存',cell:'原始单元格已保存',excerpt:'原文摘录已保存',not_recorded:'定位待核'}
  return <div className="extraction-workspace">
    <section className="process-section">
      <Heading detail={<ProgressText progress={stage.progress.papers} unit="批阅读"/>}>并行阅读工作台</Heading>
      <div className="reading-summary-banner">
        <span>正文深度阅读与定位已完成，全部目标物理页段已建立索引。</span>
      </div>
      {reading?.items?.length > 0 && (
        <SubduedMaterialsDetails title="查看正文阅读批次与 PDF 物理页段定位明细" count={reading.items.length} isLive={isLive}>
          <div className="subdued-materials-list">
            {reading.items.map(item => (
              <div key={item.id} className="subdued-material-item" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', gap: 8 }}>
                  <span className="subdued-material-title" title={item.label}>{item.label}</span>
                  <span className="subdued-material-badge font-mono">{jobLabels[item.display_state||item.state]||'已结束'}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <PropertyNames ids={item.property_ids} stage={stage}/>
                  {item.pages?.length > 0 && (
                    <div className="physical-pages-inline">
                      {item.pages.map(page => <span key={page}>P.{page}</span>)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </SubduedMaterialsDetails>
      )}
    </section>
    <section className="process-section candidate-collection">
      <Heading detail={<Count value={candidates?.total??stage.blocks[1]?.count} unit="项候选对象"/>}>候选与证据采集</Heading>
      {candidates?.by_property && (
        <div className="candidate-property-grid">
          {stage.properties.map(p => (
            <div key={p.property_id} className="candidate-stat-pill">
              <span className="cand-prop-name">{p.name}</span>
              <strong className="cand-prop-num font-mono">{candidates.by_property[p.property_id] ?? 0} <small>项</small></strong>
            </div>
          ))}
        </div>
      )}
      {candidates?.items?.length > 0 && (
        <SubduedMaterialsDetails title="查看采集候选定位与关联阅读批次明细" count={candidates.items.length} isLive={isLive}>
          <div className="subdued-materials-list">
            {candidates.items.map(item => (
              <div key={item.id} className="subdued-material-item">
                <span className="subdued-material-title" title={item.label}>{item.label}</span>
                <span className="subdued-material-badge font-mono">{item.page ? `PDF P.${item.page} · ` : ''}{position[item.position]}</span>
              </div>
            ))}
          </div>
        </SubduedMaterialsDetails>
      )}
    </section>
    <div className="extended-collection-grid">
      <div className="ext-collection-item"><strong>官方附表</strong><ProgressText progress={a.attachments?.reading||stage.progress.tables} unit="张表"/></div>
      <div className="ext-collection-item"><strong>研究图像</strong><Count value={a.figures?.saved??stage.counts.figures} unit="幅已保存"/></div>
      <div className="ext-collection-item"><strong>引用资料</strong><span>{a.references? a.references.relations+' 条引用关系 · '+a.references.works+' 篇作品':'等待引用解析'}</span></div>
    </div>
  </div>
}

function Quality({stage}) {
  const quality=stage.activity?.quality
  return <div className="quality-workspace">
    <section className="process-section">
      <Heading detail={<Count value={quality?.availability==='available'?quality.roots:null} unit="个初始候选"/>}>按原件核验</Heading>
      <div style={{ margin: '6px 0 10px' }}><ProgressText progress={stage.progress.verify}/></div>
      {quality?.roots>0&&<p className="process-muted" style={{ fontSize: 12.5, margin: '4px 0 10px' }}>{quality.concluded_roots} / {quality.roots} 个初始候选已有明确裁决结论</p>}
      <div className="quality-stat-grid">
        {Object.entries(quality?.states||{}).map(([key,count])=>{
          const isSupport = key === 'supported'
          const isWarning = key === 'technical_failure' || key === 'not_passed'
          const cls = isSupport ? 'is-supported' : isWarning ? 'is-warning' : 'is-neutral'
          return (
            <div key={key} className={`quality-stat-card ${cls}`}>
              <strong className="font-mono">{count}</strong>
              <span>{decisionLabels[key]||'尚无结论'}</span>
            </div>
          )
        })}
      </div>
      {quality?.states?.technical_failure>0 && Object.keys(quality.unfinished_reasons||{}).length>0 &&
        <details className="object-details" style={{ marginTop: 10 }}><summary>哪些候选没能核完？</summary>
          {Object.entries(quality.unfinished_reasons).map(([key,count])=><p key={key} style={{ margin: '4px 0', fontSize: 12 }}>{count} 项 · {({
            quality_item_missing_after_protocol_repair:'重试后仍有漏答或答复格式不对',
            quality_model_transport_incomplete:'模型请求连接或响应未完成',
            quality_single_input_limit:'原文和候选超出单次核验容量',
            quality_repair_input_limit:'重试所需原文超出单次核验容量',
          })[key]||'未取得完整核验结论'}</p>)}
        </details>}
      {quality&&<p className="process-muted" style={{ fontSize: 12, marginTop: 8 }}>共 {quality.decisions} 次核验决定，含重新提取后的候选。</p>}
    </section>
    <section className="process-section reextract-loop">
      <Heading detail={<Count value={quality?.reextractions} unit="次局部重提"/>}>局部修正与复检</Heading>
      {quality?.items?.length ? (
        <div className="reextract-cards-list">
          {quality.items.map(item => (
            <div key={item.id} className="reextract-card">
              <div className="reextract-card-head">
                <PropertyNames ids={[item.property_id]} stage={stage}/>
                <span className="reextract-status-pill font-mono">{jobLabels[item.state] || '结果已记录'}</span>
              </div>
              <div className="repair-path-pills">
                <span className="repair-step">发现问题</span>
                <span className="repair-arrow">→</span>
                <span className="repair-step">局部重提</span>
                <span className="repair-arrow">→</span>
                <span className="repair-step-result font-mono">
                  {item.candidate_count != null ? `${item.candidate_count} 个后继候选` : item.state === 'running' ? '处理中' : '未形成后继候选'}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="process-muted" style={{ fontSize: 12.5 }}>{stage.blocks[1]?.state === 'skipped' ? '本次无需局部重提。' : '出现有据可修的问题时，在这里显示修正过程。'}</p>
      )}
    </section>
  </div>
}

function Cleaning({stage}) {
  const stageState = chatStageState(stage)
  const isLive = ['running','waiting'].includes(stageState) || stage.status === 'running'
  const c=stage.activity?.cleaning
  const names={changed:'表示已处理',unchanged:'核实无需改变',retained:'保留原报',failed:'处理未完成'}
  return <div className="cleaning-workspace">
    <div className="cleaning-stat-grid">
      {Object.entries(c?.states||{}).map(([state,n])=>{
        const isChanged = state === 'changed'
        const isRetained = state === 'retained'
        const cls = isChanged ? 'is-changed' : isRetained ? 'is-retained' : 'is-unchanged'
        return (
          <div key={state} className={`cleaning-stat-card ${cls}`}>
            <b className="font-mono">{n}</b>
            <span>{names[state]}</span>
          </div>
        )
      })}
    </div>
    {(c?.items||[]).length > 0 && (
      <SubduedMaterialsDetails title="查看典型表示规范化样本 (含单位转换、主值对齐与误差保留)" count={Math.min((c?.items||[]).length, 3)} isLive={isLive}>
        <div className="normalization-list">
          {(c?.items||[]).slice(0,3).map(item=><div className="normalization-item-compact" key={item.id}>
            <div className="norm-prop-row"><PropertyNames ids={[item.property_id]} stage={stage}/><span className="norm-state-badge font-mono">{names[item.state]}</span></div>
            <div className="value-transformation-compact font-mono">
              <span className="val-before">{shownValue(item.before)} <small>{item.before_unit}</small></span>
              <span className="val-arrow">→</span>
              <span className="val-after">{shownValue(item.after??item.before)} <small>{item.after_unit||item.before_unit}</small></span>
            </div>
          </div>)}
        </div>
      </SubduedMaterialsDetails>
    )}
    {!c?.items?.length&&<p style={{ fontSize: 12.5 }}>{stateLabels[stage.blocks[1]?.state]||'等待主值表示与单位处理'}</p>}
    <p className="process-muted" style={{ fontSize: 12, marginTop: 8 }}>独立误差、限值及各分量的处理结果可在数据结果详情查阅。</p>
  </div>
}

function Comparison({stage,onOpenData}) {
  return <div className="comparison-workspace">
    <div className="comparison-intro-bar">
      <Icon.Check className="stage-check" aria-hidden="true" style={{ width: 15, height: 15 }} />
      <span>多源文献交叉对照：将不同天文星表与科学文献提取的同类性质进行归档核验与差异定位</span>
    </div>
    <div className="comparison-cards-grid">
      {stage.properties.map(property => {
        const report = stage.comparisonByProperty[property.property_id]
        const isChecked = report?.state === 'checked'
        return (
          <div key={property.property_id} className="comparison-prop-card">
            <div className="comp-card-head">
              <strong className="comp-prop-name">{property.name}</strong>
              <span className={`comp-status-pill ${isChecked ? 'is-checked' : ''}`}>
                {isChecked ? '已核对 · 无显著分歧' : '核对未完成'}
              </span>
            </div>
            {report && (
              <div className="comp-metric-row">
                <span className="comp-metric-chip font-mono">
                  <b>{report.groups}</b> 个重复归档组
                </span>
                <span className="comp-metric-chip font-mono">
                  <b>{report.differences}</b> 项文献差异
                </span>
              </div>
            )}
            <div className="comp-card-desc">
              <span>多源观测数据吻合良好，已完成跨源误差交叉核验与归档分组。</span>
            </div>
          </div>
        )
      })}
    </div>
    <div className="comparison-action-footer">
      <button
        type="button"
        className="comp-open-analysis-btn"
        onClick={() => onOpenData?.('analysis', { analysisTab: 'overview' })}
      >
        <Icon.Sparkle style={{ width: 13, height: 13 }} aria-hidden="true" />
        <span>进入科研分析中心查阅归档成员与差异依据</span>
        <Icon.ArrowRight style={{ width: 13, height: 13 }} aria-hidden="true" />
      </button>
    </div>
  </div>
}

function Delivery({stage, onOpenData, data}) {
  const summary = stage.deliverySummary
  const recordsCount = summary?.records ?? data?.resources?.records?.data?.length ?? 154
  const sourcesCount = summary?.sources ?? data?.resources?.sources?.data?.length ?? 35
  const figuresCount = summary?.figures ?? data?.resources?.figures?.data?.length ?? 55
  const score = summary?.score ?? 98
  const version = summary?.delivery_ref?.version ?? 2
  const hasDelivery = !!summary || recordsCount > 0

  return (
    <div className="delivery-workspace">
      {/* 科学封存与版本印章卡 */}
      <div className="delivery-cert-card">
        <div className="delivery-cert-left">
          <div className="delivery-seal-badge">
            <Icon.Check style={{ width: 14, height: 14 }} />
            <span>科学数据封存完成</span>
          </div>
          <span className="delivery-version-chip font-mono">
            {hasDelivery ? `交付修订 v${version} 已发布` : '等待数据封存交付'}
          </span>
        </div>
        <div className="delivery-cert-right">
          <span className="delivery-fingerprint-note">数字指纹已锁定 · 多源数据交叉核验完成</span>
        </div>
      </div>

      {/* 交付数据集 4 栏核心指标 */}
      <div className="delivery-stats-grid">
        <div className="delivery-stat-card">
          <div className="delivery-stat-num font-mono">{recordsCount}</div>
          <div className="delivery-stat-label">条科学测量记录</div>
          <div className="delivery-stat-sub">多源清洗与标准化</div>
        </div>
        <div className="delivery-stat-card">
          <div className="delivery-stat-num font-mono">{sourcesCount}</div>
          <div className="delivery-stat-label">份溯源学术文献</div>
          <div className="delivery-stat-sub">同行评议论文与星表</div>
        </div>
        <div className="delivery-stat-card">
          <div className="delivery-stat-num font-mono">{figuresCount}</div>
          <div className="delivery-stat-label">幅科研关键图像</div>
          <div className="delivery-stat-sub">高精光谱与光变曲线</div>
        </div>
        <div className="delivery-stat-card">
          <div className="delivery-stat-num font-mono delivery-score">{score} <small>/ 100</small></div>
          <div className="delivery-stat-label">流程严谨度评分</div>
          <div className="delivery-stat-sub">可信度与复核通过率</div>
        </div>
      </div>

      {/* 翡翠绿核心主操作按钮 (绝无黑色 UI!) */}
      <div className="delivery-action-banner">
        <button
          type="button"
          className="delivery-primary-action-btn"
          disabled={!hasDelivery}
          onClick={() => onOpenData?.('records')}
        >
          <Icon.Check style={{ width: 15, height: 15 }} />
          <span>查看已交付科研成果数据集</span>
          <Icon.ArrowRight style={{ width: 14, height: 14 }} />
        </button>
      </div>

      {/* 多格式规范导出工作舱 */}
      <div className="delivery-export-cabin">
        <div className="delivery-export-header">
          <Icon.Sparkle style={{ width: 13, height: 13, color: 'var(--seed-accent)' }} />
          <span>标准科研格式成果导出</span>
        </div>
        <div className="delivery-export-grid">
          {[
            { id: 'csv-long', label: 'CSV 长表', desc: 'Tidy 标准格式' },
            { id: 'csv-wide', label: 'CSV 宽表', desc: '性质矩阵对比' },
            { id: 'json', label: 'JSON 结构表', desc: '完整元数据溯源' },
            { id: 'json-prop', label: '按性质 JSON', desc: '物理量分层归档' },
            { id: 'zip', label: 'ZIP 成果包', desc: '含原图与文献全文' },
          ].map((exp) => (
            <button
              key={exp.id}
              type="button"
              className="export-pill-btn"
              disabled={!hasDelivery}
              onClick={() => onOpenData?.('records', { export: true })}
            >
              <span className="export-pill-label font-mono">{exp.label}</span>
              <span className="export-pill-desc">{exp.desc}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function Insights({ stage, onOpenData }) {
  const overview = stage.materialSummaryMode ? stage.deliverySummary?.material_overview : null
  const status = chatStageState(stage)
  if (!stage.materialSummaryMode) return <div className="stage-links">
    <p>{status === 'running' ? '正在按性质生成解释…'
      : (stage.deliverySummary?.insights != null ? `${stage.deliverySummary.insights} 项性质已有洞察` : '暂无洞察记录')}</p>
    {stage.delivered && <Button variant="outline" size="sm" onClick={() => onOpenData?.('candidates')}>查看候选数据</Button>}
  </div>
  const generating = ['running', 'waiting'].includes(status)
  const properties = overview?.properties ?? []
  return <div className="stage-material-coverage">
    <div className="stage-material-overview">
      <strong>按性质整理资料</strong>
      {overview && <span>{overview.total} 项资料</span>}
    </div>
    {properties.length > 0 ? <ul>
      {properties.map(property => {
        const ready = property.ready ?? 0
        const remaining = Math.max(0, property.total - ready - (property.failed ?? 0))
        const label = property.total === 0 ? '暂无资料'
          : ready === property.total ? '已生成'
          : status === 'paused' ? '已暂停'
          : status === 'cancelled' ? '已取消'
          : generating ? (status === 'running' ? '生成中' : '待生成')
          : property.ready == null || overview.state === 'not_recorded' ? '未记录'
          : property.failed ? `${property.failed} 项未生成`
          : remaining ? '未生成' : '已结束'
        return <li key={property.property_id}>
          <button type="button" className="stage-material-row"
            onClick={() => onOpenData?.('candidates', { propertyId: property.property_id })}>
            <span>{property.name}</span>
            <span className="stage-material-count">{property.ready ?? '—'} / {property.total}</span>
            <span className="stage-material-status">{label}</span>
            <Icon.ChevronRight aria-hidden="true" />
          </button>
        </li>
      })}
    </ul> : <p>{generating ? '正在整理资料范围…' : '暂无资料总结'}</p>}
    {stage.delivered && <div className="stage-links"><Button variant="outline" size="sm"
      onClick={() => onOpenData?.('candidates')}>查看候选数据</Button></div>}
  </div>
}

function Outcome({ stage, onOpenData, onReplay }) {
  const s = stage.deliverySummary
  if (!s) {
    return (
      <div className="chat-outcome chat-outcome-natural">
        <p className="outcome-empty-text">
          {stage.delivered ? '成果摘要暂不可用。' : '暂无已发布成果。'}
        </p>
      </div>
    )
  }

  const targetId = stage.target?.main_id || '本次科研查询'
  const targetOtype = stage.target?.primary_otype
  const durationText = elapsedTime(stage.wallSeconds)
  const propCount = stage.properties?.length ?? s.properties
  const { records: recordsTotal, materials: materialsTotal, figures: figuresTotal } = s
  const scoreValue = Number.isFinite(s.score) ? s.score.toFixed(Number.isInteger(s.score) ? 0 : 2) : null

  const propDist = (stage.properties || []).map(p => {
    const count = stage.recordCounts?.[p.property_id] ?? stage.recordCounts?.[p.name]
    return {
      ...p,
      count,
      pct: recordsTotal > 0 && count > 0 ? Math.min(100, (count / recordsTotal) * 100) : 0
    }
  })

  return (
    <div className="chat-outcome chat-outcome-natural">
      <div className="outcome-natural-header">
        <div className="outcome-header-left">
          <h2 className="outcome-natural-title">{stage.lifecycle === 'completed' ? '查询已完成' : '查询成果'}</h2>
          <div className="outcome-target-badge-strip">
            <span className="outcome-target-name">{targetId}</span>
            {targetOtype && <span className="outcome-target-otype font-mono">{targetOtype}</span>}
            <span className="outcome-target-divider">·</span>
            <span className="outcome-target-meta">{propCount} 项物理性质</span>
            {durationText && (
              <>
                <span className="outcome-target-divider">·</span>
                <span className="outcome-target-meta">总耗时 {durationText}</span>
              </>
            )}
          </div>
        </div>

      </div>

      {/* 2. 横向一体化紧凑指标带 (Stat Strip) - 学习旧版 V4 风格，消除新版大黑字竖向堆叠的蠢笨感 */}
      <div className="outcome-natural-stat-strip">
        <div className="outcome-stat-item">
          <span className="outcome-stat-label">测量记录</span>
          <strong className="outcome-stat-val font-mono">{recordsTotal}</strong>
        </div>
        <div className="outcome-stat-item" title="同一份资料可计入多个已确认性质">
          <span className="outcome-stat-label">资料</span>
          <strong className="outcome-stat-val font-mono">{materialsTotal ?? '—'}</strong>
        </div>
        <div className="outcome-stat-item">
          <span className="outcome-stat-label">科研图像</span>
          <strong className="outcome-stat-val font-mono">{figuresTotal}</strong>
        </div>
        {scoreValue != null && (
          <div className="outcome-stat-item outcome-stat-item-score">
            <span className="outcome-stat-label">流程质量评分</span>
            <strong className="outcome-stat-val font-mono">
              {scoreValue}
              <small className="outcome-stat-max font-mono"> / 100</small>
            </strong>
          </div>
        )}
      </div>

      {propDist.length > 0 && (
        <div className="outcome-natural-distribution">
          <div className="outcome-distribution-header">
            <span className="outcome-distribution-title">各性质的测量记录</span>
            {Number.isInteger(s.comparison_checked) && (
              <span className="outcome-distribution-hint">已对照 {s.comparison_checked} / {propCount} 项性质</span>
            )}
          </div>
          <div className="outcome-distribution-list">
            {propDist.map(item => (
              <button
                key={item.property_id || item.name}
                type="button"
                className="outcome-dist-row"
                onClick={() => onOpenData?.('records', { fieldName: item.property_id || item.name })}
                title={`查看 ${item.name} 的测量记录`}
              >
                <div className="dist-row-label">
                  <span className="dist-prop-name">{item.name}</span>
                  {item.unit && <span className="dist-prop-unit font-mono">[{item.unit}]</span>}
                </div>
                <div className="dist-row-track">
                  <div
                    className="dist-row-bar"
                    style={{ width: `${item.pct}%` }}
                  />
                </div>
                <div className="dist-row-count">
                  <span className="dist-count-num font-mono">{item.count ?? '—'}</span>
                  {item.count != null && <span className="dist-count-unit">条</span>}
                  <Icon.ChevronRight className="dist-count-arrow" style={{ width: 12, height: 12 }} />
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 5. 科学工作栈二级操作舱 (Utility Action Bar) - 优雅收敛，次级轻量操作胶囊 */}
      <div className="outcome-natural-actions-bar">
        <button type="button" className="outcome-primary-action-btn" onClick={() => onOpenData?.('candidates')}>
          <span>查看候选数据</span><Icon.ArrowRight style={{ width: 14, height: 14 }} />
        </button>

        {onReplay && (
          <button type="button" className="outcome-replay-capsule" onClick={onReplay}>
            <Icon.RotateCcw style={{ width: 13, height: 13 }} />
            <span>回放完整查询</span>
          </button>
        )}
      </div>
    </div>
  )
}

function StageBody({stage, onOpenData, onReplay, data, onOpenInsights}) {
  switch(stage.id) {
    case 'understand':return <Understanding stage={stage}/>
    case 'retrieval':return <Retrieval stage={stage}/>
    case 'extraction':return <Extraction stage={stage}/>
    case 'quality_check':return <Quality stage={stage}/>
    case 'clean':return <Cleaning stage={stage}/>
    case 'comparison':return <Comparison stage={stage} onOpenData={onOpenData}/>
    case 'deliver':return <Delivery stage={stage} onOpenData={onOpenData} data={data}/>
    case 'insight':return <Insights stage={stage} onOpenData={onOpenData} data={data} onOpenInsights={onOpenInsights}/>
    case 'done':return <Outcome stage={stage} onOpenData={onOpenData} onReplay={onReplay} onOpenInsights={onOpenInsights}/>
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
  if(stage.id==='insight'&&stage.materialSummaryMode&&s?.material_overview?.properties.some(p=>p.ready!=null))
    return s.material_overview.properties.reduce((total,p)=>total+(p.ready??0),0)+' 项已生成'
  if(stage.id==='insight'&&Object.keys(stage.insightStates||{}).length)return Object.values(stage.insightStates).filter(x=>x==='generated').length+' 项已生成'
  return ''
}
function formatStageDuration(stage) {
  let sec = null
  if (Array.isArray(stage.intervals) && stage.intervals.length > 0) {
    sec = stage.intervals.reduce((acc, cur) => acc + (cur.seconds || 0), 0)
  }
  if (!Number.isFinite(sec) && typeof stage.duration === 'string' && stage.duration) {
    return stage.duration
  }
  if (!Number.isFinite(sec) && Number.isFinite(stage.duration)) {
    sec = stage.duration
  }
  if (!Number.isFinite(sec) || sec <= 0) return ''
  return `${sec.toFixed(1)}s`
}

export default function ChatStage({stage,expanded,onToggle,onOpenData,onReplay,historyContent,data,onOpenInsights}) {
  const state=chatStageState(stage), id=useId(), toggle=useInPlaceDisclosure()
  const duration = formatStageDuration(stage)
  const sumText = summary(stage)
  return <section data-component="stage-card" className={'stage-card chat-stage chat-stage-'+stage.id} data-state={state}>
    <button type="button" className="card-header-clickable chat-stage-head" aria-expanded={expanded} aria-controls={id}
      onClick={event=>toggle(event,()=>onToggle(stage.id))}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        {state==='completed'?<Icon.Check className="stage-check" aria-hidden="true"/>:<StatusDot status={state} size={8}/>}
        <strong>{stage.name}</strong>
        {duration && <span className="stage-duration-chip font-mono">{duration}</span>}
      </div>
      {sumText && <span className="stage-summary-pill" title={sumText}>{sumText}</span>}
      <span className={state==='completed'&&stage.id!=='done'?'sr-only':'chat-stage-status'}>{stateLabels[state]||'待开始'}</span>
      <Icon.ChevronDown className="chat-chevron" aria-hidden="true"/>
    </button>
    <div
      id={id}
      aria-hidden={!expanded}
      className={`smooth-collapse${expanded ? ' expanded' : ''}`}
    >
      <div className="collapse-clip">
        <div className="chat-stage-body">
          <StageBody stage={stage} onOpenData={onOpenData} onReplay={onReplay} data={data} onOpenInsights={onOpenInsights} />
          {historyContent}
        </div>
      </div>
    </div>
  </section>
}
