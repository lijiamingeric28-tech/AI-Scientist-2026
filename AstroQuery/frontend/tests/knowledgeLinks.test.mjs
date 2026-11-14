import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import * as reading from '../src/components/knowledge/knowledgeReading.js'

test('editing saves only declared outgoing knowledge IDs and retains sources and concurrency identity', () => {
  const initial = { id: 'self', title: 'Theory', revision: 8, is_user: false,
    related_ids: ['outgoing', 'outgoing', 'self'], sources: [{ title: 'Reviewed paper', doi: '10.1/paper' }],
    relations: { related: [{ id: 'incoming', title: 'Other theory', direction: 'incoming' }, { id: 'outgoing', title: 'Linked theory' }] } }
  const draft = reading.createKnowledgeDraft(initial, 'edit')
  assert.deepEqual(draft.relatedIds, ['outgoing'])
  const payload = reading.buildKnowledgePayload(draft, initial, 'edit')
  assert.deepEqual(payload.related_ids, ['outgoing'])
  assert.equal(payload.id, 'self')
  assert.equal(payload.expected_revision, 8)
  assert.equal(payload.is_override, true)
  assert.equal('sources' in payload, false)
  assert.deepEqual(initial.sources, [{ title: 'Reviewed paper', doi: '10.1/paper' }])
  assert.deepEqual(reading.createKnowledgeDraft({ title: 'Incoming only', relations: initial.relations }).relatedIds, [])
})

test('fork links can refer to the original and have fresh identity without its revision', () => {
  const initial = { id: 'base', title: 'Base', revision: 7, related_ids: ['base', 'other'], sources: 'Research notebook' }
  const payload = reading.buildKnowledgePayload(reading.createKnowledgeDraft(initial, 'fork'), initial, 'fork', () => 'fresh')
  assert.equal(payload.id, 'user_fresh')
  assert.equal(payload.base_id, 'base')
  assert.deepEqual(payload.related_ids, ['base', 'other'])
  assert.equal(payload.expected_revision, undefined)
  assert.equal(payload.sources, 'Research notebook')
})

test('payload deduplicates canonical IDs and rejects selections over the supported limit', () => {
  const draft = { ...reading.createKnowledgeDraft({ title: 'Theory' }), relatedIds: [' linked ', 'linked', '', 'other'] }
  assert.deepEqual(reading.buildKnowledgePayload(draft, null, 'create', () => 'fresh').related_ids, ['linked', 'other'])
  draft.relatedIds = Array.from({ length: 101 }, (_, index) => `entry_${index}`)
  assert.throws(() => reading.buildKnowledgePayload(draft, null, 'create', () => 'fresh'), /100/)
})

test('conflict comparison includes outgoing knowledge selections without copying incoming summaries', () => {
  const draft = { ...reading.createKnowledgeDraft({ title: 'Theory' }), relatedIds: ['mine'] }
  const rows = reading.knowledgeDraftComparison(draft, { title: 'Theory', related_ids: ['latest'], relations: { related: [{ id: 'incoming' }] } })
  assert.deepEqual(rows.find(row => row.field === 'relatedIds'), { field: 'relatedIds', label: '关联知识', draft: '[\n  "mine"\n]', latest: '[\n  "latest"\n]' })
})

test('selected links resolve labels by ID and expose missing entries without inventing titles', () => {
  assert.equal(typeof reading.knowledgeLinkSelection, 'function')
  assert.deepEqual(reading.knowledgeLinkSelection(['known', 'missing'], [{ id: 'incoming', title: 'Incoming' }, { id: 'known', title: 'Known theory', category: 'physical_laws' }]), [
    { id: 'known', title: 'Known theory', category: 'physical_laws', unavailable: false },
    { id: 'missing', title: '', unavailable: true },
  ])
  assert.deepEqual(reading.knowledgeLinkSelection(['missing'], [{ id: 'missing', title: 'Obsolete title', unavailable: true }]), [{ id: 'missing', title: '', unavailable: true }])
})

test('knowledge relation evidence labels user links separately from physical-quantity bindings', () => {
  assert.equal(reading.knowledgeRelationEvidence({}, 'related'), '用户建立的知识关联')
  assert.equal(reading.knowledgeRelationEvidence({ provenance: 'entry.related_ids' }, 'entry'), '用户建立的知识关联')
})

test('knowledge search waits for 250 milliseconds of stable input and cancels after disposal', context => {
  assert.equal(typeof reading.createKnowledgeLinkSearch, 'function')
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const calls = []
  const search = reading.createKnowledgeLinkSearch((filters, options) => { calls.push({ filters, ...options }); return new Promise(() => {}) }, () => {})
  search.search('first')
  context.mock.timers.tick(249)
  assert.equal(calls.length, 0)
  search.search('second')
  context.mock.timers.tick(249)
  assert.equal(calls.length, 0)
  context.mock.timers.tick(1)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].filters, { keyword: 'second', limit: 24, offset: 0 })
  search.dispose()
  assert.equal(calls[0].signal.aborted, true)
  context.mock.timers.reset()
})

test('knowledge search reports failures and supports retry while preserving an honest empty result', async context => {
  assert.equal(typeof reading.createKnowledgeLinkSearch, 'function')
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const states = []
  let attempts = 0
  const search = reading.createKnowledgeLinkSearch(async () => {
    attempts += 1
    if (attempts === 1) throw new Error('Connection lost')
    return { items: [], total: 0 }
  }, state => states.push(state))
  try {
    search.search('science'); context.mock.timers.tick(250)
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(states.at(-1).status, 'error')
    assert.equal(states.at(-1).error, 'Connection lost')
    search.search('science'); context.mock.timers.tick(250)
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(states.at(-1), { status: 'ready', items: [], total: 0, error: '' })
  } finally { search.dispose(); context.mock.timers.reset() }
})

test('knowledge search debounces, aborts and ignores an obsolete response while requesting one bounded page', async () => {
  assert.equal(typeof reading.createKnowledgeLinkSearch, 'function')
  const states = [], calls = []
  const search = reading.createKnowledgeLinkSearch((filters, options) => new Promise(resolve => calls.push({ filters, ...options, resolve })), value => states.push(value), { excludeId: 'self', delay: 0 })
  try {
    search.search('old')
    await new Promise(resolve => setTimeout(resolve, 5))
    search.search(' new ')
    await new Promise(resolve => setTimeout(resolve, 5))
    assert.equal(calls[0].signal.aborted, true)
    assert.deepEqual(calls[1].filters, { keyword: 'new', limit: 24, offset: 0 })
    calls[1].resolve({ items: [{ id: 'self', title: 'Self' }, { id: 'new', title: 'New result' }], total: 2 })
    await new Promise(resolve => setImmediate(resolve))
    calls[0].resolve({ items: [{ id: 'old', title: 'Old result' }], total: 1 })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(states.at(-1).status, 'ready')
    assert.deepEqual(states.at(-1).items, [{ id: 'new', title: 'New result' }])
  } finally { search.dispose() }
})

let server, Picker, Editor
before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })
  Editor = (await server.ssrLoadModule('/src/components/knowledge/KnowledgeEditorModal.jsx')).default
  try { Picker = (await server.ssrLoadModule('/src/components/knowledge/KnowledgeLinkPicker.jsx')).default } catch {}
})
after(async () => { await server?.close() })
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))

test('editor exposes a separate knowledge picker with selected titles, categories and honest unavailable IDs', () => {
  const html = render(Editor, { isOpen: true, mode: 'edit', existingCategories: [], initialData: {
    id: 'self', title: 'Theory', related_ids: ['known', 'missing'], relations: { related: [{ id: 'known', title: 'Linked science', category: 'physical_laws' }, { id: 'incoming', title: 'Incoming only' }] },
  } })
  assert.match(html, /<legend>关联知识<\/legend>/)
  assert.match(html, /aria-label="搜索关联知识"/)
  assert.match(html, /Linked science/)
  assert.match(html, /物理定律/)
  assert.match(html, /missing/)
  assert.match(html, /条目暂不可用/)
  assert.match(html, /aria-label="移除关联：Linked science"/)
  assert.doesNotMatch(html, /Incoming only/)
})

test('locked picker preserves selected links while disabling removal and search', () => {
  assert.equal(typeof Picker, 'function')
  const html = render(Picker, { value: ['entry'], summaries: [{ id: 'entry', title: 'Selected science' }], disabled: true })
  assert.match(html, /Selected science/)
  assert.match(html, /aria-label="移除关联：Selected science" disabled=""/)
  assert.match(html, /aria-label="搜索关联知识"[^>]*disabled=""/)
})

test('selected knowledge uses current category names and preserves summary labels outside the loaded catalog', () => {
  const props = { value: ['entry'], summaries: [{ id: 'entry', title: 'Selected science', category: 'custom_id', category_label: '原分类' }] }
  const renamed = render(Picker, { ...props, categories: [{ id: 'custom_id', label: '更新后的分类' }] })
  assert.match(renamed, /更新后的分类/)
  assert.doesNotMatch(renamed, /原分类/)
  assert.match(render(Picker, props), /原分类/)
})
