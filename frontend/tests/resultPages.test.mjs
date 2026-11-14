import test from 'node:test'
import assert from 'node:assert/strict'
const module = await import('../src/services/resultPages.js').catch(() => ({}))

test('records read exactly one bounded page, preserving global totals, collapsed counts and filters', async () => {
  assert.equal(typeof module.createResultPages, 'function')
  const calls=[]
  const api=module.createResultPages(async(path,options)=>{calls.push({path,options});return {delivery_id:'d',delivery_revision:7,items:[{record_id:'m'}],total:6001,display_total:5900,aggregates:{total:7000}}})
  const controller=new AbortController()
  const page=await api.readResourcePage('t','d','records',7,{offset:50,limit:50,q:'mass α',quick:'modified',fields:[],year_sort:'desc',collapse_duplicates:true},{signal:controller.signal})
  assert.equal(calls.length,1)
  const query=new URL(calls[0].path,'http://local').searchParams
  assert.equal(query.get('offset'),'50'); assert.equal(query.get('fields'),'[]'); assert.equal(query.get('q'),'mass α')
  assert.equal(query.get('expected_delivery_revision'),'7');assert.equal(query.get('collapse_duplicates'),'true')
  assert.equal(page.total,6001);assert.equal(page.display_total,5900);assert.equal(page.aggregates.total,7000)
  assert.equal(calls[0].options.signal,controller.signal)
})
test('page revision mismatch rejects before a row is exposed',async()=>{
  assert.equal(typeof module.createResultPages,'function')
  const api=module.createResultPages(async()=>({delivery_id:'d',delivery_revision:8,items:[]}))
  await assert.rejects(api.readResourcePage('t','d','records',7),/修订/)
})
test('preview reads one page and pins subsequent pages to the displayed revision',async()=>{
  assert.equal(typeof module.createResultPages,'function')
  const calls=[];const api=module.createResultPages(async path=>{calls.push(path);return {preview_id:'preview-v2-x',items:[],total:6001}})
  const page=await api.getPreview('t',{}, {offset:50,limit:50,expected_preview_id:'preview-v2-x'})
  assert.equal(calls.length,1);const q=new URL(calls[0],'http://local').searchParams
  assert.equal(q.get('preview_protocol'),'2');assert.equal(q.get('offset'),'50');assert.equal(q.get('expected_preview_id'),'preview-v2-x')
  assert.equal(page.offset,50);assert.equal(page.limit,50)
})
test('filtered export preserves scope and unchecked IDs across pages without pagination',()=>{
  assert.equal(typeof module.filteredSelection,'function')
  assert.deepEqual(module.filteredSelection({q:'x',quick:'modified',fields:[],offset:50,limit:50,collapse_duplicates:true},new Set(['m1','m51'])),{mode:'filtered',filter_version:1,filters:{q:'x',quick:'modified',fields:[]},excluded_measurement_ids:['m1','m51']})
})
test('preview invalidates by preview revision with legacy cursor fallback only',()=>{
  assert.equal(typeof module.previewReadKey,'function')
  assert.equal(module.previewReadKey({preview_revision:'p',core_event_cursor:1}),module.previewReadKey({preview_revision:'p',core_event_cursor:2}))
  assert.notEqual(module.previewReadKey({core_event_cursor:1}),module.previewReadKey({core_event_cursor:2}))
})
test('first-page identity reuses the initial resource only for identical scope and filters',()=>{
  assert.equal(typeof module.resultPageKey,'function')
  const scope={taskId:'t',deliveryId:'d',revision:7}
  assert.equal(module.resultPageKey(scope,{}),module.resultPageKey(scope,{q:'',quick:'target',field:'all',source_id:'all',year_sort:'none',offset:0,limit:50,collapse_duplicates:true}))
  assert.notEqual(module.resultPageKey(scope,{}),module.resultPageKey({...scope,revision:8},{}))
  assert.notEqual(module.resultPageKey(scope,{}),module.resultPageKey(scope,{offset:50}))
})

test('same revision page identity differs across replay cutoffs and sealed visibility',()=>{
 const scope={taskId:'t',deliveryId:'d',revision:7}
 assert.notEqual(module.resultPageKey(scope,{}),module.resultPageKey({...scope,atSeq:37,sealedOnly:true},{}))
 assert.notEqual(module.resultPageKey({...scope,atSeq:37},{}),module.resultPageKey({...scope,atSeq:38},{}))
})
