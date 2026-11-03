import { useLayoutEffect } from 'react'

// The indicator is decorative; tab identity, focus and navigation stay unchanged.
export function useSlidingUnderline(ref, selection) {
  useLayoutEffect(() => {
    const nav = ref.current
    if (!nav) return
    const place = () => {
      const selected = nav.querySelector(':scope > button.active')
      if (!selected) return
      nav.style.setProperty('--indicator-x', `${selected.offsetLeft}px`)
      nav.style.setProperty('--indicator-width', `${selected.offsetWidth}px`)
      nav.style.setProperty('--indicator-y', `${selected.offsetTop + selected.offsetHeight - 3}px`)
      nav.dataset.slidingUnderline = ''
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(nav)
    nav.querySelectorAll(':scope > button').forEach(button => observer.observe(button))
    return () => observer.disconnect()
  }, [ref, selection])
}
