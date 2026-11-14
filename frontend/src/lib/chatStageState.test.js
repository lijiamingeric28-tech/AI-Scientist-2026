import test from 'node:test'
import assert from 'node:assert/strict'
import { chatStageState, elapsedTime } from './chatStageState.js'

const visited = { id: 'retrieval', seen: true, status: 'partial', activeStage: 'retrieval' }
test('chat reports a finished phase without erasing its incomplete coverage', () => {
  assert.equal(chatStageState({ ...visited, lifecycle:'completed' }), 'completed')
  assert.equal(chatStageState({ ...visited, activeStage:'extraction', lifecycle:'running' }), 'completed')
  assert.equal(chatStageState({ ...visited, lifecycle:'running' }), 'running')
  assert.equal(visited.status, 'partial')
})
test('stopped, waiting and disabled phases keep their own outcome', () => {
  for (const [lifecycle, status] of [['error','failed'],['budget_exhausted','failed'],['cancelled','cancelled'],['interrupted','paused'],['waiting_review','waiting']])
    assert.equal(chatStageState({ ...visited, lifecycle }), status)
  assert.equal(chatStageState({ ...visited, status:'skipped', lifecycle:'completed' }), 'skipped')
  assert.equal(chatStageState({ ...visited, status:'pending', seen:false, lifecycle:'cancelled' }), 'pending')
  assert.equal(elapsedTime(2662.75), '44 分 23 秒')
})
