import React from 'react'
import {createRoot} from 'react-dom/client'
import {usePipeline} from '../src/hooks/usePipeline'
const status=document.getElementById('status'),fixture=document.getElementById('fixture'),root=createRoot(fixture)
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
let done=0,updates=0,reads=0
const nativeFetch=window.fetch
window.fetch=async input=>{
 const url=new URL(String(input),location.href);const id=url.pathname.split('/')[3]
 if(!url.pathname.endsWith('/state')||url.searchParams.get('view')!=='workspace')throw Error('Unexpected request '+url)
 reads++
 return new Response(JSON.stringify({task_id:id,kind:'normal',revision:1,lifecycle:'completed',status:'completed',core_event_cursor:1,
  presentation:{task_id:id,cursor:1,latest_cursor:1,historical:false,lifecycle:'completed',properties:[],stages:[],messages:[]}}),{headers:{'Content-Type':'application/json'}})
}
function Probe({task}){
 const pipeline=usePipeline(task,{conversation:false,onTaskDone:()=>done++,onTaskUpdate:()=>updates++})
 return <output data-task={task.task_id}>{pipeline.taskDone?'completed':'loading'}</output>
}
const checks=[]
async function run(){
 for(const [n,task,expected] of [
  ['opening a completed sample from an unknown placeholder does not announce a new completion',{task_id:'initial-placeholder'},0],
  ['a known running task still announces its actual completion',{task_id:'known-running',status:'running'},1],
  ['a newly created task with lifecycle-only state still announces completion',{task_id:'created',lifecycle:'queued'},1],
  ['a known completed task does not refresh history again',{task_id:'known-done',status:'completed'},0],
 ]){
  done=0;updates=0;reads=0;root.render(<Probe key={task.task_id} task={task}/>);
  for(let i=0;i<100&&fixture.querySelector(`[data-task="${task.task_id}"]`)?.textContent!=='completed';i++)await pause(10)
  await pause(20)
  if(fixture.textContent!=='completed'||done!==expected||updates!==1||reads!==1)throw Error(`${n}: done=${done},updates=${updates},reads=${reads}`)
  checks.push(n)
 }
 status.textContent=`PASS ${checks.length}\n${checks.join('\n')}`
}
run().catch(e=>status.textContent=`FAIL ${e.message}\n${checks.join('\n')}`).finally(()=>{root.unmount();window.fetch=nativeFetch})
