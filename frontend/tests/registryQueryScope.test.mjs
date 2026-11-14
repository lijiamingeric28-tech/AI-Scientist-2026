import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let server, Scope
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr:false }, appType: 'custom', logLevel: 'error' })
  Scope = (await server.ssrLoadModule('/src/components/chat/RegistryQueryScope.jsx')).default
})
after(async () => { await server?.close() })

test('custom subtype is a separate user choice with original external type visible', () => {
  const html = renderToStaticMarkup(React.createElement(Scope, { draft: {
    target: { primary_otype: 'G' }, registry_bundle: { id: 'bundle_first', registry_ref: { id: 'registry_first' } },
  }, question: { user_type_choices: [{ id: 'user_type_1', label: '自定义低表面亮度星系' }],
    user_type_ref: { id: 'user_type_1' }, capability_gaps: [{ property_id: 'user_property_1', label: '用户附加长度', automatic_execution_ready: false }] },
    submit: () => {} }))
  assert.match(html, /SIMBAD 原始类型：G/)
  assert.match(html, /用户指定子类/)
  assert.match(html, /value="user_type_1" selected/)
  assert.match(html, /自动处理未就绪/)
  assert.match(html, /用户附加长度/)
  assert.doesNotMatch(html, /user_property_1/)
  assert.match(html, /暂不进入自动检索和转换/)
  assert.match(html, /升级规范并重新确认/)
})

test('legacy query without version bundle or subtype choices retains uncluttered confirmation', () => {
  assert.equal(renderToStaticMarkup(React.createElement(Scope, {
    draft: { target: { primary_otype: '*' } }, question: {}, submit: () => {},
  })), '')
})

test('native-only user property remains selectable and explains the concrete conversion limitation',()=>{
  const capability={schema_version:'user-property-capabilities/1',origin:'user_defined',retrieval:{ready:true},extraction:{ready:true},native:{ready:true},normalization:{ready:false,reasons:['尚未验证转换样例']}}
  const html=renderToStaticMarkup(React.createElement(Scope,{draft:{target:{primary_otype:'G'}},
    question:{property_catalog:{bindings:[{property_id:'custom',display_name:'用户直径',execution_capabilities:capability}]}},submit:()=>{}}))
  assert.match(html,/用户直径/)
  assert.match(html,/可提取，保留原值/)
  assert.match(html,/尚未验证转换样例/)
  assert.doesNotMatch(html,/暂不进入自动检索和转换/)
})
