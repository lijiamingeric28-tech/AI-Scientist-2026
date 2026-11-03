import test from 'node:test'
import assert from 'node:assert/strict'
import { buildTrack, nextPlayback } from './replayTrack.js'
import { conversationTimeline } from './conversationTimeline.js'

const at = n => new Date(Date.UTC(2026,0,1) + n*1000).toISOString()
const event = (seq,t,kind) => ({seq,at:at(t),kind})
test('questions, receipts and return visits at one timestamp each retain a sequence position', () => {
  const track=buildTrack({created_at:at(0),terminal_at:at(5),timeline:[
    event(1,1,'review_ready'),event(2,1,'answer_received'),event(3,1,'review_applied'),
    event(4,1,'execution_stage_changed'),event(5,5,'task_state_changed')]})
  let p={seq:0,elapsed:0}
  const seen=[]
  for(let i=0;i<5;i++){p=nextPlayback(track,p,100);seen.push(p.seq)}
  assert.deepEqual(seen,[1,2,3,4,5])
})
test('a locked gate survives high speed and idle compression until explicitly released', () => {
  const gate={key:'r:1:3',available:true,question_seq:3,answer_seq:5}
  const track=buildTrack({created_at:at(0),terminal_at:at(430),review_gates:[gate],timeline:[
    event(3,10,'review_ready'),{...event(4,11,'task_state_changed'),lifecycle:'waiting_review'},
    event(5,425,'answer_received'),event(6,430,'review_applied')]})
  const pending={elapsed:10,seq:3}
  assert.deepEqual(nextPlayback(track,pending,10000),pending)
  const submitted=nextPlayback(track,pending,10000,new Set([gate.key]))
  assert.equal(submitted.seq,4)
  assert.equal(nextPlayback(track,submitted,10000,new Set([gate.key])).seq,5)
})
test('missing historical answers keep replay readable and cannot create a gate', () => {
  const track=buildTrack({created_at:at(0),terminal_at:at(3),
    review_gates:[{key:'missing',available:false,question_seq:1,answer_seq:null}],
    timeline:[event(1,1,'review_ready'),event(2,2,'review_withdrawn'),event(3,3,'task_state_changed')]})
  assert.equal(nextPlayback(track,{elapsed:1,seq:1},30).seq,2)
})
test('each stage is rendered once while quality and comparison returns stay in sequence', () => {
  const stages=[{id:'quality_check',seen:true,status:'completed',intervals:[{seq:8,start:at(8)},{seq:30,start:at(30)}]},
    {id:'comparison',seen:true,status:'completed',intervals:[{seq:20,start:at(20)},{seq:35,start:at(35)}]},
    {id:'done',seen:true,status:'completed',intervals:[]}]
  const p={at:at(40),terminal_seq:40,reviews:[{review_id:'r',seq:22,created_at:at(22)}],milestones:[
    {stage_id:'quality_check',seq:8,at:at(8)},{stage_id:'comparison',seq:20,at:at(20)},
    {stage_id:'quality_check',seq:30,at:at(30)},{stage_id:'comparison',seq:35,at:at(35)}]}
  const result=conversationTimeline([],stages,p)
  assert.equal(result.filter(x=>x.kind==='stage'&&x.id==='quality_check').length,1)
  assert.deepEqual(result.map(x=>x.seq),[8,20,22,30,35,40])
  assert.equal(result.filter(x=>x.kind==='visit').length,2)
})
