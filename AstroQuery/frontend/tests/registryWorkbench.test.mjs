import test from 'node:test'
import assert from 'node:assert/strict'

test('registry API preserves opaque keys, shared scope, versions and requires explicit write ACK', async () => {
  const { createRegistryApi } = await import('../src/services/registryApi.js')
  const calls = []
  const api = createRegistryApi(async (path, options) => { calls.push({path, options}); return { success:true, workspace:{id:'w',revision:3,status:'draft'} } })
  const controller = new AbortController()
  await api.detail('properties', 'mass|v1/a', {workspace_id:'w',keyword:'all'}, {signal:controller.signal})
  assert.equal(calls[0].path, '/registry-workbench/properties/mass%7Cv1%2Fa?workspace_id=w&keyword=all')
  assert.equal(calls[0].options.signal, controller.signal)
  await api.save('w', 'properties', 'mass|v1/a', {label:'质量'}, 2)
  assert.equal(calls[1].options.method, 'PUT')
  assert.deepEqual(JSON.parse(calls[1].options.body), {label:'质量', expected_revision:2})
  await api.remove('w', 'bindings', 'b/a', 3)
  assert.equal(calls[2].options.method, 'DELETE')
  assert.deepEqual(JSON.parse(calls[2].options.body), {expected_revision:3})
  for (const result of [{}, {success:false}, {success:'true'}]) await assert.rejects(createRegistryApi(async()=>result).createWorkspace(), /回执/)
})

test('registry publication forwards validation, active bundle guard and stable idempotency key', async () => {
  const { createRegistryApi } = await import('../src/services/registryApi.js')
  let request
  const api=createRegistryApi(async(path,options)=>{request={path,body:JSON.parse(options.body)};return {success:true}})
  await api.publish('draft/1',{expected_revision:7,validation_id:'v7',expected_active_bundle_id:'bundle-1',idempotency_key:'op-1'})
  assert.equal(request.path,'/registry-workbench/workspaces/draft%2F1/publish')
  assert.deepEqual(request.body,{expected_revision:7,validation_id:'v7',expected_active_bundle_id:'bundle-1',idempotency_key:'op-1'})
})

test('shared queries bound lists independently of graph budget and retain exact type/family/release scope', async () => {
  const { registryQuery, registryGraphQuery } = await import('../src/lib/registryWorkbench.js')
  const filters={keyword:'  mass  ',type_id:'type/*',family_id:'physics',origin:'user',status:'disabled',sort:'name',workspace_id:'w',release_id:'old',offset:50,limit:100}
  assert.deepEqual(registryQuery(filters,'cards'), {keyword:'mass',type_id:'type/*',family_id:'physics',origin:'user',status:'disabled',sort:'name',workspace_id:'w',release_id:'old',offset:50,limit:24})
  assert.equal(registryQuery(filters,'table').limit,100)
  assert.equal(registryQuery({keyword:'all'},'cards').keyword,'all')
  assert.deepEqual(registryGraphQuery(filters,{view:'property',focus_id:'exact-key'},200),{keyword:'mass',type_id:'type/*',family_id:'physics',origin:'user',status:'disabled',sort:'name',workspace_id:'w',release_id:'old',view:'property',focus_id:'exact-key',limit:200})
})

test('graph adapter preserves namespaced IDs, exact records and conditional edge identity', async () => {
  const { adaptRegistryGraph }=await import('../src/lib/registryWorkbench.js')
  const result=adaptRegistryGraph({nodes:[{id:'type:t',kind:'type',record_id:'t'},{id:'property:k1',kind:'property',property_id:'mass',record_id:'k1'},{id:'property:k2',kind:'property',property_id:'mass',record_id:'k2'}],edges:[{source:'type:t',target:'property:k2',relation_type:'conditional'}],meta:{view:'type'}})
  assert.deepEqual(result.nodes.map(n=>[n.id,n.kind,n.source_kind]),[['type:t','property','type'],['property:k1','entry','property'],['property:k2','entry','property']])
  assert.equal(result.edges[0].relation_type,'conditional')
})

test('form payloads protect standard code and scientific identity while keeping exact profiles', async () => {
  const { registryEditorValues, registryEditorPayload, registryWritable, registryLaunch } = await import('../src/lib/registryWorkbench.js')
  const type={id:'official:*',code:'*',origin:'builtin',label:'恒星',parent_id:null}
  const values=registryEditorValues('types',type)
  values.code='hack';values.label='恒星新称'
  const payload=registryEditorPayload('types',values,type)
  assert.equal(payload.code,undefined)
  assert.equal(payload.label,'恒星新称')
  const property={id:'key-1',property_id:'mass',definition:{quantity_key:'mass',subject_class_id:'star',scope:'whole_object',unit:{canonical_symbol:'kg'},metadata:{retained:true}},output_profiles:[{id:'p1',representation:{kind:'linear'},unit:{canonical_symbol:'kg'}}]}
  const pv=registryEditorValues('properties',property);pv.label='质量';pv.unit='g'
  assert.equal(registryEditorPayload('properties',pv,property).definition.quantity_key,'mass')
  assert.equal(registryEditorPayload('properties',pv,property).definition.metadata.retained,true)
  assert.equal(registryEditorPayload('properties',pv,property).output_profiles[0].unit.canonical_symbol,'g')
  assert.equal(registryWritable({view:'draft',workspace:{id:'w',status:'draft'}},false,false),true)
  assert.equal(registryWritable({view:'published',workspace:null},false,false),false)
  assert.equal(registryWritable({view:'draft',workspace:{id:'w',status:'draft'}},true,false),false)
  assert.deepEqual(registryLaunch('#settings=registry'),{tab:'registry',studioMode:'registry'})
})

test('publication eligibility expires after writes and failed/stale validation cannot publish', async () => {
  const { canPublishRegistry, registryEditorPayload, registryEditorValues }=await import('../src/lib/registryWorkbench.js')
  const summary={view:'draft',workspace:{id:'w',status:'draft',revision:8}}
  assert.equal(canPublishRegistry(summary,{id:'v',state:'passed',workspace_revision:8},false,false),true)
  assert.equal(canPublishRegistry(summary,{id:'v',state:'passed',workspace_revision:7},false,false),false)
  assert.equal(canPublishRegistry(summary,{id:'v',state:'failed',workspace_revision:8},false,false),false)
  const item={id:'key',definition:{quantity_key:'mass',subject_class_id:'star',scope:'whole_object',value_schema:{kind:'real'}},output_profiles:[{id:'p',object_scale_id:'star',conversion_policy_ref:{id:'identity',version:'1',content_sha256:'exact'},unit:{canonical_symbol:'kg'},representation:{kind:'linear'}}]}
  const values=registryEditorValues('properties',item)
  values.subject_class_id='galaxy';values.quantity_key='distance';values.scale_id='star'
  const payload=registryEditorPayload('properties',values,item)
  assert.equal(payload.definition.subject_class_id,'star')
  assert.equal(payload.definition.quantity_key,'mass')
  assert.deepEqual(payload.output_profiles[0].conversion_policy_ref,{id:'identity',version:'1',content_sha256:'exact'})
})

test('registry grouped editor renders protected standard code, custom parent choices and scientific identity locks', async () => {
  const {createServer}=await import('vite')
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  try {
    const {default:React}=await import('react')
    const {renderToStaticMarkup}=await import('react-dom/server')
    const {default:Editor}=await server.ssrLoadModule('/src/components/registry/RegistryEditor.jsx')
    const props={kind:'types',types:[{id:'official-star',label:'恒星',code:'*'}],families:[],capabilities:{},onSave:()=>{},onClose:()=>{}}
    const official=renderToStaticMarkup(React.createElement(Editor,{...props,item:{id:'official-star',origin:'builtin',code:'*',label:'恒星'}}))
    assert.match(official,/<input[^>]*name="code"[^>]*disabled/)
    const custom=renderToStaticMarkup(React.createElement(Editor,{...props,item:{}}))
    assert.match(custom,/<select[^>]*name="parent_id"[^>]*required/)
    assert.match(custom,/<option value="official-star">/)
    const property=renderToStaticMarkup(React.createElement(Editor,{...props,kind:'properties',item:{id:'exact-key',definition:{quantity_key:'mass',subject_class_id:'star'},output_profiles:[]}}))
    assert.match(property,/<input[^>]*name="quantity_key"[^>]*disabled/)
    assert.match(property,/当前来源没有输出方案/)
    assert.equal((property.match(/<fieldset/g)||[]).length,5)
    const binding=renderToStaticMarkup(React.createElement(Editor,{...props,kind:'bindings',item:{id:'binding',property_key:'exact',type_id:'official-star',profile_ref:{id:'same',version:2,content_sha256:'second'}},properties:[{id:'exact',output_profiles:[{profile_id:'same',version:1,content_sha256:'first'},{profile_id:'same',version:2,content_sha256:'second'}]}]}))
    assert.match(binding,/为当前类型自定义输出配置/)
    assert.match(binding,/<option value="[^\"]*second[^\"]*" selected="">/)
  } finally {await server.close()}
})

test('record browser exposes both exact property variants and detail separates shared edits from type binding', async () => {
  const {createServer}=await import('vite');const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  try {
    const {default:React}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server')
    const {RegistryRecords,RegistryDetail}=await server.ssrLoadModule('/src/components/registry/RegistryWorkspace.jsx')
    const items=[{id:'exact-a',kind:'property',property_id:'mass',label:'质量 A'},{id:'exact-b',kind:'property',property_id:'mass',label:'质量 B'}]
    const markup=renderToStaticMarkup(React.createElement(RegistryRecords,{items,kind:'properties',mode:'cards',onSelect:()=>{}}))
    assert.match(markup,/exact-a/);assert.match(markup,/exact-b/);assert.match(markup,/质量 A/);assert.match(markup,/质量 B/)
    const detail=renderToStaticMarkup(React.createElement(RegistryDetail,{kind:'properties',item:{...items[0],bindings:[{id:'binding-1',type_id:'type-1',status:'active',conditions:['单星']}],knowledge_links:[{entry_id:'theory-1',title:'理论一',compatibility:'suspended',reason:'定义发生变化'}]},writable:true,onClose:()=>{},onEdit:()=>{},onImpact:()=>{},onKnowledge:()=>{}}))
    assert.match(detail,/编辑共享定义/);assert.match(detail,/编辑当前类型绑定/);assert.match(detail,/定义发生变化/)
  } finally {await server.close()}
})

test('canonical editor preserves profile reference identity and represents parser and logarithmic references explicitly', async()=>{
  const {registryEditorValues,registryEditorPayload,registryProfileRef}=await import('../src/lib/registryWorkbench.js')
  const item={id:'exact',definition:{description:'原始定义',quantity_key:'mass',subject_class_id:'star'},output_profiles:[{profile_id:'profile-exact',version:2,content_sha256:'abc',unit:{kind:'physical',canonical_symbol:'K',dimension:'temperature',parser_format:'generic',parser_version:'7'},representation:{kind:'log10',scale:'2',offset:'1',reference_value:'1',reference_unit:'K'}}]}
  const values=registryEditorValues('properties',item)
  assert.equal(values.description,'原始定义')
  assert.equal(values.representation_scale,'2')
  values.description='新定义';values.reference_unit='mK'
  const payload=registryEditorPayload('properties',values,item)
  assert.equal(payload.definition.description,'新定义')
  assert.equal(payload.output_profiles[0].unit.parser_version,'7')
  assert.equal(payload.output_profiles[0].representation.reference_unit,'mK')
  assert.deepEqual(registryProfileRef(item.output_profiles[0]),{id:'profile-exact',version:2,content_sha256:'abc'})
})

test('binding editor roundtrips structured condition data without splitting its commas',async()=>{
  const {registryEditorValues,registryEditorPayload}=await import('../src/lib/registryWorkbench.js')
  const item={id:'binding',conditions:[{key:'subject',value:'star',operator:'eq'}],excluded_conditions:['未解析来源条件'],definition_ref:{id:'d',version:1,content_sha256:'hash'},profile_ref:{id:'p',version:1,content_sha256:'hash'}}
  const payload=registryEditorPayload('bindings',registryEditorValues('bindings',item),item)
  assert.deepEqual(payload.conditions,[{key:'subject',value:'star',operator:'eq'}])
  assert.deepEqual(payload.excluded_conditions,['未解析来源条件'])
})

test('registry bounded cache reuses same scope, deduplicates pending reads and never caches cancelled search',async()=>{
  const {createRegistryReadCache}=await import('../src/lib/registryWorkbench.js')
  const cache=createRegistryReadCache(2);let calls=0,resolve
  const controller=new AbortController()
  const first=cache.read('summary:published',()=>{calls++;return new Promise(r=>resolve=r)},controller.signal)
  const duplicate=cache.read('summary:published',()=>{throw new Error('duplicate request')},controller.signal)
  resolve({revision:1});await Promise.all([first,duplicate]);assert.equal(calls,1)
  assert.deepEqual(await cache.read('summary:published',()=>{throw new Error('unneeded fetch')}),{revision:1})
  const cancelled=new AbortController();cancelled.abort()
  await cache.read('search:old',async()=>({revision:0}),cancelled.signal)
  assert.equal(cache.peek('search:old'),undefined)
  await cache.read('list:page1',async()=>[1]);await cache.read('list:page2',async()=>[2])
  assert.equal(cache.peek('summary:published'),undefined)
  cache.clear();assert.equal(cache.peek('list:page1'),undefined)
})

test('backend canonical DTO excludes server-owned fields, normalizes policy refs and displays failed validation receipts',async()=>{
  const {registryEditorValues,registryEditorPayload,normalizeRegistryCapabilities,registryCondition}=await import('../src/lib/registryWorkbench.js')
  const {createRegistryApi}=await import('../src/services/registryApi.js')
  const values=registryEditorValues('properties',{});values.label='自定义';values.coordinate_meaning='来源坐标'
  const payload=registryEditorPayload('properties',values,{})
  assert.equal(Object.hasOwn(payload,'property_id'),false)
  assert.equal(Object.hasOwn(payload.output_profiles[0],'output_coordinate_meaning'),false)
  const binding=registryEditorPayload('bindings',registryEditorValues('bindings',{}),{definition_ref:{id:'server-derived'}})
  assert.equal(Object.hasOwn(binding,'definition_ref'),false)
  const normalized=normalizeRegistryCapabilities({conversion_policies:[{policy_id:'policy-exact',version:2,content_sha256:'abc'}]})
  assert.deepEqual(normalized.conversion_policies[0].ref,{id:'policy-exact',version:2,content_sha256:'abc'})
  assert.deepEqual(registryCondition('subject_class','star',true),{not:{subject_class:'star'}})
  const failed={success:false,validation:{id:'v',state:'failed',workspace_revision:1,errors:[{message:'invalid'}]}}
  assert.deepEqual(await createRegistryApi(async()=>failed).validate('w',1),failed)
  await assert.rejects(createRegistryApi(async()=>({success:false})).validate('w',1),/回执/)
})

test('new category and relation definitions retain explicit value schema and magnitude system references',async()=>{
  const {registryEditorValues,registryEditorPayload}=await import('../src/lib/registryWorkbench.js')
  const values=registryEditorValues('properties',{});Object.assign(values,{value_kind:'category',categories:'A=甲类\nB=乙类',representation_kind:'magnitude',system_id:'ab-system',system_version:'2',system_hash:'exact'})
  let payload=registryEditorPayload('properties',values,{})
  assert.deepEqual(payload.definition.value_schema,{kind:'category',categories:{A:'甲类',B:'乙类'}})
  assert.deepEqual(payload.output_profiles[0].representation.system_ref,{id:'ab-system',version:'2',content_sha256:'exact'})
  Object.assign(values,{value_kind:'relation',predicate_id:'associated_with',subject_role:'primary',object_role:'companion'})
  payload=registryEditorPayload('properties',values,{})
  assert.deepEqual(payload.definition.value_schema,{kind:'relation',predicate_id:'associated_with',subject_role:'primary',object_role:'companion'})
})

test('formal knowledge links use the registry source and preserve original author basis labels',async()=>{
  const {createRegistryApi}=await import('../src/services/registryApi.js')
  let path;await createRegistryApi(async p=>{path=p;return {entry:{}}}).knowledge('formal/333',{workspace_id:'draft'})
  assert.equal(path,'/registry-workbench/knowledge/formal%2F333?workspace_id=draft')
  const {createServer}=await import('vite');const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  try{
    const {default:React}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server')
    const {RegistryKnowledgeCard}=await server.ssrLoadModule('/src/components/registry/RegistryWorkspace.jsx')
    const html=renderToStaticMarkup(React.createElement(RegistryKnowledgeCard,{result:{entry:{entry_id:'formal',title:'原始作者标题',blocks:[{role:'statement',text:'原始作者陈述',basis:'author_knowledge',source_ids:[]},{role:'limitation',text:'来源核对陈述',basis:'source_checked',source_ids:['source-1']}],conditions:[{text:'原始适用条件'}],limitations_zh:'原始局限'},compatibility:[{state:'suspended',reason:'精确定义已变化'}],sources:[]}}))
    const visible=html.split('<details class="rwb-technical"')[0]
    for(const text of ['原始作者标题','原始作者陈述','author_knowledge','source_checked','原始适用条件','原始局限','精确定义已变化'])assert.ok(visible.includes(text),text)
  }finally{await server.close()}
})

test('activation retries reuse a token only until ACK, so later A to B cycles perform a new activation',async()=>{
  const {createRegistryOperationTokens}=await import('../src/lib/registryWorkbench.js')
  let next=0;const tokens=createRegistryOperationTokens(()=>`operation-${++next}`)
  assert.equal(tokens.get('activate:B:A'),'operation-1')
  assert.equal(tokens.get('activate:B:A'),'operation-1')
  tokens.ack('activate:B:A')
  assert.equal(tokens.get('activate:A:B'),'operation-2');tokens.ack('activate:A:B')
  assert.equal(tokens.get('activate:B:A'),'operation-3')
})

test('binding profile selection distinguishes duplicate IDs by full version and hash and keeps overrides type scoped',async()=>{
  const {registryProfileKey,registryBindingProfile,registryEditorValues,registryOutputProfile}=await import('../src/lib/registryWorkbench.js')
  const first={profile_id:'same-profile',version:1,content_sha256:'first',unit:{kind:'physical',canonical_symbol:'m',dimension:'length',parser_format:'generic',parser_version:'1'},representation:{kind:'linear'}},second={...first,version:2,content_sha256:'second',unit:{...first.unit,canonical_symbol:'km'}}
  const ref={id:'same-profile',version:2,content_sha256:'second'}
  const values=registryEditorValues('bindings',{profile_ref:ref})
  assert.equal(values.profile_id,registryProfileKey(second))
  assert.deepEqual(registryBindingProfile({output_profiles:[first,second]},values.profile_id,ref),ref)
  assert.notEqual(registryProfileKey(first),registryProfileKey(second))
  const overrideValues=registryEditorValues('properties',{output_profiles:[second]});overrideValues.unit='cm'
  const override=registryOutputProfile(overrideValues,second)
  assert.equal(override.unit.canonical_symbol,'cm');assert.equal(second.unit.canonical_symbol,'km')
  assert.equal(override.profile_id,'same-profile')
})

test('display label and search alias edits leave existing scientific definition content exact',async()=>{
  const {registryEditorValues,registryEditorPayload}=await import('../src/lib/registryWorkbench.js')
  const definition={name_cn:'科学原名',aliases:['来源别名'],description:'科学原定义',family_id:'family',quantity_key:'mass',subject_class_id:'star'}
  const item={id:'exact',label:'显示名称',description:'科学原定义',aliases:['显示别名'],family_id:'family',definition,output_profiles:[]}
  const values=registryEditorValues('properties',item);values.label='新显示名称';values.aliases='新检索别名'
  const payload=registryEditorPayload('properties',values,item)
  assert.deepEqual(payload.definition,definition)
  assert.deepEqual(payload.output_profiles,[])
  assert.equal(payload.label,'新显示名称');assert.deepEqual(payload.aliases,['新检索别名'])
})

test('clearing a current-type output override explicitly removes it and returns to a shared exact profile',async()=>{
  const {registryEditorValues,registryEditorPayload}=await import('../src/lib/registryWorkbench.js')
  const item={id:'binding',property_key:'exact',profile_ref:{id:'custom',version:1,content_sha256:'custom'},output_profile:{profile_id:'custom',version:1,unit:{canonical_symbol:'cm'}}}
  const values=registryEditorValues('bindings',item);values.custom_output=false
  const payload=registryEditorPayload('bindings',values,item)
  assert.equal(Object.hasOwn(payload,'output_profile'),true)
  assert.equal(payload.output_profile,null)
  const reopened=registryEditorValues('bindings',{...item,output_profile:null})
  assert.equal(reopened.custom_output,false)
})

test('editor dismissal retains modified inputs after failures and blocks dismissal during writes',async()=>{
  const {registryEditorValues,registryEditorCloseAction}=await import('../src/lib/registryWorkbench.js')
  const initial=registryEditorValues('types',{id:'user_type_a',origin:'user',label:'原始名称'})
  assert.equal(registryEditorCloseAction(initial,initial,false),'close')
  const changed={...initial,label:'未保存名称',source_note:'写盘失败后保留的依据'}
  assert.equal(registryEditorCloseAction(changed,initial,false),'confirm')
  assert.equal(registryEditorCloseAction(changed,initial,true),'blocked')
  assert.equal(registryEditorCloseAction(initial,initial,true),'blocked')
  assert.equal(registryEditorCloseAction({...initial,display_order:'0',create_profile:false},initial,false),'close')
})

test('inline discard notice exposes continue and explicit discard controls, disabled while saving',async()=>{
  const {createServer}=await import('vite');const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  try{
    const {default:React}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server')
    const {RegistryDiscardNotice}=await server.ssrLoadModule('/src/components/registry/RegistryEditor.jsx')
    const props={onContinue:()=>{},onDiscard:()=>{}}
    const html=renderToStaticMarkup(React.createElement(RegistryDiscardNotice,props))
    assert.match(html,/未保存修改/);assert.match(html,/继续编辑/);assert.match(html,/放弃未保存修改/)
    const busyHtml=renderToStaticMarkup(React.createElement(RegistryDiscardNotice,{...props,busy:true}))
    assert.equal((busyHtml.match(/disabled=""/g)||[]).length,2)
  }finally{await server.close()}
})

test('scientific selectors visibly distinguish canonical IDs even when source descriptions are identical',async()=>{
  const {createServer}=await import('vite');const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  try{
    const {default:React}=await import('react');const {renderToStaticMarkup}=await import('react-dom/server')
    const {default:Editor}=await server.ssrLoadModule('/src/components/registry/RegistryEditor.jsx')
    const html=renderToStaticMarkup(React.createElement(Editor,{kind:'properties',item:{},types:[],families:[],capabilities:{subjects:[{id:'subject-one',label:'相同主体说明'},{id:'subject-two',label:'相同主体说明'}],scales:[{id:'scale-one',label:'相同尺度说明'},{id:'scale-two',label:'相同尺度说明'}],conversion_policies:[{policy_id:'policy-one',version:1,content_sha256:'one',description:'Identity is scientifically allowed'},{policy_id:'policy-two',version:1,content_sha256:'two',description:'Identity is scientifically allowed'}]},onSave:()=>{},onClose:()=>{}}))
    for(const id of ['subject-one','subject-two','scale-one','scale-two'])assert.match(html,new RegExp(`<option value="${id}">${id} · `))
    for(const id of ['policy-one','policy-two'])assert.match(html,new RegExp(`>${id} · v1 · `))
    const first={policy_id:'same-policy',version:1,content_sha256:'first',description:'相同策略说明'},second={policy_id:'same-policy',version:2,content_sha256:'second',description:'相同策略说明'}
    const duplicateHtml=renderToStaticMarkup(React.createElement(Editor,{kind:'properties',item:{id:'exact',output_profiles:[{conversion_policy_ref:{id:'same-policy',version:2,content_sha256:'second'}}]},types:[],families:[],capabilities:{conversion_policies:[first,second,{...second}]},onSave:()=>{},onClose:()=>{}}))
    assert.equal((duplicateHtml.match(/>same-policy · v2 · second/g)||[]).length,1)
    assert.match(duplicateHtml,/<option value="[^\"]*second[^\"]*" selected="">same-policy · v2 · second/)
  }finally{await server.close()}
})

test('editor catalog ignores browsing filters, shares scoped cache, and never falls back to a different version',async()=>{
  const {createRegistryReadCache,readRegistryEditorCatalog}=await import('../src/lib/registryWorkbench.js')
  const cache=createRegistryReadCache(),calls=[]
  await cache.read('summary:{"workspace_id":"w","keyword":"隔离验证长度"}',async()=>({types:[],families:[]}))
  const catalog={types:[{id:'official',label:'标准锚点'}],families:[{id:'all-family',label:'全部分类'}],capabilities:{subjects:[{id:'subject'}]}}
  const api={summary:async(query,options)=>{calls.push({query,signal:options.signal});if(query.release_id==='different')throw new Error('当前历史目录不可读');return catalog}}
  const controller=new AbortController()
  const actual=await readRegistryEditorCatalog(api,cache,{workspace_id:'w',keyword:'隔离验证长度',type_id:'filtered',family_id:'filtered',origin:'user'},controller.signal)
  assert.deepEqual(calls[0].query,{workspace_id:'w',projection:'full'});assert.equal(calls[0].signal,controller.signal)
  assert.deepEqual(actual,catalog)
  assert.deepEqual(await readRegistryEditorCatalog(api,cache,{workspace_id:'w'},controller.signal),catalog)
  assert.equal(calls.length,1)
  await assert.rejects(readRegistryEditorCatalog(api,cache,{release_id:'different'},controller.signal),/当前历史目录不可读/)
})

test('conversion policies retain duplicate IDs by exact reference, dedupe exact repeats and select the current exact policy',async()=>{
  const {normalizeRegistryCapabilities,registryEditorValues,registryProfileKey}=await import('../src/lib/registryWorkbench.js')
  const first={policy_id:'same-policy',version:1,content_sha256:'first',description:'来源允许恒等转换'},second={policy_id:'same-policy',version:2,content_sha256:'second',description:'来源允许恒等转换'}
  const policies=normalizeRegistryCapabilities({conversion_policies:[first,second,{...second}]}).conversion_policies
  assert.equal(policies.length,2)
  assert.notEqual(policies[0].id,policies[1].id)
  assert.deepEqual(policies[1].ref,{id:'same-policy',version:2,content_sha256:'second'})
  const values=registryEditorValues('properties',{id:'exact',output_profiles:[{conversion_policy_ref:{id:'same-policy',version:2,content_sha256:'second'}}]})
  assert.equal(values.conversion_policy,registryProfileKey(policies[1].ref))
  assert.deepEqual(policies.find(p=>p.id===values.conversion_policy).ref,{id:'same-policy',version:2,content_sha256:'second'})
  assert.match(policies[1].label,/same-policy.*v2.*second/)
})
