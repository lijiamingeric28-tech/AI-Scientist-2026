import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
let server,views
before(async()=>{
  server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom',logLevel:'error'})
  views=await server.ssrLoadModule('/src/components/results/DataView.jsx')
})
after(async()=>{await server?.close()})
test('new material-summary reports expose summary coverage instead of an empty legacy insight message',()=>{
  assert.equal(typeof views.MaterialSummaryOverview,'function')
  const html=renderToStaticMarkup(React.createElement(views.MaterialSummaryOverview,{
    report:{schema_version:'MaterialSummaryReport/1',status:'partial',counts:{p:{requested:7,ready:4,failed:2,bibliography:1}}},
    properties:[{property_id:'p',name:'合成性质'}],onOpenProperty:()=>{},
  }))
  assert.match(html,/合成性质/);assert.match(html,/4/);assert.match(html,/7/)
  assert.match(html,/浏览资料/);assert.doesNotMatch(html,/本次没有已保存的洞察报告/)
})
test('new report without ready summaries states its saved reason and retains the material navigation',()=>{
  assert.equal(typeof views.MaterialSummaryOverview,'function')
  const html=renderToStaticMarkup(React.createElement(views.MaterialSummaryOverview,{
    report:{schema_version:'MaterialSummaryReport/1',status:'pending',reason:'等待资料处理',counts:{}},onOpenProperty:()=>{},
  }))
  assert.match(html,/等待资料处理/);assert.match(html,/浏览资料/)
})
