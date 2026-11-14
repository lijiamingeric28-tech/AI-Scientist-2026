import test from 'node:test'
import assert from 'node:assert/strict'

test('execution reads reuse exact cursor sections and isolate returned values',async()=>{
  const {createExecutionReads}=await import('../src/services/executionReads.js')
  let calls=0
  const cache=createExecutionReads(async()=>{calls++;return {items:[{job_id:'j'}]}})
  const first=await cache.read('t',{at_seq:8,section:'jobs'})
  first.items.length=0
  assert.equal((await cache.read('t',{section:'jobs',at_seq:8})).items.length,1)
  assert.equal(calls,1)
  await cache.read('t',{at_seq:7,section:'jobs'})
  await cache.read('other',{at_seq:8,section:'jobs'})
  await cache.read('t',{at_seq:8,section:'jobs'},{readVersion:1})
  assert.equal(calls,4)
})

test('concurrent sections coalesce per key and one cancelled subscriber does not abort another',async()=>{
  const {createExecutionReads}=await import('../src/services/executionReads.js')
  let done,calls=0,signal
  const cache=createExecutionReads(async(t,q,o)=>{calls++;signal=o.signal;return new Promise(r=>done=r)})
  const controller=new AbortController()
  const first=cache.read('t',{at_seq:4},{signal:controller.signal})
  const second=cache.read('t',{at_seq:4})
  await Promise.resolve();controller.abort()
  await assert.rejects(first,{name:'AbortError'})
  assert.equal(signal.aborted,false);done({items:[]})
  await second;assert.equal(calls,1)
})

test('execution cache evicts pages, retries failures and does not freeze unpinned live reads',async()=>{
  const {createExecutionReads}=await import('../src/services/executionReads.js')
  let calls=0
  const cache=createExecutionReads(async()=>{calls++;if(calls===1)throw new Error('offline');return {items:[]}}, {maxEntries:1})
  await assert.rejects(cache.read('t',{at_seq:1}),/offline/)
  await cache.read('t',{at_seq:1});await cache.read('t',{at_seq:2});await cache.read('t',{at_seq:1})
  await cache.read('t',{});await cache.read('t',{})
  assert.equal(calls,6)
})

test('quality tabs request only their own dependencies',async()=>{
  const {qualityResources}=await import('../src/lib/qualityReads.js')
  assert.deepEqual(qualityResources('overview'),['quality','sourceList'])
  assert.deepEqual(qualityResources('trace'),['quality','sourceList'])
  // Coverage includes saved human-review decisions as well as the matrix.
  assert.deepEqual(qualityResources('comparison'),['quality','sourceList','analysisRecords','differences','matrix','reviewActivity'])
  assert.deepEqual(qualityResources('details'),[])
})
