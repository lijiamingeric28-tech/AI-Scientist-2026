import test from 'node:test'
import assert from 'node:assert/strict'

const model = () => import('./knowledgeWorkbench.js').catch(() => ({}))
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

test('explicit knowledge relation navigation wins over an identically named property', async () => {
  const { resolveKnowledgeNavigation } = await model()
  assert.deepEqual(resolveKnowledgeNavigation({ id:'mass', kind:'entry', title:'Knowledge Mass' }, {properties:[{id:'mass'}]}), {kind:'entry',id:'mass'})
})

test('deleting the active category moves the filter to its destination and clears obsolete graph history', async () => {
  const { createWorkbenchState, workbenchReducer } = await model()
  const state = { ...createWorkbenchState({ selectedCategory: 'custom_a', selectedId: 'entry', offset: 48 }), history: [{ filters: { category: 'custom_a' } }] }
  const changed = workbenchReducer(state, { type: 'categoryRemoved', id: 'custom_a', target: 'user_private' })
  assert.equal(changed.filters.category, 'user_private')
  assert.equal(changed.selectedId, 'entry')
  assert.equal(changed.offset, 0)
  assert.deepEqual(changed.history, [])
})

test('closing an overlay keeps selection and reading position, while graph navigation reveals the canvas', async () => {
  const { createWorkbenchState, workbenchReducer } = await model()
  const selected = workbenchReducer(createWorkbenchState({ offset: 48 }), { type: 'select', id: 'blackbody' })
  assert.equal(selected.detailOpen, true)
  const closed = workbenchReducer(selected, { type: 'dismissDetail' })
  assert.equal(closed.detailOpen, false)
  assert.equal(closed.selectedId, 'blackbody')
  assert.equal(closed.offset, 48)
  assert.equal(workbenchReducer(closed, { type: 'select', id: 'blackbody' }).detailOpen, true)
  const focus = workbenchReducer(selected, { type: 'navigate', scene: { view: 'focus', focus_id: 'blackbody' } })
  assert.equal(focus.detailOpen, false)
  assert.equal(focus.selectedId, 'blackbody')
  assert.equal(focus.scene.focus_id, 'blackbody')
})

test('graph budget defaults to eighty and explicit expansion stays within two hundred without changing filters', async () => {
  const { createWorkbenchState, workbenchReducer, buildKnowledgeGraphQuery } = await model()
  const initial = createWorkbenchState({ selectedId: 'kepler', selectedCategory: 'physical_laws' })
  assert.equal(initial.graphLimit, 80)
  const expanded = workbenchReducer(initial, { type: 'graphBudget', limit: 200 })
  assert.equal(expanded.graphLimit, 200)
  assert.equal(expanded.selectedId, initial.selectedId)
  assert.deepEqual(expanded.filters, initial.filters)
  assert.equal(buildKnowledgeGraphQuery(expanded.filters, expanded.scene, expanded.graphLimit).limit, 200)
  assert.equal(buildKnowledgeGraphQuery({}, initial.scene, 3000).limit, 80)
  assert.equal(workbenchReducer(expanded, { type: 'graphBudget', limit: 3000 }).graphLimit, 80)
})

test('shared query preserves exact property bindings and bounds paginated requests', async () => {
  const { buildKnowledgeQuery } = await model()
  assert.equal(typeof buildKnowledgeQuery, 'function')
  assert.deepEqual(buildKnowledgeQuery({ keyword: '  luminosity  ', category: 'stellar', source: 'user', preferred_only: true, property_ids: ['mass', 'radius', 'mass'], sort: 'updated', offset: 2990 }, 'cards'), {
    keyword: 'luminosity', category: 'stellar', source: 'user', preferred_only: true, property_ids: 'mass,radius', sort: 'updated', offset: 2990, limit: 24, view: 'summary',
  })
  assert.equal(buildKnowledgeQuery({ limit: -1 }, 'table').limit, 50)
  assert.equal(buildKnowledgeQuery({ limit: 100 }, 'table').limit, 100)
  assert.equal(buildKnowledgeQuery({ limit: 1000 }, 'table').limit, 50)
})

test('view changes retain selection and filters, while filter edits reset pagination', async () => {
  const { createWorkbenchState, workbenchReducer } = await model()
  assert.equal(typeof workbenchReducer, 'function')
  let state = createWorkbenchState({ selectedId: 'kepler', selectedCategory: 'orbital', offset: 48 })
  state = workbenchReducer(state, { type: 'view', mode: 'matrix' })
  assert.equal(state.selectedId, 'kepler')
  assert.equal(state.filters.category, 'orbital')
  assert.equal(state.offset, 48)
  state = workbenchReducer(state, { type: 'filter', key: 'source', value: 'user' })
  assert.equal(state.offset, 0)
  assert.equal(state.selectedId, 'kepler')
})

test('explicit expanded graph scene returns to its original scope and camera', async () => {
  const { createWorkbenchState, workbenchReducer, knowledgeSceneKey } = await model()
  assert.equal(typeof knowledgeSceneKey, 'function')
  let state = createWorkbenchState({ selectedCategory: 'stellar', selectedId: 'e1' })
  const key = knowledgeSceneKey(state)
  state = workbenchReducer(state, { type: 'camera', key, value: { x: 4, y: 9, scale: 1.2 } })
  state = workbenchReducer(state, { type: 'navigate', scene: { view: 'focus', focus_id: 'e1', allAssociations: true } })
  assert.equal(state.scene.allAssociations, true)
  assert.notEqual(knowledgeSceneKey(state), key)
  state = workbenchReducer(state, { type: 'back' })
  assert.equal(state.filters.category, 'stellar')
  assert.deepEqual(state.cameras[key], { x: 4, y: 9, scale: 1.2 })
  assert.equal(knowledgeSceneKey(state), key)
})

test('late responses are ignored even when the transport ignores AbortSignal', async () => {
  const { createKnowledgeCache, createLatestKnowledgeRequest } = await model()
  assert.equal(typeof createLatestKnowledgeRequest, 'function')
  const states = []
  const cache = createKnowledgeCache()
  const request = createLatestKnowledgeRequest({ cache, onChange: value => states.push(value) })
  const first = deferred(); const second = deferred(); let oldSignal
  const a = request.run('first', ({ signal }) => { oldSignal = signal; return first.promise })
  const b = request.run('second', () => second.promise)
  assert.equal(oldSignal.aborted, true)
  second.resolve({ items: [{ id: 'new' }], total: 1, revision: 4 })
  await b
  first.resolve({ items: [{ id: 'old' }], total: 1, revision: 3 })
  await a
  assert.equal(states.at(-1).data.items[0].id, 'new')
  assert.equal(cache.get('first'), null)
})

test('failed requests expose only the same successful query cache as read-only', async () => {
  const { createKnowledgeCache, createLatestKnowledgeRequest } = await model()
  assert.equal(typeof createKnowledgeCache, 'function')
  const cache = createKnowledgeCache()
  const states = []
  const request = createLatestKnowledgeRequest({ cache, onChange: value => states.push(value) })
  await request.run('mass', async () => ({ items: [{ id: 'mass-1' }], total: 1, revision: 8 }))
  await request.run('mass', async () => { throw new Error('offline') })
  assert.equal(states.at(-1).status, 'stale')
  assert.equal(states.at(-1).readOnly, true)
  assert.equal(states.at(-1).data.items[0].id, 'mass-1')
  assert.equal(states.at(-1).error.message, 'offline')
  await request.run('radius', async () => { throw new Error('offline') })
  assert.equal(states.at(-1).data, null)
  assert.equal(states.at(-1).status, 'error')
})

test('bounded cache survives storage failure and invalidates all query variants', async () => {
  const { createKnowledgeCache } = await model()
  assert.equal(typeof createKnowledgeCache, 'function')
  const cache = createKnowledgeCache({ maxEntries: 2, storage: { getItem() { throw Error('blocked') }, setItem() { throw Error('full') }, removeItem() { throw Error('blocked') } } })
  cache.set('a', { revision: 1 }); cache.set('b', { revision: 2 }); cache.set('c', { revision: 3 })
  assert.equal(cache.get('a'), null)
  assert.equal(cache.get('c').data.revision, 3)
  cache.clear()
  assert.equal(cache.get('b'), null)
  assert.equal(cache.get('c'), null)
})

test('mutations commit canonical server data and invalidate only after acknowledgement', async () => {
  const { performKnowledgeMutation } = await model()
  assert.equal(typeof performKnowledgeMutation, 'function')
  const pending = deferred(); const events = []
  const promise = performKnowledgeMutation({ request: () => pending.promise, optimistic: () => events.push('optimistic'), rollback: () => events.push('rollback'), commit: value => events.push(value.entry.id), invalidate: () => events.push('invalidate') })
  assert.deepEqual(events, ['optimistic'])
  pending.resolve({ success: true, entry: { id: 'server-id', revision: 2 } })
  await promise
  assert.deepEqual(events, ['optimistic', 'server-id', 'invalidate'])
})

test('failed preference and conflict roll back and reject to preserve the editor draft', async () => {
  const { performKnowledgeMutation } = await model()
  assert.equal(typeof performKnowledgeMutation, 'function')
  const events = []; const conflict = Object.assign(new Error('conflict'), { status: 409 })
  await assert.rejects(performKnowledgeMutation({ request: async () => { throw conflict }, optimistic: () => events.push('optimistic'), rollback: () => events.push('rollback'), commit: () => events.push('commit'), invalidate: () => events.push('invalidate') }), error => error === conflict)
  assert.deepEqual(events, ['optimistic', 'rollback'])
  await assert.rejects(performKnowledgeMutation({ request: async () => ({ success: false }), invalidate: () => events.push('invalidate') }), /未确认/)
  assert.deepEqual(events, ['optimistic', 'rollback'])
})

test('mutation invalidation prevents older in-flight reads from repopulating the cache', async () => {
  const { createKnowledgeCache, createLatestKnowledgeRequest } = await model()
  const cache = createKnowledgeCache(); const states = []; const old = deferred()
  const reader = createLatestKnowledgeRequest({ cache, onChange: state => states.push(state) })
  const pending = reader.run('list', () => old.promise)
  cache.clear()
  old.resolve({ items: [{ id: 'deleted' }], total: 1 })
  await pending
  assert.equal(cache.get('list'), null)
  assert.notEqual(states.at(-1).status, 'ready')
})

test('focus expansion changes graph scope explicitly while summary and list remain filtered', async () => {
  const { buildKnowledgeGraphQuery } = await model()
  assert.equal(typeof buildKnowledgeGraphQuery, 'function')
  const filters = { keyword: 'mass', category: 'stellar', source: 'user', property_ids: ['mass'] }
  assert.deepEqual(buildKnowledgeGraphQuery(filters, { view: 'focus', focus_id: 'e1', allAssociations: false }), { keyword: 'mass', category: 'stellar', source: 'user', property_ids: 'mass', sort: 'name', view: 'focus', focus_id: 'e1', limit: 80 })
  assert.deepEqual(buildKnowledgeGraphQuery(filters, { view: 'focus', focus_id: 'e1', allAssociations: true }), { view: 'focus', focus_id: 'e1', limit: 80 })
})

test('newer server revisions supersede canonical mutation overlays while optimistic changes remain visible', async () => {
  const { mergeKnowledgeEntry } = await model()
  assert.equal(typeof mergeKnowledgeEntry, 'function')
  assert.deepEqual(mergeKnowledgeEntry({ id: 'e', title: 'External update', revision: 9 }, { id: 'e', title: 'Earlier edit', revision: 8 }), { id: 'e', title: 'External update', revision: 9 })
  assert.equal(mergeKnowledgeEntry({ id: 'e', preferred: false, revision: 9 }, { preferred: true }).preferred, true)
  assert.equal(mergeKnowledgeEntry({ id: 'e', title: 'Old', revision: 7 }, { id: 'e', title: 'Saved', revision: 8 }).title, 'Saved')
  assert.equal(mergeKnowledgeEntry({ id: 'e', category_label: '新分类名称', revision: 8, library_revision: 12 }, { id: 'e', category_label: '旧分类名称', revision: 8, library_revision: 11 }).category_label, '新分类名称')
})

test('graph camera scene keys follow the applied query rather than in-progress search typing', async () => {
  const { createWorkbenchState, knowledgeSceneKey } = await model()
  const state = createWorkbenchState({ searchQuery: 'm' })
  const before = knowledgeSceneKey(state, { keyword: 'mass', category: 'all' })
  const typing = knowledgeSceneKey({ ...state, keyword: 'ma' }, { keyword: 'mass', category: 'all' })
  assert.equal(typing, before)
})

test('property links navigate their exact binding even outside the current projected graph', async () => {
  const { resolveKnowledgeNavigation } = await model()
  assert.equal(typeof resolveKnowledgeNavigation, 'function')
  assert.deepEqual(resolveKnowledgeNavigation('prop_mass', { relations: { properties: [{ id: 'prop_mass', property_id: 'mass', label: '质量' }] } }), { kind: 'property', id: 'mass' })
  assert.deepEqual(resolveKnowledgeNavigation('cat_stars', { nodes: [{ id: 'cat_stars', kind: 'category', category: 'stars' }] }), { kind: 'category', id: 'stars' })
  assert.deepEqual(resolveKnowledgeNavigation('einstein', { nodes: [] }), { kind: 'entry', id: 'einstein' })
})

test('property picker searches every real ID and label but exposes only a bounded set plus the selected binding', async () => {
  const { searchKnowledgeProperties } = await model()
  assert.equal(typeof searchKnowledgeProperties, 'function')
  const properties = Array.from({ length: 1883 }, (_, index) => ({ id: `property_${index}`, label: `物理量 ${index}`, count: index }))
  const initial = searchKnowledgeProperties(properties, '', 'property_1882')
  assert.equal(initial.items.length, 31)
  assert.equal(initial.items[0].id, 'property_1882')
  assert.equal(initial.total, 1883)
  const distant = searchKnowledgeProperties(properties, 'PROPERTY_1881', 'property_1882')
  assert.deepEqual(distant.items.map(item => item.id), ['property_1882', 'property_1881'])
  assert.equal(distant.total, 1)
  assert.equal(searchKnowledgeProperties(properties, '不存在', '').items.length, 0)
})

test('selected detail keeps real summary identity while pending and never invents category or origin', async () => {
  const { selectedKnowledgeShell } = await model()
  assert.equal(typeof selectedKnowledgeShell, 'function')
  const list = { id: 'known', title: 'Real list title', category: 'stellar', is_user: true }
  const graph = { id: 'known', label: 'Real graph label', category: 'stellar', kind: 'entry' }
  const detail = { id: 'known', title: 'Full canonical title', revision: 2 }
  assert.equal(selectedKnowledgeShell('known', { detail, items: [list], nodes: [graph] }), detail)
  assert.equal(selectedKnowledgeShell('known', { detail: { id: 'old' }, items: [list], nodes: [graph] }), list)
  assert.equal(selectedKnowledgeShell('known', { nodes: [graph] }), graph)
  assert.deepEqual(selectedKnowledgeShell('not-loaded'), { id: 'not-loaded', title: '正在读取…', loading_only: true })
  assert.equal(selectedKnowledgeShell(null), null)
})

test('other-category aggregates open the filtered matrix instead of inventing a category ID', async () => {
  const { resolveKnowledgeNavigation } = await model()
  assert.deepEqual(resolveKnowledgeNavigation({ id: 'aggregate:other', kind: 'aggregate', label: '其他分类', count: 34 }), { kind: 'matrix' })
  assert.deepEqual(resolveKnowledgeNavigation({ id: 'aggregate:stellar', kind: 'aggregate', category: 'stellar' }), { kind: 'category', id: 'stellar' })
})

test('matrix search result detour retains phrase, all shared filters, selection and graph return camera', async () => {
  const { createWorkbenchState, workbenchReducer, knowledgeSceneKey, buildKnowledgeQuery } = await model()
  let state = createWorkbenchState({ keyword: 'exact scientific phrase', selectedId: 'entry_2999', filters: { category: 'stellar', source: 'user', preferred_only: true, property_ids: ['luminosity'], sort: 'relevance' } })
  state = workbenchReducer(state, { type: 'navigate', scene: { view: 'focus', focus_id: 'entry_2999', allAssociations: false } })
  const scene = knowledgeSceneKey(state)
  state = workbenchReducer(state, { type: 'camera', key: scene, value: { x: 18, y: -20, scale: 1.3 } })
  const history = state.history
  state = workbenchReducer(state, { type: 'view', mode: 'matrix' })
  assert.equal(state.selectedId, 'entry_2999')
  assert.deepEqual(buildKnowledgeQuery({ ...state.filters, keyword: state.keyword }, state.listMode), { keyword: 'exact scientific phrase', category: 'stellar', source: 'user', preferred_only: true, property_ids: 'luminosity', sort: 'relevance', offset: 0, limit: 24, view: 'summary' })
  state = workbenchReducer(state, { type: 'view', mode: 'graph' })
  assert.equal(knowledgeSceneKey(state), scene)
  assert.deepEqual(state.cameras[scene], { x: 18, y: -20, scale: 1.3 })
  assert.equal(state.history, history)
})
