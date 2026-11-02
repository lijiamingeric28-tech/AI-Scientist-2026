import { useEffect, useRef } from 'react'

// Keep the clicked heading in view while content above it changes height.
// This runs only for a deliberate disclosure action, never for incoming events.
export function useInPlaceDisclosure() {
  const cleanup = useRef(() => {})
  useEffect(() => () => cleanup.current(), [])
  return (event, update) => {
    cleanup.current()
    const heading = event.currentTarget
    let scroller = heading.parentElement
    while (scroller && !(/auto|scroll/.test(getComputedStyle(scroller).overflowY) && scroller.scrollHeight > scroller.clientHeight)) scroller = scroller.parentElement
    if (!scroller) { update(); return }
    const top = heading.getBoundingClientRect().top
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let frame, start
    const cancel = () => {
      cancelAnimationFrame(frame)
      for (const name of ['wheel', 'touchstart', 'pointerdown', 'keydown']) scroller.removeEventListener(name, cancel)
    }
    cleanup.current = cancel
    for (const name of ['wheel', 'touchstart', 'pointerdown', 'keydown']) scroller.addEventListener(name, cancel, { passive: true })
    const follow = now => {
      if (!heading.isConnected || !scroller.isConnected || !heading.getClientRects().length) { cancel(); return }
      start ??= now
      const delta = heading.getBoundingClientRect().top - top
      if (Math.abs(delta) > 0.5) scroller.scrollTop += delta
      if (!reduced && now - start < 340) frame = requestAnimationFrame(follow)
      else cancel()
    }
    update()
    frame = requestAnimationFrame(follow)
  }
}
