// Presentation only: no record parsing, unit conversion or scientific aggregation.
export function measurementAxis(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null
  if (min > max) [min, max] = [max, min]
  const span = max - min
  const padding = (span || Math.abs(min) * .1 || 1) * .06
  const lo = Number.isFinite(min - padding) ? min - padding : min
  const hi = Number.isFinite(max + padding) ? max + padding : max
  const rawStep = (hi - lo) / count
  const magnitude = 10 ** Math.floor(Math.log10(rawStep))
  const unit = rawStep / magnitude
  const step = (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * magnitude
  let ticks = []
  if (Number.isFinite(step) && step > 0 && Number.isFinite(lo / step)) {
    const start = Math.ceil(lo / step)
    for (let i = 0; i < 12; i++) {
      const value = (start + i) * step
      if (value > hi) break
      if (value >= lo && Number.isFinite(value)) ticks.push(Number(value.toPrecision(12)))
    }
  }
  if (ticks.length < 2) ticks = Array.from({ length: count + 1 }, (_, i) => lo * (1 - i / count) + hi * (i / count))
  ticks = [...new Set(ticks.filter(Number.isFinite))]
  return { lo, hi, ticks }
}
function formattedAxisLabel(value, precision) {
  if (!Number.isFinite(value)) return ''
  if (value === 0) return '0'
  const size = Math.abs(value)
  if (size >= 1e6 || size < .001) return value.toExponential(precision - 1).replace(/\.?0+e/, 'e')
  return Number(value.toPrecision(precision)).toLocaleString('en-US', { maximumSignificantDigits: precision })
}
export function axisLabel(value) { return formattedAxisLabel(value, 6) }
export function axisTickLabels(values) {
  for (let precision = 6; precision <= 15; precision++) {
    const labels = values.map(value => formattedAxisLabel(value, precision))
    if (new Set(labels).size === values.length) return labels
  }
  return values.map(String)
}
export function resolveSelection(key, keys) { return keys.includes(key) ? key : keys[0] ?? null }
export function relationshipKeys(rows) {
  const seen = new Map()
  return rows.map(row => {
    const base = JSON.stringify([row.id ?? row.relationship_id ?? null, row.field_a, row.field_b, row.relationship_type ?? row.type ?? null])
    const occurrence = seen.get(base) || 0
    seen.set(base, occurrence + 1)
    return `${base}:${occurrence}`
  })
}
export function labelLines(label, length = 18) {
  const chars = Array.from(String(label))
  if (chars.length <= length) return [chars.join('')]
  return [chars.slice(0, length).join(''), chars.slice(length, length * 2 - 1).join('') + (chars.length > length * 2 - 1 ? '…' : '')]
}
