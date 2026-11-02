import { journalLabel } from './journal.js'
import { exactRecordIds, modificationReport, executionTraces, percentScore, measurementGroups, parseMeasurement } from './resultData.js'

// Display adapters only: never serialize unknown report objects into the UI.
export function readableText(value) {
  if (value == null) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''
  if (typeof value === 'string') {
    const text = value.trim()
    if (/^[\[{]/.test(text)) {
      try { return readableText(JSON.parse(text)) } catch { if (/^\{/.test(text)) return '' }
    }
    return text
  }
  if (Array.isArray(value)) return value.map(readableText).filter(Boolean).join('\n')
  if (typeof value === 'object') {
    for (const key of ['description', 'text', 'summary', 'message', 'reason', 'observation', 'interpretation', 'title']) {
      if (typeof value[key] === 'string' && value[key].trim()) return readableText(value[key])
    }
    if (typeof value.value === 'number' || typeof value.value === 'string') return [readableText(value.value), value.unit].filter(Boolean).join(' ')
  }
  return ''
}

export const DIMENSION_LABELS = { completeness: '完整性', consistency: '一致性', format: '格式规范', source_reliability: '来源可信度', conflict_risk: '多源一致性', extraction_quality: '提取质量' }
export const SOURCE_TYPES = { paper: '论文', database: '数据库', db: '数据库', supplement: '补充材料', supplementary: '补充材料' }
export const sourceType = type => ({ db:'database', supplementary:'supplement' })[type] || type
const EXTRACTION_LABELS = { database:'数据库查询', database_query:'数据库查询', csv_parsing:'CSV 解析', llm_text:'LLM 文本', llm_table:'LLM 表格', vlm_pdf:'VLM PDF', vlm_text:'VLM 文本', vlm_table:'VLM 表格', vlm_figure:'VLM 图像' }
export const extractionLabel = method => EXTRACTION_LABELS[method] || (typeof method === 'string' && method) || '该记录未提供'
export const isDatabaseRecord = (record, source) => ['database', 'db'].includes(source?.source_type) || ['database', 'database_query'].includes(record?.extraction_method)
// Report prose may contain several independently meaningful fields. Read all
// supported prose fields rather than treating an object as its first string.
export function reportParagraphs(value) {
  if (Array.isArray(value)) return value.flatMap(reportParagraphs)
  if (value && typeof value === 'object') {
    const keys = ['title', 'observation', 'interpretation', 'description', 'text', 'body', 'summary', 'message', 'reason']
    return [...new Set(keys.flatMap(key => typeof value[key] === 'string' ? reportParagraphs(value[key]) : []))]
  }
  const text = readableText(value)
  return text ? [text] : []
}
export function sourceName(source, id, short = false) {
  if (short && /^\d{4}[A-Za-z&]/.test(id || '')) return journalLabel(id)
  if (short && source?.journal) return [source.journal, source.year].filter(Boolean).join(' ')
  if (source?.title) return source.title
  return journalLabel(id) || '来源未提供'
}

export function sourceExplanation(source = {}, reason, label = key => key) {
  const dimensions = Object.entries(source.quality_scoring?.dimension_scores || {}).map(([key, value]) => ({ key, label: DIMENSION_LABELS[key] || key, score: percentScore(value) })).filter(row => row.score != null)
  const impacts = []
  const raw = reportParagraphs(reason).join('\n\n')
  const missing = source.completeness?.missing_expected_fields || source.missing_expected_fields
  if (Array.isArray(missing) && missing.length) impacts.push(`该来源未提供${missing.map(label).join('、')}。`)
  const consistency = source.consistency || {}
  if (Array.isArray(consistency.issues)) impacts.push(...consistency.issues.map(readableText).filter(Boolean))
  const anomalies = source.conflict_risk?.anomalies || source.conflict_risk?.conflicts
  if (Array.isArray(anomalies) && anomalies.length) impacts.push(`报告识别到 ${anomalies.length} 项记录异常。`)
  if (source.below_adaptive_threshold === true) impacts.push('该来源的性质覆盖率低于报告采用的阈值。')
  if (Array.isArray(source.issues)) impacts.push(...source.issues.map(issue => readableText(issue.message || issue.description || issue.reason)).filter(Boolean))
  for (const match of (!Array.isArray(missing) ? raw : '').matchAll(/missing_expected_fields:\s*\[([^\]]+)\]/g)) {
    const fields = [...match[1].matchAll(/['"]([^'"]+)['"]/g)].map(match => label(match[1]))
    if (fields.length) impacts.push(`该来源未提供${fields.join('、')}。`)
  }
  for (const match of raw.matchAll(/unit_mismatch:\s*(\w+)\s*\([^)]*\)\s*has\s*\[([^\]]+)\]\s*\(expected\s+([^)]*)\)/g)) {
    impacts.push(`${label(match[1])}的原始单位为 ${match[2].replace(/['"]/g, '')}，与要求的 ${match[3]} 不一致。`)
  }
  const anomaly = raw.match(/Anomalies:\s*(\d+)\s*record-level anomalies detected/i)
  if (anomaly) impacts.push(`报告识别到 ${anomaly[1]} 条记录级异常。`)
  if (raw.includes('below_adaptive_threshold')) impacts.push('该来源的性质覆盖率低于报告采用的阈值。')
  // Only the producer's decision-line format is internal, not words in prose.
  if (!impacts.length && raw && !/^Matrix escalation:.*→\s*(DirectExport|Normalization|Conflict|Quarantine)\s*$/s.test(raw)) impacts.push(raw)
  const extraction = readableText(source.extraction_quality?.summary).replace(/(\d+)\/(\d+) records with invalid extraction_method/gi, '报告中 $1/$2 条记录的提取方式标记未通过格式检查')
  return { dimensions, impacts: [...new Set(impacts)], extraction }
}

const ACTION_LABELS = {
  extract_central_value: '提取中心值', extract_base_value: '提取基础数值', extract_main_value: '提取主要数值', extract_primary_value: '提取主要数值',
  range_to_midpoint: '提取区间中点', range_to_mean: '提取区间均值', parse_range_to_central: '解析区间中心值', parse_range_to_midpoint: '解析区间中点',
  numeric_convert: '转换为数值', unit_converter: '转换单位', extract_uncertainty: '提取误差信息', extract_uncertainty_value: '提取误差信息',
  marked: '添加标记', annotate: '添加标注', mark_missing_unit: '标记缺失单位', ops_mark_missing_unit: '标记缺失单位',
  parallel: '并行处理', fill_missing_redshift_unit: '补齐红移单位', split_dual_velocity: '拆分速度数据', parse_mass_range_to_lower_bound: '提取质量区间下限',
  strip_uncertainty: '整理数值与误差格式', string_to_numeric: '转换为数值', clean_string: '整理文本格式',
  trim: '去除首尾空白', strip_prefix: '去除数值前缀', drop_suffix: '去除指定后缀', replace_substring: '替换指定文本',
  unit_normalize: '规范化单位', filled_value: '填写缺失值', filled_unit: '填写缺失单位', format_cleanup: '整理数值格式',
  unit_mismatch_kept: '保留不同单位的记录', removed: '移除记录',
}
export function operationLabel(code) {
  if (!code) return '数据处理'
  if (typeof code !== 'string' && typeof code !== 'number') return '数据处理'
  if (ACTION_LABELS[code]) return ACTION_LABELS[code]
  return String(code)
}
export function measurementText(value, unit) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    if (value.field_value != null) return measurementText(value.field_value, value.field_unit)
    if (value.value != null) return measurementText(value.value, value.unit)
  }
  return [readableText(value), readableText(unit)].filter(Boolean).join(' ')
}
export function modificationView(row, records = []) {
  const ids = exactRecordIds(row)
  const record = records.find(record => ids.includes(record.record_id))
  const field = record?.field_name || row.field_name || row.field
  const rawReason = readableText(row.reason)
  const codeReason = /^[a-z][a-z0-9_]+$/.test(rawReason) && rawReason.includes('_')
  const code = row.action || (codeReason ? rawReason : null) || row.tool || row.stage || row.fix
  const operation = operationLabel(code)
  const originals = [...new Set([row.action, row.tool, row.stage, row.fix, codeReason ? rawReason : null].filter(value => typeof value === 'string' && value))]
  const reason = codeReason ? '' : rawReason
  return { ids, record, entity: record?.entity_name || row.entity_name || '', field: field === 'field_value' ? null : field,
    before: measurementText(row.before ?? row.original ?? row.original_value, row.from_unit ?? row.from), after: measurementText(row.after ?? row.new ?? row.new_value ?? row.normalized_value ?? row.mapped, row.to_unit ?? row.to),
    operation, originals, timestamp: row.timestamp, iteration: row.iteration ?? row.round, reportOrigin: row.reportOrigin,
    reason: reason === 'tools executed' || reason === operation ? '' : reason }
}
export function recordChanges(record, quality) {
  const trace = quality?.quality_report?.output_state?.traceability?.per_record_trace?.[record.record_id]
  const rows = executionTraces(quality).filter(row => exactRecordIds(row).includes(record.record_id)).map(row => ({ ...row, reportOrigin: '执行记录' }))
  // Cross-report matching is one-to-one: identical repeated actions in a round
  // are retained. Never deduplicate primary execution events by their values.
  const merge = (items, origin) => {
    const matched = new Set(), existingLength = rows.length
    for (const item of items) {
      const candidate = modificationView(item)
      const index = rows.findIndex((row, i) => {
        if (i >= existingLength || matched.has(i)) return false
        const existing = modificationView(row)
        if (candidate.iteration != null && existing.iteration != null && candidate.iteration !== existing.iteration) return false
        if (item.timestamp && row.timestamp && item.timestamp !== row.timestamp) return false
        if (candidate.before !== existing.before || candidate.after !== existing.after) return false
        return candidate.originals.some(code => existing.originals.includes(code)) &&
          (!candidate.reason || !existing.reason || candidate.reason === existing.reason)
      })
      if (index >= 0) { matched.add(index); rows[index] = { ...item, ...rows[index] }; continue }
      rows.push({ ...item, reportOrigin: origin })
    }
  }
  merge(Array.isArray(trace?.modifications) ? trace.modifications : [], '逐记录溯源')
  merge(modificationReport(quality).rows.filter(row => exactRecordIds(row).includes(record.record_id)), '修改报告补充')
  return { trace, rows }
}
export function normalizeInsights(insights) {
  return { fields: Array.isArray(insights?.field_insights) ? insights.field_insights : [],
    relations: Array.isArray(insights?.cross_field_relationships) ? insights.cross_field_relationships : Array.isArray(insights?.relationships) ? insights.relationships : [],
    recommendations: insights?.usage_recommendations || insights?.recommendations || {} }
}
export function insightGroups(insights) {
  const groups = new Map()
  for (const row of normalizeInsights(insights).fields) {
    const key = `${row.entity_name || ''}|${row.field_name || ''}`
    if (!groups.has(key)) groups.set(key, { key, entity: row.entity_name || '', field: row.field_name, rows: [] })
    groups.get(key).rows.push(row)
  }
  return [...groups.values()]
}
export function referenceInfo(value, catalog = {}) {
  if (typeof value === 'object' && value) return value.title ? { title: readableText(value.title), source: readableText(value.source), url: /^https?:\/\//.test(value.url || '') ? value.url : null } : referenceInfo(value.id || value.ref, catalog)
  if (typeof value !== 'string') return null
  const id = value.replace(/^kb:/, '')
  if (catalog[id]?.title) return { title: catalog[id].title, source: readableText(catalog[id].source) }
  if (/^https?:\/\//.test(value)) return { title: value, url: value }
  if (/^kb:|^[a-z0-9_]+$/i.test(value)) return { title: value }
  return { title: value }
}

export function measurementSeries(records, quality) {
  const traces = quality?.quality_report?.output_state?.traceability?.per_record_trace || {}
  return measurementGroups(records).map(group => {
    const rows = group.rows.map(row => {
      const trace = traces[row.record.record_id]
      const original = trace && trace.original_unit === group.unit ? parseMeasurement(trace.original_value) : null
      return { ...row, measurement: original?.lower != null || original?.upper != null ? original : row.measurement }
    })
    const valid = rows.filter(row => row.measurement)
    const values = valid.flatMap(({ measurement: m }) => [m.lower ?? m.value, m.upper ?? m.value]).filter(Number.isFinite)
    return { ...group, rows, valid, unparsed: rows.length - valid.length, min: values.length ? Math.min(...values) : null, max: values.length ? Math.max(...values) : null }
  })
}
