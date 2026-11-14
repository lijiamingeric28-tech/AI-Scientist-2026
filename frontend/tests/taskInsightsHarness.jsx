import React,{useState} from 'react'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import TaskInsights from '../src/components/results/TaskInsights'
import TaskKnowledgeBasis from '../src/components/results/TaskKnowledgeBasis'
import {Summary} from '../src/components/results/MaterialWorkbench'
import ContextDrawer from '../src/components/layout/ContextDrawer'
import {ToastProvider} from '../src/components/ui/toast'
import '../src/styles.css'
import '../src/frontend-v1.css'
import '../src/research-results.css'

const fixture=document.querySelector('#fixture'),status=document.querySelector('#status')
const root=createRoot(fixture),calls=[],checks=[]
const nativeFetch=window.fetch
const scope={taskId:'integration',deliveryId:'delivery',revision:7,atSeq:37,sealedOnly:true}
const block={property_ids:['p'],entry_id:'entry',title:'任务归档背景',revision:4,content_sha256:'saved-hash',origin:'user_background',conditions:['仅在记录条件成立时解释'],claim:{claim_id:'claim',text:'当时保存的正文 $L=4\\pi R^2\\sigma T^4$'},sources:[{source_id:'s',title:'归档论文来源',locator:'第八页'}]}
const context={context_id:'ctx',content_sha256:'ctx-hash',library_version:9,entries:[block],properties:[{property_id:'p',name:'亮度',state:'conditional',entry_ids:['entry'],reason:'条件未确认'},{property_id:'custom',name:'自定义性质',state:'missing',entry_ids:[],reason:'尚无匹配的知识解释'}]}
const record={legacy_version:1,record_id:'measurement',field_name:'亮度',field_value:'12.30',field_unit:'mag',entity_name:'Target',source_id:'source',source:{task_id:'integration',raw_value:'12.30',unit:'mag'},evidence:[]}
const summary={state:'ready',text:'这份资料保留了本次测量与原始引用。',basis:{knowledge:[block],evidence:[{measurement_id:'measurement',evidence_id:'evidence',source_id:'source'}]}}
const property={schema_version:'InsightReport/4',status:'partial',cards:[{card_id:'card',property_id:'p',status:'partial',knowledge_coverage:{state:'missing',message:'未取得足够解释背景'},coverage:{target_record_count:1,contributing_source_count:1},sections:{found:[{text:'文献报告 12.30 mag，原值保持不变。',measurement_ids:['measurement'],claim_ids:[]}],comparison:[],uses:[],limitations:[]}}]}
const bundle={schema_version:'InsightBundle/1',material_report:{schema_version:'MaterialSummaryReport/1',status:'partial',counts:{p:{requested:3,ready:2,failed:1}}},property_report:property,components:{material:{status:'partial'},property:{status:'partial'}}}
let retryCount=0,releaseOld,oldSignal,ensureCount=0
window.fetch=async(input,options={})=>{
 const url=new URL(input,location.href)
 if(!url.pathname.startsWith('/api/'))return nativeFetch(input,options)
 calls.push({url,signal:options.signal,method:options.method||'GET'})
 if(url.pathname.endsWith('/knowledge/entry'))return new Response(JSON.stringify({id:'entry',title:'当前库条目',description:'当前库修改后的正文',revision:10,is_user:true,sources:[]}))
 const task=url.pathname.split('/')[3],revision=Number(url.searchParams.get('delivery_revision')||7)
 if(url.pathname.endsWith('/knowledge_context')){
  if(task==='retry'&&retryCount++===0)return new Response(JSON.stringify({detail:'测试暂时不可读'}),{status:503})
  if(task==='late'){oldSignal=options.signal;await new Promise(resolve=>{releaseOld=resolve})}
  return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:revision,snapshot_ref:{id:'snap'},context:{...context,entries:[{...block,title:task==='fresh'?'新交付依据':task==='late'?'迟到旧依据':block.title}]},origin:'historical_saved_basis'}))
 }
 if(url.pathname.endsWith('/records'))return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:7,total:url.searchParams.has('source_id')?101:1,items:[record]}))
 if(url.pathname.endsWith('/sources'))return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:7,total:1,items:[{source_id:'source',material_id:'source',title:'归档来源',kind:'paper',work:{records:[]}}]}))
 if(url.pathname.endsWith('/materials'))return new Response(JSON.stringify({delivery_id:'delivery',delivery_revision:7,total:1,items:[{material_id:'source',source_id:'source',title:'归档来源',kind:'paper',record_ids:['measurement'],work:{records:[]}}]}))
 throw new Error(`Unexpected API request ${url}`)
}
const data={taskId:scope.taskId,deliveryId:'delivery',deliveryRevision:7,resources:{records:{status:'success',data:[record]},sources:{status:'success',data:[]},quality:{status:'success',data:null},figures:{data:[]}}}
function App(){
 const [detail,setDetail]=useState(null),[opened,setOpened]=useState('')
 return <ToastProvider><main className="data-section" style={{maxWidth:1080,margin:'24px auto',padding:24}}>
  <TaskInsights scope={scope} report={bundle} records={[record]} ensureRecords={()=>{ensureCount++}} properties={[{property_id:'p',name:'亮度'}]} onOpenProperty={id=>setOpened(id)} onOpenRecord={value=>setDetail({type:'record',record:value})} onOpenKnowledge={value=>setDetail({type:'knowledge',block:value})}/>
  <output aria-label="资料定位">{opened}</output>
  <Summary scope={scope} item={{group_id:'source',property_id:'p',summary}} readOnly active onOpenDetail={setDetail}/>
 </main><ContextDrawer detail={detail} data={data} pipeline={{stages:[]}} onClose={()=>setDetail(null)} onChange={setDetail}/></ToastProvider>
}
const mount=value=>flushSync(()=>root.render(value))
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
const settle=async()=>{await pause(50);await pause(50)}
const assert=(condition,message)=>{if(!condition)throw new Error(message);checks.push(message)}
const click=(text,container=fixture)=>{const button=[...container.querySelectorAll('button')].find(value=>value.textContent.includes(text)||(value.getAttribute('aria-label')||'').includes(text));if(!button)throw new Error(`Missing button ${text}`);flushSync(()=>button.click())}
try{
 mount(<App/>);await settle()
 assert(fixture.querySelector('[role="tab"][aria-selected="true"]').textContent==='资料总结','bundle defaults to material summary')
 assert(calls.length===0,'default summary performs no knowledge/current-library HTTP reads')
 click('浏览资料');assert(fixture.querySelector('output').textContent==='p','summary navigation keeps exact property ID')
 click('性质洞察');await settle()
 assert(fixture.textContent.includes('12.30 mag'),'saved property findings are visible')
 assert(!fixture.textContent.includes('推荐基准采纳值')&&!fixture.textContent.includes('天体物理拓扑网络'),'missing saved claims never produce a benchmark or inferred topology')
 click('查阅测量记录与上下文');await settle()
 assert(fixture.querySelector('[role="dialog"]')?.textContent.includes('12.30'),'property evidence opens measurement drawer')
 click('关闭',fixture.querySelector('[role="dialog"]'));await pause(220)
 click('知识依据');await settle()
 const contextCall=calls.find(value=>value.url.pathname.endsWith('/knowledge_context'))
 assert(contextCall.url.searchParams.get('delivery_revision')==='7'&&contextCall.url.searchParams.get('at_seq')==='37'&&contextCall.url.searchParams.get('sealed_only')==='true','knowledge request pins revision, replay cursor and sealed boundary')
 assert(fixture.textContent.includes('条件未确认')&&fixture.textContent.includes('尚无匹配的知识解释'),'unknown conditions and no-match states remain distinct')
 click('查看当时依据');await settle()
 assert(fixture.querySelector('[role="dialog"]').textContent.includes('任务当时版本'),'knowledge opens archived version in existing overlay drawer')
 assert(!calls.some(value=>value.url.pathname.endsWith('/knowledge/entry')),'opening archive never reads current store')
 click('打开当前知识库条目');await settle()
 assert(fixture.querySelector('[role="dialog"]').textContent.includes('当前库修改后的正文'),'explicit current-library action displays current text')
 click('返回上一项');await settle()
 assert(fixture.querySelector('[role="dialog"]').textContent.includes('当时保存的正文'),'back navigation restores original archived text')
 click('关闭',fixture.querySelector('[role="dialog"]'));await pause(220)
 click('输入知识背景');await settle()
 assert(fixture.querySelector('[role="dialog"]').textContent.includes('不表示逐句实际引用'),'material background preserves input-versus-citation wording')
 click('查看当时依据',fixture.querySelector('[role="dialog"]'));await settle()
 assert(fixture.querySelector('[role="dialog"]').textContent.includes('saved-hash'),'material background shows archived block and exact hash')
 click('关闭',fixture.querySelector('[role="dialog"]'));await pause(220)
 const evidenceStart=calls.length
 click('原文依据');await settle();click('定位测量与原文');await settle()
 assert(fixture.querySelector('[role="dialog"]')?.textContent.includes('12.30'),'material original-evidence link locates saved measurement')
 const recordCall=calls.slice(evidenceStart).find(value=>value.url.pathname.endsWith('/records'))
 assert(recordCall?.url.searchParams.get('at_seq')==='37'&&recordCall.url.searchParams.get('sealed_only')==='true','summary measurement request preserves replay cutoff and sealed visibility')
 click('返回上一项');await settle();click('打开来源资料');await settle()
 const sourceCall=calls.slice(evidenceStart).find(value=>value.url.pathname.endsWith('/sources'))
 const materialCall=calls.slice(evidenceStart).find(value=>value.url.pathname.endsWith('/materials'))
 assert(sourceCall?.url.searchParams.get('at_seq')==='37'&&sourceCall.url.searchParams.get('sealed_only')==='true','summary source request preserves replay cutoff and sealed visibility')
 assert(materialCall?.url.searchParams.get('at_seq')==='37'&&materialCall.url.searchParams.get('sealed_only')==='true','source material detail preserves replay cutoff and sealed visibility')
 click('下一页',fixture.querySelector('[role="dialog"]'));await settle()
 const sourcePage=calls.slice(evidenceStart).find(value=>value.url.pathname.endsWith('/records')&&value.url.searchParams.get('offset')==='50')
 assert(sourcePage?.url.searchParams.get('at_seq')==='37'&&sourcePage.url.searchParams.get('sealed_only')==='true','source related-record pagination preserves replay cutoff and sealed visibility')
 assert(calls.every(value=>value.method==='GET'),'historical browsing sends no mutations')
 mount(<TaskKnowledgeBasis scope={{...scope,taskId:'retry'}}/>);await settle()
 assert(fixture.textContent.includes('读取失败'),'unreadable knowledge is reported rather than shown as empty success')
 click('重试');await settle();assert(fixture.textContent.includes('任务归档背景'),'failed context can retry')
 mount(<TaskKnowledgeBasis scope={{...scope,taskId:'late'}}/>);await settle()
 mount(<TaskKnowledgeBasis scope={{...scope,taskId:'fresh',revision:8}}/>);await settle()
 assert(oldSignal.aborted,'leaving a context scope aborts its read')
 releaseOld();await settle()
 assert(fixture.textContent.includes('新交付依据')&&!fixture.textContent.includes('迟到旧依据'),'late old context cannot overwrite new delivery')
 mount(<TaskInsights report={bundle.material_report} initialTab="properties"/>);await settle()
 assert(fixture.textContent.includes('此历史任务未生成性质级综合洞察'),'historical summary has honest no-property-report state')
 status.textContent=`PASS ${checks.length} checks\n${checks.join('\n')}`
 window.__taskInsightResults={pass:true,checks,calls:calls.map(value=>value.url.href)}
 mount(<App/>);await settle()
}catch(error){status.textContent=`FAIL ${error.stack}\n${checks.join('\n')}`;window.__taskInsightResults={pass:false,error:error.message,checks};console.error(error)}
