import test from 'node:test'
import assert from 'node:assert/strict'

test('detail relation management uses a scoped endpoint with entry and library conflict versions', async () => {
  const { createKnowledgeApi } = await import('../src/services/knowledgeApi.js')
  const calls=[]
  const api=createKnowledgeApi(async(path,options)=>{calls.push({path,options})})
  assert.equal(typeof api.updateKnowledgeRelations,'function')
  await api.updateKnowledgeRelations('a/b',{related_ids:['new'],unlink_incoming_ids:['source'],expected_revision:2,expected_library_revision:9})
  assert.equal(calls[0].path,'/knowledge/a%2Fb/relations')
  assert.equal(calls[0].options.method,'PUT')
  assert.deepEqual(JSON.parse(calls[0].options.body),{related_ids:['new'],unlink_incoming_ids:['source'],expected_revision:2,expected_library_revision:9})
})

test('category appearance and order preserve color plus concurrency versions', async () => {
  const { createKnowledgeApi } = await import('../src/services/knowledgeApi.js')
  const calls = []
  const api = createKnowledgeApi(async (path, options) => { calls.push({path,options}); return {success:true} })
  await api.updateKnowledgeCategory('physical_laws', { color:'#a03f6b', expected_revision:0 })
  assert.deepEqual(JSON.parse(calls[0].options.body), {color:'#a03f6b',expected_revision:0})
  assert.equal(typeof api.reorderKnowledgeCategories, 'function')
  await api.reorderKnowledgeCategories({ ids:['b','a'], expected_revision:4 })
  assert.equal(calls[1].path, '/knowledge/categories/order')
  assert.deepEqual(JSON.parse(calls[1].options.body), {ids:['b','a'],expected_revision:4})
})

test('independent category CRUD uses stable IDs and explicit category revisions', async () => {
  const { createKnowledgeApi } = await import('../src/services/knowledgeApi.js')
  const calls = []
  const api = createKnowledgeApi(async (path, options) => { calls.push({ path, options }); return { success: true } })
  assert.equal(typeof api.getKnowledgeCategories, 'function')
  await api.getKnowledgeCategories()
  await api.createKnowledgeCategory({ label: '星系演化' })
  await api.updateKnowledgeCategory('旧分类/1', { label: '科研笔记', expected_revision: 0 })
  await api.deleteKnowledgeCategory('旧分类/1', { target_category: 'user_private', expected_revision: 2 })
  assert.equal(calls[0].path, '/knowledge/categories')
  assert.equal(calls[1].options.method, 'POST')
  assert.deepEqual(JSON.parse(calls[1].options.body), { label: '星系演化' })
  assert.equal(calls[2].path, '/knowledge/categories/%E6%97%A7%E5%88%86%E7%B1%BB%2F1')
  assert.deepEqual(JSON.parse(calls[2].options.body), { label: '科研笔记', expected_revision: 0 })
  assert.equal(calls[3].options.method, 'DELETE')
  assert.equal(calls[3].path, '/knowledge/categories/%E6%97%A7%E5%88%86%E7%B1%BB%2F1?target_category=user_private&expected_revision=2')
})

test('knowledge adapters send bounded shared filters, AbortSignal, and explicit restore revision', async () => {
  const { createKnowledgeApi } = await import('../src/services/knowledgeApi.js').catch(() => ({}))
  assert.equal(typeof createKnowledgeApi, 'function')
  const requests = []
  const api = createKnowledgeApi(async (path, options) => { requests.push({ path, options }); return { success: true } })
  const controller = new AbortController()
  await api.getKnowledgeSummary({ keyword: 'a b', source: 'builtin', property_ids: ['mass', 'radius'] }, { signal: controller.signal })
  assert.equal(requests[0].path, '/knowledge/summary?keyword=a+b&source=builtin&property_ids=mass%2Cradius')
  assert.equal(requests[0].options.signal, controller.signal)
  await api.restoreKnowledge('a/b', { expected_revision: 6 })
  assert.equal(requests[1].path, '/knowledge/a%2Fb/restore')
  assert.equal(requests[1].options.method, 'POST')
  assert.deepEqual(JSON.parse(requests[1].options.body), { expected_revision: 6 })
  await api.deleteKnowledge('a/b', { expected_revision: 7, signal: controller.signal })
  assert.equal(requests[2].path, '/knowledge/a%2Fb?expected_revision=7')
  assert.equal(requests[2].options.method, 'DELETE')
  assert.equal(requests[2].options.signal, controller.signal)
})

test('literal keyword all remains searchable while sentinel category and source are omitted', async () => {
  const { createKnowledgeApi } = await import('../src/services/knowledgeApi.js')
  const api = createKnowledgeApi(async path => path)
  assert.equal(await api.getKnowledge({ keyword: 'all', source: 'all', category: 'all', offset: 0, limit: 24 }), '/knowledge?keyword=all&offset=0&limit=24')
})
