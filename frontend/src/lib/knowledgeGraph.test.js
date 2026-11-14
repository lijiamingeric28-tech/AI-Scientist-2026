import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'

async function graph() {
  const url = new URL('./knowledgeGraph.js', import.meta.url)
  assert.ok(existsSync(url), 'the graph behavior module is required')
  return import(url)
}

const fixture = (count = 80) => ({
  nodes: [
    { id: 'prop_temperature', kind: 'property', is_property: true, label: '有效温度' },
    ...Array.from({ length: count }, (_, i) => ({ id: `entry-${i}`, kind: 'entry', label: `Knowledge ${i}`, category: `category-${i % 5}`, preferred: i === 3 })),
  ],
  edges: Array.from({ length: count }, (_, i) => ({ source: `entry-${i}`, target: 'prop_temperature' })),
})

test('overview constellation follows the saved category order rather than alphabetical IDs', async () => {
  const { layoutKnowledgeGraph } = await graph()
  const nodes = layoutKnowledgeGraph([{id:'category:a',kind:'category',order:5},{id:'category:b',kind:'category',order:0}], [])
  assert.ok(nodes.find(node=>node.id==='category:b').y < nodes.find(node=>node.id==='category:a').y)
})

test('registry type hubs remain visually distinct and navigable at overview zoom', async () => {
  const { layoutKnowledgeGraph, selectGraphLabels, graphNodeAction } = await graph()
  const nodes = layoutKnowledgeGraph([
    {id:'type:G',kind:'property',source_kind:'type',label:'星系',count:58},
    {id:'property:mass',kind:'entry',source_kind:'property',label:'质量',category:'physical'},
  ], [{source:'type:G',target:'property:mass'}])
  assert.ok(nodes[0].radius !== nodes[1].radius)
  assert.ok(nodes.find(n=>n.source_kind==='type').radius >= 20)
  const labels = selectGraphLabels(nodes, [], {camera:{x:300,y:250,scale:.5},width:600,height:500})
  assert.ok(labels.some(label=>label.id==='type:G'))
  assert.deepEqual(graphNodeAction(nodes.find(n=>n.id==='type:G')), {type:'property',id:'type:G'})
})

test('dense registry type hubs and labels leave their count discs unobstructed', async () => {
  const {layoutKnowledgeGraph,selectGraphLabels}=await graph()
  const points=layoutKnowledgeGraph(Array.from({length:66},(_,i)=>({id:`type:${i}`,kind:'property',source_kind:'type',label:`Type ${i}`,count:40})),[])
  for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++)assert.ok(Math.hypot(points[i].x-points[j].x,points[i].y-points[j].y)>=points[i].radius+points[j].radius+6)
  const camera={x:600,y:440,scale:.7},labels=selectGraphLabels(points,[],{camera,width:1200,height:880})
  assert.ok(labels.length)
  for(const label of labels)for(const point of points){
    const x=point.x*camera.scale+camera.x,y=point.y*camera.scale+camera.y
    assert.ok(Math.hypot(x-Math.max(label.x,Math.min(x,label.x+label.width)),y-Math.max(label.y,Math.min(y,label.y+label.height)))>=point.radius*camera.scale+3)
  }
})

test('constellation coordinates are finite, deterministic and independent of response ordering', async () => {
  const { layoutKnowledgeGraph } = await graph()
  const data = fixture(199)
  const a = layoutKnowledgeGraph(data.nodes, data.edges)
  const b = layoutKnowledgeGraph([...data.nodes].reverse(), [...data.edges].reverse())
  const positions = nodes => Object.fromEntries(nodes.map(n => [n.id, [n.x, n.y, n.radius]]))
  assert.deepEqual(positions(a), positions(b))
  assert.ok(a.every(n => Number.isFinite(n.x) && Number.isFinite(n.y) && n.radius > 0))
  assert.equal(a.length, 200)
})

test('one-entry focus is centered and property/category nodes retain distinct radii', async () => {
  const { layoutKnowledgeGraph } = await graph()
  const data = fixture(12)
  data.nodes.push({ id: 'category:law', kind: 'category', category: 'law', label: '物理定律', count: 60 })
  const nodes = layoutKnowledgeGraph(data.nodes, data.edges, { focusId: 'entry-3' })
  const focus = nodes.find(n => n.id === 'entry-3')
  assert.deepEqual([focus.x, focus.y], [0, 0])
  assert.ok(nodes.find(n => n.kind === 'category').radius > nodes.find(n => n.kind === 'property').radius)
  assert.ok(nodes.find(n => n.kind === 'property').radius > nodes.find(n => n.id === 'entry-4').radius)
})

test('dense property hubs occupy separate orbits rather than overlapping in one ring', async () => {
  const { layoutKnowledgeGraph } = await graph()
  const nodes = layoutKnowledgeGraph(Array.from({ length: 100 }, (_, i) => ({ id: `property-${i}`, kind: 'property', label: `Property ${i}` })), [])
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    assert.ok(Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y) >= nodes[i].radius + nodes[j].radius + 6, `property hubs ${i}/${j} must not overlap`)
  }
})

test('overview category discs stay outside dense hub rings and labels never cover their counts', async () => {
  const { layoutKnowledgeGraph, selectGraphLabels } = await graph()
  const points = layoutKnowledgeGraph([
    ...Array.from({ length: 74 }, (_, i) => ({ id: `property-${i}`, kind: 'property', label: `Property ${i}` })),
    ...Array.from({ length: 6 }, (_, i) => ({ id: `category-${i}`, kind: 'category', count: 100, label: `Category ${i}` })),
  ], [])
  const categories = points.filter(n => n.kind === 'category')
  for (const category of categories) for (const hub of points.filter(n => n.kind === 'property')) {
    assert.ok(Math.hypot(category.x - hub.x, category.y - hub.y) > category.radius + hub.radius + 30)
  }
  const camera = { x: 600, y: 440, scale: .7 }
  const labels = selectGraphLabels(points, [], { camera, width: 1200, height: 880 })
  for (const label of labels) for (const category of categories) {
    const x = category.x * camera.scale + camera.x, y = category.y * camera.scale + camera.y, radius = category.radius * camera.scale
    const closestX = Math.max(label.x, Math.min(x, label.x + label.width)), closestY = Math.max(label.y, Math.min(y, label.y + label.height))
    assert.ok(Math.hypot(x - closestX, y - closestY) >= radius + 3, `${label.id} must not cover ${category.id}`)
  }
})

test('camera fitting contains empty, isolated and dense scenes without invalid coordinates', async () => {
  const { layoutKnowledgeGraph, fitGraphCamera } = await graph()
  for (const count of [0, 1, 80, 199]) {
    const data = fixture(count)
    const nodes = layoutKnowledgeGraph(data.nodes, [])
    const camera = fitGraphCamera(nodes, { width: 640, height: 500 })
    assert.ok([camera.x, camera.y, camera.scale].every(Number.isFinite))
    assert.ok(camera.scale > 0)
    for (const n of nodes) {
      assert.ok(n.x * camera.scale + camera.x >= 24)
      assert.ok(n.x * camera.scale + camera.x <= 616)
      assert.ok(n.y * camera.scale + camera.y >= 24)
      assert.ok(n.y * camera.scale + camera.y <= 476)
    }
  }
  assert.ok(Number.isFinite(fitGraphCamera([], { width: 0, height: 0 }).scale))
})

test('zoom preserves the world position under the cursor and clamps extreme scale', async () => {
  const { zoomGraphCamera } = await graph()
  const before = { x: 150, y: 80, scale: 0.8 }
  const point = { x: 430, y: 275 }
  const after = zoomGraphCamera(before, 1.4, point)
  assert.ok(Math.abs((point.x - before.x) / before.scale - (point.x - after.x) / after.scale) < 1e-8)
  assert.ok(Math.abs((point.y - before.y) / before.scale - (point.y - after.y) / after.scale) < 1e-8)
  assert.ok(zoomGraphCamera(before, Infinity, point).scale <= 4)
  assert.ok(zoomGraphCamera(before, 0, point).scale > 0)
})

test('resizing a detail pane preserves zoom and the world point at the viewport center', async () => {
  const module = await graph()
  assert.equal(typeof module.resizeGraphCamera, 'function')
  const before = { x: 144, y: 220, scale: 1.8 }
  const a = { width: 1180, height: 700 }, b = { width: 820, height: 700 }
  const resized = module.resizeGraphCamera(before, a, b)
  assert.equal(resized.scale, before.scale)
  assert.equal((a.width / 2 - before.x) / before.scale, (b.width / 2 - resized.x) / resized.scale)
  assert.equal((a.height / 2 - before.y) / before.scale, (b.height / 2 - resized.y) / resized.scale)
})

test('aggregate nodes navigate to the full matrix rather than an undefined category', async () => {
  const module = await graph()
  assert.equal(typeof module.graphNodeAction, 'function')
  assert.deepEqual(module.graphNodeAction({ id: 'aggregate:categories', kind: 'aggregate', category: null }), { type: 'matrix' })
  assert.deepEqual(module.graphNodeAction({ id: 'category:law', kind: 'category', category: 'law' }), { type: 'category', id: 'law' })
  assert.deepEqual(module.graphNodeAction({ id: 'prop_age', kind: 'property', property_id: 'age' }), { type: 'property', id: 'age' })
  assert.deepEqual(module.graphNodeAction({ id: 'law-1', kind: 'entry' }), { type: 'entry', id: 'law-1' })
})

test('neighbors only include existing nodes and selected labels win collision avoidance', async () => {
  const { graphNeighbors, selectGraphLabels } = await graph()
  const nodes = [
    { id: 'chosen', kind: 'entry', label: 'Selected original evidence', x: 0, y: 0, radius: 8 },
    { id: 'other', kind: 'entry', label: 'Overlapping label', x: 1, y: 0, radius: 8 },
  ]
  const links = [{ source: 'chosen', target: 'missing' }, { source: 'chosen', target: 'other' }]
  assert.deepEqual([...graphNeighbors(nodes, links, 'chosen')].sort(), ['chosen', 'other'])
  const labels = selectGraphLabels(nodes, links, { camera: { x: 200, y: 150, scale: 1 }, width: 400, height: 300, selectedId: 'chosen' })
  assert.equal(labels[0].id, 'chosen')
  for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
    const a = labels[i], b = labels[j]
    assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y)
  }
})

test('frame scheduling coalesces invalidations, stops at rest and cancels on disposal', async () => {
  const { createGraphFrameScheduler } = await graph()
  const callbacks = new Map()
  let next = 0, draws = 0
  const scheduler = createGraphFrameScheduler(cb => { callbacks.set(++next, cb); return next }, id => callbacks.delete(id), () => { draws++; return false })
  scheduler.invalidate(); scheduler.invalidate(); scheduler.invalidate()
  assert.equal(callbacks.size, 1)
  const [id, cb] = callbacks.entries().next().value
  callbacks.delete(id); cb(100)
  assert.equal(draws, 1)
  assert.equal(callbacks.size, 0, 'a stable scene must not perpetually schedule another frame')
  scheduler.invalidate(); scheduler.dispose()
  assert.equal(callbacks.size, 0)
  scheduler.invalidate()
  assert.equal(callbacks.size, 0)
})

test('focused edge names describe confirmed adjacent links and avoid existing reading labels', async () => {
  const module = await graph()
  assert.equal(typeof module.selectGraphEdgeLabels, 'function')
  const nodes = [{ id: 'a', x: -100, y: 0, radius: 8 }, { id: 'b', x: 100, y: 0, radius: 8 }, { id: 'c', x: 0, y: 100, radius: 8 }]
  const edges = [{ id: 'explicit', source: 'a', target: 'b', label: '显式物理量关联', relation_type: 'explicit_property' }, { id: 'unrelated', source: 'b', target: 'c', label: '非相邻关系' }, { id: 'candidate', source: 'a', target: 'c', label: '近似匹配', relation_type: 'candidate' }]
  const options = { camera: { x: 200, y: 150, scale: 1 }, width: 400, height: 300 }
  assert.deepEqual(module.selectGraphEdgeLabels(nodes, edges, options), [])
  const labels = module.selectGraphEdgeLabels(nodes, edges, { ...options, selectedId: 'a', labels: [{ x: 180, y: 120, width: 50, height: 24 }] })
  assert.equal(labels.length, 1)
  assert.equal(labels[0].id, 'explicit')
  assert.equal(labels[0].text, '显式物理量关联')
  assert.ok(labels[0].y >= 148 || labels[0].y + labels[0].height <= 116)
})
