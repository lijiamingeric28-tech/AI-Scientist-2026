import test from 'node:test'
import assert from 'node:assert/strict'

const graphTheme = await import('../src/lib/graphTheme.js').catch(() => ({}))
const style = values => ({ getPropertyValue: key => values[key] || '' })

test('canvas theme reads current system tokens including custom palette and contrast surfaces', () => {
  assert.equal(typeof graphTheme.readGraphTheme, 'function')
  const palette=graphTheme.readGraphTheme(style({'--seed-accent':'rgb(80, 30, 130)','--surface-canvas':'rgb(15, 20, 25)',
    '--surface-card':'rgb(30, 35, 40)','--text-primary':'rgb(240, 245, 250)','--border-default':'rgb(150, 160, 170)',
    '--reference-text':'rgb(170, 100, 40)','--seed-aux':'rgb(40, 130, 140)','--font-ui':'Custom Serif'}))
  assert.deepEqual(palette,{accent:'rgb(80, 30, 130)',bg:'rgb(15, 20, 25)',surface:'rgb(30, 35, 40)',ink:'rgb(240, 245, 250)',
    line:'rgb(150, 160, 170)',gold:'rgb(170, 100, 40)',aux:'rgb(40, 130, 140)',font:'Custom Serif'})
})

test('category colors stay stable for an ID but respond to changed system seeds', () => {
  assert.equal(typeof graphTheme.graphCategoryColor,'function')
  const first=graphTheme.readGraphTheme(style({'--seed-accent':'#112233','--seed-aux':'#8899aa'}))
  const second=graphTheme.readGraphTheme(style({'--seed-accent':'#991122','--seed-aux':'#22aa44'}))
  assert.equal(graphTheme.graphCategoryColor('stellar',first),graphTheme.graphCategoryColor('stellar',first))
  assert.notEqual(graphTheme.graphCategoryColor('stellar',first),graphTheme.graphCategoryColor('stellar',second))
  assert.notEqual(graphTheme.graphCategoryColor('stellar',first),graphTheme.graphCategoryColor('galaxy',first))
})

test('canvas follows the system font preference before the default UI font', () => {
  const palette=graphTheme.readGraphTheme(style({'--font-ui':'System Sans','--font-custom-override':'Academic Serif'}))
  assert.equal(palette.font,'Academic Serif')
})

test('conditional applicability remains visually distinct from confirmed unqualified edges', () => {
  assert.equal(typeof graphTheme.graphEdgeDash,'function')
  assert.deepEqual(graphTheme.graphEdgeDash('conditional',2),[3,2])
  assert.deepEqual(graphTheme.graphEdgeDash('applicable',2),[])
  assert.deepEqual(graphTheme.graphEdgeDash('user_link',2),[2.5,2])
})
