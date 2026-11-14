// Offline integration checks: real Hook, API adapter, cache and family picker.
// Only the fetch boundary is replaced, allowing controlled delay/abort/failure.
import React,{useRef,useState} from 'react'
import {createRoot} from 'react-dom/client'
import {useRegistryWorkbench} from '../src/hooks/useRegistryWorkbench'
import RegistryFamilySelect from '../src/components/registry/RegistryFamilySelect'
import '../src/styles.css'
import '../src/components/registry/registryWorkbench.css'

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms))
const catalogue=[{id:'mass',label:'恒星质量'},{id:'distance',label:'天体距离'},{id:'velocity',label:'径向速度'}]
const records=Array.from({length:75},(_,i)=>({id:`property-${i}`,label:`${i<70?'恒星质量':'天体距离'} ${i}${i===0?' late':''}`,family_id:i<70?'mass':'distance',origin:'builtin',status:'active'}))
let calls=[]
const originalFetch=window.fetch.bind(window)
window.fetch=(input,options={})=>{
  const url=new URL(String(input),location.href)
  if(!url.pathname.startsWith('/api/registry-workbench/'))return originalFetch(input,options)
  if(options.method&&options.method!=='GET')return Promise.reject(new Error('离线回归禁止写入'))
  const endpoint=url.pathname.slice('/api/registry-workbench/'.length),q=Object.fromEntries(url.searchParams)
  const call={endpoint,...q,aborted:false,settled:false};calls.push(call)
  const history=q.release_id==='historical'
  const all=history?[{id:'historic-property',label:'历史距离',family_id:'historic',origin:'builtin',status:'active'}]:records
  const filtered=all.filter(row=>(!q.keyword||row.label.includes(q.keyword))&&(!q.family_id||row.family_id===q.family_id)&&(!q.origin||row.origin===q.origin)&&(!q.status||row.status===q.status))
  const families=(history?[{id:'historic',label:'历史分类'}]:catalogue).filter(f=>filtered.some(row=>row.family_id===f.id)).map(f=>({...f,count:filtered.filter(row=>row.family_id===f.id).length}))
  const summary={view:'published',revision:history?2:1,workspace:null,active_bundle:{id:history?'bundle-history':'bundle-current'},counts:{types:1,properties:filtered.length,bindings:filtered.length},types:[{id:'star',label:'恒星'}],families,capabilities:{},knowledge_coverage:{available:filtered.length,missing:0}}
  if(q.projection==='directory')summary.families=(history?[{id:'historic',label:'历史分类'}]:catalogue).map(f=>({...f,count:all.filter(row=>row.family_id===f.id).length}));
  if(q.projection==='stats'){delete summary.types;delete summary.families;delete summary.capabilities}
  if(q.projection==='directory')delete summary.capabilities
  const data=endpoint==='summary'?summary:endpoint==='graph'?{nodes:filtered.slice(0,Number(q.limit)||80),edges:[],categories:families,meta:{node_count:filtered.length,matched_entries:filtered.length}}:endpoint==='workspaces'?{workspaces:[]}:endpoint==='releases'?{releases:[]}:endpoint.includes('/')?{item:all.find(row=>row.id===decodeURIComponent(endpoint.split('/').at(-1)))}:{items:filtered.slice(Number(q.offset)||0,(Number(q.offset)||0)+(Number(q.limit)||24)),total:filtered.length}
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{
      call.settled=true
      resolve(new Response(JSON.stringify(endpoint==='graph'&&q.keyword==='graph-error'?{detail:'模拟图谱失败'}:data),{status:endpoint==='graph'&&q.keyword==='graph-error'?503:200,headers:{'Content-Type':'application/json'}}))
    },q.keyword==='late'?800:12)
    const abort=()=>{if(call.settled)return;call.aborted=true;if(q.keyword!=='late'){clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))}}
    if(options.signal?.aborted)abort();else options.signal?.addEventListener('abort',abort,{once:true})
  })
}
async function until(read,timeout=4000){const start=performance.now();while(performance.now()-start<timeout){if(read())return;await sleep(16)}throw new Error('等待规范状态超时')}

function Probe({stateRef}){
  const w=useRegistryWorkbench();stateRef.current=w
  return <div className="rwb-workspace"><RegistryFamilySelect families={w.families||w.summary?.families||[]} value={w.filters.family_id} onChange={value=>w.setFilter('family_id',value)} showCounts/>
    <pre aria-label="当前规范状态">{JSON.stringify({mode:w.mode,listMode:w.listMode,keyword:w.keyword,filters:w.filters,offset:w.offset,loading:w.loading,stale:w.stale,error:w.error,total:w.matchedTotal,items:w.list.items,selected:w.selected,scope:w.scope},null,2)}</pre></div>
}
function Harness(){
  const [mounted,setMounted]=useState(false),[epoch,setEpoch]=useState(0),[running,setRunning]=useState(false),[results,setResults]=useState([])
  const state=useRef(null),w=()=>state.current
  const check=(name,pass,evidence)=>setResults(previous=>[...previous,{name,pass:!!pass,evidence}])
  const count=(endpoint,condition=()=>true)=>calls.filter(call=>call.endpoint===endpoint&&!call.aborted&&condition(call)).length
  const idle=async()=>{await sleep(40);await until(()=>w()&&!w().loading);await sleep(24)}
  const keyword=async value=>{w().setKeyword(value);await sleep(310);await idle()}
  const matrix=async mode=>{w().setMode('matrix');w().setListMode(mode);await idle()}
  const typeFamilySearch=async value=>{const input=document.querySelector('[aria-label="搜索性质分类"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));await sleep(32)}
  const run=async()=>{
    setResults([]);setRunning(true);setMounted(false);await sleep(32);state.current=null;calls=[];setEpoch(n=>n+1);setMounted(true)
    try{
      await idle()
      check('初始只读图谱，目录与未筛选统计共享一次请求',count('properties')===0&&count('summary')===1&&count('graph')===1,{summary:count('summary'),graph:count('graph'),list:count('properties')})
      check('版本历史在打开前不读取',count('workspaces')===0&&count('releases')===0)
      w().loadVersions();await until(()=>!w().directoryLoading);await sleep(24)
      check('版本历史按需读取精简目录',count('workspaces')===1&&count('releases')===1&&calls.filter(c=>['workspaces','releases'].includes(c.endpoint)).every(c=>c.projection==='directory'))
      check('图谱记录数量不依赖隐藏列表',w().matchedTotal===75,{actual:w().matchedTotal})
      await matrix('cards')
      check('首次卡片只请求24条列表',count('properties')===1&&calls.filter(c=>c.endpoint==='properties'&&!c.aborted).at(-1)?.limit==='24'&&count('graph')===1)
      w().setMode('graph');await idle()
      check('相同图谱返回复用缓存',count('graph')===1)
      await matrix('cards');w().setOffset(24);await idle()
      const beforePageReturn=count('properties')
      w().setMode('graph');await idle();await matrix('cards')
      check('返回相同矩阵保留页码且复用分页缓存',w().offset===24&&count('properties')===beforePageReturn,{offset:w().offset})
      await matrix('table')
      check('表格单独读取50条分页，切换不重读目录',calls.filter(c=>c.endpoint==='properties'&&!c.aborted).at(-1)?.limit==='50'&&count('summary')===1)
      w().setFilter('family_id','mass');w().setFilter('origin','builtin');w().setFilter('status','active');await keyword('恒星')
      w().setSelected({kind:'properties',id:'property-0'});await until(()=>w().detail?.id==='property-0')
      check('完整分类目录不被已选分类或关键词缩小',w().families?.some(f=>f.id==='distance'),{families:w().families?.map(f=>f.id)})
      const beforeLocalSearch=calls.length
      await typeFamilySearch('不存在')
      const familySelect=document.querySelector('[name="family_id"]'),enter=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true})
      document.querySelector('[aria-label="搜索性质分类"]').dispatchEvent(enter)
      check('分类空结果保留当前选择且搜索不发请求',familySelect.value==='mass'&&familySelect.selectedOptions[0].textContent.includes('恒星质量')&&calls.length===beforeLocalSearch&&enter.defaultPrevented)
      w().setMode('graph');await idle();await matrix('cards');await matrix('table')
      check('跨三种视图保留搜索、筛选、分类搜索与选中对象',w().keyword==='恒星'&&w().filters.family_id==='mass'&&w().filters.origin==='builtin'&&w().filters.status==='active'&&w().selected?.id==='property-0'&&document.querySelector('[aria-label="搜索性质分类"]').value==='不存在')
      await keyword('graph-error')
      check('隐藏图谱不请求且失败不会污染表格',count('graph',c=>c.keyword==='graph-error')===0&&!w().error&&!w().stale)
      w().setMode('graph');await idle()
      check('当前图谱失败明确显示',w().error.includes('模拟图谱失败')&&w().stale)
      await matrix('table')
      check('离开失败视图后恢复当前表格状态',!w().error&&!w().stale)
      w().setKeyword('late');await sleep(290)
      await keyword('天体距离');await sleep(850)
      check('迟到的过期响应不能覆盖当前检索',w().filters.keyword==='天体距离'&&w().list.items.every(item=>item.label.includes('天体距离'))&&w().list.total===0)
      const lateBefore=calls.filter(c=>c.endpoint==='properties'&&c.keyword==='late').length
      w().setKeyword('late');await sleep(290)
      check('被取消的旧结果不会成为有效缓存',calls.filter(c=>c.endpoint==='properties'&&c.keyword==='late').length===lateBefore+1)
      await keyword('恒星')
      const beforeRefresh={list:count('properties'),graph:count('graph'),summary:count('summary')}
      w().reload();await idle()
      check('刷新只重读当前列表并失效目录/统计',count('properties')===beforeRefresh.list+1&&count('graph')===beforeRefresh.graph&&count('summary')===beforeRefresh.summary+2)
      const graphBefore=count('graph');w().setMode('graph');await idle()
      check('刷新后首次返回图谱重新读取',count('graph')===graphBefore+1)
      w().setScope({release_id:'historical'});await idle()
      check('版本目录和当前结果精确隔离且筛选保留',w().families?.length===1&&w().families[0].id==='historic'&&w().summary.active_bundle.id==='bundle-history'&&w().filters.family_id==='mass'&&w().keyword==='恒星'&&w().matchedTotal===0)
      const currentSummaryBefore=count('summary',c=>!c.release_id)
      w().setScope({});await idle()
      check('返回原版本复用其缓存和目录',w().families?.some(f=>f.id==='distance')&&count('summary',c=>!c.release_id)===currentSummaryBefore)
    }catch(error){check('回归执行',false,error.message)}finally{setRunning(false)}
  }
  return <main style={{padding:24,color:'var(--text-primary)'}}><h1>规范工作台读取回归</h1><p>离线固定响应；不读取或保存真实任务、规范与配置。</p><button className="ui-button" onClick={run} disabled={running}>运行读取回归</button>
    <ol aria-label="读取回归结果">{results.map(result=><li key={result.name} data-pass={result.pass}>{result.pass?'通过':'失败'} · {result.name}<details><summary>证据</summary><pre>{JSON.stringify(result.evidence,null,2)}</pre></details></li>)}</ol>
    <output aria-label="读取回归状态">{running?'检查中':results.length?results.every(result=>result.pass)?`全部通过 · ${results.length} 项`:'存在失败':'等待检查'}</output>
    {mounted&&<Probe key={epoch} stateRef={state}/>}<details><summary>请求记录</summary><pre aria-label="请求记录">{JSON.stringify(calls,null,2)}</pre></details>
  </main>
}
createRoot(document.getElementById('root')).render(<React.StrictMode><Harness/></React.StrictMode>)
