import test from 'node:test'
import assert from 'node:assert/strict'

async function client(fetcher,options){const mod=await import('../src/services/jsonReads.js').catch(()=>({}));assert.equal(typeof mod.createJsonReads,'function','Shared GET reader is not implemented');return mod.createJsonReads(fetcher,options)}
const response=(body,etag)=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json',...(etag?{ETag:etag}:{})}})
test('equivalent GET queries share one request and cancellation belongs to each subscriber',async()=>{
  let finish,signal,calls=0
  const reads=await client((url,options)=>{calls++;signal=options.signal;return new Promise(resolve=>{finish=()=>resolve(response({items:[1]}))})})
  const a=new AbortController(),b=new AbortController()
  const first=reads.request('/api/items?b=2&a=1',{signal:a.signal}),second=reads.request('/api/items?a=1&b=2',{signal:b.signal})
  const cancelled=assert.rejects(first,{name:'AbortError'})
  await Promise.resolve();a.abort();await cancelled
  assert.equal(signal.aborted,false);finish()
  assert.deepEqual(await second,{items:[1]});assert.equal(calls,1)
})
test('all consumers cancelling prevents dispatch or aborts only their underlying read',async()=>{
  let calls=0
  const reads=await client(async()=>{calls++;return response({})})
  const a=new AbortController(),p=reads.request('/early',{signal:a.signal});a.abort()
  await assert.rejects(p,{name:'AbortError'});await Promise.resolve();assert.equal(calls,0)
  const b=new AbortController();const again=reads.request('/early',{signal:b.signal})
  assert.deepEqual(await again,{});assert.equal(calls,1)
})
test('ETag revalidation returns the exact cached body on 304 and writes invalidate validators',async()=>{
  const seen=[]
  const reads=await client(async(url,options)=>{seen.push({url,headers:new Headers(options.headers),method:options.method});return options.method==='POST'?response({success:true}):seen.length===2?new Response(null,{status:304}):response({revision:seen.length},'"v1"')})
  assert.deepEqual(await reads.request('/catalog'),{revision:1})
  assert.deepEqual(await reads.request('/catalog'),{revision:1})
  assert.equal(seen[1].headers.get('If-None-Match'),'"v1"')
  await reads.request('/save',{method:'POST',body:'{}'})
  await reads.request('/catalog');assert.equal(seen[3].headers.has('If-None-Match'),false)
})
test('304 without a local body retries once and never invents a successful empty response',async()=>{
  let calls=0;const reads=await client(async()=>++calls===1?new Response(null,{status:304}):response({revision:2}))
  assert.deepEqual(await reads.request('/missing'),{revision:2});assert.equal(calls,2)
  const broken=await client(async()=>new Response(null,{status:304}))
  await assert.rejects(broken.request('/broken'),/304/)
})
test('failed reads can retry and retain structured backend error details',async()=>{
  let calls=0;const reads=await client(async()=>++calls===1?new Response(JSON.stringify({detail:{code:'BAD_VERSION',message:'版本冲突'}}),{status:409}):response({revision:3}))
  await assert.rejects(reads.request('/retry'),error=>error.status===409&&error.code==='BAD_VERSION'&&error.message==='版本冲突')
  assert.deepEqual(await reads.request('/retry'),{revision:3})
})
test('POST requests are never deduplicated and exact scope/headers partition reads',async()=>{
  let calls=0;const reads=await client(async()=>{calls++;return response({success:true})})
  await Promise.all([reads.request('/write',{method:'POST',body:'{}'}),reads.request('/write',{method:'POST',body:'{}'})]);assert.equal(calls,2)
  await Promise.all([reads.request('/r?release_id=A'),reads.request('/r?release_id=B')]);assert.equal(calls,4)
})

test('material reads can opt out of retained ETag bodies without changing ordinary conditional reads',async()=>{
  const seen=[]
  const reads=await client(async(url,options)=>{
    seen.push({headers:new Headers(options.headers),options})
    return options.headers.has('If-None-Match')?new Response(null,{status:304}):response({value:'native 12.30'},'"material"')
  })
  await reads.request('/material',{retainBody:false})
  await reads.request('/material',{retainBody:false})
  assert.ok(seen.every(call=>!call.headers.has('If-None-Match')),'opted-out pages retain no conditional body')
  assert.ok(seen.every(call=>!Object.hasOwn(call.options,'retainBody')),'internal retention policy must not leak into fetch')
  await reads.request('/material')
  assert.deepEqual(await reads.request('/material'),{value:'native 12.30'})
  assert.equal(seen[3].headers.get('If-None-Match'),'"material"','ordinary raw readers keep their existing conditional contract')
  await reads.request('/material',{retainBody:false})
  assert.equal(seen[4].headers.has('If-None-Match'),false,'a retained raw reader cannot populate the opted-out namespace')
})

test('unretained material reads still share transport and cancellation remains independent',async()=>{
  let finish,signal,calls=0
  const reads=await client((_url,options)=>{calls++;signal=options.signal;return new Promise(resolve=>{finish=()=>resolve(response({items:[1]},'"body"'))})})
  const a=new AbortController(),b=new AbortController()
  const first=reads.request('/material',{retainBody:false,signal:a.signal}),second=reads.request('/material',{retainBody:false,signal:b.signal})
  const cancelled=assert.rejects(first,{name:'AbortError'})
  await Promise.resolve();a.abort();await cancelled
  assert.equal(signal.aborted,false)
  finish();assert.deepEqual(await second,{items:[1]});assert.equal(calls,1)
})
