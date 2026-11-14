export function readingPage({ total = 0, offset = 0, limit = 24, count = 0 }) {
  return {
    start: count ? offset + 1 : 0, end: count ? Math.min(total, offset + count) : 0, total,
    previous: Math.max(0, offset - limit), next: offset + limit,
    hasPrevious: offset > 0, hasNext: offset + limit < total,
  }
}

export function entryOrigin(item = {}) {
  if (item.is_override) return { id: 'override', label: '用户已修改' }
  if (item.is_user) return { id: 'user', label: '用户条目' }
  return { id: 'builtin', label: '内置条目' }
}

export function knowledgeCategoryLabel(value, categories) {
  return categories.find(category => category.id === value || category.label === value)?.label || value
}

export function knowledgeCategoryValue(value, categories) {
  return categories.find(category => category.id === value || category.label === value)?.id || value
}

export function createKnowledgeCategory(name, categories = []) {
  const label = String(name || '').replace(/\s+/g, ' ').trim()
  if (!label) throw new Error('请填写分类名称')
  if ([...label].length > 40) throw new Error('分类名称最多 40 个字')
  if (['all', '全部分类', '全部知识', '全部理论'].includes(label.toLocaleLowerCase())) throw new Error('该名称用于分类导航，请换一个名称')
  const existing = categories.find(category => (category.is_custom ? [category.label] : [category.id, category.label, ...(category.alt_names || category.altNames || [])])
    .some(value => String(value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase() === label.toLocaleLowerCase()))
  if (existing) throw new Error(`分类「${existing.label}」已存在，请从列表中选择`)
  return { id: label, label, is_custom: true }
}

export function knowledgeRelationEvidence(node, kind, { isOverride = false } = {}) {
  if (kind === 'base') return isOverride ? '覆盖记录：当前用户修改基于该内置条目' : '派生记录：当前条目以此条目为基础'
  if (kind === 'derived') return '派生记录：此条目以当前条目为基础'
  const provenance = typeof node.provenance === 'object' ? node.provenance?.source : node.provenance
  if (kind === 'related' || provenance === 'entry.related_ids') return '用户建立的知识关联'
  const bindingState = node.binding_state || node.provenance?.binding_state
  if (bindingState === 'unreviewed') return '条目显式声明，标识尚未审定'
  if (provenance === 'curated_property_aliases') return '已审定性质标识/别名映射'
  if (provenance === 'entry.properties' || kind === 'property') return '条目显式声明的关联性质'
  return '图谱记录的关联'
}

export function sourceRecords(sources) {
  if (!sources) return []
  return (Array.isArray(sources) ? sources : [sources])
    .filter(Boolean).map(source => typeof source === 'string' ? { title: source } : { ...source })
}

export function propertyChoices(values = [], known = []) {
  return values.map(value => {
    const raw = typeof value === 'string' ? value : value.property_id || value.id || value.name || value.label || ''
    const match = known.find(property => [property.id, property.property_id, property.label, property.name].includes(raw))
    return match ? { id: match.property_id || match.id, label: match.label || match.name || raw, bound: match.binding_state !== 'unreviewed' && match.bound !== false } :
      { id: raw, label: typeof value === 'string' ? value : value.label || value.name || raw, bound: false }
  }).filter(property => property.id)
}

const textOf = value => typeof value === 'string' ? value : value?.text || value?.description || value?.label || value?.name || value?.id || ''
export const conditionText = conditions => Array.isArray(conditions) ? conditions.map(textOf).filter(Boolean).join('\n') : conditions || ''
export const sourcesText = sources => sourceRecords(sources).map(source => Object.entries(source)
  .map(([key, value]) => key === 'title' ? value : `${key}: ${Array.isArray(value) ? value.join(', ') : typeof value === 'object' ? JSON.stringify(value) : value}`)
  .join('\n')).join('\n\n')
export const splitValues = value => [...new Set(String(value || '').split(/[,，\n]/).map(part => part.trim()).filter(Boolean))]

export function knowledgeLinkIds(values, excludeId) {
  return [...new Set((Array.isArray(values) ? values : []).filter(value => typeof value === 'string').map(value => value.trim()).filter(value => value && value !== excludeId))]
}

export function knowledgeLinkSelection(ids = [], summaries = []) {
  const byId = new Map(summaries.filter(item => item?.id).map(item => [item.id, item]))
  return knowledgeLinkIds(ids).map(id => {
    const item = byId.get(id)
    if (!item || item.unavailable) return { id, title: '', unavailable: true }
    return { ...item, id, title: item.title || item.name || '', unavailable: false }
  })
}

export function createKnowledgeLinkSearch(request, onState, { excludeId, delay = 250 } = {}) {
  let sequence = 0, timer, controller
  const cancel = () => { sequence += 1; clearTimeout(timer); controller?.abort() }
  return {
    search(value) {
      cancel()
      const current = sequence, keyword = String(value || '').trim()
      const active = new AbortController()
      controller = active
      onState({ status: 'loading', items: [], total: 0, error: '' })
      timer = setTimeout(async () => {
        try {
          const result = await request({ keyword, limit: 24, offset: 0 }, { signal: active.signal })
          if (current !== sequence || active.signal.aborted) return
          if (!Array.isArray(result?.items)) throw new Error('关联知识响应不完整')
          const unique = new Map(result.items.filter(item => item?.id && item.id !== excludeId && !item.unavailable).map(item => [item.id, item]))
          onState({ status: 'ready', items: [...unique.values()], total: result.total ?? result.items.length, error: '' })
        } catch (failure) {
          if (current === sequence && !active.signal.aborted) onState({ status: 'error', items: [], total: 0, error: failure.message || '无法读取关联知识' })
        }
      }, delay)
    },
    dispose: cancel,
  }
}

export function createKnowledgeDraft(initial, mode = 'create') {
  return {
    title: initial ? `${initial.title || initial.name || ''}${mode === 'fork' ? ' (派生版)' : ''}` : '',
    category: initial?.category || 'user_private',
    formula: initial?.formula || initial?.claim?.formula || '',
    description: initial?.description || initial?.claim?.text || initial?.content || '',
    conditionsText: conditionText(initial?.conditions),
    propertiesText: Array.isArray(initial?.properties) ? initial.properties.map(property => typeof property === 'string' ? property : property.property_id || property.id || property.name || property.label || '').filter(Boolean).join(', ') : initial?.properties || '',
    tagsText: Array.isArray(initial?.tags) ? initial.tags.map(textOf).join(', ') : initial?.tags || '',
    relatedIds: knowledgeLinkIds(initial?.related_ids, mode === 'edit' ? initial?.id : undefined),
    sourcesText: sourcesText(initial?.sources || initial?.source),
    preferred: Boolean(initial?.preferred || initial?.user_preference === 'preferred'),
    parameters: initial?.parameters?.map(parameter => typeof parameter === 'string' ? { name: parameter } : { ...parameter, desc: parameter.desc || parameter.description || '' }) || [],
  }
}

export function buildKnowledgePayload(draft, initial, mode, idFactory = () => globalThis.crypto.randomUUID()) {
  if (!draft.title.trim()) throw new Error('请填写理论知识标题')
  const editing = mode === 'edit'
  const relatedIds = knowledgeLinkIds(draft.relatedIds, editing ? initial?.id : undefined)
  if (relatedIds.length > 100) throw new Error('关联知识最多选择 100 项')
  const payload = {
    id: editing ? initial.id : `user_${idFactory()}`,
    title: draft.title.trim(), category: draft.category.trim() || 'user_private',
    formula: draft.formula.trim(), description: draft.description.trim(),
    conditions: draft.conditionsText.split('\n').map(value => value.trim()).filter(Boolean),
    properties: splitValues(draft.propertiesText), tags: splitValues(draft.tagsText),
    related_ids: relatedIds,
    parameters: draft.parameters.filter(parameter => Object.values(parameter).some(value => String(value || '').trim())),
    sources: draft.sourcesText.trim(),
    preferred: draft.preferred, user_preference: draft.preferred ? 'preferred' : 'neutral',
    is_user: editing ? Boolean(initial.is_user) : true,
  }
  if (editing) {
    // Legacy rich citations/conditions are readable, but omitted when unchanged:
    // the write API merges fields and accepts string citations/string conditions.
    if (initial.sources && typeof initial.sources !== 'string' && draft.sourcesText === sourcesText(initial.sources)) delete payload.sources
    if (initial.conditions?.some?.(value => typeof value !== 'string') && draft.conditionsText === conditionText(initial.conditions)) delete payload.conditions
    payload.revision = initial.revision ?? 0
    payload.expected_revision = initial.revision ?? 0
    if (!initial.is_user || initial.is_override) payload.is_override = true
    if (initial.base_id) payload.base_id = initial.base_id
  }
  if (mode === 'fork') payload.base_id = initial?.id
  return payload
}

export function createSaveGate() {
  let pending = false
  return {
    get pending() { return pending },
    async run(operation) {
      if (pending) return { saved: false, reason: 'pending' }
      pending = true
      try { return { saved: true, value: await operation() } }
      finally { pending = false }
    },
  }
}

export async function loadKnowledgeReportEditor(block, api) {
  const id = block.entry_id || block.id
  if (!id) throw new Error('报告未记录可编辑的知识条目编号，可将内容派生为新条目')
  const item = await api.getKnowledgeItem(id)
  if (!item?.id) throw new Error('未能读取当前知识条目，可将报告内容派生为新条目')
  return { mode: 'edit', item }
}

export async function prepareKnowledgeReportCopy(block, api) {
  const sourceId = block.entry_id || block.id
  const provenance = `报告来源：${block.title || '未命名报告条目'}${sourceId ? `\n报告原条目编号：${sourceId}` : ''}`
  const item = {
    ...block,
    description: block.claim?.text || block.claim?.statement || block.description || block.text || '',
    sources: [sourcesText(block.sources || block.source), provenance].filter(Boolean).join('\n\n'),
  }
  try {
    const canonical = sourceId ? await api.getKnowledgeItem(sourceId) : null
    if (canonical?.id) return { mode: 'fork', item: { ...item, id: canonical.id }, baseUnavailable: false }
  } catch {
    // Copying frozen evidence remains possible when its original is unavailable.
  }
  delete item.id
  delete item.base_id
  delete item.revision
  return { mode: 'create', item: { ...item, report_copy: true }, baseUnavailable: true }
}

function validateLatestKnowledge(base, latest) {
  if (!latest?.id || latest.id !== base.id) throw new Error('最新版本与当前编辑条目不匹配')
  if (!Number.isInteger(latest.revision) || latest.revision < (base.revision ?? 0)) throw new Error('最新版本缺少有效修订，请重新读取')
}

export async function loadKnowledgeConflict(base, loadLatest) {
  const latest = await loadLatest(base.id)
  validateLatestKnowledge(base, latest)
  return latest
}

export function knowledgeDraftComparison(draft, latest) {
  const current = createKnowledgeDraft(latest, 'edit')
  const fields = [['title', '标题'], ['category', '分类'], ['formula', '公式'], ['description', '核心阐述'],
    ['parameters', '参数'], ['conditionsText', '适用条件'], ['relatedIds', '关联知识'], ['propertiesText', '关联物理量'], ['tagsText', '标签'], ['sourcesText', '来源'], ['preferred', '科研优选']]
  const format = value => typeof value === 'boolean' ? value ? '是' : '否' : Array.isArray(value) ? JSON.stringify(value, null, 2) : String(value ?? '')
  return fields.filter(([field]) => format(draft[field]) !== format(current[field]))
    .map(([field, label]) => ({ field, label, draft: format(draft[field]), latest: format(current[field]) }))
}

export function acceptKnowledgeConflict(draft, base, latest) {
  validateLatestKnowledge(base, latest)
  return { draft, base: latest }
}

export async function saveKnowledgeReportDraft(payload, mode, api, onSaved) {
  if (mode === 'edit' && (!payload.id || !Number.isInteger(payload.expected_revision))) throw new Error('缺少条目修订，请重新读取后编辑')
  if (!['edit', 'create', 'fork'].includes(mode)) throw new Error('未知的知识编辑模式')
  const result = mode === 'edit' ? await api.updateKnowledge(payload.id, payload) : await api.createKnowledge(payload)
  onSaved?.(result, mode)
  return result
}

export async function saveKnowledgeReportPreference(block, preferred, api, onSaved) {
  const { item } = await loadKnowledgeReportEditor(block, api)
  const result = await api.setKnowledgePreference(item.id, {
    preference: preferred ? 'preferred' : 'neutral', weight_boost: preferred ? 1.5 : 1,
    expected_revision: item.revision ?? 0,
  })
  onSaved?.(result)
  return result
}
