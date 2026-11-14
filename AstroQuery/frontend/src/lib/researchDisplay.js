export const activityLabels = {
  original: '原报形成',
  quality: '原文核验',
  reextraction: '局部重提',
  human: '人工判断',
  representation: '主值处理',
  uncertainty: '误差处理',
  archive: '重复归档',
  comparison: '对照检查',
  delivery: '封存交付',
}
export const stateLabels = {
  complete: '已完成',
  checked: '已核对',
  supported: '原文支持',
  not_applicable: '免二次核验 (权威基准)',
  not_supported: '未通过',
  technical_failure: '技术处理失败',
  reextraction_requested: '交回局部重提',
  rechecked: '复检已结束',
  recheck_pending: '复检未闭环',
  no_target_candidate: '重提未产生目标候选',
  archived: '已归档',
  sealed: '已封存',
  converted: '已转换',
  no_change: '确认采纳原报',
  verified: '已核实处理',
  not_run: '采纳原报物理量',
  ready: '处理就绪',
  identity: '原表示',
  exact: '已精确转换',
  approximate: '近似传播',
  failed: '处理失败',
  error: '处理失败',
  unresolved: '含义待核实',
  pending: '待汇总',
  not_recorded: '未记录',
  partial: '部分完成',
  incomplete: '未完成',
  not_checked: '未核对',
  applied: '已应用',
  received: '已收到',
  passed: '复检通过',
  different_conditions: '按不同测量条件保留',
  available: '已取得',
  parsed: '已解释原报',
  generated: '已生成',
  confirmed: '已确认',
  recorded: '原始观测记录已归档',
  checked_no_relevant: '文献核验未见独立图',
  original_page_fallback: '文献原版面收录',
  native_single_caption_geometry: '独立图例精细裁切',
  source_unresolved: '原文含义待核实',
  unsupported: '保留原误差',
  check_failed: '核验未完成',
}
export const stateText = (state) => stateLabels[state] || '待扩展核验'
export const titleText = (source) =>
  Array.isArray(source?.title) ? source.title.join('；') : source?.title || '题名未记录'
export function displayText(value) {
  if (value == null) return '未记录'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map(displayText).join('；')
  if (typeof value === 'object')
    return (
      value.raw_text ||
      value.text ||
      value.canonical_symbol ||
      value.label ||
      (typeof value.value !== 'object' && value.value != null ? String(value.value) : '见关联原文')
    )
  return String(value)
}
