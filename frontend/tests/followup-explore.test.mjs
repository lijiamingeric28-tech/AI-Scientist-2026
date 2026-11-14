import test from 'node:test'
import assert from 'node:assert/strict'
import { exploreCurve } from '../src/components/chat/exploreMath.js'

const parameters = [{ name: 'i', min: 0, max: 90, step: 1, value: 60, choices: [] }]
test('explorer updates the exact projection and treats undefined points as gaps', () => {
  const result = exploreCurve({ expression: '200*sin(i*pi/180)', x: 'i', parameters, values: { i: 30 } })
  assert.ok(Math.abs(result.current - 100) < 1e-10)
  assert.equal(result.points.length, 101)
  assert.deepEqual(result.points.at(-1), [90, 200])
  assert.equal(exploreCurve({ expression: '1/i', x: 'i', parameters, values: { i: 0 } }).current, null)
})
test('explorer blocks assignments, imports, property access and arbitrary functions', () => {
  for (const expression of ['i=5', 'import(i)', 'i.constructor', 'evaluate(i)', '[i,2]', 'i; i']) {
    assert.throws(() => exploreCurve({ expression, x: 'i', parameters, values: {} }))
  }
})
