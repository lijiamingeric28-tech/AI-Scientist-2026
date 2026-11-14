export function mergeCategoryFacets(catalog = [], facets = []) {
  const counts = new Map(facets.map(category => [category.id, category.count || 0]))
  return catalog.map(category => ({ ...category, count: counts.get(category.id) || 0 }))
}

export function categoryMutationResult(result, operation, id) {
  const valid = result?.success === true && (operation === 'order'
    ? Array.isArray(result.items) && Number.isInteger(result.revision) && result.items.length === id.length && new Set(result.items.map(item => item.id)).size === id.length && result.items.every((item, index) => item.id === id[index])
    : operation === 'delete'
    ? result.id === id && typeof result.target_category === 'string' && Number.isFinite(result.moved_count)
    : typeof result.category?.id === 'string' && result.category.id.trim() && typeof result.category.label === 'string' && Number.isInteger(result.category.revision)
      && /^#[0-9a-f]{6}$/.test(result.category.color || '') && (operation === 'create' || result.category.id === id))
  if (!valid) throw new Error('服务器未确认分类保存，请重新读取后重试')
  return result
}

export function normalizeCategoryColor(value) {
  if (typeof value !== 'string' || !/^#[0-9a-f]{6}$/i.test(value)) throw new Error('请输入完整的十六进制颜色，例如 #24583b')
  return value.toLowerCase()
}

export function moveCategoryId(ids, source, target) {
  const from = ids.indexOf(source), to = ids.indexOf(target)
  if (from < 0 || to < 0 || from === to) return ids
  const moved = [...ids]
  moved.splice(from, 1); moved.splice(to, 0, source)
  return moved
}

export function rebaseCategoryDraft(base, draft, latest) {
  return {
    name: draft.name.trim() === base.label ? latest.label : draft.name,
    color: draft.color.toLowerCase() === base.color?.toLowerCase() ? latest.color : draft.color,
  }
}
