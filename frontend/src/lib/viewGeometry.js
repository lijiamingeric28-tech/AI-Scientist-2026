// Screen geometry only. Scientific values and relationship identities are unchanged.
export function floatingPosition(anchor, viewport, contentHeight, maxWidth = 320) {
  const margin = 12, gap = 8
  const width = Math.min(maxWidth, Math.max(0, viewport.width - margin * 2))
  const below = Math.max(0, viewport.height - anchor.bottom - gap - margin)
  const above = Math.max(0, anchor.top - gap - margin)
  const upward = below < Math.min(contentHeight, 360) && above > below
  const maxHeight = Math.min(360, upward ? above : below)
  const height = Math.min(contentHeight, maxHeight)
  return { width, maxHeight, left: Math.max(margin, Math.min(anchor.right - width, viewport.width - width - margin)),
    top: Math.max(margin, Math.min(upward ? anchor.top - gap - height : anchor.bottom + gap, viewport.height - height - margin)) }
}

export function relationshipEndpoints(a, b, halfWidth = 85, halfHeight = 25, radius = 10, gap = 3) {
  const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy)
  if (!distance) return { x1: a.x, y1: a.y, x2: b.x, y2: b.y }
  const ux = dx / distance, uy = dy / distance
  let lo = 0, hi = Math.hypot(halfWidth, halfHeight)
  for (let i = 0; i < 28; i++) {
    const mid = (lo + hi) / 2, x = Math.abs(ux * mid), y = Math.abs(uy * mid)
    const inside = x <= halfWidth && y <= halfHeight &&
      Math.hypot(Math.max(0, x - halfWidth + radius), Math.max(0, y - halfHeight + radius)) <= radius
    if (inside) lo = mid; else hi = mid
  }
  const offset = Math.min(lo + gap, distance / 2)
  return { x1: a.x + ux * offset, y1: a.y + uy * offset, x2: b.x - ux * offset, y2: b.y - uy * offset }
}
