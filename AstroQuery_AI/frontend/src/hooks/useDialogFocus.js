import { useEffect, useRef } from 'react'
export function useDialogFocus(open, onClose, { trap = true } = {}) {
  const ref = useRef(null), closeRef = useRef(onClose), trapRef = useRef(trap)
  closeRef.current = onClose
  trapRef.current = trap
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    const elements = () => [...(ref.current?.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], summary, [tabindex="0"]') || [])].filter(el => el.getClientRects().length && !el.closest('[inert]') && el.tabIndex >= 0)
    const frame = requestAnimationFrame(() => (elements()[0] || ref.current)?.focus({ preventScroll: true }))
    const onKey = event => {
      if (event.defaultPrevented) return
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeRef.current?.(); return }
      if (event.key !== 'Tab' || !trapRef.current) return
      const items = elements(), first = items[0], last = items.at(-1)
      if (!items.length) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || !el.contains(document.activeElement))) { event.preventDefault(); last.focus({ preventScroll: true }) }
      else if (!event.shiftKey && (document.activeElement === last || !el.contains(document.activeElement))) { event.preventDefault(); first.focus({ preventScroll: true }) }
    }
    const el = ref.current
    el?.addEventListener('keydown', onKey)
    return () => { cancelAnimationFrame(frame); el?.removeEventListener('keydown', onKey); if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [open])
  return ref
}
