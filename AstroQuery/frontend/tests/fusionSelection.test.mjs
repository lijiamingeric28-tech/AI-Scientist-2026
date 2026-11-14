import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'

let server, selection
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
  selection = await server.ssrLoadModule('/src/hooks/useWorkbenchSelection.js')
})
after(async () => { await server?.close() })

test('result selections use exact task, publication and revision identity', () => {
  assert.equal(typeof selection.workbenchSelectionKey, 'function')
  const key = selection.workbenchSelectionKey
  assert.equal(key('task', 'delivery', 7), key('task', 'delivery', 7))
  assert.notEqual(key('task', 'delivery', 7), key('task', 'delivery', 8))
  assert.notEqual(key('task', 'delivery', 7), key('other', 'delivery', 7))
  assert.notEqual(key('task', 'delivery', 7), key('task', 'other', 7))
  assert.notEqual(key('a.b', 'c', 7), key('a', 'b.c', 7))
})

test('a selection is unavailable before a complete publication identity exists', () => {
  assert.equal(typeof selection.workbenchSelectionKey, 'function')
  const key = selection.workbenchSelectionKey
  for (const args of [[null, 'd', 7], ['t', null, 7], ['t', 'd'], ['t', 'd', 0]])
    assert.equal(key(...args), null)
})
