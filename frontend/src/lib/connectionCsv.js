export function parseConnectionCsv(text) {
  const rows = []; let row = [], value = '', quoted = false
  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (char === '"') {
      if (quoted && text[i+1] === '"') { value += '"'; i++ }
      else quoted = !quoted
    } else if (!quoted && char === ',') { row.push(value.trim()); value = '' }
    else if (!quoted && (char === '\n' || char === '\r')) {
      if (char === '\r' && text[i+1] === '\n') i++
      row.push(value.trim()); if (row.some(Boolean)) rows.push(row)
      row = []; value = ''
    } else value += char
  }
  if (quoted) throw new Error('CSV 引号不完整，请重新下载百炼密钥文件。')
  row.push(value.trim()); if (row.some(Boolean)) rows.push(row)
  if (rows[0]?.[0]) rows[0][0] = rows[0][0].replace(/^\uFEFF/,'')
  const pairs = new Map(rows.map(row=>[row[0],row[1]]))
  const headers = rows[0] || []
  const headerExport = headers.includes('apiKey') && headers.includes('openAiCompatible')
  const key = headerExport ? rows[1]?.[headers.indexOf('apiKey')] : pairs.get('apiKey')
  const endpoint = headerExport ? rows[1]?.[headers.indexOf('openAiCompatible')] : pairs.get('openAiCompatible')
  if (!key || !endpoint) throw new Error('这份 CSV 缺少 API Key 或兼容接口地址。')
  return {dashscope_api_key:key,dashscope_base_url:endpoint}
}
