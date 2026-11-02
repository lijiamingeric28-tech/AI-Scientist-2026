import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createNavigationMotion, navigationDirection } from '@/lib/navigationMotion'
import { parentIsMoving } from '@/hooks/useContentTransition'

// Keep original pane nodes alive while the previous pane leaves. This hook owns
// presentation only; resources and events continue to belong to their components.
export function useSlidingPanes(ref, selection, order, { active = true, identity = '' } = {}) {
  const [exitKey, setExitKey] = useState(null)
  const [moving, setMoving] = useState(false)
  const [, settle] = useState(0)
  const previous = useRef({ key: selection, identity, active })
  const visited = useRef(new Set([selection]))
  const controller = useRef(null)
  controller.current ||= createNavigationMotion()
  const changed = previous.current.key !== selection
  const sameContext = previous.current.identity === identity && previous.current.active && active
  const motionEnabled = typeof window !== 'undefined' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches && typeof Element.prototype.animate === 'function'
  const outgoing = sameContext && motionEnabled ? (changed ? previous.current.key : exitKey) : null
  visited.current.add(selection)
  const orderKey = order.join('|')

  useLayoutEffect(() => {
    const old = previous.current
    previous.current = { key: selection, identity, active }
    controller.current.cancel()
    if (old.key === selection || !old.active || !active || old.identity !== identity || parentIsMoving(ref.current)) {
      setExitKey(null); setMoving(false)
      // A parent transition can suppress the first navigation without changing
      // either state above. Commit the new selection before paint in that case.
      if (old.key !== selection) settle(value => value + 1)
      return
    }
    const panes = [...(ref.current?.querySelectorAll(':scope > [data-slide-pane]') || [])]
    const enter = panes.find(pane => pane.dataset.slidePane === selection)
    const exit = panes.find(pane => pane.dataset.slidePane === old.key)
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!enter || reduced) { setExitKey(null); setMoving(false); return }
    setExitKey(old.key); setMoving(true)
    controller.current.run({ enter, exit, direction: navigationDirection(order, old.key, selection),
      onExit: () => setExitKey(null), onFinish: () => setMoving(false) })
  }, [selection, active, identity, orderKey, ref])

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const stop = () => { if (media.matches) { controller.current.cancel(); setExitKey(null); setMoving(false) } }
    media.addEventListener('change', stop)
    return () => { media.removeEventListener('change', stop); controller.current.cancel() }
  }, [])

  return {
    moving: motionEnabled && (moving || (changed && sameContext)),
    hasVisited: key => visited.current.has(key),
    paneProps: (key, display) => ({
      'data-slide-pane': key,
      'data-slide-exit': outgoing === key ? '' : undefined,
      hidden: selection !== key && outgoing !== key,
      inert: selection !== key ? '' : undefined,
      'aria-hidden': selection !== key ? true : undefined,
      style: { display: selection === key || outgoing === key ? display : 'none' },
    }),
  }
}
