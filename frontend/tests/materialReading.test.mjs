import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
let server,api,reading,analysis,DataView,ToastProvider
before(async()=>{
 server=await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'silent'})
 api=await server.ssrLoadModule('/src/services/api.js')
})
after(async()=>{await server?.close()})
const html=(Component,props)=>renderToStaticMarkup(React.createElement(Component,props))

test('data navigation removes independent insights and recovers old tab memory',async()=>{
 DataView=(await server.ssrLoadModule('/src/components/results/DataView.jsx')).default
 ToastProvider=(await server.ssrLoadModule('/src/components/ui/toast.jsx')).ToastProvider
 const resources=Object.fromEntries(['records','sources','sourceList','figures','quality','exports','materials','changes','insights','activity','differences','matrix','analysisRecords'].map(key=>[key,{status:'success',data:key==='quality'?null:[]}]))
 const result=renderToStaticMarkup(React.createElement(ToastProvider,null,React.createElement(DataView,{
  memory:{workbenchSection:'insights'},task:{task_id:'t',delivery_ref:{id:'d',version:2}},
  data:{availability:'complete',resources,ensure:()=>{},reload:()=>{}},pipeline:{presentation:{properties:[]}},onOpenDetail:()=>{}
 })))
 assert.doesNotMatch(result,/总结与洞察|总结与洞察分区/)
 assert.match(result,/数据结果分类/); assert.match(result,/性质对照/); assert.match(result,/测量记录/)
})

test('compact material identity keeps true scope and original links',async()=>{
 reading=await server.ssrLoadModule('/src/components/results/MaterialReading.jsx')
 const result=html(reading.MaterialIdentity,{scope:{taskId:'t'},item:{title:'Saved title',kind:'paper',
  material:{authors:['A','B','C','D'],year:2015,bibcode:'bib',artifact:{artifact_id:'pdf'}},
  record_count:322,figure_count:2,property_id:'p',property_name:'星等',
  available_properties:[{property_id:'p',name:'星等',record_count:322}]}})
 assert.match(result,/Saved title/);assert.match(result,/322/);assert.match(result,/查阅原件/)
 assert.doesNotMatch(result,/960|已收敛同行评议|权威模型/)
})

test('profile displays saved conditions and labels missing information',async()=>{
 reading=await server.ssrLoadModule('/src/components/results/MaterialReading.jsx')
 const result=html(reading.MaterialOverview,{profile:{record_count:2,material_record_count:5,units:['mag'],bands:[{value:'B'}],epochs:[],conditions:[],target:{main_id:'SN 2014J'}},item:{property_name:'视星等'}})
 assert.match(result,/SN 2014J/);assert.match(result,/mag/);assert.match(result,/B/);assert.match(result,/未记录/)
 assert.doesNotMatch(result,/高可信度基准/)
})

test('analysis values come from saved record and show exact provenance not a model numeric suggestion',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const report={scope:{kind:'material'},sections:{found:[{text:'原文观察',measurement_ids:['m'],evidence_ids:['e'],claim_ids:[]}]},
  recommendations:{benchmark:{measurement_id:'m',source_value:{value:{kind:'real',value:'2'},unit:'m'},
   source_uncertainty:{components:[{raw_text:'±0.1 m'}]},source:{title:'Saved source'},text:'依照原条件参考。',
   recommended_value:'FAKE 10.51',confidence_level:'not_assessed'},data_cleaning:[],application_guidance:[]},knowledge_blocks:[]}
 const result=html(analysis.MaterialAdvice,{report})
 assert.match(result,/2/);assert.match(result,/±0.1 m/);assert.match(result,/Saved source/)
 assert.doesNotMatch(result,/FAKE|10.51|高可信度/)
})

test('empty advice does not synthesize a benchmark or formula',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.MaterialAdvice,{report:{scope:{property_id:'stellar_mass'},recommendations:{}}})
 assert.doesNotMatch(result,/开普勒|Pogson|推荐基准|高可信度/)
 assert.match(result,/未保存/)
})

test('unreported reference conditions show one clear gap instead of repeated generic placeholders',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.MaterialAdvice,{report:{recommendations:{benchmark:{measurement_id:'m',
  source_value:{value:{kind:'real',value:'1'},unit:'mag'},conditions:[
   {key:'source_subject_and_measurand',state:'not_reported',value:null},
   {key:'source_method_model_and_context',state:'not_reported',value:null}]}}}})
 assert.match(result,/适用条件未记录/)
 assert.doesNotMatch(result,/见关联原文；见关联原文/)
})

test('unverified model advice remains visible without fabricated citation actions or numeric adoption',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.MaterialAdvice,{report:{recommendations:{},unverified_advice:[{section:'benchmark',text:'这一建议保留给用户核对。',verification:'needs_review',usable_as_measurement:false}]}})
 assert.match(result,/这一建议保留给用户核对/)
 assert.match(result,/待核对/)
 assert.doesNotMatch(result,/查阅测量|建议参考测量/)
})

test('reading-only controls preserve failed status without offering new model calls',async()=>{
 reading=await server.ssrLoadModule('/src/components/results/MaterialReading.jsx')
 const result=html(reading.AnalysisControls,{kind:'material',state:{value:{generation:{allowed:true},
  run:{status:'failed',reason:'timeout'},report:{status:'complete'},versions:[]}}})
 assert.match(result,/生成失败/); assert.doesNotMatch(result,/重试本资料解读/)
})

test('loading a saved reading does not temporarily claim that no report exists',async()=>{
 reading=await server.ssrLoadModule('/src/components/results/MaterialReading.jsx')
 const result=html(reading.AnalysisControls,{kind:'property_comparison',state:{loading:true}})
 assert.match(result,/正在读取已保存解读/)
 assert.match(result,/role="status"/)
 assert.doesNotMatch(result,/原资料总结|跨来源综合|生成本性质对照/)
})

test('reading navigation settles only after the requested report and earlier loading content are ready',async()=>{
 reading=await server.ssrLoadModule('/src/components/results/MaterialReading.jsx')
 assert.equal(reading.readingNavigationReady('comparison',{loading:true},{value:{report:{}}}),false)
 assert.equal(reading.readingNavigationReady('comparison',{loading:false},{value:{report:{}}}),true)
 assert.equal(reading.readingNavigationReady('comparison',{loading:false},{}),false)
 assert.equal(reading.readingNavigationReady('advice',{value:{report:{}}},{}),true)
})

test('reading coverage distinguishes a saved partial reading from complete scientific coverage',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.AnalysisCoverage,{report:{scope:{kind:'material'},status:'complete',
  generation_method:'saved_batch_and_summary',coverage:{requested_ids:['a','b','c'],completed_ids:['a','foreign']},
  knowledge_blocks:[{entry_id:'k'},{entry_id:'k'}]}})
 assert.match(result,/1\s*\/\s*3/)
 assert.match(result,/已读取记录范围/);assert.match(result,/不代表科学可信度/)
 assert.doesNotMatch(result,/全部完成|2\s*\/\s*3/)
})

test('structured reading preserves section scope and keeps only real evidence actions',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.AnalysisSections,{report:{scope:{kind:'property_comparison'},sections:{
  found:[{text:'跨来源事实',measurement_ids:['m1','m1'],claim_ids:['k1']}],
  comparison:[{text:'原报方法有差异'}],limitations:[{text:'不能直接合并'}]},
  knowledge_blocks:[{claim:{claim_id:'k1'},title:'准确知识依据'}]}})
 assert.match(result,/跨来源观察/);assert.match(result,/方法与条件/);assert.match(result,/适用边界/)
 assert.match(result,/reading-section-found/);assert.match(result,/准确知识依据/)
 assert.equal((result.match(/原文与测量 2/g)||[]).length,1)
 assert.doesNotMatch(result,/本资料观察|原文与测量 3/)
})

test('overview deduplicates repeated band values and identity uses saved DOI arrays',async()=>{
 reading=await server.ssrLoadModule('/src/components/results/MaterialReading.jsx')
 const result=html(reading.MaterialOverview,{profile:{bands:[{value:'B'},{value:'B'},{value:'V'}]}})
 assert.match(result,/B；V/);assert.doesNotMatch(result,/B；B/)
 const identity=html(reading.MaterialIdentity,{scope:{taskId:'t'},item:{material:{dois:['10.1/journal','10.48550/arxiv.1']}}})
 assert.doesNotMatch(identity,/doi.org/);assert.doesNotMatch(identity,/完整标识/)
})

test('analysis transport pins scope revision cutoff and version and never generates on GET',async()=>{
 const seen=[],original=globalThis.fetch
 globalThis.fetch=async(url,options={})=>{seen.push({url:new URL(url,'http://local'),options});return new Response(JSON.stringify({delivery_id:'d',delivery_revision:2,scope:{material_id:'m',property_id:'p',kind:'property_comparison'},versions:[]}))}
 try{
  assert.equal(typeof api.getMaterialAnalysis,'function')
  await api.getMaterialAnalysis({taskId:'t',deliveryId:'d',revision:2,atSeq:37,sealedOnly:true},{materialId:'m',propertyId:'p',kind:'property_comparison',reportVersion:3})
  const query=seen[0].url.searchParams
  assert.equal(query.get('delivery_revision'),'2');assert.equal(query.get('expected_delivery_revision'),'2')
  assert.equal(query.get('scope'),'property_comparison');assert.equal(query.get('report_version'),'3')
  assert.equal(query.get('at_seq'),'37');assert.equal(query.get('sealed_only'),'true')
  assert.equal(seen[0].options.method??'GET','GET')
 }finally{globalThis.fetch=original}
})


test('compact tips preserve the exact saved action, rationale and its explicit citation',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.MaterialAdvice,{report:{recommendations:{data_cleaning:[{rule:'Saved rule',action:'Do not combine the two filters',action_type:'exclude',text:'Their response differs',suggestion_only:true,measurement_ids:['m']}]}}})
 assert.match(result,/Do not combine the two filters/);assert.match(result,/Their response differs/);assert.match(result,/建议排除/)
})
test('long sections retain all paragraphs in a clearly labelled disclosure',async()=>{
 analysis=await server.ssrLoadModule('/src/components/results/MaterialAnalysisView.jsx')
 const result=html(analysis.AnalysisSections,{report:{sections:{found:[{text:'one'},{text:'two'},{text:'three'}]}}})
 assert.match(result,/节选 · 展开本节完整解读/);assert.match(result,/<details class="reading-section-more">/);assert.match(result,/three/)
})
test('snapshot drawer keeps the formula and complete frozen text without a current-library lookup',async()=>{
 const {default:Snapshot}=await server.ssrLoadModule('/src/components/results/SnapshotKnowledgeDetail.jsx')
 const result=html(Snapshot,{block:{entry_id:'e',claim:{text:'cited fragment'},raw_entry:{formula:'F=ma',description:'complete frozen body'}}})
 assert.match(result,/cited fragment/);assert.match(result,/complete frozen body/);assert.match(result,/katex/)
})
test('archived sources retain their original URL and supporting excerpt',async()=>{
 const {default:Snapshot}=await server.ssrLoadModule('/src/components/results/SnapshotKnowledgeDetail.jsx')
 const result=html(Snapshot,{initialTab:'sources',block:{sources:[{title:'Frozen source',url:'https://example.org/paper',support_note:'Saved support'}],claim:{text:'cited'}}})
 assert.match(result,/href="https:\/\/example.org\/paper"/);assert.match(result,/Saved support/)
})

test('opening the current library from a result remains explicitly distinct and read only',async()=>{
 const {default:Snapshot}=await server.ssrLoadModule('/src/components/results/SnapshotKnowledgeDetail.jsx')
 const result=html(Snapshot,{block:{current_library:true,archived:true,raw_entry:{description:'Current text'},claim:{text:'Current text'}}})
 assert.match(result,/当前知识库版本 · 只读/);assert.doesNotMatch(result,/任务当时版本|设为科研优选|编辑\/派生/)
})
