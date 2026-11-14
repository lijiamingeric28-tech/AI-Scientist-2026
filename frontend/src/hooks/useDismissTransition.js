import { useLayoutEffect, useRef, useState } from 'react'
import { createDismissTransition } from '@/lib/dismissTransition'

export function useDismissTransition(onClose, { duration = 140, active = true, identity } = {}) {
  const [closing, setClosing] = useState(false)
  const callback = useRef(onClose), controller = useRef(null)
  callback.current = onClose
  if (!controller.current) controller.current = createDismissTransition({ onChange: setClosing, onClose: () => callback.current?.() })
  useLayoutEffect(() => { controller.current.cancel(); return () => controller.current.cancel() }, [active, identity])
  return {
    closing,
    onKeyDownCapture: event => { if (closing && ['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation() } },
    close: () => { if (active) controller.current.request(duration, window.matchMedia('(prefers-reduced-motion: reduce)').matches) },
    onAnimationEnd: event => { if (event.target === event.currentTarget && /-out$/.test(event.animationName)) controller.current.finish() },
  }
}
