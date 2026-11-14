// Plot coordinates are approximate; original decimal strings remain authoritative.
function decimalKey(raw) {
  if (typeof raw !== 'string' || raw.length > 4096) return null
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(raw)
  if (!match || !(match[2] + (match[3] || '')).length) return null
  let digits = (match[2] + (match[3] || '')).replace(/^0+/, '')
  if (!digits) return '0'
  let exponent = Number(match[4] || 0) - (match[3] || '').length
  if (!Number.isSafeInteger(exponent)) return null
  while (digits.endsWith('0')) { digits = digits.slice(0, -1); exponent += 1 }
  return `${match[1] === '-' ? '-' : ''}${digits}e${exponent}`
}

export function plotNumber(raw) {
  const value = Number(raw), key = decimalKey(raw)
  // Reject underflow, overflow and decimal rounding that would merge distinct values.
  return key !== null && Number.isFinite(value) && key === decimalKey(String(value)) ? value : null
}

export function errorEndpoint(centre, delta, direction) {
  const distance = plotNumber(delta)
  if (distance === null || distance < 0) return null
  const endpoint = centre + direction * distance
  return Number.isFinite(endpoint) && (distance === 0 || endpoint !== centre) ? endpoint : null
}

export function plotBounds(points) {
  let lo = Infinity, hi = -Infinity
  for (const point of points) {
    for (const value of [point.centre, ...point.ranges.flatMap(range => [range.lo, range.hi])]) {
      if (value !== null && Number.isFinite(value)) { lo = Math.min(lo, value); hi = Math.max(hi, value) }
    }
  }
  return { lo, hi, span: hi - lo, valid: Number.isFinite(lo) && Number.isFinite(hi) && Number.isFinite(hi - lo) }
}
