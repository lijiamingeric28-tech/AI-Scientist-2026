import test from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

test('the actual aggregated review exposes only the exact locked replay gate beside its continue button',async()=>{
 const server=await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'error'})
 try{
  const {default:Card}=await server.ssrLoadModule('/src/components/chat/AggregatedReviewCard.jsx')
  const review={review_id:'review-a',revision:2,basis_hash:'basis-a',status:'pending',question:'请核对原报测量。',choices:[{action:'confirm',label:'确认当前解释'}]}
  const gate={available:true,review_id:'review-a',review_revision:2,basis_hash:'basis-a',key:'review-a:2:100',answer:{action:'confirm'}}
  const render=g=>renderToStaticMarkup(React.createElement(Card,{taskId:'t',reviews:[review],readOnly:true,gate:g}))
  const html=render(gate)
  assert.match(html,/data-replay-gate="review-a:2:100"/)
  assert.match(html,/提交并继续回放/)
  assert.doesNotMatch(render({...gate,basis_hash:'other-basis'}),/data-replay-gate=|提交并继续回放/)
  assert.doesNotMatch(render({...gate,review_revision:1}),/data-replay-gate=|提交并继续回放/)
 }finally{await server.close()}
})
