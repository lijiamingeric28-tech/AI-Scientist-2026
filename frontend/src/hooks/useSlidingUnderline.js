import { useLayoutEffect } from 'react'

// The indicator is decorative; tab identity, focus and navigation stay unchanged.
export function useSlidingUnderline(ref, selection) {
  useLayoutEffect(() => {
    const nav = ref.current
    if (!nav) return
    const place = () => {
      const selected = nav.querySelector(':scope > button.active')
      if (!selected) return
      const box=nav.getBoundingClientRect(),item=selected.getBoundingClientRect()
      nav.style.setProperty('--indicator-x', `${item.left-box.left-nav.clientLeft+nav.scrollLeft}px`)
      nav.style.setProperty('--indicator-width', `${item.width}px`)
      nav.style.setProperty('--indicator-y', `${item.bottom-box.top-nav.clientTop+nav.scrollTop-3}px`)
      nav.dataset.slidingUnderline = ''
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(nav)
    nav.querySelectorAll(':scope > button').forEach(button => observer.observe(button))
    return () => observer.disconnect()
  }, [ref, selection])
}
