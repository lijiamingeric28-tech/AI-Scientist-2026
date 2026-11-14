import { Button } from '@/components/ui/button'
import { LatexText } from './LatexMath'

export default function SummaryBasisDetail({detail,onClose,onKnowledge,onRecord,onSource}) {
  const knowledge=detail.tab==='knowledge',items=detail.basis?.[knowledge?'knowledge':'evidence']||[]
  return <><header className="settings-header"><h2 data-detail-heading tabIndex={-1}>{knowledge?'输入知识背景':'原文依据'}</h2><Button variant="ghost" onClick={onClose}>关闭</Button></header>
    <div className="context-content source-reading">
      {knowledge&&<p className="hint">以下为这份总结提供给生成模型的背景，按当时保存的正文读取，不表示逐句实际引用。</p>}
      {!items.length&&<p className="hint">此总结没有保存{knowledge?'知识背景':'原文依据'}。</p>}
      {items.map((item,index)=>knowledge?<section className="source-support-item" key={`${item.claim?.claim_id||item.entry_id}:${index}`}><h3>{item.title||'已保存知识背景'}</h3>{item.claim?.text&&<p><LatexText text={item.claim.text}/></p>}<Button size="sm" variant="outline" onClick={()=>onKnowledge({...item,archived:true})}>查看当时依据</Button></section>:<section className="source-support-item" key={item.evidence_id||index}>
        <h3>原文依据 {index+1}</h3><p>证据标识：{item.evidence_id}</p>
        {item.measurement_id&&<Button variant="outline" size="sm" onClick={()=>onRecord(item.measurement_id)}>定位测量与原文</Button>}
        {item.source_id&&<button type="button" className="text-link" onClick={()=>onSource(item.source_id)}>打开来源资料</button>}
      </section>)}
    </div></>
}
