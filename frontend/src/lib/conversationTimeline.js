// One ordered conversation model for live tasks and event-backed replay.
export function conversationTimeline(messages, stages, presentation) {
  const first = messages[0]
  const entries = messages.map(message=>({kind:'msg',id:message.id,seq:message.seq||0,at:message.at}))
  for (const stage of stages) {
    if (stage.seen===false || stage.status==='pending') continue
    const visits=stage.intervals||[]
    entries.push({kind:'stage',id:stage.id,seq:stage.id==='understand'?0:stage.id==='done'?presentation?.terminal_seq:
      visits[0]?.seq,at:stage.id==='understand'?first?.at:visits[0]?.start||presentation?.at})
  }
  const seen=new Set()
  let prior=null
  for(const point of presentation?.milestones||[]) {
    if(point.stage_id===prior) continue
    prior=point.stage_id
    if(seen.has(point.stage_id)) entries.push({kind:'visit',id:point.stage_id+':'+point.seq,
      stageId:point.stage_id,seq:point.seq,at:point.at})
    seen.add(point.stage_id)
  }
  const reviewEvents=presentation?.review_events||presentation?.reviews||[]
  for (const review of reviewEvents)
    entries.push({kind:'review',id:review.review_id+':'+(review.revision||1)+':'+review.seq,reviewId:review.review_id,
      revision:review.revision,seq:review.seq,at:review.at||review.created_at})
  return entries.sort((a,b)=>{
    if(a.id===first?.id) return -1
    if(b.id===first?.id) return 1
    if(Number.isFinite(a.seq)&&Number.isFinite(b.seq)&&a.seq!==b.seq) return a.seq-b.seq
    return (Date.parse(a.at)||0)-(Date.parse(b.at)||0)
  })
}
