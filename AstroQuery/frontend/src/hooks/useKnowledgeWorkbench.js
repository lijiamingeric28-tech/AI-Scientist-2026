import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import {
  getKnowledge, getKnowledgeSummary, getKnowledgeGraph, getKnowledgeItem,
  createKnowledge, updateKnowledge, updateKnowledgeRelations, deleteKnowledge, restoreKnowledge, setKnowledgePreference,
  getKnowledgeCategories, createKnowledgeCategory, updateKnowledgeCategory, deleteKnowledgeCategory, reorderKnowledgeCategories,
} from '@/services/api'
import {
  buildKnowledgeQuery, buildKnowledgeGraphQuery, createWorkbenchState, workbenchReducer,
  createKnowledgeCache, createLatestKnowledgeRequest, performKnowledgeMutation, knowledgeSceneKey, mergeKnowledgeEntry,
} from '@/lib/knowledgeWorkbench'
import { categoryMutationResult } from '@/lib/knowledgeCategories'
import { relationMutationResult } from '@/components/knowledge/knowledgeRelationManagement'

const idle = { key: null, status: 'idle', data: null, error: null, readOnly: true }
function browserStorage() { try { return globalThis.sessionStorage } catch { return undefined } }

function useKnowledgeResource(key, read, enabled, cache, revision) {
  const [resource, setResource] = useState(idle)
  const reader = useRef(null)
  if (!reader.current) reader.current = createLatestKnowledgeRequest({ cache, onChange: setResource })
  useEffect(() => {
    if (!enabled) { reader.current.cancel(); return }
    reader.current.run(key, read)
    return () => reader.current.cancel()
  }, [key, read, enabled, revision])
  // Never render a previous query under the current filters, even before effects run.
  return resource.key === key ? resource : { ...idle, key, status: enabled ? 'loading' : 'idle' }
}

const valid = (kind, data) => {
  const okay = kind === 'list' ? Array.isArray(data?.items) && Number.isFinite(data?.total)
    : kind === 'summary' ? Array.isArray(data?.categories) && Number.isFinite(data?.total) && Number.isFinite(data?.matched_total)
      : kind === 'categories' ? Array.isArray(data?.items) && data.items.every(item => typeof item.id === 'string' && typeof item.label === 'string')
      : kind === 'graph' ? Array.isArray(data?.nodes) && Array.isArray(data?.edges) && data?.meta
        : typeof data?.id === 'string'
  if (!okay) throw new Error('知识库响应不完整，请重新读取')
  return data
}

export function useKnowledgeWorkbench({ memory, initialMode, active = true, taskProperties = [] }) {
  const [state, dispatch] = useReducer(workbenchReducer, memory, createWorkbenchState)
  const [keyword, setKeyword] = useState(state.keyword.trim())
  const [revision, bumpRevision] = useReducer(n => n + 1, 0)
  const [pendingIds, setPendingIds] = useState(new Set())
  const [patches, setPatches] = useState({})
  const pendingRef = useRef(new Set())
  const cache = useRef(null)
  if (!cache.current) cache.current = createKnowledgeCache({ storage: browserStorage() })
  useEffect(() => { if (initialMode === 'graph' || initialMode === 'matrix') dispatch({ type: 'view', mode: initialMode }) }, [initialMode])
  useEffect(() => { const timer = setTimeout(() => setKeyword(state.keyword.trim()), 250); return () => clearTimeout(timer) }, [state.keyword])
  useEffect(() => { Object.assign(memory, state, { searchQuery: state.keyword, selectedCategory: state.filters.category, preferredOnly: state.filters.preferred_only }) }, [memory, state])
  const bindingKey = JSON.stringify(taskProperties)
  const filters = useMemo(() => ({ ...state.filters, keyword, property_ids: state.taskScoped ? taskProperties : state.filters.property_ids }), [state.filters, keyword, state.taskScoped, bindingKey])
  const commonKey = JSON.stringify(buildKnowledgeQuery(filters, 'filters'))
  const listQuery = useMemo(() => buildKnowledgeQuery({ ...filters, offset: state.offset, limit: state.tableLimit }, state.listMode), [commonKey, state.offset, state.tableLimit, state.listMode])
  const graphQuery = useMemo(() => buildKnowledgeGraphQuery(filters, state.scene, state.graphLimit), [commonKey, state.scene, state.graphLimit])
  const summaryFilters=buildKnowledgeQuery(filters,'filters');delete summaryFilters.sort
  const summaryFilterKey=JSON.stringify(summaryFilters),hasSummaryFilters=Object.keys(summaryFilters).length>0
  const directoryRead=useCallback(async options=>valid('summary',await getKnowledgeSummary({projection:'directory'},options)),[])
  const summaryRead = useCallback(async options => valid('summary', await getKnowledgeSummary({...JSON.parse(summaryFilterKey),projection:'stats'}, options)), [summaryFilterKey])
  const listRead = useCallback(async options => valid('list', await getKnowledge(listQuery, options)), [listQuery])
  const graphRead = useCallback(async options => valid('graph', await getKnowledgeGraph(graphQuery, options)), [graphQuery])
  const detailRead = useCallback(async options => valid('detail', await getKnowledgeItem(state.selectedId, options)), [state.selectedId])
  const categoriesRead = useCallback(async options => valid('categories', await getKnowledgeCategories(options)), [])
  const loadEntry = useCallback(async entryId => valid('detail', await getKnowledgeItem(entryId)), [])
  const directory=useKnowledgeResource('summary:directory:v2',directoryRead,active,cache.current,revision)
  const filteredSummary = useKnowledgeResource(`summary:stats:${summaryFilterKey}`, summaryRead, active&&hasSummaryFilters, cache.current, revision)
  const summary=hasSummaryFilters?filteredSummary:directory
  const list = useKnowledgeResource(`list:${JSON.stringify(listQuery)}`, listRead, active && state.mode === 'matrix', cache.current, revision)
  const graph = useKnowledgeResource(`graph:${JSON.stringify(graphQuery)}`, graphRead, active && state.mode === 'graph', cache.current, revision)
  const detail = useKnowledgeResource(`detail:${state.selectedId}`, detailRead, active && Boolean(state.selectedId), cache.current, revision)
  const categoryResource = useKnowledgeResource('knowledge-category-catalog', categoriesRead, active, cache.current, revision)
  const main = state.mode === 'graph' ? graph : list
  const readOnly = summary.readOnly || directory.readOnly || main.readOnly || categoryResource.readOnly
  const items = useMemo(() => (list.data?.items || []).map(item => mergeKnowledgeEntry(item, patches[item.id])), [list.data, patches])
  const graphData = useMemo(() => ({ ...(graph.data || {}), nodes: (graph.data?.nodes || []).map(item => mergeKnowledgeEntry(item, patches[item.id])), edges: graph.data?.edges || [] }), [graph.data, patches])
  const selectedItem = detail.data ? mergeKnowledgeEntry(detail.data, patches[detail.data.id]) : null
  const reload = useCallback(() => bumpRevision(), [])
  const getEntry = useCallback(entryId => selectedItem?.id === entryId ? selectedItem : items.find(item => item.id === entryId) || graphData.nodes.find(item => item.id === entryId), [selectedItem, items, graphData])
  const mutate = useCallback(async (entryId, request, { optimistic, canonical = false, selectAfter = false, categoryOperation = false } = {}) => {
    if (categoryOperation ? categoryResource.readOnly : readOnly || (selectedItem?.id === entryId && detail.readOnly)) throw new Error('当前为只读状态，请成功连接知识库后重试')
    if (pendingRef.current.has(entryId)) throw new Error('该条目正在保存，请稍候')
    pendingRef.current.add(entryId); setPendingIds(new Set(pendingRef.current))
    const previous = patches[entryId]
    const removePatch = () => setPatches(current => { const next = { ...current }; if (previous) next[entryId] = previous; else delete next[entryId]; return next })
    try {
      return await performKnowledgeMutation({
        request: async () => { const response = await request(); if (canonical && !(response?.entry || response)?.id) throw new Error('服务器未返回已保存条目'); return response },
        optimistic: optimistic ? () => setPatches(current => ({ ...current, [entryId]: optimistic })) : undefined,
        rollback: removePatch,
        commit: result => { const entry = result.entry || (canonical ? result : null); if (entry?.id) { setPatches(current => ({ ...current, [entry.id]: entry })); if (selectAfter) dispatch({ type: 'select', id: entry.id }) } },
        invalidate: () => { cache.current.clear(); bumpRevision() },
      })
    } finally { pendingRef.current.delete(entryId); setPendingIds(new Set(pendingRef.current)) }
  }, [readOnly, categoryResource.readOnly, selectedItem, detail.readOnly, patches])
  const preference = useCallback((entryId, preferred) => {
    const entry = getEntry(entryId)
    return mutate(entryId, () => setKnowledgePreference(entryId, { preference: preferred ? 'preferred' : 'neutral', weight_boost: preferred ? 1.5 : 1, expected_revision: entry?.revision ?? 0 }), { canonical: true, optimistic: { preferred, user_preference: preferred ? 'preferred' : 'neutral' } })
  }, [getEntry, mutate])
  const save = useCallback((payload, mode) => {
    const entryId = mode === 'edit' ? payload.id : '__create__'
    return mutate(entryId, () => mode === 'edit'
      ? updateKnowledge(payload.id, { ...payload, expected_revision: payload.expected_revision ?? payload.revision ?? getEntry(payload.id)?.revision ?? 0 })
      : createKnowledge(payload), { canonical: true, selectAfter: true })
  }, [getEntry, mutate])
  const manageRelations = useCallback(async (entryId, payload) => {
    const result = await mutate(entryId, async () => relationMutationResult(await updateKnowledgeRelations(entryId, payload), entryId), { canonical: true })
    // Incoming removals also change their source entries. Do not let earlier
    // preference/edit patches mask those canonical updates after the refresh.
    setPatches(current => Object.fromEntries(Object.entries(current).filter(([id]) => id === entryId || !result.affected_ids.includes(id))))
    return result
  }, [mutate])
  const remove = useCallback(async entryId => {
    const result = await mutate(entryId, () => deleteKnowledge(entryId, { expected_revision: getEntry(entryId)?.revision ?? 0 }))
    if (state.selectedId === entryId) dispatch({ type: 'select', id: null })
    setPatches(current => { const next = { ...current }; delete next[entryId]; return next })
    return result
  }, [getEntry, mutate, state.selectedId])
  const restore = useCallback(entryId => mutate(entryId, () => restoreKnowledge(entryId, { expected_revision: getEntry(entryId)?.revision ?? 0 }), { canonical: true }), [getEntry, mutate])
  const createCategory = useCallback(label => mutate('category:create', async () => categoryMutationResult(await createKnowledgeCategory({ label }), 'create'), { categoryOperation: true }), [mutate])
  const renameCategory = useCallback((category, label) => mutate(`category:${category.id}`, async () => categoryMutationResult(await updateKnowledgeCategory(category.id, { label, expected_revision: category.revision ?? 0 }), 'rename', category.id), { categoryOperation: true }), [mutate])
  const updateCategory = useCallback((category, changes) => mutate(`category:${category.id}`, async () => categoryMutationResult(await updateKnowledgeCategory(category.id, { ...changes, expected_revision: category.revision ?? 0 }), 'update', category.id), { categoryOperation: true }), [mutate])
  const reorderCategories = useCallback((ids, expectedRevision) => mutate('category:order', async () => categoryMutationResult(await reorderKnowledgeCategories({ ids, expected_revision: expectedRevision }), 'order', ids), { categoryOperation: true }), [mutate])
  const removeCategory = useCallback(async (category, target) => {
    const result = await mutate(`category:${category.id}`, async () => categoryMutationResult(await deleteKnowledgeCategory(category.id, { target_category: target, expected_revision: category.revision ?? 0 }), 'delete', category.id), { categoryOperation: true })
    dispatch({ type: 'categoryRemoved', id: category.id, target: result.target_category })
    setPatches({})
    return result
  }, [mutate])
  // A deletion or preference filter can shorten the last page.
  useEffect(() => {
    if (state.mode === 'matrix' && list.status === 'ready' && state.offset > 0 && list.data.total <= state.offset) dispatch({ type: 'page', offset: Math.max(0, Math.ceil(list.data.total / listQuery.limit) - 1) * listQuery.limit })
  }, [list.status, list.data, state.offset, state.mode, listQuery.limit])
  return { state, dispatch, filters, directory, properties:directory.data?.properties||[], summary, list, graph, detail, main, categoryResource, readOnly, items, graphData, selectedItem, pendingIds, reload, loadEntry, preference, save, manageRelations, remove, restore, createCategory, renameCategory, updateCategory, reorderCategories, removeCategory, sceneKey: knowledgeSceneKey(state, filters) }
}
