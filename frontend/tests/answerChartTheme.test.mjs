import test from 'node:test'
import assert from 'node:assert/strict'
const module = await import('../src/lib/answerChartTheme.js').catch(()=>({}))
test('answer charts use resolved system colors including custom palettes without CSS color-mix',()=>{
  assert.equal(typeof module.readAnswerChartTheme,'function')
  const theme=module.readAnswerChartTheme({getPropertyValue:key=>({'color':'rgb(11, 22, 33)','background-color':'rgb(44, 55, 66)','border-top-color':'rgb(77, 88, 99)','outline-color':'rgb(100, 110, 120)','font-family':'Demo Serif'}[key]||'')})
  assert.deepEqual(theme,{ink:'rgb(11, 22, 33)',paper:'rgb(44, 55, 66)',line:'rgb(77, 88, 99)',accent:'rgb(100, 110, 120)',font:'Demo Serif'})
})
