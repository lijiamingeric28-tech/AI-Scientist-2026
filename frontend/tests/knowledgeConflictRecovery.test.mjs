import test from 'node:test'
import assert from 'node:assert/strict'
import * as reading from '../src/components/knowledge/knowledgeReading.js'

test('reading the latest conflict version leaves the draft and original expected revision intact', async () => {
  const original = { id: 'entry', title: 'Old', description: 'Old text', revision: 3, is_user: true }
  const draft = reading.createKnowledgeDraft(original, 'edit')
  draft.title = 'My draft'
  const latest = await reading.loadKnowledgeConflict(original, async id => {
    assert.equal(id, 'entry')
    return { id, title: 'Other edit', description: 'New text', revision: 4, is_user: true }
  })
  assert.equal(reading.buildKnowledgePayload(draft, original, 'edit').expected_revision, 3)
  assert.equal(draft.title, 'My draft')
  const comparison = reading.knowledgeDraftComparison(draft, latest)
  assert.deepEqual(comparison.find(row => row.field === 'title'), { field: 'title', label: '标题', draft: 'My draft', latest: 'Other edit' })
  assert.deepEqual(comparison.find(row => row.field === 'description'), { field: 'description', label: '核心阐述', draft: 'Old text', latest: 'New text' })
})

test('only deliberate conflict acceptance updates the revision and keeps every current draft field', () => {
  const original = { id: 'entry', title: 'Old', revision: 3, is_user: true }
  const latest = { id: 'entry', title: 'Other edit', revision: 4, is_user: true }
  const draft = reading.createKnowledgeDraft(original, 'edit')
  draft.title = 'My draft'; draft.description = 'Still being edited'
  const accepted = reading.acceptKnowledgeConflict(draft, original, latest)
  assert.equal(accepted.draft, draft)
  const payload = reading.buildKnowledgePayload(accepted.draft, accepted.base, 'edit')
  assert.equal(payload.expected_revision, 4)
  assert.equal(payload.title, 'My draft')
  assert.equal(payload.description, 'Still being edited')
  assert.equal(original.revision, 3)
  assert.throws(() => reading.acceptKnowledgeConflict(draft, original, { id: 'unrelated', revision: 8 }), /条目/)
})

test('failed or invalid latest reads keep recovery blocked instead of silently rebasing', async () => {
  const original = { id: 'entry', revision: 3 }
  await assert.rejects(reading.loadKnowledgeConflict(original, async () => { throw new Error('Offline') }), /Offline/)
  await assert.rejects(reading.loadKnowledgeConflict(original, async () => ({ id: 'entry' })), /修订/)
  await assert.rejects(reading.loadKnowledgeConflict(original, async () => ({ id: 'entry', revision: 2 })), /修订/)
})
