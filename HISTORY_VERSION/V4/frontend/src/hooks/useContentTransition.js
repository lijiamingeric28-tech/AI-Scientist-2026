import { useLayoutEffect, useRef, useState } from 'react'

export function parentIsMoving(element) {
  return Boolean(element?.closest('[hidden],[inert]') || element?.parentElement?.closest('[data-sliding],[data-context-moving]'))
}

// Explicit navigation only. Resource changes keep the current node and position.
export function useContentTransition(ref, selection, { active = true, selector, axis = 'y', distance = 4, duration = 220, order } = {}) {
  const previous = useRef(selection)
  const [moving, setMoving] = useState(false)
  const pending = previous.current !== selection && active
  const orderKey = order?.join('|') || ''
  useLayoutEffect(() => {
    const old = previous.current, changed = old !== selection
    previous.current = selection
    const element = selector ? ref.current?.querySelector(selector) : ref.current
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (!changed || !active || media.matches || !element?.animate || parentIsMoving(element)) { setMoving(false); return }
    const direction = order ? Math.sign(order.indexOf(selection) - order.indexOf(old)) || 1 : 1
    const animation = element.animate([{ opacity: .5, transform: `translate${axis.toUpperCase()}(${distance * direction}px)` }, { opacity: 1, transform: `translate${axis.toUpperCase()}(0)` }], { duration, easing: 'cubic-bezier(.22,1,.36,1)' })
    let alive = true
    setMoving(true)
    const finish = () => { if (alive) setMoving(false) }
    animation.finished.then(finish, finish)
    const reduce = () => { if (media.matches) { animation.cancel(); finish() } }
    media.addEventListener('change', reduce)
    return () => { alive = false; animation.cancel(); media.removeEventListener('change', reduce) }
  }, [selection, active, selector, ref, axis, distance, duration, orderKey])
  return active && (moving || pending) && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
