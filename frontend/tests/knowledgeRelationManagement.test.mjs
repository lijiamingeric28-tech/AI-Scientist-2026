import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const helpers = await import('../src/components/knowledge/knowledgeRelationManagement.js').catch(() => ({}))
const base = { id: 'focus', revision: 2, library_revision: 8, related_ids: ['out', 'both'], relations: { related: [
  { id: 'out', title: 'Outgoing', direction: 'outgoing' },
  { id: 'both', title: 'Both', direction: 'both' },
  { id: 'in', title: 'Incoming', direction: 'incoming' },
] } }

test('detail relation edits distinguish outgoing selections from incoming removals and require snapshot versions', () => {
  assert.equal(typeof helpers.buildRelationPayload, 'function')
  const draft = helpers.createRelationDraft(base)
  assert.deepEqual(draft, { relatedIds: ['out', 'both'], unlinkIncomingIds: [] })
  assert.equal(helpers.relationDraftChanged(base, draft), false)
  assert.deepEqual(helpers.buildRelationPayload(base, { relatedIds: ['both', 'new', 'new'], unlinkIncomingIds: ['in'] }), {
    related_ids: ['both', 'new'], unlink_incoming_ids: ['in'], expected_revision: 2, expected_library_revision: 8,
  })
  assert.equal(helpers.relationDraftChanged(base, { ...draft, unlinkIncomingIds: ['in'] }), true)
  assert.throws(() => helpers.buildRelationPayload(base, { relatedIds: [], unlinkIncomingIds: ['out'] }), /传入关联/)
  assert.throws(() => helpers.buildRelationPayload({ ...base, library_revision: undefined }, draft), /修订/)
  assert.throws(() => helpers.buildRelationPayload(base, { ...draft, relatedIds: Array.from({length:101}, (_,i)=>`item${i}`) }), /100/)
})

test('conflict rebase preserves local link changes while retaining independently added relationships', () => {
  assert.equal(typeof helpers.rebaseRelationDraft, 'function')
  const latest = { ...base, revision: 3, library_revision: 10, related_ids: ['out', 'both', 'remote'], relations: { related: [
    ...base.relations.related, { id: 'other-in', direction: 'incoming' },
  ] } }
  const rebased = helpers.rebaseRelationDraft(base, { relatedIds: ['both', 'new'], unlinkIncomingIds: ['in'] }, latest)
  assert.deepEqual(rebased, { relatedIds: ['both', 'remote', 'new'], unlinkIncomingIds: ['in'] })
  assert.throws(() => helpers.rebaseRelationDraft(base, helpers.createRelationDraft(base), { ...latest, id: 'different' }), /不匹配/)
  assert.throws(() => helpers.rebaseRelationDraft(base, helpers.createRelationDraft(base), { ...latest, related_ids: undefined }), /不完整/)
  assert.throws(() => helpers.rebaseRelationDraft(base, helpers.createRelationDraft(base), { ...latest, relations: undefined }), /不完整/)
})

test('relation save acknowledgement rejects false success and a different entry', () => {
  assert.equal(typeof helpers.relationMutationResult, 'function')
  const result = { success:true, id:'focus', revision:3, library_revision:9, affected_ids:['focus','in'], entry: {
    ...base, revision:3, library_revision:9, relations:{related:[]},
  } }
  assert.equal(helpers.relationMutationResult(result, 'focus'), result)
  assert.throws(()=>helpers.relationMutationResult({...result,success:false}, 'focus'), /确认/)
  assert.throws(()=>helpers.relationMutationResult({...result,entry:{...result.entry,id:'different'}}, 'focus'), /确认/)
  assert.throws(()=>helpers.relationMutationResult({...result,entry:{...result.entry,relations:undefined}}, 'focus'), /确认/)
})

let server, Drawer, Manager
before(async () => {
  server=await createServer({server:{middlewareMode:true},appType:'custom',logLevel:'error'})
  Drawer=(await server.ssrLoadModule('/src/components/knowledge/KnowledgeDrawer.jsx')).default
  try { Manager=(await server.ssrLoadModule('/src/components/knowledge/KnowledgeRelationManager.jsx')).default } catch {}
})
after(async()=>server?.close())
const render=(component,props)=>renderToStaticMarkup(React.createElement(component,props))

test('real entry details expose relation management, while hubs and readonly entries cannot modify bindings', () => {
  assert.match(render(Drawer,{item:{...base,title:'Focus'},onManageRelations:()=>{}}), /管理关联/)
  const readonly = render(Drawer,{item:{...base,title:'Focus'},readOnly:true,onManageRelations:()=>{}})
  const manageButton = [...readonly.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find(match => match[2].includes('管理关联'))
  assert.match(manageButton[1], /disabled=""/)
  assert.doesNotMatch(render(Drawer,{item:{id:'cat',kind:'category',label:'Category'},onManageRelations:()=>{}}), /管理关联/)
})

test('relation manager renders searchable outgoing selection plus incoming direction removal controls', () => {
  assert.equal(typeof Manager,'function')
  const html=render(Manager,{item:{...base,title:'Focus'}})
  assert.match(html,/aria-label="搜索关联知识"/)
  assert.match(html,/aria-label="解除传入关联：Incoming"/)
  assert.match(html,/aria-label="解除传入关联：Both"/)
  assert.doesNotMatch(html,/aria-label="解除传入关联：Outgoing"/)
  assert.match(html,/保存关联/)
})
