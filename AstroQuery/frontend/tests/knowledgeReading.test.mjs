import test from 'node:test'
import assert from 'node:assert/strict'
import {
  readingPage, entryOrigin, sourceRecords, propertyChoices,
  createKnowledgeDraft, buildKnowledgePayload, createSaveGate,
} from '../src/components/knowledge/knowledgeReading.js'
import * as reading from '../src/components/knowledge/knowledgeReading.js'

test('new category names are normalized and cannot duplicate builtins, existing custom categories or reserved navigation', () => {
  assert.equal(typeof reading.createKnowledgeCategory, 'function')
  const categories = [{ id: 'physical_laws', label: '物理定律', alt_names: ['law', 'physics'] }, { id: 'My Notes', label: 'My Notes' }]
  const category = reading.createKnowledgeCategory('  我的\n科研\t笔记  ', categories)
  assert.deepEqual(category, { id: '我的 科研 笔记', label: '我的 科研 笔记', is_custom: true })
  for (const value of ['', '  ', '物理定律', 'physical_laws', 'Law', 'PHYSICS', 'my notes', 'all', '全部分类', '全部知识', '类'.repeat(41)]) {
    assert.throws(() => reading.createKnowledgeCategory(value, categories), undefined, value)
  }
  const draft = { ...createKnowledgeDraft(null), title: '新知识', category: category.id }
  assert.equal(buildKnowledgePayload(draft, null, 'create', () => 'category-test').category, category.id)
  assert.equal(reading.createKnowledgeCategory('旧名称', [{ id: '旧名称', label: '重命名后的分类', is_custom: true }]).label, '旧名称')
})

test('server pagination preserves the corpus total and exposes the next offset without truncating a page', () => {
  assert.deepEqual(readingPage({ total: 3000, offset: 48, limit: 24, count: 24 }), {
    start: 49, end: 72, total: 3000, previous: 24, next: 72, hasPrevious: true, hasNext: true,
  })
  assert.deepEqual(readingPage({ total: 3000, offset: 2976, limit: 24, count: 24 }), {
    start: 2977, end: 3000, total: 3000, previous: 2952, next: 3000, hasPrevious: true, hasNext: false,
  })
  assert.equal(readingPage({ total: 3000, offset: 48, limit: 24, count: 0 }).start, 0)
})

test('modified and user entries never inherit the builtin origin badge', () => {
  assert.equal(entryOrigin({ is_override: true, is_user: false }).id, 'override')
  assert.equal(entryOrigin({ is_user: true }).id, 'user')
  assert.equal(entryOrigin({ is_user: false }).id, 'builtin')
})

test('known category labels stay readable while payload values preserve IDs and free custom names', () => {
  const categories = [{ id: 'user_private', label: '用户私有' }, { id: 'physical_laws', label: '物理定律' }]
  assert.equal(reading.knowledgeCategoryLabel('user_private', categories), '用户私有')
  assert.equal(reading.knowledgeCategoryValue('物理定律', categories), 'physical_laws')
  assert.equal(reading.knowledgeCategoryValue('我的自定义分类', categories), '我的自定义分类')
})

test('full sources retain every source and its citation metadata', () => {
  assert.deepEqual(sourceRecords([{ title: 'First', doi: '10.1/a', authors: ['A', 'B'] }, { title: 'Second', year: 2025 }]), [
    { title: 'First', doi: '10.1/a', authors: ['A', 'B'] }, { title: 'Second', year: 2025 },
  ])
  assert.deepEqual(sourceRecords('Research notebook\nPage 8'), [{ title: 'Research notebook\nPage 8' }])
  assert.deepEqual(sourceRecords(null), [])
})

test('property selection binds exact known IDs and labels while preserving custom unbound values', () => {
  assert.deepEqual(propertyChoices(['stellar_mass', '光度', 'my_new_quantity'], [
    { id: 'stellar_mass', label: '恒星质量' }, { id: 'luminosity', label: '光度' },
  ]), [
    { id: 'stellar_mass', label: '恒星质量', bound: true },
    { id: 'luminosity', label: '光度', bound: true },
    { id: 'my_new_quantity', label: 'my_new_quantity', bound: false },
  ])
})

test('a literal property appearing in the corpus is still unbound until its binding is reviewed', () => {
  assert.deepEqual(propertyChoices(['my_quantity'], [{ id: 'my_quantity', label: 'My quantity', binding_state: 'unreviewed' }]), [
    { id: 'my_quantity', label: 'My quantity', bound: false },
  ])
})

test('relation evidence distinguishes reviewed identifier mappings from unreviewed declarations and recorded derivations', () => {
  assert.equal(reading.knowledgeRelationEvidence({ provenance: 'curated_property_aliases', binding_state: 'curated' }, 'property'), '已审定性质标识/别名映射')
  assert.equal(reading.knowledgeRelationEvidence({ provenance: 'entry.properties', binding_state: 'unreviewed' }, 'property'), '条目显式声明，标识尚未审定')
  assert.equal(reading.knowledgeRelationEvidence({ provenance: 'curated_property_aliases', binding_state: 'unreviewed' }, 'property'), '条目显式声明，标识尚未审定')
  assert.equal(reading.knowledgeRelationEvidence({}, 'base'), '派生记录：当前条目以此条目为基础')
  assert.equal(reading.knowledgeRelationEvidence({}, 'derived'), '派生记录：此条目以当前条目为基础')
  assert.equal(reading.knowledgeRelationEvidence({}, 'base', { isOverride: true }), '覆盖记录：当前用户修改基于该内置条目')
})

test('editing keeps entry identity and revision while omitting unchanged legacy fields the write API cannot accept', () => {
  const initial = {
    id: 'builtin_1', title: 'Original', category: 'physical_laws', revision: 7, is_user: false,
    sources: [{ title: 'Paper A', doi: '10.1/a' }, { title: 'Paper B', year: 2024 }],
    conditions: [{ text: 'Hydrostatic equilibrium', provenance: 'reviewed' }], parameters: [],
  }
  const draft = createKnowledgeDraft(initial, 'edit')
  draft.title = ' Updated '
  const payload = buildKnowledgePayload(draft, initial, 'edit')
  assert.equal(payload.id, 'builtin_1')
  assert.equal(payload.expected_revision, 7)
  assert.equal(payload.revision, 7)
  assert.equal(payload.is_override, true)
  assert.equal('sources' in payload, false)
  assert.equal('conditions' in payload, false)
  assert.deepEqual(initial.sources, [{ title: 'Paper A', doi: '10.1/a' }, { title: 'Paper B', year: 2024 }])
  assert.deepEqual(initial.conditions, [{ text: 'Hydrostatic equilibrium', provenance: 'reviewed' }])
})

test('property IDs and parameter descriptions survive editing rather than becoming display labels', () => {
  const initial = { id: 'entry', title: 'Theory', is_user: true,
    properties: [{ id: 'stellar_mass', label: '恒星质量' }],
    parameters: ['alpha', { name: 'T', description: 'Temperature', unit: 'K' }],
  }
  const draft = createKnowledgeDraft(initial, 'edit')
  assert.equal(draft.propertiesText, 'stellar_mass')
  assert.equal(draft.parameters[0].name, 'alpha')
  assert.equal(draft.parameters[1].desc, 'Temperature')
})

test('fork creates a UUID-based ID and records the base without copying its concurrency revision', () => {
  const initial = { id: 'base', title: 'Base', revision: 9, category: 'physical_laws', properties: [] }
  const draft = createKnowledgeDraft(initial, 'fork')
  const payload = buildKnowledgePayload(draft, initial, 'fork', () => '1234-uuid')
  assert.equal(payload.id, 'user_1234-uuid')
  assert.equal(payload.base_id, 'base')
  assert.equal(payload.title, 'Base (派生版)')
  assert.equal(payload.expected_revision, undefined)
  assert.equal(payload.revision, undefined)
})

test('save gate prevents duplicate writes and releases after failure so a retained draft can retry', async () => {
  const gate = createSaveGate()
  let rejectSave
  let writes = 0
  const pending = gate.run(() => { writes += 1; return new Promise((resolve, reject) => { rejectSave = reject }) })
  assert.equal(gate.pending, true)
  assert.deepEqual(await gate.run(() => { writes += 1 }), { saved: false, reason: 'pending' })
  rejectSave(new Error('Revision conflict'))
  await assert.rejects(pending, /Revision conflict/)
  assert.equal(gate.pending, false)
  assert.deepEqual(await gate.run(async () => { writes += 1; return { revision: 8 } }), { saved: true, value: { revision: 8 } })
  assert.equal(writes, 2)
})

test('payload rejects an empty title before any save and retains custom fields as plain values', () => {
  const draft = createKnowledgeDraft(null, 'create')
  assert.throws(() => buildKnowledgePayload(draft, null, 'create'), /标题/)
  draft.title = 'Custom'
  draft.propertiesText = 'luminosity, unknown_value，unknown_value'
  draft.parameters = [{ name: '', symbol: '', range: '', unit: '', desc: 'Units need review' }]
  const payload = buildKnowledgePayload(draft, null, 'create', () => 'uuid')
  assert.deepEqual(payload.properties, ['luminosity', 'unknown_value'])
  assert.equal(payload.parameters[0].desc, 'Units need review')
})
