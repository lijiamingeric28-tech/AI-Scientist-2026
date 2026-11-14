/** Deterministic world-space geometry and demand-driven drawing for the knowledge atlas. */
const TAU = Math.PI * 2
const GOLDEN = Math.PI * (3 - Math.sqrt(5))
const finite = (value, fallback = 0) => Number.isFinite(value) ? value : fallback
export const nodeKind = node => node.kind || (node.is_property ? 'property' : 'entry')
export const endpoint = value => typeof value === 'object' ? value?.id : value
const idOrder = (a, b) => String(a.id).localeCompare(String(b.id), 'en')

function hash(text) {
  let value = 2166136261
  for (const c of String(text)) value = Math.imul(value ^ c.charCodeAt(0), 16777619)
  return (value >>> 0) / 4294967296
}

export function layoutKnowledgeGraph(inputNodes = [], inputEdges = [], { focusId } = {}) {
  const seen = new Set()
  const nodes = inputNodes.filter(n => n?.id && !seen.has(n.id) && seen.add(n.id)).map(n => ({ ...n, kind: nodeKind(n) })).sort(idOrder)
  const degree = new Map()
  for (const e of inputEdges) for (const id of [endpoint(e.source), endpoint(e.target)]) degree.set(id, (degree.get(id) || 0) + 1)
  const hubs = nodes.filter(n => n.kind === 'property')
  const categories = nodes.filter(n => n.kind === 'category' || n.kind === 'aggregate').sort((a,b) => finite(a.order, Number.MAX_SAFE_INTEGER) - finite(b.order, Number.MAX_SAFE_INTEGER) || idOrder(a,b))
  const entries = nodes.filter(n => n.kind === 'entry')
  const groups = new Map()
  for (const n of entries) {
    const category = n.category || 'uncategorized'
    if (!groups.has(category)) groups.set(category, [])
    groups.get(category).push(n)
  }
  const groupKeys = [...groups.keys()].sort()
  const focus = nodes.find(n => n.id === focusId)
  const assign = (node, x, y, radius, cluster) => Object.assign(node, { x, y, radius, cluster, degree: degree.get(node.id) || 0 })

  const registryHubs = hubs.some(n => n.source_kind === 'type')
  const hubInnerOrbit = registryHubs ? 120 : 96, hubRingGap = registryHubs ? 66 : 42
  const hubOuterOrbit = hubs.length > 1 ? hubInnerOrbit + Math.floor((hubs.length - 1) / 12) * hubRingGap : hubs.length ? hubInnerOrbit : 0
  hubs.forEach((n, i) => {
    const ring = Math.floor(i / 12), ringCount = Math.min(12, hubs.length - ring * 12)
    const angle = -Math.PI / 2 + (i % 12) * TAU / Math.max(1, ringCount) + ring * .14
    const orbit = hubs.length === 1 && !focus ? 0 : hubInnerOrbit + ring * hubRingGap
    assign(n, Math.cos(angle) * orbit, Math.sin(angle) * orbit, n.source_kind === 'type' ? 23 : 13, 'properties')
  })
  categories.forEach((n, i) => {
    const angle = -Math.PI / 2 + i * TAU / Math.max(1, categories.length)
    const orbit = categories.length === 1 && !hubs.length ? 0 : Math.max(330, hubOuterOrbit + 130)
    assign(n, Math.cos(angle) * orbit, Math.sin(angle) * orbit, 29 + Math.min(12, Math.sqrt(n.count || 1) / 2), n.category || n.id)
  })
  groupKeys.forEach((key, index) => {
    const group = groups.get(key)
    const angle = -Math.PI / 2 + index * TAU / Math.max(1, groupKeys.length)
    const orbit = groupKeys.length === 1 ? 0 : Math.max(330 + Math.sqrt(nodes.length) * 4, hubOuterOrbit + 160)
    const cx = Math.cos(angle) * orbit, cy = Math.sin(angle) * orbit
    group.forEach((n, i) => {
      const radial = hubs.length && groupKeys.length === 1
        ? Math.max(205, hubOuterOrbit + 80) + Math.floor(i / 24) * 36
        : 22 + Math.sqrt(i) * 24
      const a = groupKeys.length === 1 ? i * GOLDEN : i * GOLDEN + hash(key) * TAU
      assign(n, cx + Math.cos(a) * radial, cy + Math.sin(a) * radial, n.id === focusId ? 10 : n.preferred ? 8 : 6.5, key)
    })
  })
  if (focus) {
    assign(focus, 0, 0, focus.kind === 'entry' ? 10 : focus.radius, focus.cluster)
    // A lone focus must remain distinct from coincident hubs.
    for (const n of nodes) if (n !== focus && Math.hypot(n.x, n.y) < 45) {
      const angle = hash(n.id) * TAU
      n.x = Math.cos(angle) * 150; n.y = Math.sin(angle) * 150
    }
  }
  return nodes
}

export function fitGraphCamera(nodes, { width, height, padding = 64 }) {
  width = Math.max(1, finite(width, 1)); height = Math.max(1, finite(height, 1))
  if (!nodes.length) return { x: width / 2, y: height / 2, scale: 1 }
  let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity
  for (const n of nodes) {
    const margin = Math.max(n.radius || 8, 24)
    left = Math.min(left, n.x - margin); right = Math.max(right, n.x + margin)
    top = Math.min(top, n.y - margin); bottom = Math.max(bottom, n.y + margin)
  }
  const safePadding = Math.min(padding, Math.min(width, height) * .15)
  const scale = Math.min(1.45, Math.max(.001, Math.min((width - safePadding * 2) / Math.max(80, right - left), (height - safePadding * 2) / Math.max(80, bottom - top))))
  return { x: width / 2 - (left + right) / 2 * scale, y: height / 2 - (top + bottom) / 2 * scale, scale }
}

export function zoomGraphCamera(camera, factor, point) {
  const previous = Math.max(.001, finite(camera.scale, 1))
  const multiplier = factor === Infinity ? 1000 : Math.max(.001, finite(factor, 1))
  const scale = Math.max(.12, Math.min(4, previous * multiplier))
  return { x: point.x - (point.x - finite(camera.x)) * scale / previous, y: point.y - (point.y - finite(camera.y)) * scale / previous, scale }
}

export function resizeGraphCamera(camera, previous, next) {
  return { x: finite(camera.x) + (finite(next.width) - finite(previous.width)) / 2,
    y: finite(camera.y) + (finite(next.height) - finite(previous.height)) / 2,
    scale: Math.max(.001, finite(camera.scale, 1)) }
}

export function graphNodeAction(node) {
  if (!node?.id) return null
  const kind = nodeKind(node)
  if (kind === 'aggregate') return { type: 'matrix' }
  if (kind === 'category') return node.category || node.category_id ? { type: 'category', id: node.category || node.category_id } : { type: 'matrix' }
  if (kind === 'property') return { type: 'property', id: node.property_id || node.properties?.[0] || node.id }
  return { type: 'entry', id: node.entry_id || node.id }
}

export function graphNeighbors(nodes, edges, id) {
  const valid = new Set(nodes.map(n => n.id))
  const related = new Set(valid.has(id) ? [id] : [])
  for (const e of edges) {
    const source = endpoint(e.source), target = endpoint(e.target)
    if (source === id && valid.has(target)) related.add(target)
    if (target === id && valid.has(source)) related.add(source)
  }
  return related
}

const intersects = (a, b) => !(a.x + a.width + 4 <= b.x || b.x + b.width + 4 <= a.x || a.y + a.height + 4 <= b.y || b.y + b.height + 4 <= a.y)

export function selectGraphLabels(nodes, edges, { camera, width, height, selectedId, hoveredId, measureText = text => text.length * 7, maxLabels = 30 }) {
  const adjacent = graphNeighbors(nodes, edges, hoveredId || selectedId)
  const ranked = nodes.map(n => {
    const kind = nodeKind(n)
    const priority = (n.id === hoveredId ? 20000 : n.id === selectedId ? 19000 : adjacent.has(n.id) ? 9000 : 0)
      + (kind === 'category' || kind === 'aggregate' ? 5000 : kind === 'property' ? 3000 : n.preferred ? 1000 : 0) + (n.degree || 0)
    return { n, kind, priority }
  }).sort((a, b) => b.priority - a.priority || idOrder(a.n, b.n))
  const labels = []
  const protectedDiscs = nodes.filter(n => n.source_kind === 'type' || ['category', 'aggregate'].includes(nodeKind(n))).map(n => ({
    x: n.x * camera.scale + camera.x, y: n.y * camera.scale + camera.y, radius: (n.radius || 29) * camera.scale + 4,
  }))
  const coversDisc = box => protectedDiscs.some(disc => Math.hypot(disc.x - Math.max(box.x, Math.min(disc.x, box.x + box.width)), disc.y - Math.max(box.y, Math.min(disc.y, box.y + box.height))) < disc.radius)
  for (const { n, kind, priority } of ranked) {
    if (labels.length >= maxLabels) break
    if (kind === 'entry' && camera.scale < .78 && nodes.length > 24 && priority < 1000) continue
    const sx = n.x * camera.scale + camera.x, sy = n.y * camera.scale + camera.y
    if (sx < 0 || sx > width || sy < 0 || sy > height) continue
    const fullText = String(n.label || n.title || n.id)
    const text = fullText.length > 23 ? fullText.slice(0, 22) + '…' : fullText
    const fontSize = kind === 'category' ? 12.5 : kind === 'property' ? 11.5 : 11
    const labelWidth = Math.min(185, measureText(text, fontSize) + 18)
    const labelHeight = 24
    const gap = (n.radius || 7) * camera.scale + 7
    const candidates = [
      { x: sx - labelWidth / 2, y: sy + gap },
      { x: sx + gap, y: sy - labelHeight / 2 },
      { x: sx - labelWidth / 2, y: sy - gap - labelHeight },
    ].map(box => ({ ...box, x: Math.max(4, Math.min(width - labelWidth - 4, box.x)), y: Math.max(4, Math.min(height - labelHeight - 4, box.y)), width: labelWidth, height: labelHeight }))
    const box = candidates.find(candidate => !coversDisc(candidate) && !labels.some(placed => intersects(candidate, placed)))
    if (box) labels.push({ ...box, id: n.id, text, fullText, fontSize, priority })
  }
  return labels
}

export function selectGraphEdgeLabels(nodes, edges, { camera, width, height, selectedId, labels = [], measureText = text => text.length * 7, maxLabels = 8 }) {
  if (!selectedId) return []
  const byId = new Map(nodes.map(node => [node.id, node])), result = []
  for (const edge of edges) {
    if (result.length >= maxLabels) break
    if (!edge.label || edge.relation_type === 'candidate') continue
    const a = byId.get(endpoint(edge.source)), b = byId.get(endpoint(edge.target))
    if (!a || !b || (a.id !== selectedId && b.id !== selectedId)) continue
    const text = String(edge.label), labelWidth = Math.min(190, measureText(text, 10.5) + 16), labelHeight = 20
    const x = (a.x + b.x) / 2 * camera.scale + camera.x, y = (a.y + b.y) / 2 * camera.scale + camera.y
    const candidates = [-26, 8, -54, 36].map(offset => ({ x: x - labelWidth / 2, y: y + offset, width: labelWidth, height: labelHeight }))
    const box = candidates.find(candidate => candidate.x >= 4 && candidate.y >= 4 && candidate.x + candidate.width <= width - 4 && candidate.y + candidate.height <= height - 4
      && ![...labels, ...result].some(placed => intersects(candidate, placed))
      && !nodes.some(node => { const nx = node.x * camera.scale + camera.x, ny = node.y * camera.scale + camera.y; return Math.hypot(nx - Math.max(candidate.x, Math.min(nx, candidate.x + candidate.width)), ny - Math.max(candidate.y, Math.min(ny, candidate.y + candidate.height))) < (node.radius || 8) * camera.scale + 3 }))
    if (box) result.push({ ...box, id: edge.id || `${a.id}:${b.id}`, text })
  }
  return result
}

export function createGraphFrameScheduler(requestFrame, cancelFrame, render) {
  let pending = null, disposed = false
  const draw = time => {
    pending = null
    if (!disposed && render(time)) invalidate()
  }
  function invalidate() {
    if (!disposed && pending === null) pending = requestFrame(draw)
  }
  return { invalidate, dispose() { disposed = true; if (pending !== null) cancelFrame(pending); pending = null } }
}
