import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let server
let ListView, Drawer, Editor, CategoryManager
before(async () => {
  server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })
  ListView = (await server.ssrLoadModule('/src/components/knowledge/KnowledgeListView.jsx')).default
  Drawer = (await server.ssrLoadModule('/src/components/knowledge/KnowledgeDrawer.jsx')).default
  Editor = (await server.ssrLoadModule('/src/components/knowledge/KnowledgeEditorModal.jsx')).default
  try { CategoryManager = (await server.ssrLoadModule('/src/components/knowledge/KnowledgeCategoryManager.jsx')).default } catch {}
})
after(async () => { await server?.close() })
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))
const entries = count => Array.from({ length: count }, (_, index) => ({
  id: `entry_${index}`, title: `Entry ${index}`, category: 'physical_laws', description: 'A scientific summary.',
  formula: 'L = 4 \\pi R^2', properties: ['luminosity'], sources: 'Journal citation', is_user: false,
}))

test('standalone category manager exposes create and zero-entry custom categories while protecting builtins', () => {
  assert.equal(typeof CategoryManager, 'function')
  const html = render(CategoryManager, { categories: [
    { id: 'user_private', label: '用户私有', is_custom: false, count: 0 },
    { id: 'custom_empty', label: '独立空分类', is_custom: true, count: 0, entry_count: 0, revision: 1 },
  ] })
  assert.match(html, /分类管理/)
  assert.match(html, /创建分类/)
  assert.match(html, /独立空分类/)
  assert.match(html, /<em>内置<\/em>/)
  assert.doesNotMatch(html, /必须保存知识|随知识条目一起保存/)
})

test('knowledge detail is an accessible modal overlay with a dismissible backdrop', () => {
  const html = render(Drawer, { item: entries(1)[0] })
  assert.match(html, /role="dialog"/)
  assert.match(html, /aria-modal="true"/)
  assert.match(html, /aria-label="关闭详情遮罩"/)
})

test('editor offers explicit category selection and creation instead of an undiscoverable datalist', () => {
  const html = render(Editor, { isOpen: true, existingCategories: [{ id: '科研笔记', label: '科研笔记', is_custom: true }] })
  assert.match(html, /<select[^>]*aria-label="知识分类"/)
  assert.match(html, /新建分类/)
  assert.match(html, /value="科研笔记"/)
  assert.doesNotMatch(html, /<datalist/)
})

test('editor category options follow the authoritative catalog order without reinserting absent categories', () => {
  const html = render(Editor, { isOpen: true, existingCategories: [
    { id: 'equations_of_state_and_models', label: '状态方程与模型' },
    { id: 'physical_laws', label: '物理定律' },
    { id: 'user_private', label: '用户私有' },
  ] })
  const options = [...html.matchAll(/<option value="([^"]+)"/g)].map(match => match[1])
  assert.deepEqual(options, ['equations_of_state_and_models', 'physical_laws', 'user_private'])
})

test('cards render every item in the supplied server page with truthful 3000-entry pagination', () => {
  const html = render(ListView, { items: entries(24), total: 3000, offset: 24, limit: 24, selectedId: 'entry_23' })
  assert.equal((html.match(/data-entry-id=/g) || []).length, 24)
  assert.match(html, /Entry 23/)
  assert.match(html, /25–48/)
  assert.match(html, /3000/)
  assert.match(html, /aria-pressed="true"/)
  assert.doesNotMatch(html, /展开更多/)
})

test('matrix exposes all fifty server rows, selection and complete reading columns', () => {
  const html = render(ListView, { items: entries(50), mode: 'table', total: 3000, limit: 50, selectedId: 'entry_49' })
  assert.equal((html.match(/data-entry-id=/g) || []).length, 50)
  assert.match(html, /<table/)
  assert.match(html, /aria-selected="true"/)
  for (const label of ['名称', '公式', '关联物理量', '来源', '科研优选', '更新']) assert.ok(html.includes(label), label)
})

test('empty pages retain view controls and communicate missing results without inventing entries', () => {
  const html = render(ListView, { items: [], total: 0, mode: 'table' })
  assert.match(html, /卡片/)
  assert.match(html, /表格/)
  assert.match(html, /未找到/)
  assert.doesNotMatch(html, /data-entry-id=/)
})

test('card and table property previews are bounded while full detail retains all fifty properties', () => {
  const item = { id: 'many-properties', title: 'Survey', properties: Array.from({ length: 50 }, (_, index) => `custom_quantity_${index}`) }
  const cards = render(ListView, { items: [item] })
  assert.match(cards, /custom_quantity_2/)
  assert.doesNotMatch(cards, /custom_quantity_3/)
  assert.match(cards, /\+47/)
  const table = render(ListView, { items: [item], mode: 'table' })
  assert.match(table, /custom_quantity_1/)
  assert.doesNotMatch(table, /custom_quantity_2/)
  assert.match(table, /\+48/)
  const detail = render(Drawer, { item })
  assert.match(detail, /custom_quantity_49/)
})

test('a loading-only detail shell claims neither scientific category nor source origin', () => {
  const html = render(Drawer, { item: { id: 'unknown', title: '正在读取…', loading_only: true }, loading: true })
  assert.match(html, /正在载入完整详情/)
  assert.doesNotMatch(html, /物理定律|内置条目|用户条目|用户已修改/)
})

test('drawer preserves long formula and explicit missing-field labels instead of hiding information', () => {
  const formula = 'L = ' + '\\alpha + '.repeat(35) + '\\beta'
  const html = render(Drawer, { item: { id: 'long', title: 'Long formula', formula }, categories: [] })
  assert.match(html, /katex/)
  assert.match(html, /未提供/)
  for (const label of ['概览', '关联', '来源']) assert.ok(html.includes(label), label)
})

test('loading detail communicates pending content without declaring scientific fields missing', () => {
  const html = render(Drawer, { item: { id: 'loading', title: 'Loading entry' }, loading: true })
  assert.match(html, /正在载入完整详情/)
  assert.doesNotMatch(html, /未提供描述|未提供参数|未提供来源|未提供适用条件/)
})

test('modified detail separates its current sources from original builtin sources and labels unbound properties', () => {
  const html = render(Drawer, { item: {
    id: 'override', title: 'Modified', is_override: true, sources: 'User notebook', parameters: ['Original parameter note'],
    relations: { base: { id: 'override', title: 'Original', sources: 'Original reviewed paper' }, derived: [],
      properties: [{ id: 'custom', label: 'Custom quantity', binding_state: 'unreviewed' }] },
  } })
  assert.match(html, /User notebook/)
  assert.match(html, /Original reviewed paper/)
  assert.match(html, /未绑定/)
  assert.match(html, /Original parameter note/)
})

test('relations render identifier evidence and literal declarations without claiming unreviewed science is reviewed', () => {
  const html = render(Drawer, { item: { id: 'entry', title: 'Theory', relations: {
    properties: [{ id: 'mass', label: 'Known', provenance: 'curated_property_aliases', binding_state: 'curated' },
      { id: 'custom', label: 'Custom', provenance: 'entry.properties', binding_state: 'unreviewed' }],
    base: { id: 'base', title: 'Base' }, derived: [{ id: 'derived', title: 'Derived' }],
  } } })
  assert.match(html, /已审定性质标识\/别名映射/)
  assert.match(html, /条目显式声明，标识尚未审定/)
  assert.match(html, /派生记录：当前条目以此条目为基础/)
  assert.match(html, /派生记录：此条目以当前条目为基础/)
  const unknown = render(Drawer, { item: { id: 'unknown', title: 'Unknown', relations: {
    properties: [{ id: 'custom', label: 'Custom', provenance: 'entry.properties', binding_state: 'unreviewed' }], derived: [], base: null,
  } } })
  assert.doesNotMatch(unknown, /已审定性质标识|科学定律已验证/)
})

test('category and property hubs expose navigation without entry mutation actions', () => {
  for (const item of [{ id: 'cat', kind: 'category', category: 'physical_laws', label: 'Category' },
    { id: 'prop', kind: 'property', is_property: true, label: 'Property', property_id: 'mass' }]) {
    const html = render(Drawer, { item })
    assert.doesNotMatch(html, /编辑理论|确认删除|设为科研优选/)
    assert.match(html, /浏览关联条目/)
  }
})

test('editor opens grouped fields with preview and renders no dialog while closed', () => {
  assert.equal(render(Editor, { isOpen: false }), '')
  const html = render(Editor, { isOpen: true, initialData: entries(1)[0], mode: 'edit', readOnly: true })
  for (const label of ['基本信息', '公式与参数', '适用条件', '物理量与来源', '实时预览']) assert.ok(html.includes(label), label)
  assert.match(html, /disabled=""/)
})
