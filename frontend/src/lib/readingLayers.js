export const RESULT_TABS=[['details','数据'],['candidates','资料'],['property-comparison','性质对照'],['quality','质量与处理']]
export const QUALITY_TABS=[['overview','完成情况'],['trace','处理记录'],['comparison','覆盖与差异']]
export function resultSection(value) {
 return [...RESULT_TABS,...QUALITY_TABS].some(([key])=>key===value)?value==='quality'?'overview':value:'details'
}
export function uniqueParagraphs(rows=[]) {
 const seen=new Map()
 for(const row of rows) {
  const text=row.text?.trim()
  if(!text)continue
  if(!seen.has(text))seen.set(text,{...row})
  else for(const key of ['claim_ids','measurement_ids','evidence_ids','evidence_record_ids']) {
   const previous=seen.get(text)
   if(previous[key]||row[key])previous[key]=[...new Set([...(previous[key]||[]),...(row[key]||[])])]
  }
 }
 return [...seen.values()]
}
export function primaryReading(report,summary) {
 return report?.sections?.found?.some(p=>p.text?.trim())?{report}:{text:summary?.text||''}
}
export const analysisVersion=(versions,key)=>versions[key]||''
export function citationItems(entry={},blocks=[]) {
 const groups=new Map()
 for(const cid of new Set(entry.claim_ids||[])) {
  const block=blocks.find(b=>b.claim?.claim_id===cid)
  if(!block)continue
  const key=[block.entry_id||cid,block.raw_entry?.revision||'',block.knowledge_release_ref?.content_sha256||''].join(':')
  if(!groups.has(key))groups.set(key,{type:'knowledge',id:key,blocks:[]})
  groups.get(key).blocks.push(block)
 }
 return [...groups.values(),...[...new Set([...(entry.measurement_ids||[]),...(entry.evidence_record_ids||[])])].map(id=>({type:'record',id}))]
}
