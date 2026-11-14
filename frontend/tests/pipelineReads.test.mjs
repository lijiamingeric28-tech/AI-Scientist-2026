import test from 'node:test'
import assert from 'node:assert/strict'
async function load(api,scope){const module=await import('../src/lib/pipelineReads.js').catch(()=>({}));assert.equal(typeof module.readPipelineSnapshot,'function','Pipeline combined read not implemented');return module.readPipelineSnapshot(api,scope)}
test('chat uses one combined read while preserving questions, review authority and presentation messages',async()=>{
  const calls=[],original={task_id:'T',core_event_cursor:7,revision:4,pending:{question_id:'Q',options:[1,2]},reviews:[{review_id:'R',evidence_bundle:[1]}],presentation:{cursor:7,messages:[{text:'消息'}],stages:[{id:'understand'}]}}
  const result=await load({getChatState:async(...args)=>{calls.push(args);return original},getPresentation:()=>assert.fail('must not separately read presentation')},{id:'T',conversation:true})
  assert.equal(calls.length,1);assert.deepEqual(result.pending,original.pending);assert.deepEqual(result.reviews,original.reviews)
  assert.deepEqual(result.messages,[{text:'消息'}]);assert.deepEqual(result.stages,[{id:'understand'}]);assert.equal(original.messages,undefined)
})
test('workspace reuses its embedded projection and replay uses only the exact historical cursor',async()=>{
  let extra=0;const api={getWorkspaceState:async()=>({task_id:'T',presentation:{cursor:3}}),getPresentation:async(id,seq)=>{extra++;assert.equal(seq,2);return {cursor:2}}}
  const workspace=await load(api,{id:'T',conversation:false});assert.equal(workspace.presentation.cursor,3);assert.equal(extra,0)
  const replay=await load(api,{id:'T',player:true,seq:2});assert.equal(replay.presentation.cursor,2);assert.equal(extra,1)
  const cached=await load(api,{id:'T',player:true,seq:2,frame:{cursor:2}});assert.equal(cached.presentation.cursor,2);assert.equal(extra,1)
})
test('legacy and old server responses retain the separate compatible presentation fallback',async()=>{
  let calls=0;const result=await load({getChatState:async()=>({task_id:'L',kind:'legacy',messages:[{text:'旧消息'}]}),getPresentation:async()=>{calls++;return {cursor:1,messages:[]}}},{id:'L',conversation:true})
  assert.equal(calls,1);assert.deepEqual(result.messages,[{text:'旧消息'}])
})
test('a combined projection with a mismatching cursor is rejected rather than mixed',async()=>{
  await assert.rejects(load({getChatState:async()=>({task_id:'T',core_event_cursor:7,presentation:{cursor:6}})},{id:'T',conversation:true}),/游标/)
})
