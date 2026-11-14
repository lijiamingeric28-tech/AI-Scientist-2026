import test from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {createServer} from 'vite'

test('execution examples survive editor round trips with exact decimal literals and representation references',async()=>{
  const {registryEditorValues,registryEditorPayload,registryEditorCloseAction}=await import('../src/lib/registryWorkbench.js')
  const example={label:'原值换算',source_value:'1.234567890123456789e-9',source_unit:'m',
    source_representation:{kind:'linear',scale:'1',offset:'0'},expected_value:'1.234567890123456789e-12',
    profile_ref:{id:'output',version:2,content_sha256:'a'.repeat(64)}}
  const item={id:'user',label:'用户长度',definition:{description:'用户定义',family_id:'length'},output_profiles:[],execution_examples:[example]}
  const initial=registryEditorValues('properties',item)
  assert.deepEqual(JSON.parse(initial.execution_examples),[example])
  assert.deepEqual(registryEditorPayload('properties',initial,item).execution_examples,[example])
  const removed={...initial,execution_examples:'[]'}
  assert.equal(registryEditorCloseAction(removed,initial),'confirm')
  assert.deepEqual(registryEditorPayload('properties',removed,item).execution_examples,[])
})

test('invalid execution examples remain editable and are rejected before save without decimal rounding',async()=>{
  const {parseExecutionExamples}=await import('../src/lib/registryExecution.js')
  assert.throws(()=>parseExecutionExamples('{'),/验证样例/)
  assert.throws(()=>parseExecutionExamples(JSON.stringify([{source_value:'1',source_unit:'m',source_representation:{kind:'linear'},expected_value:''}])) ,/预期/)
  assert.throws(()=>parseExecutionExamples(JSON.stringify([{source_value:'NaN',source_unit:'m',source_representation:{kind:'linear'},expected_value:'1'}])),/来源值/)
  const result=parseExecutionExamples('[{"source_value":"1e-30","source_unit":"m","source_representation":{"kind":"linear"},"expected_value":"1e-33"}]')
  assert.equal(result[0].expected_value,'1e-33')
})

test('capabilities distinguish extraction from conversion and obey server readiness over legacy flags',async()=>{
  const {executionCapabilityRows,executionCapabilityText}=await import('../src/lib/registryExecution.js')
  const capability={schema_version:'user-property-capabilities/1',origin:'user_defined',
    retrieval:{ready:true,reasons:[]},extraction:{ready:true,reasons:[]},native:{ready:true,reasons:[]},
    normalization:{ready:false,reasons:['尚未验证转换样例']},validation:{state:'pending',checks:[],examples:[]}}
  assert.deepEqual(executionCapabilityRows(capability).map(r=>r.ready),[true,true,true,false])
  assert.match(executionCapabilityText(capability,true),/可提取，保留原值/)
  assert.doesNotMatch(executionCapabilityText(capability,true),/可自动规范化/)
  assert.match(executionCapabilityText(null,true),/原有精确范围/)
})

test('only new properties default to the explicit server-declared user conversion policy',async()=>{
  const {normalizeRegistryCapabilities,registryDefaultUserPolicy}=await import('../src/lib/registryWorkbench.js')
  const capabilities=normalizeRegistryCapabilities({user_execution_protocol:'user-property-execution/1',conversion_policies:[
    {policy_id:'source-policy',version:1,content_sha256:'source'},
    {policy_id:'user-declared-same-quantity',version:1,content_sha256:'user',user_declared:true}]})
  assert.equal(registryDefaultUserPolicy({},capabilities,''),capabilities.conversion_policies[1].id)
  assert.equal(registryDefaultUserPolicy({id:'existing'},capabilities,''),'')
  assert.equal(registryDefaultUserPolicy({},capabilities,'chosen-source'),'chosen-source')
  assert.equal(registryDefaultUserPolicy({},{} ,''),'')
})

test('execution reading and examples reuse workbench form controls with honest technical validation labels',async()=>{
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom',logLevel:'error'})
  try{
    const {RegistryExecutionStatus,RegistryExecutionExamples,RegistryExecutionReport,RegistryPublishReview}=await server.ssrLoadModule('/src/components/registry/RegistryExecution.jsx')
    const capabilities={origin:'user_defined',retrieval:{ready:true},extraction:{ready:true},native:{ready:true},normalization:{ready:false,reasons:['尚未验证转换样例']},validation:{state:'pending',checks:[{code:'typed_definition',state:'passed'}],examples:[{label:'唯一的样例名称',state:'passed',actual_value:'1',expected_value:'1'}]}}
    const status=renderToStaticMarkup(React.createElement(RegistryExecutionStatus,{capabilities}))
    for(const label of ['检索','提取','原值保留','规范化','尚未验证转换样例','用户定义'])assert.match(status,new RegExp(label))
    assert.match(status,/技术验证/)
    assert.match(status,/定义与输出结构校验/)
    assert.doesNotMatch(status,/typed_definition/)
    assert.equal((status.match(/唯一的样例名称/g)||[]).length,1)
    const output={profile_id:'type-output',version:2,content_sha256:'a'.repeat(64),unit:{canonical_symbol:'km'}}
    const html=renderToStaticMarkup(React.createElement(RegistryExecutionExamples,{value:JSON.stringify([{label:'长度样例',source_value:'1000',source_unit:'m',source_representation:{kind:'linear'},expected_value:'1',profile_ref:{id:output.profile_id,version:output.version,content_sha256:output.content_sha256}}]),profiles:[output],onChange:()=>{},busy:true,targetUnit:'km'}))
    for(const label of ['来源值','来源单位','预期输出值','添加验证样例','移除样例'])assert.match(html,new RegExp(label))
    assert.match(html,/value="1000"/)
    assert.match(html,/disabled=""/)
    assert.doesNotMatch(html,/type="number"/)
    assert.match(html,/样例目标输出方案/)
    assert.match(html,/<option value="[^\"]*type-output[^\"]*" selected="">/)
    const report=renderToStaticMarkup(React.createElement(RegistryExecutionReport,{report:{manifest:{contracts:{}},properties:{custom:{...capabilities,label:'自定义直径'},builtin:{...capabilities,origin:'builtin',label:'内置原量'}}}}))
    assert.match(report,/自定义直径/)
    assert.doesNotMatch(report,/内置原量/)
    assert.match(report,/执行清单引用/)
    const many=Object.fromEntries(Array.from({length:3000},(_,index)=>['builtin-'+index,{...capabilities,origin:'builtin',label:'HEAVY_BUILTIN_'+index}]))
    const published=renderToStaticMarkup(React.createElement(RegistryPublishReview,{workspace:{id:'draft',revision:3},validation:{state:'passed',workspace_revision:3,knowledge_coverage:{available:100,missing:1},execution:{properties:{...many,custom:{...capabilities,label:'自定义直径'}},manifest:{schema_version:'user-property-execution/1',contracts:{one:{reference:{id:'exact-contract',version:1,content_sha256:'a'},contract:{huge:'HIDDEN_EXECUTION_SOURCE_CONTENT'}}}}}},activeBundle:{id:'current'}}))
    assert.ok(published.length<18000)
    assert.match(published,/草稿修订/)
    assert.doesNotMatch(published,/HEAVY_BUILTIN_|HIDDEN_EXECUTION_SOURCE_CONTENT/)
  }finally{await server.close()}
})

test('workbench cards and detail show native-only capability without claiming an unavailable property',async()=>{
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom',logLevel:'error'})
  try{
    const {RegistryRecords,RegistryDetail}=await server.ssrLoadModule('/src/components/registry/RegistryWorkspace.jsx')
    const {default:Editor}=await server.ssrLoadModule('/src/components/registry/RegistryEditor.jsx')
    const capability={origin:'user_defined',retrieval:{ready:true},extraction:{ready:true},native:{ready:true},normalization:{ready:false,reasons:['尚未验证转换样例']},validation:{state:'pending'}}
    const item={id:'user-length',kind:'property',label:'用户直径',definition:{description:'用户定义的整体直径'},execution_capabilities:capability,automatic_conversion_ready:false}
    const cards=renderToStaticMarkup(React.createElement(RegistryRecords,{items:[item],onSelect:()=>{}}))
    assert.match(cards,/可提取，保留原值/)
    assert.doesNotMatch(cards,/自动转换未就绪/)
    const detail=renderToStaticMarkup(React.createElement(RegistryDetail,{kind:'properties',item,onClose:()=>{},onEdit:()=>{},onImpact:()=>{},onKnowledge:()=>{}}))
    assert.match(detail,/输出方案与处理能力/)
    assert.match(detail,/尚未验证转换样例/)
    const editor=renderToStaticMarkup(React.createElement(Editor,{kind:'properties',capabilities:{user_execution_protocol:'user-property-execution/1'},onSave:()=>{},onClose:()=>{}}))
    assert.match(editor,/处理与验证/)
    assert.match(editor,/添加验证样例/)
    assert.doesNotMatch(editor,/此版本沿用原有执行范围/)
    const ready=renderToStaticMarkup(React.createElement(Editor,{kind:'properties',item:{...item,execution_capabilities:{...capability,origin:'builtin',normalization:{ready:true}},output_profiles:[{unit:{kind:'physical',canonical_symbol:'m'},representation:{kind:'linear'}}]},capabilities:{user_execution_protocol:'user-property-execution/1'},onSave:()=>{},onClose:()=>{}}))
    assert.match(ready,/可自动规范化/)
    assert.doesNotMatch(ready,/用户定义 \/ 自动转换未就绪/)
  }finally{await server.close()}
})
