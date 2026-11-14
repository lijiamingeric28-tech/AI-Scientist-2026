const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
const capabilityLabels = {retrieval:'检索',extraction:'提取',native:'原值保留',normalization:'规范化'}

export function parseExecutionExamples(value) {
  let examples
  try { examples = typeof value === 'string' ? JSON.parse(value || '[]') : value || [] }
  catch { throw new Error('验证样例格式有误，输入已保留，请核对后再保存') }
  if (!Array.isArray(examples) || examples.length > 20) throw new Error('验证样例需为列表，最多保留 20 条')
  return examples.map((example,index) => {
    const prefix = `验证样例 ${index+1}：`
    if (!example || typeof example !== 'object' || Array.isArray(example)) throw new Error(prefix+'格式有误')
    if (typeof example.source_value !== 'string' || !decimal.test(example.source_value.trim())) throw new Error(prefix+'来源值需为有限十进制数')
    if (typeof example.expected_value !== 'string' || !decimal.test(example.expected_value.trim())) throw new Error(prefix+'预期输出值需为有限十进制数')
    if (typeof example.source_unit !== 'string' || !example.source_unit.trim()) throw new Error(prefix+'请填写来源单位；无量纲填写 1')
    if (!example.source_representation || typeof example.source_representation !== 'object') throw new Error(prefix+'请指定来源表示方式')
    return {...example,source_value:example.source_value.trim(),expected_value:example.expected_value.trim(),source_unit:example.source_unit.trim()}
  })
}

export function executionCapabilityRows(capabilities) {
  if (!capabilities) return []
  return Object.entries(capabilityLabels).map(([key,label])=>({key,label,ready:capabilities[key]?.ready===true,
    reasons:Array.isArray(capabilities[key]?.reasons)?capabilities[key].reasons:[]}))
}

export function executionCapabilityText(capabilities,legacyReady=false) {
  if (!capabilities) return legacyReady?'原有精确范围内可转换':'自动转换未就绪'
  if (capabilities.normalization?.ready===true) return '可自动规范化'
  if (capabilities.extraction?.ready===true && capabilities.native?.ready===true) return '可提取，保留原值'
  if (capabilities.retrieval?.ready===true) return '可检索，等待提取验证'
  return '执行能力待验证'
}

export function executionCheckText(check) {
  if (typeof check === 'string') return check
  const labels={typed_definition:'定义与输出结构校验'}
  return check?.message || check?.reason || check?.label || check?.name || labels[check?.code] || check?.code || ''
}
