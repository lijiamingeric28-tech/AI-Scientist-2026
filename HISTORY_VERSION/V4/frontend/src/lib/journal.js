/* bibcode → 期刊缩写 + 年份（来源列展示「📄 A&A 2023」，2026-09-01 设计）
 * bibcode 结构：YYYYJJJJJ...（4 位年 + 5 位期刊代码，代码含 &/. 缩写）
 * 例：2023A&A...429..645S → A&A 2023；2020MNRAS.491.7095K → MNRAS 2020
 */

const JOURNAL_ABBR = {
  'A&A': 'A&A',
  'A&AS': 'A&AS',
  'ApJ': 'ApJ',
  'AJ': 'AJ',
  'ApJS': 'ApJS',
  'ARA&A': 'ARA&A',
  'MNRAS': 'MNRAS',
  'Nat': 'Nature',
  'Sci': 'Science',
  'PASP': 'PASP',
  'BAAS': 'BAAS',
  'JApA': 'JApA',
}

export function journalLabel(bibcode) {
  if (typeof bibcode !== 'string' || bibcode.length < 5) return bibcode || ''
  const year = bibcode.slice(0, 4)
  if (!/^[0-9]{4}$/.test(year)) {
    const date = bibcode.match(/^([0-9]{4})/)
    if (!date) return bibcode
  }
  const code = bibcode.slice(4, 9).replace(/[. ]+$/, '').trim()
  return `${JOURNAL_ABBR[code] || code || ''} ${year}`.trim()
}
