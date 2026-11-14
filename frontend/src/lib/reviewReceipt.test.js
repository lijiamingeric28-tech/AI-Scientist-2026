import test from 'node:test'
import assert from 'node:assert/strict'
import { reviewReceipt } from './reviewReceipt.js'

test('saved unable is unresolved after actual application, including empty reason and simulation', () => {
  const result = reviewReceipt({ question: '可比较吗？', answer: { action: 'unable', reason: '', simulation: true }, application: { status: 'applied', postcheck: 'unresolved' } }, 'completed')
  assert.equal(result.status, '答案已保存并复检')
  assert.equal(result.simulation, true)
  assert.equal(result.reason, '')
  assert.match(result.outcome, /保留未决/)
  assert.equal(result.continuation, '查询已完成')
})
test('answer waiting or failed application is not presented as applied', () => {
  assert.equal(reviewReceipt({ status: 'pending' }, 'running'), null)
  const waiting = reviewReceipt({ answer: { action: 'correct' } }, 'running')
  assert.match(waiting.status, /等待责任模块复检/)
  assert.equal(waiting.outcome, '')
  const failed = reviewReceipt({ answer: { action: 'correct' }, application: { status: 'failed' } }, 'failed')
  assert.doesNotMatch(failed.status, /并复检/)
  assert.equal(failed.continuation, '')
})
test('different conditions uses actual stored outcome without declaring agreement or completing paused work', () => {
  const result = reviewReceipt({ answer: { action: 'confirm', comparison_outcome: 'different_conditions' }, application: { status: 'applied' } }, 'paused')
  assert.match(result.outcome, /不同测量条件/)
  assert.equal(result.outcome, '按不同测量条件保留')
  assert.doesNotMatch(result.outcome, /测量一致|科学上相同/)
  assert.match(result.continuation, /已暂停/)
})
