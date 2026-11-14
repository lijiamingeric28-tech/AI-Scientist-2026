import test,{before,after} from 'node:test'
import assert from 'node:assert/strict'
import {createServer} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
let server,DataView,ContextDrawer,ToastProvider
before(async()=>{
  server=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom',logLevel:'error'})
  DataView=(await server.ssrLoadModule('/src/components/results/DataView.jsx')).default
  ContextDrawer=(await server.ssrLoadModule('/src/components/layout/ContextDrawer.jsx')).default
  ToastProvider=(await server.ssrLoadModule('/src/components/ui/toast.jsx')).ToastProvider
})
after(async()=>{await server?.close()})
const resources=()=>Object.fromEntries(['records','sources','sourceList','figures','quality','exports','materials','changes','insights','activity','differences','matrix','analysisRecords'].map(key=>[key,{status:'success',data:key==='quality'?null:[]}]))
test('cancelled scientific tasks continue to identify their preserved partial results',()=>{
  const task={task_id:'t',status:'cancelled',delivery_ref:{id:'d',version:1}}
  const html=renderToStaticMarkup(React.createElement(ToastProvider,null,React.createElement(DataView,{
    memory:{workbenchSection:'details'},task,data:{taskId:'t',deliveryId:'d',deliveryRevision:1,availability:'partial',resources:resources(),ensure:()=>{},reload:()=>{}},
    pipeline:{taskDone:true,stages:[],presentation:{properties:[]}},onOpenDetail:()=>{},
  })))
  assert.match(html,/任务未完成/);assert.match(html,/部分结果/)
})

test('legacy archives retain the qualification that they were not rechecked under newer scientific rules',()=>{
  const task={task_id:'t',legacy_version:1,status:'completed',delivery_ref:{id:'d',version:1}}
  const html=renderToStaticMarkup(React.createElement(ToastProvider,null,React.createElement(DataView,{
    memory:{workbenchSection:'details'},task,data:{taskId:'t',deliveryId:'d',deliveryRevision:1,availability:'complete',resources:resources(),ensure:()=>{},reload:()=>{}},
    pipeline:{taskDone:true,stages:[],presentation:{properties:[]}},onOpenDetail:()=>{},
  })))
  assert.match(html,/旧版历史/);assert.match(html,/未按新科学规则复检/)
})
test('the figure drawer retains upstream selection with both checked and unchecked states',()=>{
  for(const checked of [false,true]){
    const html=renderToStaticMarkup(React.createElement(ContextDrawer,{
      detail:{type:'figure',figure:{figure_id:'f',source_id:'s',caption:'合成图像'}},
      data:{taskId:'t',deliveryId:'d',deliveryRevision:1,resources:resources()},pipeline:{stages:[]},onClose:()=>{},onChange:()=>{},
      selection:{has:()=>checked,toggle:()=>{}},
    }))
    assert.match(html,new RegExp(checked?'取消选择':'选择图像'))
    assert.match(html,new RegExp(`aria-pressed="${checked}"`))
  }
})
