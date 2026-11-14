import test from 'node:test'
import assert from 'node:assert/strict'
import { buildTrack, advance, lastAt } from './replayTrack.js'
const at=s=>new Date(Date.UTC(2026,0,1)+s*1000).toISOString()
const row=(seq,t,kind,lifecycle)=>({seq,at:at(t),kind,lifecycle})
const base={created_at:at(0),terminal_at:at(430),timeline:[
 row(1,0,'task_state_changed','clarifying'),row(2,8,'execution_stage_changed'),
 row(3,10,'review_ready'),row(4,11,'task_state_changed','waiting_review'),
 row(5,425,'answer_received'),row(6,425.3,'review_applied'),row(7,426,'execution_stage_changed'),
 row(8,427,'delivery_ready'),row(9,430,'task_state_changed','completed'),row(10,920,'export_updated')]}
test('fast playback presents each recorded interaction, compresses only idle waiting, then reaches original terminal',()=>{
 const t=buildTrack(base);let pos=0,seqs=[]
 for(let i=0; i<20 && pos<t.duration;i++){pos=advance(t,pos,100);seqs.push(lastAt(t.frames,pos)?.seq)}
 assert.deepEqual(seqs,[2,3,4,5,6,7,8,9]);assert.equal(advance(t,11,.1),425)
 assert.equal(lastAt(t.events,424).seq,4);assert.equal(lastAt(t.events,425.2).seq,5)
 assert.equal(lastAt(t.events,t.duration).seq,9)
})
test('an event inside the apparent waiting interval is not discarded',()=>{
 const t=buildTrack({...base,timeline:[...base.timeline.slice(0,4),row(4.5,55,'batch_committed'),...base.timeline.slice(4)]})
 assert.deepEqual(t.gaps,[]);assert.equal(advance(t,11,.25),11.25)
})
test('jobs sharing a timestamp with a stage do not wipe out its milestone; empty and cancelled histories stop',()=>{
 const t=buildTrack({created_at:at(0),terminal_at:at(2),timeline:[row(1,1,'execution_stage_changed'),row(2,1,'job_state_changed'),row(3,2,'task_state_changed','cancelled')]})
 assert.equal(lastAt(t.stops,1).seq,1);assert.equal(lastAt(t.events,2).seq,3)
 assert.equal(buildTrack(null).duration,0)
})
