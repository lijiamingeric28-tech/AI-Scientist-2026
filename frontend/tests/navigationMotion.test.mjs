import test from 'node:test'
import assert from 'node:assert/strict'
import { createNavigationMotion, navigationDirection } from '../src/lib/navigationMotion.js'

function clock() {
  const queue = new Map(); let id = 0
  return { schedule: (fn, ms) => { queue.set(++id, { fn, ms }); return id }, unschedule: key => queue.delete(key),
    flush: ms => { for (const [key, entry] of [...queue]) if (entry.ms <= ms) { queue.delete(key); entry.fn() } }, queue }
}
function pane() {
  const calls = []
  return { calls, animate: (frames, options) => { const animation = { cancelled: false, cancel() { this.cancelled = true } }; calls.push({ frames, options, animation }); return animation } }
}
test('navigation reverses direction and completes exit before entry', () => {
  assert.equal(navigationDirection(['chat','data','workflow'], 'chat', 'workflow'), 1)
  assert.equal(navigationDirection(['records','evidence','analysis'], 'analysis', 'records'), -1)
  const time = clock(), motion = createNavigationMotion(time), enter = pane(), exit = pane(), events = []
  motion.run({ enter, exit, direction: -1, onExit: () => events.push('exit'), onFinish: () => events.push('finish') })
  assert.equal(enter.calls[0].frames[0].transform, 'translateX(-28px)')
  assert.equal(exit.calls[0].frames[1].transform, 'translateX(14px)')
  time.flush(160); assert.deepEqual(events, ['exit'])
  time.flush(320); assert.deepEqual(events, ['exit','finish']); assert.equal(time.queue.size, 0)
})
test('rapid replacement invalidates even queued old callbacks', () => {
  const time = clock(), motion = createNavigationMotion(time), first = pane(), last = pane(), events = []
  motion.run({ enter: first, onExit: () => events.push('old-exit'), onFinish: () => events.push('old-finish') })
  const stale = [...time.queue.values()].map(entry => entry.fn)
  motion.run({ enter: last, onExit: () => events.push('last-exit'), onFinish: () => events.push('last-finish') })
  stale.forEach(fn => fn()); time.flush(320)
  assert.deepEqual(events, ['last-exit','last-finish']); assert.ok(first.calls[0].animation.cancelled)
})
test('task change or unmount cancels exit and entry callbacks', () => {
  const time = clock(), motion = createNavigationMotion(time), enter = pane(), events = []
  motion.run({ enter, onExit: () => events.push('exit'), onFinish: () => events.push('finish') })
  const stale = [...time.queue.values()].map(entry => entry.fn)
  motion.cancel(); stale.forEach(fn => fn()); time.flush(320)
  assert.deepEqual(events, []); assert.ok(enter.calls[0].animation.cancelled); assert.equal(time.queue.size, 0)
})
test('reduced motion applies final visibility synchronously without animations', () => {
  const time = clock(), motion = createNavigationMotion(time), enter = pane(), events = []
  motion.run({ enter, reduced: true, onExit: () => events.push('exit'), onFinish: () => events.push('finish') })
  assert.deepEqual(events, ['exit','finish']); assert.equal(enter.calls.length, 0); assert.equal(time.queue.size, 0)
})
