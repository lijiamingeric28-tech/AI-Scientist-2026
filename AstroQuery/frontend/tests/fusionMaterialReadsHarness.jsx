import React from 'react'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {CandidateMaterials, MaterialPage, useWorkbenchPage} from '../src/components/results/MaterialWorkbench'
import * as api from '../src/services/api'

// Exercise real mounted components, effects, aborts and API transport. Only the
// external HTTP boundary and the five-second clock are controlled.
const fixture = document.querySelector('#fixture')
const status = document.querySelector('#status')
for (const task of ['activity','delayed']) {
  for (const section of ['main','attachment'])
    sessionStorage.removeItem(`astroquery.material.page.${task}.delivery.7.paper.temperature.${section}`)
}
const root = createRoot(fixture)
const nativeFetch = window.fetch
const nativeInterval = window.setInterval
const nativeClearInterval = window.clearInterval
const timers = new Map()
const calls = []
const checks = []
const writeAttempts = new Map(), writeReleases = new Map()
let timerId = -1
let releaseDelayed
let releaseShared, releaseStale, releaseSummary, delaySummary=false
window.setInterval = (fn, ms, ...args) => {
  if (ms !== 5000) return nativeInterval(fn,ms,...args)
  const id = timerId--
  timers.set(id,() => fn(...args))
  return id
}
window.clearInterval = id => timers.delete(id) || nativeClearInterval(id)
const source = {material_id:'paper',source_id:'paper',kind:'paper',title:'Lifecycle paper',work:{records:[]},citations:[]}
const item = {group_id:'paper',property_id:'temperature',property_name:'温度',title:'Lifecycle paper',kind:'paper',record_count:82,body_record_count:41,figure_count:13,output:'both',material:source,related_materials:[{material_id:'attachment',kind:'official_attachment',title:'Attachment'}],attachments:[{material_id:'attachment',table_id:'Table A',record_count:41}],summary:{state:'pending'}}
window.fetch = async (input,options={}) => {
  const url = new URL(input,location.href)
  if (!url.pathname.startsWith('/api/')) return nativeFetch(input,options)
  const call = {url,signal:options.signal,at:performance.now()}
  calls.push(call)
  const resource = url.pathname.split('/').at(-1)
  const offset = Number(url.searchParams.get('offset') || 0)
  let body
  const task=url.pathname.split('/')[3],q=Object.fromEntries(url.searchParams),revision=Number(q.delivery_revision||7)
  if (options.method === 'POST' && resource === 'material-summary' && task.startsWith('write-'))
    return new Response(JSON.stringify({state:'pending'}),{headers:{'Content-Type':'application/json'}})
  if (resource === 'materials') {
    if(q.projection==='summary') body={summary:q.at_seq?{state:'ready',text:'Captured summary 37'}:{state:'pending'}}
    else if(q.candidates_only) body={total:41,properties:[{property_id:'temperature',name:'温度'}],selected_property_id:'temperature',items:[{...item,title:q.search||'Candidate initial'}]}
    else body={total:1,items:[{...item,title:`Lifecycle paper revision ${revision}`,summary:q.at_seq?{state:'ready',text:'Captured summary 37'}:{state:'pending'}}]}
    if(task==='bytes')body={total:1,items:[{text:'温'.repeat(q.huge?3_000_000:1_000_000)}]}
    if(task==='shared'||task==='stale')body={total:1,items:[{title:q.search||task}]}
    if(task.startsWith('write-')) {
      const attempt=(writeAttempts.get(task)||0)+1
      writeAttempts.set(task,attempt)
      const held=task==='write-race'||task==='write-hide-retry'?attempt<=2:attempt===1
      body={total:1,items:[{title:held?'stale before write':'fresh after write'}]}
      if(held)await new Promise(resolve=>writeReleases.set(`${task}:${attempt}`,resolve))
    }
  }
  else if (resource === 'material_records') {
    const section = url.searchParams.get('record_section')
    body = {total:41,ids:[`${section}-${offset}`],items:[{legacy_version:1,record_id:`${section}-${offset}`,entity_name:'Target',field_name:'温度',field_value:'12.30',field_unit:'K',source_id:'paper'}]}
  } else if (resource === 'material_figures') body = {total:13,ids:[`figure-${offset}`],items:[{figure_id:`figure-${offset}`,label:`Figure ${offset}`,page:1,caption:'Lifecycle figure',image_url:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E'}]}
  else throw new Error(`Unexpected read: ${url}`)
  if (url.pathname.includes('/delayed/')) await new Promise(resolve => {releaseDelayed = resolve})
  if(task==='shared')await new Promise(resolve=>{releaseShared=resolve})
  if(task==='stale'&&q.search==='old')await new Promise(resolve=>{releaseStale=resolve})
  if(delaySummary&&q.projection==='summary')await new Promise(resolve=>{releaseSummary=resolve})
  return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:revision,snapshot_ref:{id:`snap-${revision}`},...body}),{headers:{'Content-Type':'application/json'}})
}
const scope = {taskId:'activity',deliveryId:'delivery',revision:7}
const mount = value => flushSync(()=>root.render(value))
const render = (active,taskId='activity',extra={},readOnly=false) => mount(<MaterialPage key={taskId} scope={{...scope,taskId,...extra}} entry={{id:'paper',property:'temperature'}} active={active} readOnly={readOnly} onBack={()=>{}} onOpenDetail={()=>{}} />)
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
const settle = () => pause(60)
const assert = (condition,message) => {if(!condition) throw new Error(message);checks.push(message)}
const nextPage = label => {
  const nav = fixture.querySelector(`nav[aria-label="${label}"]`)
  if(!nav) throw new Error(`Missing pagination ${label}`)
  flushSync(() => nav.querySelectorAll('button')[1].click())
}
function Probe({active=true,search='',task='shared',label='probe'}) {
  const value=useWorkbenchPage({...scope,taskId:task},'materials',{search},active)
  return <output aria-label={label}>{value.error||value.value?.items[0]?.title||'waiting'}</output>
}
const type=value=>{
  const input=fixture.querySelector('input[type="search"]')
  flushSync(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}))})
}
async function checkWriteRace() {
  mount(<><Probe task="write-race" label="write-first"/><Probe task="write-race" label="write-second"/></>)
  await settle()
  assert(writeAttempts.get('write-race')===1,'write race begins with one shared mounted read')
  await api.generateMaterialSummary('write-race','delivery',{delivery_revision:7,material_id:'paper',property_id:'temperature'})
  await settle()
  assert(writeAttempts.get('write-race')===2&&[...fixture.querySelectorAll('output')].every(el=>el.textContent==='waiting'),'successful summary write restarts the active shared read without a cancellation error')
  await api.generateMaterialSummary('write-race','delivery',{delivery_revision:7,material_id:'paper',property_id:'temperature'})
  await settle()
  assert(writeAttempts.get('write-race')===3&&[...fixture.querySelectorAll('output')].every(el=>el.textContent==='fresh after write'),'consecutive writes share one replacement read per epoch and recover current content')
  writeReleases.get('write-race:1')();writeReleases.get('write-race:2')();await settle()
  assert([...fixture.querySelectorAll('output')].every(el=>el.textContent==='fresh after write'),'invalidated late response cannot overwrite the replacement read')
  mount(<Probe task="write-hidden"/>);await settle()
  const write=api.generateMaterialSummary('write-hidden','delivery',{delivery_revision:7,material_id:'paper',property_id:'temperature'})
  mount(<Probe task="write-hidden" active={false}/>)
  await write;await settle()
  assert(writeAttempts.get('write-hidden')===1,'a hidden consumer does not restart when a write invalidates its old read')
  writeReleases.get('write-hidden:1')();await settle()
  assert(fixture.textContent==='waiting','late hidden response remains invisible after write invalidation')
  mount(<Probe task="write-hide-retry"/>);await settle()
  await api.generateMaterialSummary('write-hide-retry','delivery',{delivery_revision:7,material_id:'paper',property_id:'temperature'})
  await settle()
  assert(writeAttempts.get('write-hide-retry')===2,'an active consumer begins its replacement read after invalidation')
  mount(<Probe task="write-hide-retry" active={false}/>)
  await api.generateMaterialSummary('write-hide-retry','delivery',{delivery_revision:7,material_id:'paper',property_id:'temperature'})
  await settle()
  assert(writeAttempts.get('write-hide-retry')===2,'hiding the replacement consumer stops retries on later writes')
  writeReleases.get('write-hide-retry:1')();writeReleases.get('write-hide-retry:2')();await settle()
  assert(fixture.textContent==='waiting','abandoned replacement responses cannot update a hidden consumer')
  mount(null)
}
function finish() {
  status.textContent = `PASS ${checks.length}\n${checks.join('\n')}`
  window.__fusionMaterialReads = {status:'pass',checks,calls:calls.map(({url})=>url.pathname+url.search)}
}
async function run() {
  if(location.search.includes('write-race')) { await checkWriteRace(); finish(); return }
  if(location.search.includes('search-red')) {
    const memory={page:2,search:'',property:'temperature',output:'all',kind:'all'}
    mount(<CandidateMaterials scope={{...scope,taskId:'search-red'}} memory={memory} onOpen={()=>{}}/>);await settle()
    const start=calls.length
    type('a');await pause(80);type('al');await pause(80);type('alpha');await pause(180)
    assert(calls.length===start,'rapid input emits no HTTP requests before 250ms debounce')
    return
  }
  render(false)
  await settle()
  assert(calls.length===0,'initially hidden material starts zero requests')
  render(true)
  await settle()
  assert(calls.length===4,'activation reads detail, body, attachment and figures once')
  assert(timers.size===1,'pending summary installs one polling timer')
  nextPage('正文测量分页')
  nextPage('Table A分页')
  nextPage('资料图像分页')
  await settle()
  assert(calls.length===7,'paging reads one additional bounded page per child')
  assert(fixture.textContent.includes('12.30'),'formatted scientific values preserve trailing precision')
  const content = fixture.textContent
  const beforePoll = calls.length
  for(const tick of [...timers.values()]) tick()
  await settle()
  assert(calls.length===beforePoll+1&&calls.at(-1).url.searchParams.get('projection')==='summary','pending polling refreshes only the lightweight summary projection')
  render(false)
  await settle()
  const hiddenCount = calls.length
  assert(timers.size===0,'hiding cancels pending-summary polling')
  assert(fixture.textContent===content,'hidden view retains cached content and page state')
  for(const tick of [...timers.values()]) tick()
  await settle()
  assert(calls.length===hiddenCount,'hidden view performs no further reads')
  render(true)
  await settle()
  const resumed = calls.slice(hiddenCount)
  assert(resumed.length===1&&resumed[0].url.searchParams.get('projection')==='summary','resuming reuses static pages and only confirms summary')
  assert(fixture.querySelector('[aria-label="正文测量分页"]').textContent.includes('第 2 /'),'resuming preserves record pagination')
  assert(fixture.querySelector('[aria-label="资料图像分页"]').textContent.includes('第 2 /'),'resuming preserves figure pagination')
  delaySummary=true
  for(const tick of [...timers.values()])tick()
  await settle()
  const pendingSummary=calls.at(-1)
  render(false);await settle()
  assert(pendingSummary.signal.aborted,'hiding aborts in-flight lightweight summary confirmation')
  releaseSummary();delaySummary=false;await settle()
  const historyStart=calls.length,history={atSeq:37,sealedOnly:true}
  render(true,'history',history,true);await settle()
  assert(calls.length===historyStart+4&&calls.slice(historyStart).every(({url})=>url.searchParams.get('at_seq')==='37'&&url.searchParams.get('sealed_only')==='true'),'every nested historical read retains sequence and sealed scope')
  assert(timers.size===0&&fixture.textContent.includes('Captured summary 37'),'historical summary cannot inherit current summary or poll')
  render(false,'history',history,true);await settle()
  const historyResume=calls.length
  render(true,'history',history,true);await settle()
  assert(calls.length===historyResume,'historical resume reuses static pages without a summary request')
  render(true,'revision',{revision:8});await settle()
  assert(fixture.textContent.includes('revision 8')&&!fixture.textContent.includes('Captured summary 37'),'same material IDs remain isolated by revision and cutoff')
  render(true,'delayed')
  await settle()
  const delayed = calls.at(-1)
  render(false,'delayed')
  await settle()
  assert(delayed.signal.aborted,'hiding aborts an in-flight detail request')
  const beforeRelease = calls.length
  releaseDelayed()
  await settle()
  assert(calls.length===beforeRelease,'late hidden detail cannot trigger nested child reads')
  const sharedStart=calls.length
  mount(<><Probe label="first"/><Probe label="second"/></>);await settle()
  assert(calls.length===sharedStart+1,'independent mounted consumers share one HTTP request')
  const sharedCall=calls.at(-1)
  mount(<><Probe label="first" active={false}/><Probe label="second"/></>);await settle()
  assert(!sharedCall.signal.aborted,'hiding one consumer cannot cancel the other consumer')
  releaseShared();await settle()
  assert(fixture.querySelector('[aria-label="second"]').textContent==='shared','remaining mounted consumer receives its result')
  mount(<Probe task="stale" search="old"/>);await settle()
  mount(<Probe task="stale" search="new"/>);await settle()
  releaseStale();await settle()
  assert(fixture.textContent==='new','late old response cannot overwrite the current query')
  const memory={page:2,search:'',property:'temperature',output:'all',kind:'all'},candidateScope={...scope,taskId:'search'}
  mount(<CandidateMaterials scope={candidateScope} memory={memory} onOpen={()=>{}}/>);await settle()
  const searchStart=calls.length
  type('a');await pause(80);type('al');await pause(80)
  const lastKey=performance.now();type('alpha');await pause(180)
  assert(calls.length===searchStart,'rapid input emits no HTTP requests before debounce')
  await pause(110)
  const searches=calls.slice(searchStart)
  assert(searches.length===1&&searches[0].url.searchParams.get('search')==='alpha'&&searches[0].url.searchParams.get('offset')==='0'&&searches[0].at-lastKey>=240,'search waits 250ms after the last keystroke and resets pagination')
  mount(<CandidateMaterials scope={candidateScope} memory={memory} active={false} onOpen={()=>{}}/>);await settle()
  const searchHidden=calls.length;await pause(280)
  assert(calls.length===searchHidden,'hidden candidates make zero requests')
  mount(<CandidateMaterials scope={candidateScope} memory={memory} onOpen={()=>{}}/>);await settle()
  assert(calls.length===searchHidden&&fixture.querySelector('input').value==='alpha','candidate resume reuses its search page and input')
  mount(null)
  const budgetStart=calls.length
  for(let offset=0;offset<33;offset++)await api.getWorkbenchPage('budget','delivery',7,'materials',{offset})
  await api.getWorkbenchPage('budget','delivery',7,'materials',{offset:1})
  assert(calls.length===budgetStart+33,'32-page cache retains recent material pages')
  await api.getWorkbenchPage('budget','delivery',7,'materials',{offset:0})
  assert(calls.length===budgetStart+34,'the 33rd material page evicts the oldest page')
  const byteStart=calls.length
  for(let offset=0;offset<3;offset++)await api.getWorkbenchPage('bytes','delivery',7,'materials',{offset})
  await api.getWorkbenchPage('bytes','delivery',7,'materials',{offset:1})
  await api.getWorkbenchPage('bytes','delivery',7,'materials',{offset:0})
  assert(calls.length===byteStart+4,'8 MiB UTF-8 budget evicts older material bodies')
  await api.getWorkbenchPage('bytes','delivery',7,'materials',{huge:true})
  await api.getWorkbenchPage('bytes','delivery',7,'materials',{huge:true})
  assert(calls.length===byteStart+6,'oversized material bodies are never retained')
  await checkWriteRace()
  finish()
}
run().catch(error=>{
  status.textContent=`FAIL: ${error.message}\n${checks.join('\n')}`
  window.__fusionMaterialReads={status:'fail',error:error.message,checks}
}).finally(()=>{
  root.unmount()
  window.fetch=nativeFetch
  window.setInterval=nativeInterval
  window.clearInterval=nativeClearInterval
})
