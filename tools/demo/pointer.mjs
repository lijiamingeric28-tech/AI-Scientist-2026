// Demo-only overlay: it never modifies the application's theme or saved settings.
export function installDemoPointer(){
 const install=()=>{
  if(document.getElementById('demo-cursor'))return
  const style=document.createElement('style')
  style.textContent=`html,body,body *{cursor:none!important}
   #demo-cursor{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate3d(-100px,-100px,0);width:25px;height:34px}
   #demo-cursor .demo-halo{position:absolute;left:-22px;top:-21px;width:62px;height:62px;background:radial-gradient(ellipse,rgba(48,144,255,.38),rgba(48,144,255,.16) 32%,rgba(48,144,255,0) 70%)}
   #demo-cursor svg{position:relative;width:25px;height:34px;overflow:visible;filter:drop-shadow(0 1px 1px #0005) drop-shadow(0 0 5px #58a6ff99);transform-origin:1px 1px}
   .demo-click-light{position:fixed;pointer-events:none;z-index:2147483646;width:56px;height:56px;margin:-28px;background:radial-gradient(ellipse,#58a6ff55,transparent 68%)}
  `
  document.head.append(style)
  const cursor=document.createElement('div');cursor.id='demo-cursor';cursor.setAttribute('aria-hidden','true')
  cursor.innerHTML='<span class="demo-halo"></span><svg viewBox="0 0 25 34"><path d="M1 1 L1 25 L7.6 19.2 L12.8 31 L17.2 29 L12 17.6 L21.4 17.6 Z" fill="#111111" stroke="#ffffff" stroke-width="1.4" stroke-linejoin="round"/></svg>'
  document.body.append(cursor)
  document.addEventListener('pointermove',e=>{cursor.style.transform=`translate3d(${e.clientX-1}px,${e.clientY-1}px,0)`},{passive:true})
  document.addEventListener('pointerdown',e=>{
   cursor.querySelector('svg').animate([{transform:'scale(1)'},{transform:'scale(.9)'},{transform:'scale(1)'}],{duration:230})
   const light=document.createElement('div');light.className='demo-click-light';light.style.left=e.clientX+'px';light.style.top=e.clientY+'px';document.body.append(light)
   light.animate([{opacity:.85,transform:'scale(.65)'},{opacity:0,transform:'scale(1.5)'}],{duration:450}).finished.finally(()=>light.remove())
  },{passive:true})
 }
 document.readyState==='loading'?document.addEventListener('DOMContentLoaded',install,{once:true}):install()
}
