import { useEffect, useRef } from 'react'
import { parentIsMoving } from './useContentTransition'

// Called by pagination controls, never by search or incoming resource updates.
export function usePageTransition() {
  const pending = useRef(null), animation = useRef(null)
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const stop = () => { cancelAnimationFrame(pending.current); animation.current?.cancel() }
    const reduce = () => { if (media.matches) stop() }
    media.addEventListener('change', reduce)
    return () => { stop(); media.removeEventListener('change', reduce) }
  }, [])
  return (region, update) => {
    cancelAnimationFrame(pending.current); animation.current?.cancel()
    update()
    pending.current = requestAnimationFrame(() => {
      const content = region?.querySelector('[data-page-content]')
      if (!content?.isConnected || parentIsMoving(content) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      animation.current = content.animate?.([{ opacity: .45 }, { opacity: 1 }], { duration: 140, easing: 'cubic-bezier(.22,1,.36,1)' })
    })
  }
}
