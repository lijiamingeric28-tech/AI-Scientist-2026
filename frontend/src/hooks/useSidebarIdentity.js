export function queryKey(row) {
  return typeof row.query_ref === 'string' ? row.query_ref : row.query_ref?.id || ''
}

export function sidebarIdentity(view) {
  if (!view?.target?.main_id) return null
  return {
    target: view.target.user_mentions?.[0] || view.target.main_id,
    properties: (view.properties || []).map(property => property.name).join(' · '),
    question: view.messages?.find(message => message.role === 'user')?.text,
  }
}
