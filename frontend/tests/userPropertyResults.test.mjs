import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {createServer} from 'vite'

let server,Measurement
before(async()=>{
  server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom',logLevel:'error'})
  Measurement=(await server.ssrLoadModule('/src/components/results/RuntimeMeasurement.jsx')).default
})
after(async()=>{await server?.close()})

const record=(code='user_numeric_examples_required_native_retained')=>({
  property_binding:{display_name:'用户定义直径',definition:{name_cn:'自定义直径',description:'用户声明的来源直径定义'},output_profile:{representation:{kind:'linear'}}},
  source:{task_id:'isolated',raw_value:'2',unit:'km',uncertainty:{components:[{component_id:'error',role:'unspecified',raw_text:'±0.1',values:{delta:'0.1'},interpretation_state:'parsed'}]}},
  field_value:'2',field_unit:'km',derived:{main_state:'not_run',issues:[{code}]},context:{conditions:[]},evidence:[],
})

test('user-defined result without reviewed explanation remains readable with original values and uncertainty',()=>{
  const html=renderToStaticMarkup(React.createElement(Measurement,{record:record()}))
  assert.match(html,/用户定义直径/)
  assert.match(html,/用户声明的来源直径定义/)
  assert.match(html,/原报值：2 km/)
  assert.match(html,/原报误差坐标单位：km/)
  assert.match(html,/±0.1/)
})

test('native-only result explains missing validation instead of hiding the conversion reason',()=>{
  const value=record();value.property_binding.definition.explanation={quantity:'来源原量'}
  value.derived.issues[0].message='原始数据已保留'
  const html=renderToStaticMarkup(React.createElement(Measurement,{record:value}))
  assert.match(html,/未转换原因/)
  assert.match(html,/尚无通过的转换样例/)
  assert.match(html,/原报值：2 km/)
})

test('unknown logarithmic source basis is explained without claiming a canonical conversion',()=>{
  const value=record('user_source_representation_reference_unresolved');value.property_binding.definition.explanation={quantity:'来源原量'}
  const html=renderToStaticMarkup(React.createElement(Measurement,{record:value}))
  assert.match(html,/来源.*对数.*基准/)
  assert.doesNotMatch(html,/主值：已完成处理/)
})

test('source outside logarithmic transform domain keeps its signed original value with an actionable reason',()=>{
  const value=record('TRANSFORM_DOMAIN');value.source.raw_value='-2';value.field_value='-2'
  value.derived.issues[0].message='原始数据已保留'
  const html=renderToStaticMarkup(React.createElement(Measurement,{record:value}))
  assert.match(html,/对数.*有效取值/)
  assert.match(html,/原报值：-2 km/)
})
