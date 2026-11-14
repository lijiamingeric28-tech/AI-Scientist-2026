import test from 'node:test'
import assert from 'node:assert/strict'
import * as reading from '../src/components/knowledge/knowledgeReading.js'

test('report edit loads the canonical entry by entry_id without changing the frozen report block', async () => {
  const report = { id: 'report-block', entry_id: 'canonical', title: 'Frozen title', claim: { text: 'Frozen evidence' } }
  const result = await reading.loadKnowledgeReportEditor(report, {
    getKnowledgeItem: async id => { assert.equal(id, 'canonical'); return { id: 'canonical', title: 'Current title', description: 'Full current text', revision: 8 } },
  })
  assert.deepEqual(result, { mode: 'edit', item: { id: 'canonical', title: 'Current title', description: 'Full current text', revision: 8 } })
  assert.equal(report.title, 'Frozen title')
  assert.equal(report.claim.text, 'Frozen evidence')
})

test('canonical load failure rejects so an unavailable entry is never silently edited as a fresh copy', async () => {
  await assert.rejects(reading.loadKnowledgeReportEditor({ id: 'missing' }, {
    getKnowledgeItem: async () => { throw new Error('Offline') },
  }), /Offline/)
})

test('report editor sends canonical revision when updating and acknowledges only a successful server write', async () => {
  const acknowledgements = []
  const payload = { id: 'canonical', title: 'Changed', expected_revision: 8 }
  const result = await reading.saveKnowledgeReportDraft(payload, 'edit', {
    updateKnowledge: async (id, body) => { assert.equal(id, 'canonical'); assert.deepEqual(body, { id: 'canonical', title: 'Changed', expected_revision: 8 }); return { id, revision: 9 } },
    createKnowledge: () => assert.fail('An edit must never create a duplicate entry'),
  }, entry => acknowledgements.push(entry.revision))
  assert.equal(result.revision, 9)
  assert.deepEqual(acknowledgements, [9])
  await assert.rejects(reading.saveKnowledgeReportDraft(payload, 'edit', {
    updateKnowledge: async () => { throw new Error('Conflict') },
  }, () => acknowledgements.push('false success')), /Conflict/)
  assert.deepEqual(acknowledgements, [9])
})

test('a report fork creates a fresh user entry with its base, while a revisionless edit is rejected', async () => {
  const draft = reading.createKnowledgeDraft({ id: 'original', title: 'Frozen title' }, 'fork')
  const payload = reading.buildKnowledgePayload(draft, { id: 'original' }, 'fork', () => 'fresh')
  await reading.saveKnowledgeReportDraft(payload, 'fork', {
    createKnowledge: async body => { assert.equal(body.id, 'user_fresh'); assert.equal(body.base_id, 'original'); return { id: body.id, revision: 1 } },
    updateKnowledge: () => assert.fail('A fork must never replace its source'),
  })
  await assert.rejects(reading.saveKnowledgeReportDraft({ id: 'old' }, 'edit', {}), /修订/)
})

test('report preference uses the current entry revision and does not acknowledge an unsuccessful write', async () => {
  let acknowledged = false
  const api = {
    getKnowledgeItem: async () => ({ id: 'canonical', revision: 8 }),
    setKnowledgePreference: async (id, body) => {
      assert.equal(id, 'canonical')
      assert.deepEqual(body, { preference: 'preferred', weight_boost: 1.5, expected_revision: 8 })
      throw new Error('Disk full')
    },
  }
  await assert.rejects(reading.saveKnowledgeReportPreference({ entry_id: 'canonical' }, true, api, () => { acknowledged = true }), /Disk full/)
  assert.equal(acknowledged, false)
})

test('an unavailable report base becomes standalone user knowledge with report provenance and no nonexistent base_id', async () => {
  const report = { id: 'frozen-block', entry_id: 'deleted', title: 'Frozen science', claim: { text: 'Original frozen text' }, sources: [{ title: 'Original paper', doi: '10.1/test' }] }
  const prepared = await reading.prepareKnowledgeReportCopy(report, { getKnowledgeItem: async () => { throw Object.assign(new Error('Not found'), { status: 404 }) } })
  assert.equal(prepared.mode, 'create')
  assert.equal(prepared.baseUnavailable, true)
  const payload = reading.buildKnowledgePayload(reading.createKnowledgeDraft(prepared.item, prepared.mode), prepared.item, prepared.mode, () => 'new')
  assert.equal('base_id' in payload, false)
  assert.equal(payload.id, 'user_new')
  assert.equal(payload.description, 'Original frozen text')
  assert.match(payload.sources, /报告.*Frozen science/)
  assert.match(payload.sources, /deleted/)
  assert.match(payload.sources, /Original paper/)
  assert.equal(report.entry_id, 'deleted')
})

test('a report copy keeps a valid canonical base when the source can be read', async () => {
  const prepared = await reading.prepareKnowledgeReportCopy({ entry_id: 'valid', title: 'Frozen science', claim: { text: 'Frozen text' } }, { getKnowledgeItem: async () => ({ id: 'valid', revision: 2 }) })
  assert.equal(prepared.mode, 'fork')
  const payload = reading.buildKnowledgePayload(reading.createKnowledgeDraft(prepared.item, prepared.mode), prepared.item, prepared.mode, () => 'new')
  assert.equal(payload.base_id, 'valid')
  assert.equal(payload.description, 'Frozen text')
})
