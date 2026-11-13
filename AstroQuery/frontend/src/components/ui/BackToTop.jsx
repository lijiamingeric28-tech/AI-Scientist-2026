import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/icons'
import { Button } from './button'
import './back-to-top.css'

const containers = '.data-workbench, .chat-gutter, .help-page, .settings-content, .workbench-export-body, .export-center-body'

export default function BackToTop({ active = true, scroller, floating = false, onBeforeScroll }) {
  const marker = useRef(null)
  const target = useRef(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = scroller ? marker.current?.closest('.context-drawer')?.querySelector(scroller)
      : marker.current?.closest(containers)
    target.current = el
    if (!active || !el) return
    const update = () => setVisible(el.scrollTop > 160)
    update()
    el.addEventListener('scroll', update, { passive: true })
    return () => el.removeEventListener('scroll', update)
  }, [active, scroller])

  function goToTop() {
    const el = target.current
    if (!el) return
    onBeforeScroll?.()
    const heading = el.querySelector('h1, h2, h3')
    if (heading) {
      if (!heading.hasAttribute('tabindex')) heading.tabIndex = -1
      heading.focus({ preventScroll: true })
    }
    el.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
  }

  return <div ref={marker} className={`scroll-top-control${floating ? ' in-drawer' : ''}`}>
    {active && visible && <Button type="button" variant="outline" size="sm" onClick={goToTop}>
      <Icon.ChevronDown aria-hidden="true" />返回顶部
    </Button>}
  </div>
}
