import { DEFAULT_PALETTE } from './customPalette.js'

export function readGraphTheme(style) {
  const read = (names, fallback) => names.map(name => style.getPropertyValue(name).trim()).find(Boolean) || fallback
  const accent = read(['--seed-accent', '--accent'], DEFAULT_PALETTE.accent)
  const bg = read(['--surface-canvas', '--seed-bg'], DEFAULT_PALETTE.bg)
  const ink = read(['--text-primary', '--content-fg', '--seed-ink'], DEFAULT_PALETTE.ink)
  return {
    bg, ink, accent,
    surface: read(['--surface-card', '--surface-bg', '--seed-surface'], DEFAULT_PALETTE.surface),
    aux: read(['--seed-aux'], DEFAULT_PALETTE.aux),
    line: read(['--border-default', '--surface-border', '--border-subtle'], `color-mix(in srgb, ${ink} 18%, ${bg})`),
    gold: read(['--reference-text', '--status-warning', '--seed-aux'], DEFAULT_PALETTE.aux),
    font: read(['--font-custom-override', '--font-ui'], 'sans-serif'),
  }
}

export function graphCategoryColor(id, theme) {
  let hash = 2166136261
  for (const char of String(id)) hash = Math.imul(hash ^ char.codePointAt(0), 16777619)
  const weight = 15 + (hash >>> 0) % 71
  return `color-mix(in srgb, ${theme.accent} ${weight}%, ${theme.aux})`
}

export function graphEdgeDash(relationType, scale = 1) {
  const unit = Number.isFinite(scale) && scale > 0 ? scale : 1
  return relationType === 'conditional' ? [6 / unit, 4 / unit]
    : relationType === 'candidate' ? [4 / unit, 5 / unit]
      : relationType === 'user_link' ? [5 / unit, 4 / unit] : []
}
