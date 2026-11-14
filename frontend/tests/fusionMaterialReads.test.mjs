import test from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'

test('material record adaptation leaves the shared conditional GET body server-native', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  const native = {source:{measurement_id:'native-1',value:{kind:'real',value:'12.30'},raw_value:'12.30',unit:'mag',representation:'linear',target_ref:{id:'target'},source_ref:{id:'paper'},source_kind:'paper',evidence_refs:[],native_coordinate:{band:'V',epoch:'J2000'}},property_binding:{property_id:'brightness',definition:{name_cn:'亮度'}},target:{main_id:'target'},derived:{main_state:'not_run'}}
  const body = {delivery_id:'delivery',delivery_revision:7,total:1,ids:['native-1'],items:[native]}
  const path = '/tasks/material-cache/deliveries/delivery/material_records?view=workbench&expected_delivery_revision=7&delivery_revision=7&material_id=paper&limit=20&offset=0'
  globalThis.fetch = async (url, options) => {
    calls.push({url,etag:options.headers.get('If-None-Match')})
    return options.headers.has('If-None-Match')
      ? new Response(null,{status:304})
      : new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json',ETag:'"material-native"'}})
  }
  const server = await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'error'})
  try {
    const api = await server.ssrLoadModule('/src/services/api.js')
    const adapted = await api.getWorkbenchPage('material-cache','delivery',7,'material_records',{material_id:'paper',limit:20,offset:0})
    assert.equal(adapted.items[0].field_value,'12.30')
    assert.equal(adapted.items[0].field_unit,'mag')
    const raw = await api.request(path)
    assert.equal(calls.length,2)
    assert.equal(calls[1].etag,null,'bounded workbench pages do not retain a duplicate raw ETag body')
    assert.deepEqual(raw,body,'a raw reader must receive the original server schema')
    assert.notEqual(adapted,raw)
    assert.deepEqual(adapted.items[0].source.native_coordinate,{band:'V',epoch:'J2000'})
    const adaptedAgain = await api.getWorkbenchPage('material-cache','delivery',7,'material_records',{material_id:'paper',limit:20,offset:0})
    assert.equal(adaptedAgain.items[0].field_unit,'mag')
    adaptedAgain.items[0].source.native_coordinate.band='consumer mutation'
    assert.deepEqual(await api.request(path),body)
    assert.equal(calls.at(-1).etag,'"material-native"','a raw conditional reader retains its native 304 body after adapted consumers mutate their own copy')
  } finally {
    globalThis.fetch = originalFetch
    await server.close()
  }
})

test('a successful write during an active shared read restarts current consumers and excludes the old response',async()=>{
  const originalFetch=globalThis.fetch
  let reads=0
  const releases=[],oldSignals=[]
  globalThis.fetch=async(_input,options={})=>{
    if(options.method==='POST')return new Response('{}')
    const attempt=++reads
    if(attempt<=2){oldSignals.push(options.signal);await new Promise(resolve=>{releases.push(resolve)})}
    return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:7,items:[{title:attempt<=2?'old':'current'}],total:1}))
  }
  const server=await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'error'})
  try{
    const api=await server.ssrLoadModule('/src/services/api.js')
    const a=new AbortController(),b=new AbortController(),query={material_id:'paper'}
    const first=api.getWorkbenchPage('write-race','delivery',7,'materials',query,{signal:a.signal})
    const second=api.getWorkbenchPage('write-race','delivery',7,'materials',query,{signal:b.signal})
    // Attach assertions before invalidation so a rejection is observed even in RED.
    const outcomes=Promise.allSettled([first,second])
    const dispatched=async count=>{
      for(let turn=0;releases.length<count&&turn<100;turn++)await new Promise(resolve=>setImmediate(resolve))
      assert.equal(releases.length,count,'the current active scope dispatches its expected shared read')
    }
    await dispatched(1)
    await api.generateMaterialSummary('write-race','delivery',{delivery_revision:7,material_id:'paper'})
    await dispatched(2)
    await api.generateMaterialSummary('write-race','delivery',{delivery_revision:7,material_id:'paper'})
    const result=await outcomes
    assert.ok(oldSignals.every(signal=>signal.aborted))
    assert.deepEqual(result.map(outcome=>outcome.status),['fulfilled','fulfilled'],'active subscribers restart instead of surfacing an internal cancellation')
    assert.equal(reads,3,'each consecutive invalidation shares one replacement read')
    assert.ok(result.every(outcome=>outcome.value.items[0].title==='current'))
    for(const release of releases)release()
    await new Promise(resolve=>setImmediate(resolve))
    assert.equal((await api.getWorkbenchPage('write-race','delivery',7,'materials',query)).items[0].title,'current')
    assert.equal(reads,3,'the invalidated responses cannot repopulate cache')
  }finally{for(const release of releases)release();globalThis.fetch=originalFetch;await server.close()}
})

test('material static reuse is invalidated only by successful API writes and summary reads remain light', async () => {
  const originalFetch=globalThis.fetch, calls=[]
  let mismatch=false
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(input,'http://local');calls.push(url)
    if(url.pathname.endsWith('/failed-write')) return new Response(JSON.stringify({detail:'failed'}),{status:409})
    if(options.method==='POST') return new Response('{}')
    return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:mismatch?8:7,
      ...(url.searchParams.get('projection')==='summary'?{summary:{state:'pending'}}:{items:[{group_id:'paper',summary:{state:'pending'}}],total:1})}))
  }
  const server=await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'error'})
  try {
    const api=await server.ssrLoadModule('/src/services/api.js')
    const query={material_id:'paper',property_id:'temperature'}
    await api.getWorkbenchPage('write-cache','delivery',7,'materials',query)
    await api.getWorkbenchPage('write-cache','delivery',7,'materials',query)
    assert.equal(calls.length,1,'static revisit performs zero HTTP reads')
    await assert.rejects(api.request('/failed-write',{method:'POST',body:'{}'}),/failed/)
    await api.getWorkbenchPage('write-cache','delivery',7,'materials',query)
    assert.equal(calls.length,2,'failed writes preserve a valid static page')
    await api.request('/successful-write',{method:'POST',body:'{}'})
    await api.getWorkbenchPage('write-cache','delivery',7,'materials',query)
    assert.equal(calls.length,4,'successful writes clear material pages with shared GET validators')
    for(let i=0;i<2;i++) await api.getWorkbenchPage('write-cache','delivery',7,'materials',{...query,projection:'summary',at_seq:37,sealed_only:true})
    assert.equal(calls.length,6)
    assert.ok(calls.slice(-2).every(url=>url.searchParams.get('projection')==='summary'&&url.searchParams.get('view')==='workbench'&&url.searchParams.get('at_seq')==='37'&&url.searchParams.get('sealed_only')==='true'))
    mismatch=true
    await assert.rejects(api.getWorkbenchPage('bad-version','delivery',7,'materials',query),/版本/)
    mismatch=false
    assert.equal((await api.getWorkbenchPage('bad-version','delivery',7,'materials',query)).items[0].group_id,'paper')
  } finally {globalThis.fetch=originalFetch;await server.close()}
})
