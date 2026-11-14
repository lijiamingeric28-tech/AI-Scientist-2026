const tableSizes = [25, 50, 100]
const graphBudgets = [80, 120, 200]
const sourceKinds = ['all', 'builtin', 'user', 'override']
const sorts = ['name', 'relevance', 'preferred', 'updated']
const propertyIds = value => [...new Set((Array.isArray(value) ? value : String(value || '').split(',')).map(v => String(v).trim()).filter(Boolean))]

export function buildKnowledgeQuery(filters = {}, mode = 'cards') {
  const query = {}
  const keyword = String(filters.keyword || '').trim()
  if (keyword) query.keyword = keyword
  if (filters.category && filters.category !== 'all') query.category = filters.category
  if (sourceKinds.includes(filters.source) && filters.source !== 'all') query.source = filters.source
  if (filters.preferred_only) query.preferred_only = true
  const bindings = propertyIds(filters.property_ids)
  if (bindings.length) query.property_ids = bindings.join(',')
  query.sort = sorts.includes(filters.sort) ? filters.sort : 'name'
  if (mode !== 'filters') {
    query.offset = Math.max(0, Math.trunc(Number(filters.offset) || 0))
    query.limit = mode === 'table' ? (tableSizes.includes(Number(filters.limit)) ? Number(filters.limit) : 50) : 24
    query.view = 'summary'
  }
  return query
}

export function buildKnowledgeGraphQuery(filters, scene, budget = 80) {
  return { ...(scene.allAssociations ? {} : buildKnowledgeQuery(filters, 'filters')), view: scene.view, ...(scene.focus_id ? { focus_id: scene.focus_id } : {}), limit: graphBudgets.includes(Number(budget)) ? Number(budget) : 80 }
}

export function createWorkbenchState(memory = {}) {
  const category = memory.filters?.category || memory.selectedCategory || 'all'
  return {
    mode: memory.mode === 'matrix' ? 'matrix' : 'graph',
    listMode: memory.listMode === 'table' ? 'table' : 'cards',
    keyword: memory.keyword ?? memory.searchQuery ?? '',
    filters: { category, source: 'all', preferred_only: Boolean(memory.preferredOnly), property_ids: [], sort: 'name', ...memory.filters },
    taskScoped: Boolean(memory.taskScoped),
    selectedId: memory.selectedId || null,
    detailOpen: memory.detailOpen ?? Boolean(memory.selectedId),
    offset: Math.max(0, Number(memory.offset) || 0),
    tableLimit: tableSizes.includes(memory.tableLimit) ? memory.tableLimit : 50,
    graphLimit: graphBudgets.includes(memory.graphLimit) ? memory.graphLimit : 80,
    scene: memory.scene || { view: category === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false },
    history: [], cameras: memory.cameras || {},
  }
}

export function workbenchReducer(state, action) {
  switch (action.type) {
    case 'view': return { ...state, mode: action.mode === 'matrix' ? 'matrix' : 'graph' }
    case 'listMode': return { ...state, listMode: action.mode === 'table' ? 'table' : 'cards', offset: 0 }
    case 'keyword': return { ...state, keyword: action.value, offset: 0, history: [], scene: { view: state.filters.category === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false } }
    case 'filter': {
      const filters = { ...state.filters, [action.key]: action.value }
      return { ...state, filters, offset: 0, history: [], scene: { view: filters.category === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false } }
    }
    case 'taskScoped': return { ...state, taskScoped: action.value, offset: 0, history: [], scene: { view: state.filters.category === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false } }
    case 'page': return { ...state, offset: Math.max(0, Number(action.offset) || 0) }
    case 'pageSize': return { ...state, tableLimit: tableSizes.includes(Number(action.limit)) ? Number(action.limit) : 50, offset: 0 }
    case 'graphBudget': return { ...state, graphLimit: graphBudgets.includes(Number(action.limit)) ? Number(action.limit) : 80 }
    case 'select': return { ...state, selectedId: action.id || null, detailOpen: Boolean(action.id) }
    case 'dismissDetail': return { ...state, detailOpen: false }
    case 'categoryRemoved': {
      const category = state.filters.category === action.id ? action.target || 'user_private' : state.filters.category
      return { ...state, filters: { ...state.filters, category }, offset: 0, history: [], scene: { view: category === 'all' ? 'overview' : 'category', focus_id: null, allAssociations: false } }
    }
    case 'navigate': return { ...state, mode: 'graph', detailOpen: false, filters: action.filters ? { ...state.filters, ...action.filters } : state.filters, offset: 0, scene: action.scene, history: [...state.history, { scene: state.scene, filters: state.filters, offset: state.offset }].slice(-20) }
    case 'back': {
      const previous = state.history.at(-1)
      return previous ? { ...state, ...previous, history: state.history.slice(0, -1) } : state
    }
    case 'camera': return { ...state, cameras: { ...state.cameras, [action.key]: action.value } }
    default: return state
  }
}

export function knowledgeSceneKey(state, filters = { ...state.filters, keyword: state.keyword }) {
  return JSON.stringify({ ...buildKnowledgeQuery(filters, 'filters'), ...state.scene, limit: state.graphLimit || 80 })
}

export function resolveKnowledgeNavigation(value, { nodes = [], properties = [], relations } = {}) {
  const id = typeof value === 'string' ? value : value?.id
  const node = typeof value === 'object' ? value : nodes.find(item => item.id === id)
  if (node?.kind === 'entry') return { kind: 'entry', id }
  if (node?.kind === 'aggregate' && !node.category && !node.category_id) return { kind: 'matrix' }
  if (node?.kind === 'category' || node?.kind === 'aggregate') return { kind: 'category', id: node.category || node.category_id || id }
  const property = node?.kind === 'property' || node?.is_property ? node : [...(relations?.properties || []), ...properties].find(item => (typeof item === 'string' ? item : item.id || item.property_id) === id)
  if (property) return { kind: 'property', id: typeof property === 'string' ? property : property.property_id || property.id }
  return { kind: 'entry', id }
}

export function selectedKnowledgeShell(selectedId, { detail, items = [], nodes = [] } = {}) {
  if (!selectedId) return null
  return (detail?.id === selectedId ? detail : null) || items.find(item => item.id === selectedId) || nodes.find(node => node.id === selectedId) || { id: selectedId, title: '正在读取…', loading_only: true }
}

export function searchKnowledgeProperties(properties, keyword = '', selectedId = '', limit = 30) {
  const text = String(keyword).trim().toLocaleLowerCase()
  const matching = properties.filter(property => !text || `${property.id} ${property.label || ''}`.toLocaleLowerCase().includes(text))
  const items = matching.slice(0, Math.max(1, Math.min(30, limit)))
  const selected = properties.find(property => property.id === selectedId)
  if (selected && !items.some(property => property.id === selectedId)) items.unshift(selected)
  return { items, total: matching.length, hasMore: matching.length > limit }
}

export function mergeKnowledgeEntry(item, patch) {
  if (!patch || (Number.isFinite(patch.revision) && Number.isFinite(item.revision) && item.revision > patch.revision)
    || (Number.isFinite(patch.library_revision) && Number.isFinite(item.library_revision) && item.library_revision > patch.library_revision)) return item
  return { ...item, ...patch }
}

export function createKnowledgeCache({ storage, storageKey = 'astroquery.knowledge.workbench.v1', maxEntries = 24 } = {}) {
  let entries = new Map()
  let generation = 0
  try {
    const saved = JSON.parse(storage?.getItem(storageKey) || '[]')
    if (Array.isArray(saved)) entries = new Map(saved.filter(row => Array.isArray(row) && row[1]?.data != null && Number.isFinite(row[1]?.savedAt)).slice(-maxEntries))
  } catch { /* Browser storage may be unavailable. Memory cache remains usable. */ }
  const persist = () => { try { storage?.setItem(storageKey, JSON.stringify([...entries])) } catch { /* Quota failure cannot turn a successful API response into an error. */ } }
  return {
    get generation() { return generation },
    get: key => entries.get(key) || null,
    set(key, data) { entries.delete(key); entries.set(key, { data, savedAt: Date.now() }); while (entries.size > maxEntries) entries.delete(entries.keys().next().value); persist() },
    clear() { generation++; entries.clear(); try { storage?.removeItem(storageKey) } catch { /* Storage is optional. */ } },
  }
}

export function createLatestKnowledgeRequest({ cache, onChange }) {
  let sequence = 0
  let controller
  return {
    async run(key, request) {
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      const current = ++sequence
      const generation = cache.generation
      const cached = cache.get(key)
      onChange({ key, status: 'loading', data: cached?.data || null, savedAt: cached?.savedAt, error: null, readOnly: true })
      try {
        const data = await request({ signal })
        if (current !== sequence || signal.aborted || generation !== cache.generation) return
        cache.set(key, data)
        onChange({ key, status: 'ready', data, savedAt: cache.get(key)?.savedAt, error: null, readOnly: false })
        return data
      } catch (error) {
        if (current !== sequence || signal.aborted || generation !== cache.generation) return
        onChange({ key, status: cached ? 'stale' : 'error', data: cached?.data || null, savedAt: cached?.savedAt, error, readOnly: true })
      }
    },
    cancel() { sequence++; controller?.abort() },
  }
}

export async function performKnowledgeMutation({ request, optimistic, rollback, commit, invalidate }) {
  optimistic?.()
  let result
  try {
    result = await request()
    if (!result || result.success === false) throw new Error('服务器未确认保存，请重试')
  } catch (error) {
    rollback?.()
    throw error
  }
  commit?.(result)
  invalidate?.()
  return result
}
