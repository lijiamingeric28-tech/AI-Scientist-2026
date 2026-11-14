import test from 'node:test'
import assert from 'node:assert/strict'

test('floating back-to-top starts at its scroll container bottom right and clamps dragging',async()=>{
  const {backToTopPosition}=await import('../src/lib/backToTopPosition.js')
  const bounds={left:280,top:120,right:1280,bottom:720},viewport={width:1280,height:720},button={width:110,height:38}
  assert.deepEqual(backToTopPosition(bounds,viewport,button),{x:1158,y:670})
  assert.deepEqual(backToTopPosition(bounds,viewport,button,{x:-999,y:-999}),{x:292,y:132})
  assert.deepEqual(backToTopPosition(bounds,viewport,button,{x:2000,y:2000}),{x:1158,y:670})
})

test('floating button stays on screen after viewport and sidebar changes',async()=>{
  const {backToTopPosition}=await import('../src/lib/backToTopPosition.js')
  assert.deepEqual(backToTopPosition({left:-100,top:80,right:2000,bottom:1000},{width:1024,height:600},{width:110,height:38},{x:1400,y:900}),{x:902,y:550})
})
