import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
let server,Composer
before(async()=>{
 server=await createServer({server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom',logLevel:'silent'})
 Composer=(await server.ssrLoadModule('/src/components/chat/QueryComposer.jsx')).default
})
after(async()=>{await server?.close()})
const html=props=>renderToStaticMarkup(React.createElement(Composer,{textarea:{current:null},value:'A research question',onChange:()=>{},onSubmit:()=>{},...props}))
test('homepage composer puts retrieval settings behind the shared star, without a second input row',()=>{
 const value=html({mode:'new',preferenceControls:React.createElement('div',null,'Retrieval options')})
 assert.match(value,/aria-label="检索与对话选项"/)
 assert.match(value,/class="research-composer-shell"/)
 assert.doesNotMatch(value,/research-composer-preferences|Retrieval options/)
 assert.match(value,/aria-expanded="false"/)
})
test('contextual followup uses the same capsule and keeps its selection outside the shell',()=>{
 const value=html({mode:'followup',canSwitch:true,selectionCount:2,preferenceSummary:'每项 20 篇 · 相关度优先'})
 assert.match(value,/aria-label="检索与对话选项"/)
 assert.doesNotMatch(value,/research-plus-toggle/)
 assert.match(value,/title="对话选项"/)
 assert.ok(value.indexOf('research-composer-context')<value.indexOf('research-composer-shell'))
 assert.match(value,/2 项选中内容/)
 assert.match(value,/清除追问对象/)
 assert.match(value,/max[Ll]ength="12000"/)
 assert.match(value,/发送追问/)
})
test('a running answer keeps the stop action and a disabled query cannot submit',()=>{
 assert.match(html({mode:'followup',busy:true}),/停止生成/)
 assert.match(html({mode:'new',disabled:true}),/type="submit" disabled=""/)
})

test('options fit below the homepage and above a bottom composer without viewport overflow',async()=>{
 const {composerPopoverPosition}=await server.ssrLoadModule('/src/components/chat/QueryComposer.jsx')
 const low=composerPopoverPosition({left:500,top:700,bottom:740},{width:1024,height:768},230)
 assert.ok(low.top<700);assert.ok(low.left+low.width<=1012)
 const high=composerPopoverPosition({left:20,top:260,bottom:300},{width:1440,height:900},230)
 assert.equal(high.top,310)
 const small=composerPopoverPosition({left:900,top:10,bottom:48},{width:1024,height:768},300)
 assert.ok(small.left>=12);assert.ok(small.left+small.width<=1012)
})
