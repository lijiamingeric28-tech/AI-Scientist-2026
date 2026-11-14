import React from 'react'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {MaterialPage} from '../src/components/results/MaterialWorkbench'
import '../src/styles.css'
import '../src/frontend-v1.css'
import '../src/research-results.css'

// Real mounted effects and transport. Only this test document replaces HTTP,
// visibility notifications, intersection delivery and the five-second clock.
const fixture=document.querySelector('#fixture'),status=document.querySelector('#status')
const calls=[],checks=[],timers=new Map(),observers=new Set()
const nativeFetch=window.fetch,nativeInterval=window.setInterval,nativeClear=window.clearInterval
let generated=false,submitted=false,timer=-1,ask,opened,visible='visible'
Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>visible})
window.IntersectionObserver=class {constructor(fn){this.fn=fn;observers.add(this)}observe(el){this.el=el}disconnect(){observers.delete(this)}}
const intersect=id=>{for(const ob of [...observers])if(ob.el?.id===id)ob.fn([{isIntersecting:true}])}
window.setInterval=(fn,ms,...args)=>{if(ms!==5000)return nativeInterval(fn,ms,...args);const id=timer--;timers.set(id,()=>fn(...args));return id}
window.clearInterval=id=>timers.delete(id)||nativeClear(id)
const root=createRoot(fixture),memory={}
const scope={taskId:'reading-mounted',deliveryId:'d',revision:2}
const source={material_id:'paper',source_id:'paper',kind:'paper',title:'Saved paper',authors:['A','B','C','D'],year:2015,work:{records:[]},citations:[]}
const section={text:'仅依据本资料的原报测量。',measurement_ids:['m1'],evidence_ids:['e1'],claim_ids:[]}
const report={schema_version:'MaterialAnalysis/1',status:'complete',generated_at:'2026-11-13T00:00:00Z',sections:{found:[section]},recommendations:{},knowledge_blocks:[]}
const reference={id:'report',version:1,content_sha256:'accurate-hash',generated_at:report.generated_at,status:'complete'}
window.fetch=async(input,options={})=>{
 const url=new URL(input,location.href);if(!url.pathname.startsWith('/api/'))return nativeFetch(input,options)
 calls.push({url,method:options.method||'GET',body:options.body,signal:options.signal})
 const key=url.pathname.split('/').at(-1),p=url.searchParams.get('property_id')||'p'
 let result
 if(key==='materials'&&url.searchParams.get('projection')==='summary')result={summary:{state:'ready',text:'原始提取总结不被覆盖。',basis:{knowledge:[{title:'Cache-safe saved theory',claim:{claim_id:'k',text:'Saved conditional background'}}]}}}
 else if(key==='materials')result={total:1,items:[{group_id:'paper',property_id:p,property_name:p==='p'?'历元星等':'消光',title:'Saved paper',kind:'paper',record_count:p==='p'?322:4,figure_count:2,body_record_count:322,material:source,related_materials:[],attachments:[],available_properties:[{property_id:'p',name:'历元星等',record_count:322},{property_id:'q',name:'消光',record_count:4}],summary:p==='p'?{state:'ready',text:'原始提取总结不被覆盖。',basis:{knowledge:[]}}:undefined,profile:{record_count:322,material_record_count:326,units:['mag'],bands:[{value:'B'}],conditions:[]}}]}
 else if(key==='material-analysis'){
  const kind=url.searchParams.get('scope')||'material'
  if(options.method==='POST'){submitted=true;result={run_id:'run',status:'queued'}}
  else result={scope:{material_id:'paper',property_id:p,kind},generation:{allowed:true},versions:generated?[reference]:[],report:generated&&p==='p'?report:null,run:submitted?{run_id:'run',status:generated?'complete':'queued'}:null}
 }else if(key==='run')result={run_id:'run',status:generated?'complete':'running',stage:'controlled',completed_records:0,total_records:322}
 else if(key==='material_records')result={total:1,ids:['m1'],items:[]}
 else throw Error(`Unexpected request ${url}`)
 return new Response(JSON.stringify({delivery_id:'d',delivery_revision:2,...result}),{headers:{'Content-Type':'application/json'}})
}
const mount=(active=true)=>flushSync(()=>root.render(<MaterialPage scope={scope} entry={{id:'paper',property:'p'}} memory={memory} active={active} onBack={()=>{}} onOpenDetail={value=>{opened=value}} onAsk={value=>{ask=value}}/>))
const pause=()=>new Promise(resolve=>setTimeout(resolve,100))
const assert=(ok,message)=>{if(!ok)throw Error(message);checks.push(message)}
const click=text=>{const b=[...fixture.querySelectorAll('button')].find(el=>el.textContent===text);if(!b)throw Error(`Missing button ${text}`);flushSync(()=>b.click())}
try{
 mount(false);await pause();assert(!calls.length,'hidden MaterialPage issues zero requests')
 mount();await pause();assert(calls.length===1&&calls[0].url.pathname.endsWith('/materials'),'identity opens with exactly one material detail read')
 assert(!calls.some(c=>c.method==='POST'),'opening never invokes model generation')
 assert(fixture.textContent.includes('322 条当前性质测量')&&!fixture.textContent.includes('960'),'header uses current material counts')
 intersect('reading-reading');await pause();assert(calls.filter(c=>c.url.pathname.endsWith('/material-analysis')).length===1,'only visible local analysis loads; hidden comparison and data stay lazy')
 click('生成本资料解读');await pause();const post=calls.find(c=>c.method==='POST')
 assert(JSON.parse(post.body).expected_delivery_revision===2&&JSON.parse(post.body).scope==='material','explicit submit pins exact delivery and local scope')
 generated=true;for(const tick of [...timers.values()])await tick();await pause()
 assert(fixture.textContent.includes('仅依据本资料的原报测量。'),'terminal status refreshes immutable report body')
 click('基于此解读追问');assert(ask.materialAnalysisRef.content_sha256==='accurate-hash','followup carries selected immutable supplement ref')
 click('查阅测量 1');assert(opened.answerScope.delivery_revision===2&&opened.record.record_id==='m1','record reference opens overlay with exact delivery scope')
 const before=calls.length;visible='hidden';document.dispatchEvent(new Event('visibilitychange'));await pause();assert(timers.size===0&&calls.length===before,'hidden document cancels front-end polling')
 visible='visible';document.dispatchEvent(new Event('visibilitychange'));await pause()
 click('消光4');await pause();assert(fixture.textContent.includes('4 条当前性质测量'),'property switch replaces current scope without old count leakage')
 assert(fixture.querySelector('#reading-advice').textContent.includes('Cache-safe saved theory'),'static cache re-entry shares refreshed summary knowledge with advice section')
 assert(!calls.some(c=>c.url.pathname.endsWith('/material_records')),'unopened data section never fetches records')
 intersect('reading-data');await pause();assert(calls.some(c=>c.url.pathname.endsWith('/material_records')),'data node mounted after async material read installs observer and fetches when visible')
 mount(false);await pause();status.textContent='PASS '+checks.length+'\n'+checks.join('\n')
}catch(error){status.textContent='FAIL\n'+error.stack+'\n'+checks.join('\n');console.error(error)}
finally{window.fetch=nativeFetch;window.setInterval=nativeInterval;window.clearInterval=nativeClear}
