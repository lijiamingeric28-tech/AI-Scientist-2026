// Presentation adapters only. Original reports and record values stay intact.
export function percentScore(score) {
  return typeof score === 'number' && Number.isFinite(score) ? (score <= 1 ? score * 100 : score) : null
}

export function dimensionSummary(scoring, qualityState) {
  const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100
  const normalize = value => value > 1 ? value / 100 : value
  const direct = Object.entries(scoring?.dimension_scores || {}).filter(([, value]) => valid(value))
  if (direct.length) return { scores: Object.fromEntries(direct.map(([key, value]) => [key, normalize(value)])), method: '报告汇总维度' }
  const sources = Object.values(qualityState?.sources || {})
  const keys = new Set(sources.flatMap(source => Object.keys(source.quality_scoring?.dimension_scores || {})))
  const scores = {}, methods = new Set()
  for (const key of keys) {
    const rows = sources.filter(source => valid(source.quality_scoring?.dimension_scores?.[key]))
    const weighted = rows.filter(source => Number.isFinite(source.record_count) && source.record_count > 0)
    const selected = weighted.length ? weighted : rows
    if (!selected.length) continue
    methods.add(weighted.length ? '按有效来源记录数加权' : '有效来源等权平均')
    const denominator = selected.reduce((sum, source) => sum + (weighted.length ? source.record_count : 1), 0)
    scores[key] = selected.reduce((sum, source) => sum + normalize(source.quality_scoring.dimension_scores[key]) * (weighted.length ? source.record_count : 1), 0) / denominator
  }
  return { scores, method: [...methods].join('；') || '未提供维度评分' }
}

export function fieldDistribution(records) {
  const counts = new Map()
  for (const record of records || []) {
    const field = record.field_name || '未标识性质'
    counts.set(field, (counts.get(field) || 0) + 1)
  }
  return [...counts].map(([field, count]) => ({ field, count })).sort((a, b) => b.count - a.count || a.field.localeCompare(b.field))
}
export function modificationReport(quality) {
  const value = quality?.quality_report?.report_state?.normalization?.modifications
  if (Array.isArray(value)) return { count: value.length, rows: value }
  if (value && typeof value === 'object') {
    const rows = Array.isArray(value.details) ? value.details :
      Object.entries(value.details || {}).flatMap(([layer, items]) =>
        Array.isArray(items) ? items.map(item => ({ ...item, layer: item.layer || layer })) : [])
    return { count: typeof value.total === 'number' ? value.total : rows.length, rows }
  }
  return { count: null, rows: [] }
}

export function qualitySummary(quality) {
  return quality?.quality_report?.output_state?.quality_summary || null
}
export function executionTraceCount(quality) {
  const qr = quality?.quality_report
  const rows = qr?.data_state?.data_trace ?? qr?.data_trace
  return Array.isArray(rows) ? rows.length : null
}
export function executionTraces(quality) {
  const qr = quality?.quality_report
  const rows = qr?.data_state?.data_trace ?? qr?.data_trace
  return Array.isArray(rows) ? rows : []
}

export function riskMessages(quality) {
  const r = qualitySummary(quality)?.risk_indicators || {}
  const messages = []
  if (r.has_unconverted_units) messages.push(`${r.unconverted_unit_count ?? '部分'} 项单位未转换`)
  if (r.validation_passed === false) messages.push('输出校验未通过')
  if (r.has_unresolved_conflicts) messages.push('存在未解决冲突')
  if (r.has_human_review_items) messages.push('存在待人工复核项')
  if (r.data_completeness_warning) messages.push('数据完整性警告')
  return messages
}

export function exactRecordIds(item) {
  return [...new Set([item?.record_id, ...(Array.isArray(item?.record_ids) ? item.record_ids : [])].filter(Boolean))]
}

export function modifiedRecordIds(quality) {
  const qr = quality?.quality_report
  const ids = new Set(modificationReport(quality).rows.flatMap(exactRecordIds))
  const traces = qr?.output_state?.traceability?.per_record_trace || {}
  for (const [id, trace] of Object.entries(traces)) {
    if (Array.isArray(trace?.modifications) && trace.modifications.length) ids.add(id)
  }
  return ids
}

const NUMBER = '[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?'
export function parseMeasurement(raw) {
  if (typeof raw === 'number') return Number.isFinite(raw) ? { value: raw } : null
  const s = String(raw ?? '').trim().replace(/−/g, '-').replace(/×/g, 'x')
  let m = s.match(new RegExp(`^(${NUMBER})$`))
  if (m) return Number.isFinite(Number(m[1])) ? { value: Number(m[1]) } : null
  m = s.match(new RegExp(`^(${NUMBER})\\s*(?:±|\\+/-|\\+\\-)\\s*(${NUMBER})$`))
  if (m && Number(m[2]) >= 0) {
    const result = { value: Number(m[1]), lower: Number(m[1]) - Number(m[2]), upper: Number(m[1]) + Number(m[2]) }
    return Object.values(result).every(Number.isFinite) ? result : null
  }
  m = s.match(new RegExp(`^(${NUMBER})\\s*(?:x|\\*)\\s*10\\s*\\^\\s*([+-]?\\d+)$`, 'i'))
  if (m) { const value = Number(m[1]) * 10 ** Number(m[2]); return Number.isFinite(value) ? { value } : null }
  m = s.match(new RegExp(`^(${NUMBER})\\s*(?:–|—|-)\\s*(${NUMBER})$`))
  if (m && Number(m[1]) <= Number(m[2]) && [m[1], m[2]].every(value => Number.isFinite(Number(value)))) return { lower: Number(m[1]), upper: Number(m[2]), interval: true }
  m = s.match(new RegExp(`^(${NUMBER})\\s*\\+\\s*(\\d+(?:\\.\\d+)?)\\s*-\\s*(\\d+(?:\\.\\d+)?)$`))
  if (!m) m = s.match(new RegExp(`^(${NUMBER})\\s*\\^\\{\\+(${NUMBER})\\}\\s*_\\{-(${NUMBER})\\}$`))
  if (m) {
    if (Number(m[2]) < 0 || Number(m[3]) < 0) return null
    const result = { value: Number(m[1]), lower: Number(m[1]) - Number(m[3]), upper: Number(m[1]) + Number(m[2]) }
    return Object.values(result).every(Number.isFinite) ? result : null
  }
  return null
}

export function measurementGroups(records) {
  const groups = new Map()
  for (const record of records || []) {
    const key = JSON.stringify([record.entity_name, record.field_name, record.field_unit || ''])
    if (!groups.has(key)) groups.set(key, { key, entity: record.entity_name, field: record.field_name, unit: record.field_unit || '', rows: [] })
    groups.get(key).rows.push({ record, measurement: parseMeasurement(record.field_value) })
  }
  return [...groups.values()]
}
