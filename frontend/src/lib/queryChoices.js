// A request may have several valid definitions, or share one with another
// request. Keep the model's groups and the registry's IDs independent.
export function propertyChoices(question, draft) {
  const bindings = question?.property_catalog?.bindings || []
  const byId = new Map(bindings.map(b => [b.property_id, b]))
  const covered = new Set()
  const groups = (draft.property_requests || question?.model_property_selection?.requests || []).flatMap(request => {
    const ids = request.candidate_property_ids || (request.candidates || []).map(c => c.property_id)
    const options = [...new Set(ids)].filter(id => byId.has(id)).map(id => {
      covered.add(id)
      return {binding: byId.get(id), candidate: request.candidates?.find(c => c.property_id === id)}
    })
    return options.length ? [{text: request.text, options}] : []
  })
  const rest = bindings.filter(b => !covered.has(b.property_id))
  if (rest.length) groups.push({text: groups.length ? '其他可选性质' : '可选性质', options: rest.map(binding => ({binding}))})
  return groups
}

// Only display prose deliberately written for this surface. Old drafts may
// contain registry IDs or model-local P/S labels even in free-text fields.
export function publicCopy(text) {
  return typeof text === 'string' && !/(?:^|[^A-Za-z0-9])[PS]\d+(?![A-Za-z0-9])|\bprop-[\w-]+/u.test(text) ? text.trim() : ''
}

export function scopeChoice(issue, draft) {
  const request = (draft.property_requests || []).find(r => r.text === issue.request_text)
  if (issue.uncovered_text) return '本次略过“' + issue.uncovered_text + '”'
  if (request?.candidate_property_ids?.length) return '“' + request.text + '”仅按我勾选的定义查询'
  const subject = issue.request_text || publicCopy(issue.description)
  return subject ? '本次略过“' + subject + '”' : '本次略过此项要求'
}
