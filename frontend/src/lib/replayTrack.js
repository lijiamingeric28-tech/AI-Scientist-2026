import { playbackBounds } from './playbackBounds.js'

// Bookmarks are events a viewer must actually see. Worker traffic between them
// can be sampled. Exact seeks still address the original, unabridged history.
const bookmarks=new Set(['task_state_changed','execution_stage_changed','question_ready','query_confirmed',
  'review_ready','answer_received','review_applied','review_withdrawn','delivery_ready','insight_unit_updated','insight_updated'])
export function lastAt(rows,t){
  let lo=0,hi=rows.length
  while(lo<hi){const m=(lo+hi)>>>1;if(rows[m].t<=t)lo=m+1;else hi=m}
  return lo ? rows[lo-1] : null
}
export function buildTrack(data){
  const {start,duration}=playbackBounds(data), events=[], frames=[], stops=[], gaps=[]
  let waiting=null
  for(const e of data?.timeline||[]){
    const t=(Date.parse(e.at)-start)/1000
    if(!Number.isFinite(t)||t>duration)continue
    const row={seq:e.seq,t:Math.max(0,t),kind:e.kind}
    events.push(row)
    if(e.kind==='task_state_changed')waiting=e.lifecycle==='waiting_review'?row:null
    else if(e.kind==='answer_received'&&waiting){
      // Compress an empty wait only: never jump over another saved event.
      if(events.at(-2)?.seq===waiting.seq && row.t-waiting.t>10)gaps.push({from:waiting.t,to:row.t})
      waiting=null
    }
    const important=bookmarks.has(e.kind)
    if(important||!frames.length||row.t-frames.at(-1).t>=12||e===data.timeline.at(-1)){
      frames.push(row)
    }
    if(important)stops.push(row)
  }
  return {start,duration,events,frames,stops,gaps,gates:data?.review_gates||[]}
}
// Sequence identity is independent of time: a question and a receipt may
// legitimately share a transaction timestamp and must both be painted.
export function nextPlayback(track, position, delta, released = new Set()) {
  const gate = track.gates.find(g => g.available && !released.has(g.key) &&
    position.seq >= g.question_seq && position.seq < g.answer_seq)
  if (gate) return position
  let elapsed = Math.min(track.duration, position.elapsed + delta)
  const gap = track.gaps.find(g => position.elapsed >= g.from && position.elapsed < g.to)
  if (gap) elapsed = Math.max(elapsed, gap.to)
  const next = track.stops.find(s => s.seq > position.seq && s.t <= elapsed)
  const frame = next || lastAt(track.frames, elapsed)
  return { elapsed: next ? next.t : elapsed, seq: Math.max(position.seq, frame?.seq || 0) }
}
export function advance(track,elapsed,delta){
  let t=Math.min(track.duration,elapsed+delta)
  const gap=track.gaps.find(g=>elapsed>=g.from && elapsed<g.to)
  if(gap)t=Math.max(t,gap.to)
  const next=track.stops.find(s=>s.t>elapsed && s.t<=t)
  return next?.t ?? t
}
