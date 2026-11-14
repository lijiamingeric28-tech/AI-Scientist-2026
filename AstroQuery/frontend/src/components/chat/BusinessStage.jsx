import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { STATUS_LABELS } from '@/components/status'

const labels = { pending:'未开始',waiting:'待处理',running:'进行中',completed:'已完成',partial:'部分完成',cancelled:'已终止',skipped:'无需执行',unknown:'未记录独立状态' }
const glyphs = { completed:'✓',running:'◌',waiting:'○',partial:'◐',cancelled:'⊘',pending:'·',skipped:'−' }
export default function BusinessStage({stage,expanded,onToggle,onOpenData,onOpenAgent,presentation}) {
  const Heading=onToggle?'button':'div'
  const [property,setProperty] = useState(null)
  const detail = stage.materials?.find(p=>p.property_id===property)
  return <section className={`business-stage state-${stage.status}`} data-component="stage-card" data-stage-id={stage.id}>
    <Heading className="business-stage-heading" aria-expanded={onToggle?expanded:undefined} onClick={onToggle?()=>onToggle(stage.id):undefined}>
      <span className="stage-state-glyph" aria-hidden="true">{glyphs[stage.status] || '·'}</span>
      <strong>{stage.name}</strong><span className="stage-summary">{stage.local_failures ? `${stage.local_failures}项失败记录，范围见明细` : stage.id==='done'?(STATUS_LABELS[stage.summary]||stage.summary):stage.summary}</span>
      <span className="stage-status">{stage.id==='insight'&&stage.status==='skipped'?'未启用':labels[stage.status] || STATUS_LABELS[stage.status] || '未记录'}</span>{onToggle&&<span aria-hidden="true">{expanded?'⌃':'⌄'}</span>}
    </Heading>
    {expanded && <div className="business-stage-body">
      <ol className="business-steps">{stage.blocks.map((block,i)=><li key={block.label}>
        <span className="step-number">{i+1}</span><div><h4>{block.label}<span className={"business-step-state state-"+(block.state||'unknown')} title={block.state_basis}>{labels[block.state]||'未记录独立状态'}</span></h4>
          {block.count!=null && <p className="step-count"><strong>{block.count}</strong> {block.unit}</p>}
          {block.detail && <p className="hint">{block.label==='实际结局'?(STATUS_LABELS[block.detail]||block.detail):block.detail}</p>}
          {stage.id==='retrieval' && i===1 && <><p className="hint">评估题录 → 获取正文 → 检查缺口 · 不同可读作品 {stage.uniqueReadable ?? '未记录'} 篇</p>
            <div className="retrieval-matrix"><div className="retrieval-matrix-head"><span>性质</span><span>本轮动作</span><span>已审题录</span><span>可读正文</span></div>
              {stage.materials.map(p=><button className={`retrieval-matrix-row state-${p.state}`} key={p.property_id} onClick={()=>setProperty(property===p.property_id?null:p.property_id)} aria-expanded={property===p.property_id}>
                <strong>{p.name}</strong><span>{p.action}{p.batch!=null && <small> · 第{p.batch}批</small>}</span><span>{p.evaluated} 篇</span><span>{p.readable} / {p.target} 篇</span>
              </button>)}
            </div>{detail && <div className="material-detail"><h4>{detail.name}</h4><p>实际尝试 {detail.attempted} 篇 · 可读 {detail.readable} 篇 · 已取得超长稿 {detail.long_downloaded} 篇 · 合格候补 {detail.waiting} 篇</p><p className="hint">候补不计入可读正文；具体停止与失败范围见执行明细。</p></div>}</>}
        </div></li>)}</ol>
      {stage.local_failures>0 && <p className="scope-note">保留已完成的成果。局部未处理范围可在执行明细查看，不能解释为没有科学资料。</p>}
      <div className="stage-links">
        {['retrieval','extraction'].includes(stage.id) && <button className="text-link" onClick={()=>onOpenData?.('evidence')}>查看已取得资料</button>}
        {['quality_check','clean','comparison'].includes(stage.id) && <button className="text-link" onClick={()=>onOpenData?.('analysis',{analysisTab:stage.id==='clean'?'modifications':'overview'})}>查看处理范围与依据</button>}
        {['deliver','done'].includes(stage.id) && <><Button onClick={()=>onOpenData?.('records')}>查看记录</Button><Button variant="outline" onClick={()=>onOpenData?.('records',{export:true})}>导出</Button></>}
        {stage.id==='insight' && <button className="text-link" onClick={()=>onOpenData?.('candidates')}>查看资料总结</button>}
        <>{onOpenAgent&&<button className="text-link" onClick={()=>onOpenAgent({id:null},stage)}>执行明细</button>}</>
      </div>
    </div>}
  </section>
}
