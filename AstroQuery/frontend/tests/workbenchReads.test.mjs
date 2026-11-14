import test from 'node:test'
import assert from 'node:assert/strict'

async function cache(loader, options) {
  const mod = await import('../src/services/workbenchReads.js').catch(() => ({}))
  assert.equal(typeof mod.createWorkbenchReads, 'function', 'bounded material reader is missing')
  return mod.createWorkbenchReads(loader, options)
}
const scope = { taskId:'task', deliveryId:'delivery', revision:7 }
const page = (n = 1) => ({delivery_id:'delivery',delivery_revision:7,total:1,items:[{id:n,nested:{text:'原生科学值 12.30'}}]})

test('material pages reuse exact normalized scope and give each consumer an isolated body', async () => {
  let calls = 0
  const reads = await cache(async () => { calls++; return page() })
  const first = await reads.read(scope, 'materials', {offset:0,limit:20})
  first.items[0].nested.text = 'consumer mutation'
  const second = await reads.read(scope, 'materials', {limit:20,offset:0})
  assert.equal(calls, 1)
  assert.equal(second.items[0].nested.text, '原生科学值 12.30')
  for (const changed of [{taskId:'other'}, {deliveryId:'other'}, {revision:8}, {protocol:'next'}])
    await reads.read({...scope,...changed}, 'materials', {limit:20,offset:0})
  for (const changed of [{at_seq:0}, {at_seq:37}, {sealed_only:true}, {offset:20}, {search:'alpha'}])
    await reads.read(scope, 'materials', {limit:20,offset:0,...changed})
  assert.equal(calls, 10, 'task/delivery/revision/protocol/query/history are isolated')
})

test('the default LRU retains only 32 material pages', async () => {
  let calls = 0
  const reads = await cache(async () => page(++calls))
  for (let offset = 0; offset < 33; offset++) await reads.read(scope,'materials',{offset})
  await reads.read(scope,'materials',{offset:1})
  assert.equal(calls,33,'second oldest page survives')
  await reads.read(scope,'materials',{offset:0})
  assert.equal(calls,34,'oldest page was evicted')
})

test('the default byte budget evicts UTF-8 bodies beyond 8 MiB and skips oversized pages', async () => {
  let calls = 0
  const reads = await cache(async (_scope,_name,query) => { calls++; return {items:[{text:'温'.repeat(query.huge ? 3_000_000 : 1_000_000)}]} })
  for (let offset = 0; offset < 3; offset++) await reads.read(scope,'materials',{offset})
  await reads.read(scope,'materials',{offset:1})
  assert.equal(calls,3,'recent pages remain within byte budget')
  await reads.read(scope,'materials',{offset:0})
  assert.equal(calls,4,'UTF-8 byte budget evicts the oldest body')
  await reads.read(scope,'materials',{huge:true})
  await reads.read(scope,'materials',{huge:true})
  assert.equal(calls,6,'a page larger than the entire budget is not retained')
})

test('shared material loads cancel per consumer and abandon a load only when all leave', async () => {
  let finish, signal, calls = 0
  const reads = await cache((_scope,_name,_query,options) => { calls++; signal=options.signal; return new Promise(resolve => {finish=()=>resolve(page())}) })
  const a = new AbortController(), b = new AbortController()
  const first=reads.read(scope,'materials',{}, {signal:a.signal}),second=reads.read(scope,'materials',{}, {signal:b.signal})
  const cancelled=assert.rejects(first,{name:'AbortError'})
  await Promise.resolve(); a.abort(); await cancelled
  assert.equal(signal.aborted,false)
  finish(); assert.equal((await second).items[0].id,1); assert.equal(calls,1)
  const c=new AbortController(), last=reads.read(scope,'materials',{offset:20},{signal:c.signal})
  const abandoned=assert.rejects(last,{name:'AbortError'})
  await Promise.resolve(); c.abort(); await abandoned
  assert.equal(signal.aborted,true)
  finish(); await Promise.resolve()
})

test('an already hidden material consumer never dispatches or fills a cache entry', async () => {
  let calls=0
  const reads=await cache(async()=>{calls++;return page()})
  const controller=new AbortController(),pending=reads.read(scope,'materials',{}, {signal:controller.signal})
  controller.abort()
  await assert.rejects(pending,{name:'AbortError'})
  assert.equal(calls,0)
  await reads.read(scope,'materials',{})
  assert.equal(calls,1)
})

test('failures and invalidated in-flight responses cannot populate the material cache', async () => {
  let calls=0, finish
  const reads = await cache(async () => { calls++; if(calls===1) throw new Error('retry'); if(calls===2) return new Promise(resolve=>{finish=()=>resolve(page(2))}); return page(calls) })
  await assert.rejects(reads.read(scope,'materials',{}),/retry/)
  const stale=reads.read(scope,'materials',{})
  await Promise.resolve(); reads.invalidate(); finish(); await assert.rejects(stale,{name:'AbortError'})
  assert.equal((await reads.read(scope,'materials',{})).items[0].id,3)
  assert.equal((await reads.read(scope,'materials',{})).items[0].id,3)
  assert.equal(calls,3)
})

test('live summary bodies are never retained as static data, while cutoff summaries stay isolated', async () => {
  let calls=0
  const reads=await cache(async()=>{calls++;return {...page(),items:[{group_id:'paper',summary:{state:'pending'}}]}})
  assert.equal((await reads.read(scope,'materials',{material_id:'paper'})).items[0].summary.state,'pending')
  assert.equal((await reads.read(scope,'materials',{material_id:'paper'})).items[0].summary,undefined)
  await reads.read(scope,'materials',{material_id:'paper',projection:'summary'})
  await reads.read(scope,'materials',{material_id:'paper',projection:'summary'})
  assert.equal(calls,3,'light summary always confirms through HTTP')
  await reads.read(scope,'materials',{material_id:'paper',at_seq:37,sealed_only:true})
  assert.equal((await reads.read(scope,'materials',{material_id:'paper',at_seq:37,sealed_only:true})).items[0].summary.state,'pending')
  assert.equal(calls,4)
})

test('cache invalidation is identified by increasing epochs while caller cancellation stays ordinary',async()=>{
  const releases=[]
  const reads=await cache(async()=>new Promise(resolve=>releases.push(()=>resolve(page()))))
  const controller=new AbortController(),first=reads.read(scope,'materials',{}, {signal:controller.signal}).catch(error=>error)
  await Promise.resolve();reads.invalidate()
  const firstError=await first
  assert.equal(firstError.invalidationEpoch,1,'internal invalidation must be distinguishable from hide/transport abort')
  assert.equal(controller.signal.aborted,false)
  const second=reads.read(scope,'materials',{}, {signal:controller.signal}).catch(error=>error)
  await Promise.resolve();reads.invalidate()
  assert.equal((await second).invalidationEpoch,2)
  const hidden=reads.read(scope,'materials',{}, {signal:controller.signal}).catch(error=>error)
  controller.abort()
  const hiddenError=await hidden
  assert.equal(hiddenError.name,'AbortError')
  assert.equal(hiddenError.invalidationEpoch,undefined)
  for(const release of releases)release()
})

test('current reads restart once per newer invalidation epoch and never mask other failures',async()=>{
  const mod=await import('../src/services/workbenchReads.js')
  assert.equal(typeof mod.readCurrentWorkbench,'function','active material read restart policy is missing')
  let calls=0
  const invalidated=epoch=>Object.assign(new DOMException('Invalidated','AbortError'),{invalidationEpoch:epoch})
  const result=await mod.readCurrentWorkbench(async()=>{
    calls++;if(calls<3)throw invalidated(calls)
    return {title:'latest'}
  },new AbortController().signal)
  assert.deepEqual(result,{title:'latest'});assert.equal(calls,3)
  for(const failure of [new Error('real HTTP failure'),new DOMException('transport abort','AbortError'),invalidated(1)]) {
    let attempts=0
    await assert.rejects(mod.readCurrentWorkbench(async()=>{attempts++;throw failure}),error=>error===failure)
    assert.equal(attempts,failure.invalidationEpoch==null?1:2,'the same epoch cannot create a retry loop')
  }
  const hidden=new AbortController();let hiddenCalls=0
  await assert.rejects(mod.readCurrentWorkbench(async()=>{hiddenCalls++;hidden.abort();throw invalidated(5)},hidden.signal),{name:'AbortError'})
  assert.equal(hiddenCalls,1,'hide stops the invalidation retry before another read')
})
