import test from 'node:test'
import assert from 'node:assert/strict'
import { createDismissTransition } from '../src/lib/dismissTransition.js'
function fixture() {
  const timers = [], states = [], closed = []
  const controller = createDismissTransition({ onChange: state => states.push(state), onClose: () => closed.push(true), schedule: fn => { timers.push(fn); return timers.length }, clear: () => {} })
  return { controller, timers, states, closed }
}
test('repeated close and animation completion invoke the action once', () => {
  const f = fixture(); f.controller.request(140); f.controller.request(140)
  assert.equal(f.timers.length, 1); f.controller.finish(); f.timers[0](); f.controller.finish()
  assert.equal(f.closed.length, 1); assert.deepEqual(f.states, [true, false])
})
test('cancelled exit cannot close a newly selected detail', () => {
  const f = fixture(); f.controller.request(160); f.controller.cancel(); f.controller.request(160)
  f.timers[0](); assert.equal(f.closed.length, 0)
  f.timers[1](); assert.equal(f.closed.length, 1)
})
test('reduced motion closes immediately without a timer', () => {
  const f = fixture(); f.controller.request(140, true)
  assert.equal(f.timers.length, 0); assert.equal(f.closed.length, 1)
})
