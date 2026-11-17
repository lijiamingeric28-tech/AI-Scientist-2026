// Working measurements include superseded/excluded rows; use the pinned list.
export function completionSummary(stage, resources = {}) {
  const base = stage.deliverySummary
  if (!base) return { summary: null, recordCounts: {} }
  const head = resources.head?.status === 'success' ? resources.head.data : null
  const records = resources.records?.status === 'success' ? resources.records.data : null
  const aggregates = records?.aggregates || records?.page?.aggregates
  const counts = {}
  if (aggregates?.fields) {
    for (const p of stage.properties || []) counts[p.property_id] = 0
    for (const field of aggregates.fields) counts[field.property_id || field.field] = field.count
  } else if (Array.isArray(records) && !records.page) {
    for (const p of stage.properties || []) counts[p.property_id] = records.filter(r => r.property_id === p.property_id || r.field_name === p.name).length
  }
  return { summary: { ...base,
    records: aggregates?.total ?? head?.display_counts?.records ?? base.records,
    materials: head?.display_counts?.material_groups ?? null,
    figures: head?.display_counts?.figures ?? base.figures,
  }, recordCounts: counts }
}
