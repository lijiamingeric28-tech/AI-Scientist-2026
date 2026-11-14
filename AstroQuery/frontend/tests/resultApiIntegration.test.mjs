import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
let server,api,calls=[]
const originalFetch=globalThis.fetch
const record=n=>({source:{measurement_id:`m${n}`,value:{kind:'real',value:'4'},raw_value:'4',unit:'K',representation:'linear',target_ref:{id:'target'},source_ref:{id:'s'},source_kind:'paper',evidence_refs:[],uncertainty:{components:[]}},property_binding:{property_id:'temperature',definition:{name_cn:'温度'},output_profile:{representation:{kind:'linear'},unit:{canonical_symbol:'K'}}},target:{main_id:'天体'},derived:{main_state:'ready',value_typed:{kind:'real',value:'4'},uncertainty_typed:{components:[{status:'exact',output_component:{values:{delta:'0.1'}}}]}},source_label:{source_id:'s',title:'论文'},flags:{modified:true},duplicate_group:{group_id:'g',archive:true,live_count:2}})
before(async()=>{
  globalThis.fetch=async(input)=>{
    const u=new URL(String(input),'http://local');calls.push(u)
    const name=u.pathname.split('/').at(-1),offset=Number(u.searchParams.get('offset'))||0,limit=Number(u.searchParams.get('limit'))||500
    const total=name==='records'&&!u.searchParams.has('record_id')?601:1
    const items=name==='sources'?[{source_id:'s',title:'论文'}]:name==='figures'?[{figure_id:'f'}]:Array.from({length:Math.min(limit,total-offset)},(_,i)=>record(offset+i))
    return new Response(JSON.stringify({delivery_id:'d',delivery_revision:7,snapshot_ref:{id:'snap'},total,display_total:600,items,aggregates:{total:601}}),{headers:{'Content-Type':'application/json'}})
  }
  server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom',logLevel:'error'})
  api=await server.ssrLoadModule('/src/services/api.js')
})
after(async()=>{globalThis.fetch=originalFetch;await server?.close()})
test('records page retains compact flags/source labels and does not read second page',async()=>{
  calls=[];const page=await api.getRecordsPage('api-page','d',7)
  assert.equal(calls.length,1);assert.equal(page.items.length,50);assert.equal(page.total,601)
  assert.equal(page.items[0].flags.modified,true);assert.equal(page.items[0].source_label.title,'论文');assert.equal(page.items[0].duplicate_group.live_count,2)
})
test('analysis alone reads complete compact projection, preserving exact uncertainties across page boundary',async()=>{
  calls=[];const rows=await api.getAnalysisRecords('api-analysis','d',7)
  assert.equal(rows.length,601);assert.equal(rows[600].record_id,'m600')
  assert.equal(rows[600].derived.uncertainty_typed.components[0].output_component.values.delta,'0.1')
  assert.equal(calls.length,2);assert.ok(calls.every(u=>u.searchParams.get('view')==='analysis'&&u.searchParams.get('collapse_duplicates')==='false'))
})
test('single detail readers send exact IDs and exact delivery revision without enumerating resources',async()=>{
  calls=[]
  await api.getRecord('api-detail','d',7,'m/1');await api.getSource('api-detail','d',7,'s/1');await api.getFigure('api-detail','d',7,'f/1')
  assert.equal(calls.length,3)
  for(const [i,key] of ['record_id','source_id','figure_id'].entries())assert.equal(calls[i].searchParams.get(key),['m/1','s/1','f/1'][i])
  assert.ok(calls.every(u=>u.searchParams.get('delivery_revision')==='7'&&u.searchParams.get('expected_delivery_revision')==='7'))
})
test('source detail reports global contribution count and keeps links to measurements beyond its current page',async()=>{
  const Material=(await server.ssrLoadModule('/src/components/results/ResearchMaterialDetail.jsx')).default
  const html=renderToStaticMarkup(React.createElement(Material,{source:{protocol_version:2,source_id:'s',kind:'paper',title:'论文',citations:[{reference_id:'c',measurement_id:'m6000',role:'comparison',link_quote:'引用'}]},records:[],recordsTotal:601,scope:{taskId:'t',deliveryId:'d',deliveryRevision:7}}))
  assert.match(html,/实际贡献测量 · 601 条/)
  assert.match(html,/查看引用所在记录/)
})
test('task data hook renders the initial app without a selected task or preview page',async()=>{
  const {useTaskData}=await server.ssrLoadModule('/src/hooks/useTaskData.js')
  const {useRecordsPage}=await server.ssrLoadModule('/src/hooks/useRecordsPage.js')
  function Probe(){const data=useTaskData(null,false);useRecordsPage(null,null);return React.createElement('span',null,data.availability)}
  assert.equal(renderToStaticMarkup(React.createElement(Probe)),'<span>waiting</span>')
})
test('historical record drawer uses its linked source instead of same-ID current source cache',async()=>{
  const Drawer=(await server.ssrLoadModule('/src/components/layout/ContextDrawer.jsx')).default
  const value=await api.getRecord('historical-drawer','d',7,'m0')
  const resources={records:{data:[{...value,delivery_revision:8}]},sources:{status:'error',data:[{source_id:'s',title:'CURRENT_SOURCE_8'}]},quality:{status:'error',data:{score:88}},materials:{data:[{source_id:'s',title:'CURRENT_MATERIAL_8'}]},figures:{data:[]}}
  const html=renderToStaticMarkup(React.createElement(Drawer,{detail:{type:'record',record:value,agentContext:true,answerScope:{delivery_id:'d',delivery_revision:7},linkedSource:{source_id:'s',title:'HISTORICAL_SOURCE_7'}},data:{taskId:'historical-drawer',deliveryId:'d',deliveryRevision:8,resources},pipeline:{stages:[]},onClose:()=>{},onChange:()=>{}}))
  assert.match(html,/HISTORICAL_SOURCE_7/)
  assert.doesNotMatch(html,/CURRENT_SOURCE_8|CURRENT_MATERIAL_8/)
  assert.doesNotMatch(html,/来源读取失败|处理信息读取失败/)
})
