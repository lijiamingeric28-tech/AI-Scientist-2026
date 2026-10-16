import { useEffect } from 'react'

export function useClickFeedback() {
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const pending = new Map()
    let press = null
    const targetFor = target => target?.closest?.('button, .task-item, [role="button"]')
    const down = event => { press = { target: targetFor(event.target), x: event.clientX, y: event.clientY, dragged: false } }
    const move = event => { if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 8) press.dragged = true }
    const clear = target => {
      const entry = pending.get(target)
      if (!entry) return
      clearTimeout(entry.timer); entry.overlay.remove(); pending.delete(target)
      target.classList.remove('has-click-feedback')
    }
    const click = event => {
      const target = targetFor(event.target)
      if (!target || media.matches || target.matches(':disabled,[aria-disabled="true"]') || target.closest('[inert]')) return
      if (event.detail && press && (press.dragged || press.target !== target)) return
      clear(target)
      const rect = target.getBoundingClientRect()
      const x = event.detail ? event.clientX - rect.left : rect.width / 2
      const y = event.detail ? event.clientY - rect.top : rect.height / 2
      const diameter = Math.hypot(rect.width, rect.height) * 2
      const overlay = document.createElement('span'), ink = document.createElement('i')
      overlay.className = 'click-feedback-overlay'; overlay.setAttribute('aria-hidden', 'true')
      ink.className = 'click-feedback-ink'
      Object.assign(ink.style, { width: `${diameter}px`, height: `${diameter}px`, left: `${x - diameter / 2}px`, top: `${y - diameter / 2}px` })
      overlay.append(ink); target.classList.add('has-click-feedback'); target.append(overlay)
      pending.set(target, { overlay, timer: setTimeout(() => clear(target), 400) })
      press = null
    }
    const cancel = () => { if (press) press.dragged = true }
    const stop = () => { if (media.matches) [...pending.keys()].forEach(clear) }
    document.addEventListener('pointerdown', down, true)
    document.addEventListener('pointermove', move, true)
    document.addEventListener('pointercancel', cancel, true)
    document.addEventListener('click', click, true)
    media.addEventListener('change', stop)
    return () => {
      document.removeEventListener('pointerdown', down, true); document.removeEventListener('pointermove', move, true)
      document.removeEventListener('pointercancel', cancel, true); document.removeEventListener('click', click, true)
      media.removeEventListener('change', stop); [...pending.keys()].forEach(clear)
    }
  }, [])
}
