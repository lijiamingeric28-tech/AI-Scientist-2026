function queryString(filters = {}) {
  return new URLSearchParams(Object.fromEntries(Object.entries(filters)
    .filter(([key, value]) => value != null && value !== '' && !(value === 'all' && ['category', 'source'].includes(key)))
    .map(([key, value]) => [key, Array.isArray(value) ? value.join(',') : value]))).toString()
}

export function createKnowledgeApi(request) {
  const read = (path, filters, options) => { const query = queryString(filters); return request(`${path}${query ? `?${query}` : ''}`, options) }
  const write = (path, method, body, options = {}) => request(path, { ...options, method, body: JSON.stringify(body) })
  const id = encodeURIComponent
  return {
    getKnowledgeCategories: (options = {}) => request('/knowledge/categories', options),
    reorderKnowledgeCategories: (data, options = {}) => write('/knowledge/categories/order', 'POST', data, options),
    createKnowledgeCategory: (data, options = {}) => write('/knowledge/categories', 'POST', data, options),
    updateKnowledgeCategory: (categoryId, data, options = {}) => write(`/knowledge/categories/${id(categoryId)}`, 'PUT', data, options),
    deleteKnowledgeCategory: (categoryId, { target_category = 'user_private', expected_revision, ...options } = {}) => read(`/knowledge/categories/${id(categoryId)}`, { target_category, expected_revision }, { ...options, method: 'DELETE' }),
    getKnowledge: (filters = {}, options = {}) => read('/knowledge', filters, options),
    getKnowledgeSummary: (filters = {}, options = {}) => read('/knowledge/summary', filters, options),
    getKnowledgeGraph: (filters = {}, options = {}) => read('/knowledge/graph', filters, options),
    getKnowledgeItem: (entryId, options = {}) => request(`/knowledge/${id(entryId)}`, options),
    createKnowledge: (data, options = {}) => write('/knowledge', 'POST', data, options),
    updateKnowledge: (entryId, data, options = {}) => write(`/knowledge/${id(entryId)}`, 'PUT', data, options),
    updateKnowledgeRelations: (entryId, data, options = {}) => write(`/knowledge/${id(entryId)}/relations`, 'PUT', data, options),
    deleteKnowledge: (entryId, { expected_revision, ...options } = {}) => read(`/knowledge/${id(entryId)}`, { expected_revision }, { ...options, method: 'DELETE' }),
    restoreKnowledge: (entryId, data = {}, options = {}) => write(`/knowledge/${id(entryId)}/restore`, 'POST', data, options),
    setKnowledgePreference: (entryId, preferenceOrObj, weightBoost, options = {}) => write(`/knowledge/${id(entryId)}/preference`, 'POST', typeof preferenceOrObj === 'object' && preferenceOrObj !== null ? preferenceOrObj : { preference: preferenceOrObj, ...(weightBoost != null ? { weight_boost: weightBoost } : {}) }, options),
  }
}
