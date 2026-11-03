const conditionLabels = {
  band: '波段', passband: '波段', filter: '滤光片', epoch: '历元', instrument: '仪器',
  aperture: '孔径', method: '方法', wavelength: '波长', frequency: '频率',
  source_method_model_and_context: '方法与模型', source_context: '观测条件',
}
const roles = {reported_result:'文中报告结果', model_prediction:'模型预测', adopted_result:'采用的既有结果',
  assumption:'假设值', comparison_value:'比较值', observed:'观测值', measured:'实测值'}
export const measurementRole = proposal => roles[proposal?.result_role] || roles[proposal?.value_type]
export function readingConditions(conditions = [], schema = []) {
  const seen = new Set()
  return conditions.flatMap(c => {
    if (c.state !== 'known' || !['string','number','boolean'].includes(typeof c.value)) return []
    const value = typeof c.value === 'boolean' ? (c.value ? '是' : '否') : String(c.value).trim()
    const declared = schema.find(field => field.key === c.key)
    const label = conditionLabels[c.key] || (!c.key?.startsWith('source_') && (declared?.label || declared?.name_cn))
    if (!label || !value || seen.has(value)) return []
    seen.add(value)
    return [{label, value}]
  })
}
export function reviewRows(review) {
  const records = Object.entries(review.record_interpretations || {})
  if (records.length) return records.map(([id,item]) => ({id, propertyId:item.record?.property_ref?.id || item.proposal?.property_id, value:item.record?.raw_value ?? item.proposal?.raw_value,
    unit:item.record?.unit ?? item.proposal?.unit, role:measurementRole(item.proposal),
    method:readingConditions(item.proposal?.conditions).find(c=>c.label==='方法与模型' || c.label==='方法')?.value,
    errors:(item.proposal?.errors || []).map(e=>e.raw_text).filter(Boolean),
    evidence:(item.evidence_refs || item.record?.evidence_refs || []).map(ref=>ref.id)}))
  const p = review.current_interpretation
  return p ? [{propertyId:p.property_id,value:p.raw_value, unit:p.unit, role:measurementRole(p),
    method:readingConditions(p.conditions).find(c=>c.label==='方法与模型' || c.label==='方法')?.value, errors:(p.errors || []).map(e=>e.raw_text).filter(Boolean),
    evidence:(review.evidence_refs || []).map(ref=>ref.id)}] : []
}
const questionKinds = {comparison_contradiction:'这些测量应分别保留，还是有一条解释需要更正？',
  object_semantics:'原文中的测量属于哪个天体？',quantity_semantics:'原文报告的是这次查询的性质吗？',
  value_transcription:'这个数值与原件一致吗？',unit_semantics:'原件中的单位支持当前解释吗？',
  uncertainty_semantics:'这里报告的是哪一种误差？',condition_semantics:'原文中的测量条件支持当前解释吗？'}
export function reviewWording(review) {
  const original = (review.question || '').trim()
  const generic = questionKinds[review.issue_kind] || '原件是否支持这条测量的解释？'
  const detail = original.split(/[:：]/).at(-1)?.trim() || original
  // A registry's Chinese property prefix can precede an untranslated historical question.
  const readable = /[\u3400-\u9fff]/u.test(detail) && !/\b[RE]\d+\b/.test(detail)
  return {title:readable ? original.replace(/\bmeasurand\b/gi,'测量对象') : generic,
    original:readable ? '' : original}
}
export function rawCells(evidence) {
  if (evidence?.text_origin !== 'original_cells') return null
  let native
  try { native = JSON.parse(evidence.raw_text) } catch { return null }
  if (!native?.cells || Array.isArray(native.cells) || typeof native.cells !== 'object') return null
  const meta = new Map((Array.isArray(native.columns) ? native.columns : []).map(c=>[c.name,c]))
  return Object.entries(native.cells).map(([column,raw]) => ({column,raw,metadata:meta.get(column),
    is_main:column === evidence.locator?.column}))
}
