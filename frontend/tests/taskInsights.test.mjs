import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
let server,views,basis,detail,api,ToastProvider
before(async()=>{
 server=await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'silent'})
 api=await server.ssrLoadModule('/src/services/api.js')
 ToastProvider=(await server.ssrLoadModule('/src/components/ui/toast.jsx')).ToastProvider
})
after(async()=>{await server?.close()})
const html=(Component,props)=>renderToStaticMarkup(React.createElement(Component,props))
const material={schema_version:'MaterialSummaryReport/1',counts:{p:{requested:3,ready:2,failed:1}}}
const bundle={schema_version:'InsightBundle/1',material_report:material,property_report:{schema_version:'InsightReport/4',status:'failed',cards:[],reason:'预算已耗尽'},components:{material:{status:'partial'},property:{status:'failed',reason:'预算已耗尽'}}}
test('bundle keeps material reading as default and exposes its three reading sections',async()=>{
 views=await server.ssrLoadModule('/src/components/results/TaskInsights.jsx')
 const result=html(views.default,{report:bundle,properties:[{property_id:'p',name:'亮度'}]})
 assert.match(result,/资料总结/);assert.match(result,/性质洞察/);assert.match(result,/知识依据/)
 assert.match(result,/已完成 2 \/ 3/);assert.match(result,/aria-selected="true"[^>]*>资料总结/)
 assert.doesNotMatch(result,/预算已耗尽/)
})
test('historical material report states property insight was never generated instead of failure',async()=>{
 views=await server.ssrLoadModule('/src/components/results/TaskInsights.jsx')
 const result=html(views.default,{report:material,initialTab:'properties'})
 assert.match(result,/此历史任务未生成性质级综合洞察/)
 assert.doesNotMatch(result,/洞察失败/)
})
test('failed property component retains material report and gives its saved failure reason',async()=>{
 views=await server.ssrLoadModule('/src/components/results/TaskInsights.jsx')
 assert.match(html(views.default,{report:bundle,initialTab:'properties'}),/预算已耗尽/)
})
test('knowledge index uses explicit property IDs and separates absence, unreadable and unknown conditions',async()=>{
 basis=await server.ssrLoadModule('/src/components/results/TaskKnowledgeBasis.jsx')
 const context={context_id:'ctx',content_sha256:'hash',library_version:7,entries:[{entry_id:'e',title:'归档条目',claim:{claim_id:'c',text:'当时正文'},property_ids:['p'],origin:'user'}],properties:[{property_id:'p',name:'亮度',state:'matched',entry_ids:['e']},{property_id:'similar',name:'亮度相似名称',state:'no_match',entry_ids:[],reason:'尚无匹配的知识解释'},{property_id:'u',name:'不可读',state:'unavailable',entry_ids:[],reason:'知识不可用'},{property_id:'c',name:'条件',state:'conditions_unknown',entry_ids:[],reason:'条件未确认'}]}
 const result=html(basis.KnowledgeBasisContent,{context,origin:'historical_saved_basis'})
 assert.match(result,/历史已保存依据/);assert.match(result,/当时正文/);assert.match(result,/尚无匹配的知识解释/);assert.match(result,/知识不可用/);assert.match(result,/条件未确认/)
 assert.equal((result.match(/归档条目/g)||[]).length,1,'similar property names cannot borrow an entry')
 assert.match(result,/输入背景/);assert.doesNotMatch(result,/逐句已引用/)
})
test('archived knowledge renders saved text and version without mutation actions',async()=>{
 detail=await server.ssrLoadModule('/src/components/results/SnapshotKnowledgeDetail.jsx')
 const result=renderToStaticMarkup(React.createElement(ToastProvider,null,React.createElement(detail.default,{initialTab:'sources',block:{entry_id:'e',title:'归档知识',archived:true,revision:4,content_sha256:'abc',claim:{text:'当时保存的公式解释'}}})))
 assert.match(result,/任务当时版本/);assert.match(result,/abc/)
 assert.doesNotMatch(result,/设为科研优选|编辑\/派生该理论|以报告内容派生/)
 assert.match(result,/查看当前知识库版本/)
})
test('summary exposes saved input background and original evidence without inventing citations',async()=>{
 const materialView=await server.ssrLoadModule('/src/components/results/MaterialWorkbench.jsx')
 assert.equal(typeof materialView.Summary,'function')
 const result=html(materialView.Summary,{scope:{taskId:'t',deliveryId:'d',revision:7},item:{group_id:'m',property_id:'p',summary:{state:'ready',text:'已保存总结',basis:{evidence:[{evidence_id:'ev',measurement_id:'m1'}],knowledge:[{entry_id:'e',title:'背景',claim:{text:'旧文本'}}]}}},readOnly:true})
 assert.match(result,/原文依据/);assert.match(result,/输入知识背景/);assert.match(result,/提供给生成模型的背景/)
 assert.doesNotMatch(result,/生成总结/)
})
test('knowledge context client pins revision and replay boundary and rejects a mismatched response',async()=>{
 assert.equal(typeof api.getTaskKnowledgeContext,'function')
 const original=globalThis.fetch,seen=[]
 globalThis.fetch=async(input)=>{seen.push(new URL(input,'http://local'));return new Response(JSON.stringify({delivery_id:'d',delivery_revision:7,snapshot_ref:{id:'s'},context:{entries:[]},origin:'task_snapshot'}))}
 try{
 const result=await api.getTaskKnowledgeContext('t','d',7,{atSeq:12,sealedOnly:true})
 assert.equal(result.context.entries.length,0)
 const query=seen[0].searchParams
 assert.equal(query.get('delivery_revision'),'7');assert.equal(query.get('expected_delivery_revision'),'7');assert.equal(query.get('at_seq'),'12');assert.equal(query.get('sealed_only'),'true')
 globalThis.fetch=async()=>new Response(JSON.stringify({delivery_id:'d',delivery_revision:8,context:{entries:[]}}))
 await assert.rejects(api.getTaskKnowledgeContext('other','d',7),/版本不一致/)
 }finally{globalThis.fetch=original}
})

test('all captured blocks of one entry remain readable under its exact property',async()=>{
 basis=await server.ssrLoadModule('/src/components/results/TaskKnowledgeBasis.jsx')
 const result=html(basis.KnowledgeBasisContent,{context:{entries:[{entry_id:'e',title:'同一知识',property_ids:['p'],claim:{claim_id:'a',text:'定义正文'}},{entry_id:'e',title:'同一知识',property_ids:['p'],claim:{claim_id:'b',text:'限制正文'}}],properties:[{property_id:'p',entry_ids:['e'],state:'matched'}]}})
 assert.match(result,/定义正文/);assert.match(result,/限制正文/);assert.match(result,/1 个去重知识条目/)
})
test('replay scope never offers summary generation even without a readOnly flag',async()=>{
 const materialView=await server.ssrLoadModule('/src/components/results/MaterialWorkbench.jsx')
 const result=html(materialView.Summary,{scope:{taskId:'t',deliveryId:'d',revision:7,atSeq:12},item:{group_id:'m',property_id:'p',summary:{state:'unavailable'}},readOnly:false})
 assert.doesNotMatch(result,/生成总结/)
})

test('bundle property cards cannot invent a benchmark or topology from a property name',async()=>{
 views=await server.ssrLoadModule('/src/components/results/TaskInsights.jsx')
 const result=html(views.default,{initialTab:'properties',report:{schema_version:'InsightBundle/1',material_report:material,property_report:{schema_version:'InsightReport/4',status:'partial',cards:[{card_id:'card',property_id:'stellar_mass',status:'partial',sections:{found:[{text:'文献保留了测量事实',measurement_ids:[],claim_ids:[]}],comparison:[],uses:[],limitations:[]},coverage:{target_record_count:1,contributing_source_count:1}}]}}})
 assert.match(result,/文献保留了测量事实/)
 assert.doesNotMatch(result,/推荐基准采纳值|开普勒质心摄动|天体物理拓扑网络|已收敛同行评议权威洞察/)
})

test('archive detail retains original nested source citations and user revision metadata',async()=>{
 detail=await server.ssrLoadModule('/src/components/results/SnapshotKnowledgeDetail.jsx')
 const result=renderToStaticMarkup(React.createElement(ToastProvider,null,React.createElement(detail.default,{initialTab:'sources',block:{entry_id:'e',title:'归档',archived:true,origin:'user_background',raw_entry:{revision:9,is_override:true},claim:{text:'原解释'},sources:[{source_id:'s',identity:{title:'当时的论文'},evidence:[{evidence_id:'ev',excerpt:'原文支持片段',locator:'第八页'}]}]}})))
 assert.match(result,/当时的论文/);assert.match(result,/原文支持片段/);assert.match(result,/第八页/);assert.match(result,/条目版本：9/);assert.match(result,/用户修改/)
})

test('archived detail identifies entry, release and task-context digests separately',async()=>{
 detail=await server.ssrLoadModule('/src/components/results/SnapshotKnowledgeDetail.jsx')
 const renderBlock=block=>renderToStaticMarkup(React.createElement(ToastProvider,null,React.createElement(detail.default,{initialTab:'sources',block:{entry_id:'entry',title:'归档',archived:true,claim:{text:'保存内容'},...block}})))
 const fallback=renderBlock({task_context_ref:{content_sha256:'context-only'}})
 assert.match(fallback,/任务上下文哈希：context-only/)
 assert.doesNotMatch(fallback,/条目内容哈希|内容哈希：context-only/)
 const complete=renderBlock({content_sha256:'entry-digest',release_ref:{content_sha256:'release-digest'},task_context_ref:{content_sha256:'context-digest'}})
 assert.match(complete,/条目内容哈希：entry-digest/);assert.match(complete,/知识发布哈希：release-digest/);assert.match(complete,/任务上下文哈希：context-digest/)
})
test('nested evidence record, source, material and page clients retain the same replay query',async()=>{
 const original=globalThis.fetch,seen=[]
 globalThis.fetch=async(input)=>{const url=new URL(input,'http://local');seen.push(url);const source=url.pathname.endsWith('/sources');return new Response(JSON.stringify({delivery_id:'d',delivery_revision:7,total:1,items:[source?{legacy_version:1,source_id:'s',title:'source'}:{legacy_version:1,record_id:'record',material_id:'material'}]}))}
 try{
 const options={atSeq:37,sealedOnly:true}
 await api.getRecord('replay-child','d',7,'record',options)
 await api.getSource('replay-child','d',7,'s',options)
 await api.getMaterial('replay-child','d',7,'material',options)
 await api.getRecordsPage('replay-child','d',7,{source_id:'s',offset:50},options)
 assert.equal(seen.length,4)
 for(const url of seen){assert.equal(url.searchParams.get('at_seq'),'37',url.pathname);assert.equal(url.searchParams.get('sealed_only'),'true',url.pathname);assert.equal(url.searchParams.get('delivery_revision'),'7');assert.equal(url.searchParams.get('expected_delivery_revision'),'7')}
 }finally{globalThis.fetch=original}
})

test('one entry retains only each propertys explicitly bound archived fragments and versions',async()=>{
 basis=await server.ssrLoadModule('/src/components/results/TaskKnowledgeBasis.jsx')
 const result=html(basis.KnowledgeBasisContent,{context:{entries:[
  {entry_id:'e',property_ids:['p1'],claim:{claim_id:'c',text:'OLD_P1_ONLY'}},
  {entry_id:'e',property_ids:['p2'],claim:{claim_id:'c',text:'NEW_P2_ONLY'}},
  {entry_id:'e',property_ids:['p1'],claim:{claim_id:'other',text:'SECOND_CLAIM_P1'}},
  {entry_id:'e',property_ids:['p1'],claim:{claim_id:'c',text:'SECOND_VERSION_P1'}},
 ],properties:[{property_id:'p1',name:'P1',entry_ids:['e']},{property_id:'p2',name:'P2',entry_ids:['e']}]}})
 const sections=[...result.matchAll(/<section class="task-knowledge-property"[^>]*>([\s\S]*?)<\/section>/g)].map(match=>match[1])
 assert.equal(sections.length,2)
 assert.match(sections[0],/OLD_P1_ONLY/);assert.match(sections[0],/SECOND_CLAIM_P1/);assert.match(sections[0],/SECOND_VERSION_P1/);assert.doesNotMatch(sections[0],/NEW_P2_ONLY/)
 assert.match(sections[1],/NEW_P2_ONLY/);assert.doesNotMatch(sections[1],/OLD_P1_ONLY|SECOND_CLAIM_P1|SECOND_VERSION_P1/)
 assert.match(result,/1 个去重知识条目 · 2 项性质有已保存背景/)
})
test('unbound or differently bound fragments remain ungrouped and cannot increase property coverage',async()=>{
 basis=await server.ssrLoadModule('/src/components/results/TaskKnowledgeBasis.jsx')
 const result=html(basis.KnowledgeBasisContent,{context:{entries:[
  {entry_id:'e',property_ids:['p1'],claim:{claim_id:'c1',text:'EXACT_BOUND'}},
  {entry_id:'e',claim:{claim_id:'unknown',text:'NO_EXPLICIT_BINDING'}},
  {entry_id:'e',property_ids:['unknown_property'],claim:{claim_id:'unknown2',text:'UNKNOWN_PROPERTY'}},
  {entry_id:'e',property_ids:['p1'],claim:{claim_id:'unlisted',text:'SAME_PROPERTY_OTHER_FRAGMENT'}},
 ],properties:[{property_id:'p1',name:'Same name',entry_ids:['e']},{property_id:'p2',name:'Same name',entry_ids:['e']}]}})
 const sections=[...result.matchAll(/<section class="task-knowledge-property"[^>]*>([\s\S]*?)<\/section>/g)].map(match=>match[1])
 assert.match(sections[0],/EXACT_BOUND|SAME_PROPERTY_OTHER_FRAGMENT/)
 assert.doesNotMatch(sections[0],/NO_EXPLICIT_BINDING|UNKNOWN_PROPERTY/)
 assert.doesNotMatch(sections[1],/EXACT_BOUND|SAME_PROPERTY_OTHER_FRAGMENT|NO_EXPLICIT_BINDING|UNKNOWN_PROPERTY/)
 assert.match(result,/1 个去重知识条目 · 1 项性质有已保存背景/)
 assert.equal((result.match(/NO_EXPLICIT_BINDING/g)||[]).length,1)
 assert.equal((result.match(/UNKNOWN_PROPERTY/g)||[]).length,1)
 assert.match(result,/未归入性质分组的已保存背景/)
})
