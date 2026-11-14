import fs from 'node:fs/promises'
import path from 'node:path'
import {createRequire} from 'node:module'
import {fileURLToPath} from 'node:url'
import {spawn,execFileSync} from 'node:child_process'
import {subtitles,stamp} from './timeline.mjs'
import {needsNavigation,pointerMotion} from './pacing.mjs'
import {createScenes} from './scenes.mjs'
import {installDemoPointer} from './pointer.mjs'
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'../..')
const require=createRequire(path.join(root,'frontend/package.json'))
const {chromium}=require('playwright')
const arg=(name,fallback)=>{const i=process.argv.indexOf('--'+name);return i<0?fallback:process.argv[i+1]}
const mode=arg('mode','present'),chapter=arg('chapter',''),base=arg('url','http://127.0.0.1:5173')
const task='827c01d6-0a9a-4e3e-bba8-db6a3aa3f5b5',taskUrl=`${base}/#task=${task}&view=data`
const output=path.resolve(arg('output',path.join(root,'scratch/demo-tour-v2-2026-11-14',`${mode}${chapter?'-'+chapter:''}`)))
const allShots=JSON.parse(await fs.readFile(path.join(here,'shots.json'),'utf8'))
const from=arg('from',''),fromIndex=from?allShots.findIndex(s=>s.id===from):0
if(fromIndex<0)throw Error('Unknown --from chapter')
const shots=allShots.slice(fromIndex).filter(s=>!chapter||s.id===chapter)
if(!['rehearse','present'].includes(mode)||!shots.length)throw Error('Use --mode present|rehearse and an existing --chapter')
try{const ready=await fetch(base+'/api/config');if(!ready.ok)throw Error(String(ready.status))}
catch{throw Error('请先启动前端5173和后端8781，再运行自动演示。使用说明见 tools/demo/README.md。')}
await fs.mkdir(output,{recursive:true})
await fs.writeFile(path.join(output,'complete.srt'),subtitles(shots))
await fs.writeFile(path.join(output,'edit-86s.srt'),subtitles(shots,'edit'))
const net=await import('node:net')
const debugPort=await new Promise(resolve=>{const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const p=server.address().port;server.close(()=>resolve(p))})})
const python=path.join(root,'.venv/Scripts/python.exe')
const windowTitle=`AstroQuery AI · 第二版${mode==='present'?'应用演示':'演示彩排'}${chapter?' · '+chapter:''}`
const host=spawn(python,[path.join(here,'native_host.py'),'--url',base,'--debug-port',String(debugPort),'--profile',path.join(output,'native-profile'),'--title',windowTitle],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']})
let hostStopped=false,hostError
const stopHost=()=>{if(hostStopped)return;hostStopped=true;if(host.pid&&host.exitCode===null)try{execFileSync('taskkill',['/PID',String(host.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'})}catch{}}
// This synchronous exit guard also covers errors before CDP setup.
process.once('exit',stopHost)
process.once('SIGINT',()=>{stopHost();process.exit(130)})
process.once('SIGTERM',()=>{stopHost();process.exit(143)})
host.once('error',e=>{hostError=e})
const hostLog=[];host.stderr.on('data',d=>hostLog.push(d.toString()))
host.stdout.on('data',()=>{})
let endpoint
for(let i=0;i<150;i++){
 try{const r=await fetch(`http://127.0.0.1:${debugPort}/json/version`);if(r.ok){endpoint=`http://127.0.0.1:${debugPort}`;break}}catch{}
 if(hostError||host.exitCode!==null)throw Error('Native WebView2 failed: '+(hostError?.message||hostLog.join('')))
 await new Promise(resolve=>setTimeout(resolve,200))
}
if(!endpoint)throw Error('Native WebView2 automation endpoint did not start')
const browser=await chromium.connectOverCDP(endpoint)
const context=browser.contexts()[0]
let page
for(let i=0;i<100;i++){page=context.pages().find(p=>p.url().startsWith(base));if(page)break;await new Promise(resolve=>setTimeout(resolve,100))}
if(!page)throw Error('No AstroQuery page in the native application')
await page.bringToFront()
const requests=[],steps=[],errors=[]
page.setDefaultTimeout(90000)
page.on('pageerror',e=>errors.push(e.message))
await page.route('**/api/**',async route=>{
 const r=route.request(),u=new URL(r.url())
 requests.push({method:r.method(),path:u.pathname})
 if(!['GET','HEAD','OPTIONS'].includes(r.method())&&!u.pathname.endsWith('/replay')&&!u.pathname.endsWith('/exports/preview')){
   errors.push(`Prevented recording write: ${r.method()} ${u.pathname}`);return route.abort()
 }
 return route.continue()
})
await page.addInitScript(installDemoPointer)
const b=(name)=>page.getByRole('button',{name,exact:true})
const pause=ms=>page.waitForTimeout(mode==='rehearse'?Math.min(ms,120):ms)
let pointer={x:60,y:60},currentShot,origin=0
const beats=[],navigation=[]
async function move(x,y,{drag=false}={}){
 const target={x,y}
 if(Math.hypot(x-pointer.x,y-pointer.y)<1)return
 if(mode==='rehearse')await page.mouse.move(x,y,{steps:6})
 else if(drag){
  for(const p of pointerMotion(pointer,target)){await page.mouse.move(p.x,p.y);await new Promise(resolve=>setTimeout(resolve,12))}
 }else{
  // Animate the demonstration arrow in one renderer operation. Sending two
  // protocol messages per frame made V1-style mouse travel dominate the tour.
  await page.evaluate(({from,to})=>{
   document.getElementById('demo-cursor')?.animate([
    {transform:`translate3d(${from.x-1}px,${from.y-1}px,0)`},
    {transform:`translate3d(${to.x-1}px,${to.y-1}px,0)`}
   ],{duration:280,easing:'cubic-bezier(.4,0,.2,1)'})
  },{from:pointer,to:target})
  await page.mouse.move(x,y,{steps:6});await new Promise(resolve=>setTimeout(resolve,280))
 }
 pointer=target
}
async function reveal(locator,{block='center',force=false}={}){
 await locator.waitFor({state:'visible'})
 const moved=await locator.evaluate((el,{block,force,behavior})=>{
  const r=el.getBoundingClientRect()
  let top=100,bottom=innerHeight-28,left=0,right=innerWidth
  for(let parent=el.parentElement;parent;parent=parent.parentElement){
   const css=getComputedStyle(parent)
   if(/auto|scroll|hidden/.test(css.overflowY)){const b=parent.getBoundingClientRect();top=Math.max(top,b.top+12);bottom=Math.min(bottom,b.bottom-12)}
   if(/auto|scroll|hidden/.test(css.overflowX)){const b=parent.getBoundingClientRect();left=Math.max(left,b.left);right=Math.min(right,b.right)}
  }
  if(!force&&r.top>=top&&r.bottom<=bottom&&r.left>=left&&r.right<=right)return false
  el.scrollIntoView({block,behavior,inline:'nearest'});return true
 },{block,force,behavior:mode==='present'?'smooth':'instant'})
 if(moved)await pause(650)
}
async function click(locator){
 await reveal(locator)
 const box=await locator.boundingBox();if(box)await move(box.x+box.width/2,box.y+box.height/2)
 await pause(90);await locator.click();await pause(100)
}
async function choose(locator,value){
 await reveal(locator)
 const wanted=typeof value==='string'?value:await locator.locator('option').filter({hasText:value.label}).first().getAttribute('value')
 if(await locator.inputValue()===wanted)return
 const box=await locator.boundingBox();if(box)await move(box.x+box.width*.7,box.y+box.height/2)
 await pause(130);await locator.selectOption(value);await pause(220)
}
async function selectTab(locator,options={}){
 await locator.waitFor({state:'visible'})
 const state=await locator.evaluate(el=>({current:el.getAttribute('aria-current'),selected:el.getAttribute('aria-selected'),pressed:el.getAttribute('aria-pressed'),active:el.classList.contains('active')}))
 if(needsNavigation({...state,...options})){navigation.push({scene:currentShot?.id,label:(await locator.innerText()).trim()});await click(locator)}
}
async function read(name,locator){
 if(locator)await reveal(locator,{block:'start',force:true})
 const seconds=currentShot.beats[name]
 if(!seconds)throw Error(`Missing reading beat ${currentShot.id}.${name}`)
 const size=await page.evaluate(()=>({width:innerWidth,height:innerHeight}))
 await move(size.width-35,size.height-52)
 const start=(performance.now()-origin)/1000
 console.log(`  READ ${currentShot.id}.${name} ${seconds}s`)
 await pause(seconds*1000)
 beats.push({scene:currentShot.id,beat:name,start,end:(performance.now()-origin)/1000,seconds})
 if(process.argv.includes('--beat-screenshots'))await page.screenshot({path:path.join(output,`${currentShot.id}-${name}.png`)})
}
async function closeDrawer(){const drawer=page.locator('.context-drawer');if(await drawer.isVisible()){await click(drawer.getByRole('button',{name:/^关闭/}).first());await drawer.waitFor({state:'hidden'})}}
async function returnToSettings(){
 await closeDrawer()
 if(await page.locator('.kr-drawer-backdrop').isVisible()){await click(b('关闭详情'));await page.locator('.kr-drawer-backdrop').waitFor({state:'hidden'})}
 if(await page.locator('.rwb-detail-overlay').isVisible()){await click(b('关闭记录详情'));await page.locator('.rwb-detail-overlay').waitFor({state:'hidden'})}
 const back=page.getByRole('button',{name:/返回设置/}).filter({visible:true}).first()
 if(await back.isVisible())await click(back)
}
async function taskView(name){
 if(await page.locator('.settings-overlay:visible').count()){
  await returnToSettings();await click(b('关闭设置'));await page.locator('.settings-overlay').waitFor({state:'hidden'})
 }
 await closeDrawer()
 if(!page.url().includes(task))await page.goto(taskUrl)
 await page.getByRole('heading',{name:'SN 2014J',exact:true}).waitFor()
 await selectTab(page.getByRole('navigation',{name:'任务主页面'}).getByRole('button',{name,exact:true}))
 if(name==='数据结果')await b('数据').waitFor()
}
async function settings(){
 await returnToSettings()
 if(!await page.locator('.settings-overlay:visible').count()){
  const button=b('系统设置');if(!await button.isVisible())await click(b('展开侧栏'));await click(button)
 }
 await b('知识库与图谱').waitFor();await page.getByText('正在读取服务配置…',{exact:true}).waitFor({state:'hidden'})
}
async function navData(name){await taskView('数据结果');await selectTab(page.getByRole('navigation',{name:'数据结果分类'}).getByRole('button',{name,exact:true}),{returnToDirectory:name==='资料'&&await b('本篇解读').isVisible()})}
const scene=createScenes({page,b,base,task,click,choose,selectTab,read,pause,move,reveal,taskView,navData,settings,closeDrawer,steps})

let failed
const first=shots[0].id
await page.goto(['home','gallery','replay'].includes(first)?base:`${base}/#task=${task}&view=${first==='execution'?'workflow':first==='followup'?'chat':'data'}`)
await b('新建科研查询').waitFor()
// Native host already loaded the app before CDP attached. A hash-only goto
// does not run init scripts, so also install on this current document.
await page.evaluate(installDemoPointer)
await fs.writeFile(path.join(output,'session.json'),JSON.stringify({version:2,endpoint,mode,chapters:shots.map(s=>s.id)},null,2))
if(mode==='present'){
 const countdown=Math.max(0,Number(arg('countdown','5'))||0)
 console.log(`READY V2: 内嵌窗口已准备，${countdown} 秒后开始；脚本只演示，不录制视频。`)
 await page.waitForTimeout(countdown*1000)
}
origin=performance.now()
try{
 for(const shot of shots){
  currentShot=shot
  console.log(`START ${shot.id}`)
  const start=(performance.now()-origin)/1000
  await scene[shot.id]()
  const actionSeconds=(performance.now()-origin)/1000-start
  const end=(performance.now()-origin)/1000
  await page.screenshot({path:path.join(output,`${shot.id}.png`)})
  steps.push({id:shot.id,start,end,actionSeconds,target:shot.seconds,edit:shot.edit})
  await fs.writeFile(path.join(output,'timings.json'),JSON.stringify(steps,null,2))
  await fs.writeFile(path.join(output,'beats.json'),JSON.stringify(beats,null,2))
  await fs.writeFile(path.join(output,'navigation.json'),JSON.stringify(navigation,null,2))
  const completed=steps.filter(s=>s.id)
  await fs.writeFile(path.join(output,'actual.srt'),completed.map((s,i)=>`${i+1}\n${stamp(s.start)} --> ${stamp(s.end)}\n${allShots.find(shot=>shot.id===s.id).caption}\n`).join('\n'))
  console.log(`DONE ${shot.id} ${(end-start).toFixed(1)}s`)
 }
}catch(e){failed=e;await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});console.error(e.stack)}
finally{
 try{
  await fs.writeFile(path.join(output,'requests.json'),JSON.stringify(requests,null,2))
  await fs.writeFile(path.join(output,'errors.json'),JSON.stringify(errors,null,2))
  await fs.writeFile(path.join(output,'native-host.log'),hostLog.join(''))
  if(!failed&&mode==='present'&&!process.argv.includes('--exit-on-finish')){
   console.log('演示完成。窗口保留供自行查阅；关闭窗口或按 Ctrl+C 结束。')
   await new Promise(resolve=>{if(host.exitCode!==null)resolve();else host.once('exit',resolve)})
  }
 }finally{stopHost();await browser.close().catch(()=>{})}
}
if(failed)throw failed
if(errors.some(e=>e.startsWith('Prevented')))throw Error('Unexpected write attempted; see errors.json')
