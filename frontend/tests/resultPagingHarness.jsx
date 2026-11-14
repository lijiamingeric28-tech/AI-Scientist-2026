import React,{useState} from 'react'
import {createRoot} from 'react-dom/client'
import {RecordsTable} from '../src/components/results/ResultTabs'
import ExportDialog from '../src/components/results/ExportDialog'
import {ToastProvider} from '../src/components/ui/toast'
import {useTaskData} from '../src/hooks/useTaskData'
import TemporaryPreview from '../src/components/results/TemporaryPreview'
import DataView from '../src/components/results/DataView'
import ContextDrawer from '../src/components/layout/ContextDrawer'
import '../src/styles.css'
const calls=[]
const scope={taskId:'offline-results',deliveryId:'d',revision:7}
const row=n=>({record_id:`m${n}`,entity_name:'测试天体',field_name:n%2?'质量':'温度',field_value:String(n),field_unit:'K',source_id:'s',source_label:{source_id:'s',title:'测试来源',year:2025},details_loaded:false,protocol_version:2,delivery_id:'d',delivery_revision:7,flags:{modified:true},...(n===0?{duplicate_group:{group_id:'g',archive:true,live_count:2},archive_groups:[{group_id:'g',member_refs:[{id:'m0'},{id:'m6000'}]}]}:{})})
const fullRow=n=>({...row(n),details_loaded:true,source:{measurement_id:`m${n}`,raw_value:String(n),value:{kind:'real',value:String(n)},unit:'K',representation:'linear',limit:'none',uncertainty:{state:'not_reported',components:[]},source_ref:{id:'s'},target_ref:{id:'t'},evidence_refs:[]},property_binding:{definition:{name_cn:'温度'},output_profile:{unit:{canonical_symbol:'K'},representation:{kind:'linear'}}},context:{conditions:[]},derived:{main_state:'ready',value_typed:{kind:'real',value:String(n)}},evidence:[]})
window.fetch=async(input,options={})=>{
  const url=new URL(String(input),location.href),q=Object.fromEntries(url.searchParams)
  calls.push({path:url.pathname,q,method:options.method||'GET',body:options.body?JSON.parse(options.body):null})
  let body
  if(url.pathname.endsWith('/records')){
    if(q.q==='late')await new Promise(resolve=>setTimeout(resolve,200))
    if(q.q==='error')return new Response(JSON.stringify({detail:'模拟读取失败'}),{status:503,headers:{'Content-Type':'application/json'}})
    const offset=Number(q.offset)||0,limit=Number(q.limit)||50,revision=Number(q.delivery_revision)||7,total=q.q==='none'?0:revision>=8?100:6001
    body={delivery_id:'d',delivery_revision:revision,snapshot_ref:{id:'snapshot'},legacy_version:1,offset,limit,total,display_total:q.collapse_duplicates==='true'&&revision<8?Math.max(0,total-101):total,items:Array.from({length:Math.min(limit,Math.max(0,total-offset))},(_,i)=>row(offset+i)),aggregates:{total:revision>=8?100:7000,owner_excluded:999,modified:6001,duplicate:202,fields:[{field:'质量',property_id:'mass',count:3000},{field:'温度',property_id:'temp',count:4000}],sources:[{source_id:'s',title:'测试来源',year:2025,count:7000}]}}
    if(q.record_id){
      const detail={...fullRow(Number(q.record_id.slice(1))),delivery_revision:revision}
      if(revision>=8){detail.field_value='8000';detail.source.raw_value='8000';detail.source.value={kind:'real',value:'8000'};detail.derived.value_typed={kind:'real',value:'8000'}}
      body={...body,items:[detail],total:1};delete body.legacy_version
    }
  }else if(url.pathname.endsWith('/sources'))body={delivery_id:'d',delivery_revision:Number(q.delivery_revision)||7,items:[{source_id:'s',title:Number(q.delivery_revision)>=8?'CURRENT_SOURCE_8':'HISTORICAL_SOURCE_7'}],total:1}
  else if(url.pathname.endsWith('/preview'))body={preview_id:q.expected_preview_id||'preview-v2-a',total:201,items:[],counts:{source_records:201,pending_questions:0,accepted_answers_awaiting_application:0}}
  else if(url.pathname.endsWith('/delivery'))body={delivery_id:'d',revision:7}
  else if(url.pathname.endsWith('/exports')&&options.method==='POST')body={artifacts:[]} // Capture only: never generate or download a live artifact.
  else throw new Error(`离线回归拒绝未定义请求 ${url.pathname}`)
  return new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}})
}
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
async function until(predicate){for(let i=0;i<100;i++){if(predicate())return;await pause(20)}throw new Error('等待界面超时')}
const click=text=>{const el=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);if(!el)throw new Error(`找不到按钮 ${text}`);el.click()}
const memory={workbenchSection:'details'}
const revisionMemory={page:10,pageSize:50}
function DrawerProbe({cached=false}){
  const [detail,setDetail]=useState({type:'record',record:fullRow(0),agentContext:true,answerScope:{delivery_id:'d',delivery_revision:7},linkedSource:{source_id:'s',title:'HISTORICAL_SOURCE_7'}})
  const data={taskId:scope.taskId,deliveryId:'d',deliveryRevision:8,resources:{records:{status:'success',data:[fullRow(0),...(cached?[{...fullRow(6000),task_id:scope.taskId,delivery_revision:8,field_value:'8000',details_loaded:false}]:[])]},quality:{status:'success',data:{score:88}},sources:{status:'success',data:[{source_id:'s',title:'CURRENT_SOURCE_8'}]},figures:{status:'success',data:[]},materials:{status:'success',data:[{material_id:'s',source_id:'s',title:'CURRENT_MATERIAL_8'}]}},ensure:()=>{}}
  return <><output aria-label="详情测量标识">{detail.record.record_id} · {detail.answerScope?.delivery_revision}</output><output aria-label="详情记录版本和值">{detail.record.delivery_revision} · {detail.record.field_value}</output><ContextDrawer detail={detail} data={data} pipeline={{stages:[]}} onChange={setDetail} onClose={()=>{}}/></>
}
function ResultProbe(){
  const task={task_id:scope.taskId,status:'completed',delivery_ref:{id:'d',version:7}}
  const data=useTaskData(task,true)
  const [request,setRequest]=useState(null)
  return <><button onClick={()=>setRequest({recordId:'m6000',seq:Date.now()})}>定位页外记录</button><DataView memory={memory} task={task} data={data} request={request} pipeline={{started:true,taskDone:true,presentation:{properties:[]}}} onOpenDetail={()=>{}} /></>
}
function Harness(){
  const [mode,setMode]=useState('idle'),[result,setResult]=useState([]),[search,setSearch]=useState(''),[quick,setQuick]=useState('target'),[task,setTask]=useState({task_id:'offline-preview',query_ref:{id:'q'},core_event_cursor:1,preview_revision:'preview-v2-a'})
  const [testRevision,setTestRevision]=useState(7)
  const data=useTaskData(task,false,false,mode==='preview')
  const check=(name,pass,evidence)=>{setResult(r=>[...r,{name,pass:!!pass,evidence}]);if(!pass)throw new Error(name)}
  const run=async()=>{
    setResult([]);calls.length=0;setMode('data')
    try{
      await until(()=>document.querySelectorAll('.record-row').length===50)
      await pause(60)
      check('结果工作区首屏复用一页并使用全局7000条汇总，不读取质量或全量来源',calls.filter(c=>c.path.endsWith('/records')).length===1&&!calls.some(c=>/\/(quality|sources)$/.test(c.path))&&document.body.textContent.includes('7000'),JSON.parse(JSON.stringify(calls)))
      check('统一资料导出与原有筛选导出入口同时可用',document.body.textContent.includes('导出结果')&&document.body.textContent.includes('导出筛选记录'))
      click('下一页');await until(()=>document.querySelector('.record-row')?.textContent.includes('50'))
      click('全部原报');await until(()=>calls.some(c=>c.q.quick==='all'&&c.q.offset==='0')&&document.querySelector('.record-row')?.textContent.includes('测试天体温度0'))
      check('工作区快捷筛选从第二页回到第一页',calls.filter(c=>c.path.endsWith('/records')).at(-1).q.offset==='0')
      const controlledSearch=document.querySelector('[aria-label="搜索记录"]')
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(controlledSearch,'none');controlledSearch.dispatchEvent(new Event('input',{bubbles:true}))
      await until(()=>calls.some(c=>c.path.endsWith('/records')&&c.q.q==='none'))
      await until(()=>!document.querySelector('.record-row'))
      check('新资料工作台的全部数据搜索绑定真实服务端查询并返回全局空结果',document.body.textContent.includes('没有找到符合当前条件的记录'))
      click('定位页外记录');await until(()=>document.body.textContent.includes('显示此记录'))
      click('显示此记录');await until(()=>document.querySelector('.record-row')?.textContent.includes('6000'))
      check('显示此记录按精确ID定位页外条目，保持同一交付修订',calls.some(c=>c.q.record_id==='m6000'&&c.q.delivery_revision==='7'&&c.q.view==='list'))
      setMode('idle');await pause(30);calls.length=0;setMode('table')
      await until(()=>document.querySelectorAll('.record-row').length===50)
      check('首屏只读50行且展示5900项与6001条原报',calls.filter(c=>c.path.endsWith('/records')).length===1&&document.body.textContent.includes('5900 项')&&document.body.textContent.includes('6001 条原报'),calls)
      click('下一页');await until(()=>document.querySelector('.record-row')?.textContent.includes('50'))
      check('下一页使用offset50并保持筛选',calls.at(-1).q.offset==='50'&&calls.at(-1).q.quick==='target',calls.at(-1))
      const select=document.querySelector('[aria-label="按性质筛选"]');select.value='质量';select.dispatchEvent(new Event('change',{bubbles:true}))
      await until(()=>calls.at(-1).q.field==='质量'&&calls.at(-1).q.offset==='0')
      check('性质筛选重置页码，来源与全球性质选项保持',select.options.length===3&&calls.at(-1).q.limit==='50')
      await until(()=>document.querySelector('.record-row details summary'))
      document.querySelector('.record-row details summary').click()
      await until(()=>calls.some(c=>c.q.record_id==='m0'))
      await until(()=>document.body.textContent.includes('查看原报 2'))
      check('重复归档展开只读代表详情，所有成员可逐项打开',document.body.textContent.includes('查看原报 2')&&calls.filter(c=>c.q.record_id).length===1)
      setSearch('late');await until(()=>calls.at(-1).q.q==='late');setSearch('none')
      await until(()=>document.body.textContent.includes('没有找到符合当前条件的记录'));await pause(250)
      check('延迟旧请求不能覆盖新筛选的空结果',document.querySelectorAll('.record-row').length===0&&document.body.textContent.includes('没有找到符合当前条件的记录'))
      setSearch('error');await until(()=>document.body.textContent.includes('模拟读取失败'))
      check('失败与无匹配记录分别显示，并保留重试入口',!![...document.querySelectorAll('button')].find(b=>b.textContent==='重试')&&!document.body.textContent.includes('没有找到符合当前条件的记录'))
      setMode('export');await until(()=>document.querySelector('[data-record-id="m0"]'))
      document.querySelector('[data-record-id="m0"]').click();document.querySelector('[aria-label="导出下一页"]').click()
      await until(()=>document.querySelector('[data-record-id="m50"]'))
      document.querySelector('[data-record-id="m50"]').click();await pause(40)
      click('生成并下载 5999 条');await until(()=>calls.some(c=>c.method==='POST'))
      const body=calls.find(c=>c.method==='POST').body
      check('跨页取消勾选后导出全部匹配且固定修订',body.selection.mode==='filtered'&&body.expected_delivery_revision===7&&body.selection.excluded_measurement_ids.join(',')==='m0,m50'&&!('offset' in body.selection.filters),body)
      document.querySelector('[aria-label="选择全部匹配记录"]').click();await pause(20)
      document.querySelector('[aria-label="选择全部匹配记录"]').click();await pause(20)
      document.querySelector('[data-record-id="m50"]').click();await pause(20)
      click('生成并下载 1 条');await until(()=>calls.filter(c=>c.method==='POST').length===2)
      check('明确选择单条时使用ids而不是筛选全选',calls.filter(c=>c.method==='POST')[1].body.selection.mode==='ids'&&calls.filter(c=>c.method==='POST')[1].body.selection.measurement_ids.join(',')==='m50')
      setMode('preview');await until(()=>calls.some(c=>c.path.endsWith('/preview')))
      const before=calls.filter(c=>c.path.endsWith('/preview')).length
      setTask(t=>({...t,core_event_cursor:2}));await pause(100)
      check('仅事件游标更新不重读临时预览',calls.filter(c=>c.path.endsWith('/preview')).length===before)
      click('下一页');await until(()=>calls.at(-1).q.offset==='50')
      check('临时预览翻页固定同一preview_id',calls.at(-1).q.expected_preview_id==='preview-v2-a')
      await until(()=>document.body.textContent.includes('2 / 5 页'))
      click('下一页');await until(()=>calls.at(-1).q.offset==='100'&&document.body.textContent.includes('3 / 5 页'))
      click('上一页');await until(()=>calls.at(-1).q.offset==='50'&&document.body.textContent.includes('2 / 5 页'))
      check('真实预览响应缺少offset与limit时仍可到第三页并返回第二页',calls.at(-1).q.offset==='50')
      setTask(t=>({...t,preview_revision:'preview-v2-b'}));await until(()=>calls.at(-1).q.expected_preview_id==='preview-v2-b')
      check('临时预览修订变更从第一页重新读取',calls.at(-1).q.offset==='0')
      setMode('readonly');await pause(100)
      check('历史导出禁用创建按钮',[...document.querySelectorAll('button')].filter(b=>b.textContent.includes('生成并下载')).every(b=>b.disabled))
      setMode('revision');await until(()=>document.querySelector('.record-row')?.textContent.includes('450'))
      setTestRevision(8);await until(()=>document.querySelector('.record-row')?.textContent.includes('50')&&document.body.textContent.includes('100 项'))
      check('修订缩小后仅在成功总数到达时把第10页收回第2页',calls.at(-1).q.delivery_revision==='8'&&calls.at(-1).q.offset==='50')
      setTestRevision(9);await until(()=>calls.at(-1).q.delivery_revision==='9'&&document.querySelectorAll('.record-row').length===50)
      check('新修订仍包含当前页时保留原页',calls.at(-1).q.offset==='50')
      setMode('drawer');await until(()=>document.querySelector('.research-record-detail details summary'))
      document.querySelector('.research-record-detail details summary').click()
      const members=[...document.querySelectorAll('.research-links button')];members.at(-1).click()
      await until(()=>document.querySelector('[aria-label="详情测量标识"]')?.textContent==='m6000 · 7')
      check('详情重复组跨页成员通过精确ID载入且保留回答修订与返回历史',calls.some(c=>c.q.record_id==='m6000'&&c.q.delivery_revision==='7')&&document.body.textContent.includes('返回上一项'))
      const beforeCached=calls.length
      setMode('drawerCached');await until(()=>document.querySelector('[aria-label="详情测量标识"]')?.textContent==='m0 · 7')
      check('历史记录来源使用修订7链接，拒绝当前同ID修订8缓存',document.querySelector('.research-record-detail')?.textContent.includes('HISTORICAL_SOURCE_7')&&!document.querySelector('.research-record-detail')?.textContent.includes('CURRENT_SOURCE_8'))
      document.querySelector('.research-record-detail details summary').click()
      ;[...document.querySelectorAll('.research-links button')].at(-1).click()
      await until(()=>document.querySelector('[aria-label="详情测量标识"]')?.textContent==='m6000 · 7')
      check('历史回答中的归档成员拒绝复用当前页同ID新版本，读取并显示修订7原值',document.querySelector('[aria-label="详情记录版本和值"]')?.textContent==='7 · 6000'&&calls.slice(beforeCached).some(c=>c.q.record_id==='m6000'&&c.q.delivery_revision==='7')&&!calls.slice(beforeCached).some(c=>c.q.record_id==='m6000'&&c.q.delivery_revision==='8'),calls.slice(beforeCached))
      check('历史归档跳转后的完整来源仍按修订7读取',document.querySelector('.research-record-detail')?.textContent.includes('HISTORICAL_SOURCE_7')&&calls.slice(beforeCached).some(c=>c.path.endsWith('/sources')&&c.q.delivery_revision==='7')&&!document.querySelector('.research-record-detail')?.textContent.includes('CURRENT_SOURCE_8'))
    }catch(error){setResult(r=>[...r,{name:error.message,pass:false}])}
  }
  return <><button onClick={run}>运行结果分页回归</button><pre aria-label="回归结果">{JSON.stringify(result,null,2)}</pre>{mode==='data'&&<ResultProbe/>}{mode==='table'&&<RecordsTable serverScope={scope} records={[]} searchText={search} search={search} onSearchChange={setSearch} quick={quick} onQuickChange={setQuick}/ >}{mode==='revision'&&<RecordsTable serverScope={{...scope,revision:testRevision}} memory={revisionMemory} records={[]}/ >}{['export','readonly'].includes(mode)&&<ExportDialog open embedded taskId={scope.taskId} serverScope={scope} initialFilters={{quick:'target'}} records={[]} readOnly={mode==='readonly'}/ >}{mode==='preview'&&<TemporaryPreview preview={data.preview}/ >}{['drawer','drawerCached'].includes(mode)&&<DrawerProbe key={mode} cached={mode==='drawerCached'}/>}</>
}
createRoot(document.getElementById('root')).render(<ToastProvider><Harness/></ToastProvider>)
