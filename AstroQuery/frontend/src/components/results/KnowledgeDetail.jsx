import { Button } from '@/components/ui/button'
export default function KnowledgeDetail({block,onClose}) {
 return <><header className="settings-header"><h2 data-detail-heading tabIndex={-1}>{block.title||'知识依据'}</h2><Button variant="ghost" onClick={onClose}>关闭</Button></header><div className="context-content source-reading"><p className="hint">{block.authoring_basis==='source_checked'?'来源已核读':'作者知识整理'}</p><blockquote className="evidence-text">{block.claim.text}</blockquote>{(block.conditions||[]).map((c,i)=><p key={i}>适用条件：{c}</p>)}{(block.sources||[]).map(s=><section key={s.source_id}><h3>{s.url?<a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>:s.title}</h3><p>{s.locator}</p><p>{s.support_note}</p></section>)}</div></>
}
