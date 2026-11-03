export const ADS_SORTS = [['score desc', '相关度优先'], ['date desc', '最新发表'], ['citation_count desc', '被引最多'], ['read_count desc', '阅读最多']]
export function papersValue(value) {
  const text = String(value)
  if (!/^\d+$/.test(text)) return null
  const n = Number(text)
  return Number.isInteger(n) && n >= 1 && n <= 40 ? n : null
}
export function preferencesFromConfig(config) {
  return { papers_per_property: Number(config?.effective_values?.literature_papers_per_property || 20), ads_sort: config?.effective_values?.ads_sort || 'score desc' }
}
