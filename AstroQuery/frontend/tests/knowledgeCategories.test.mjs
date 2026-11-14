import test from 'node:test'
import assert from 'node:assert/strict'

test('category conflict recovery retains changed fields and adopts untouched remote fields', async () => {
  const module = await import('../src/lib/knowledgeCategories.js')
  assert.equal(typeof module.rebaseCategoryDraft, 'function')
  const base = { label:'原名称',color:'#24583b' }, latest = { label:'远端名称',color:'#3b82f6' }
  assert.deepEqual(module.rebaseCategoryDraft(base,{name:'原名称',color:'#a03f6b'},latest),{name:'远端名称',color:'#a03f6b'})
  assert.deepEqual(module.rebaseCategoryDraft(base,{name:'本地名称',color:'#24583B'},latest),{name:'本地名称',color:'#3b82f6'})
})

test('category colors accept canonical hex only and reorder keeps every stable ID exactly once', async () => {
  const module = await import('../src/lib/knowledgeCategories.js')
  assert.equal(typeof module.normalizeCategoryColor, 'function')
  assert.equal(module.normalizeCategoryColor('#A03F6B'), '#a03f6b')
  for (const invalid of ['red', '#fff', '#ff0044aa', 'var(--seed-accent)', 'url(x)', '']) assert.throws(() => module.normalizeCategoryColor(invalid))
  assert.deepEqual(module.moveCategoryId(['a','b','c'], 'a', 'c'), ['b','c','a'])
  assert.deepEqual(module.moveCategoryId(['a','b','c'], 'c', 'a'), ['c','a','b'])
  assert.deepEqual(module.moveCategoryId(['a','b','c'], 'missing', 'a'), ['a','b','c'])
  assert.deepEqual(module.moveCategoryId(['a','b','c'], 'b', 'b'), ['a','b','c'])
})

test('server category appearance overrides builtin swatches in reading components', async () => {
  const { getCategoryInfo } = await import('../src/components/knowledge/knowledgeConstants.js')
  assert.equal(getCategoryInfo('physical_laws', [{ id:'physical_laws', label:'物理定律', color:'#a03f6b', is_custom:false }]).color, '#a03f6b')
})

test('reorder acknowledgements must preserve every requested ID', async () => {
  const { categoryMutationResult } = await import('../src/lib/knowledgeCategories.js')
  const result = { success: true, revision: 4, items: [{ id:'b' },{ id:'a' }] }
  assert.equal(categoryMutationResult(result, 'order', ['b','a']), result)
  assert.throws(() => categoryMutationResult({ ...result, items:[{id:'b'},{id:'b'}] }, 'order', ['b','a']))
  assert.throws(() => categoryMutationResult({ ...result, items:[{id:'a'},{id:'b'}] }, 'order', ['b','a']))
})

test('unfiltered category catalog preserves empty categories and renamed labels under filtered facets', async () => {
  const module = await import('../src/lib/knowledgeCategories.js').catch(() => ({}))
  assert.equal(typeof module.mergeCategoryFacets, 'function')
  const catalog = [{ id: 'user_private', label: '用户私有', count: 3 }, { id: 'custom_a', label: '改名后的分类', count: 2, entry_count: 4, revision: 2 }, { id: 'custom_empty', label: '空分类', count: 0 }]
  const result = module.mergeCategoryFacets(catalog, [{ id: 'custom_a', label: '旧名称', count: 1 }])
  assert.equal(result.length, 3)
  assert.equal(result[1].label, '改名后的分类')
  assert.equal(result[1].count, 1)
  assert.equal(result[1].entry_count, 4)
  assert.equal(result[2].count, 0)
  assert.equal(result[0].count, 0)
})

test('category writes require canonical acknowledgement and deletion never implies entry deletion', async () => {
  const module = await import('../src/lib/knowledgeCategories.js').catch(() => ({}))
  assert.equal(typeof module.categoryMutationResult, 'function')
  assert.throws(() => module.categoryMutationResult({ success: true }, 'create'))
  assert.throws(() => module.categoryMutationResult({ success: false, category: { id: 'x' } }, 'create'))
  assert.equal(module.categoryMutationResult({ success: true, category: { id: 'custom_a', label: '分类', color:'#24583b', revision: 1 } }, 'create').category.id, 'custom_a')
  assert.throws(() => module.categoryMutationResult({success:true,category:{id:'wrong',label:'分类',color:'#24583b',revision:2}},'update','custom_a'))
  assert.throws(() => module.categoryMutationResult({success:true,category:{id:'custom_a',label:'分类',revision:2}},'update','custom_a'))
  assert.throws(() => module.categoryMutationResult({ success: true, id: 'different', target_category: 'user_private' }, 'delete', 'custom_a'))
  assert.equal(module.categoryMutationResult({ success: true, id: 'custom_a', target_category: 'user_private', moved_count: 4 }, 'delete', 'custom_a').moved_count, 4)
})
