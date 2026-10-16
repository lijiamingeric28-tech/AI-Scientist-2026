import Markdown from '@/lib/markdown'
import { readableText, reportParagraphs, referenceInfo } from '@/lib/readableData'
import references from '@/data/knowledgeReferences.json'
import { useInPlaceDisclosure } from '@/hooks/useInPlaceDisclosure'
import { useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { floatingPosition } from '@/lib/viewGeometry'

export function Prose({ value, className = '' }) {
  const content = reportParagraphs(value).join('\n\n')
  return content ? <div className={`reading-prose ${className}`}><Markdown>{content}</Markdown></div> : null
}
export function Excerpt({ value, label = '展开全文', length = 480, disclosureKey = label }) {
  const toggleInPlace = useInPlaceDisclosure()
  const text = readableText(value)
  if (!text) return null
  if (text.length <= length) return <div className="readable-excerpt"><Prose value={text} /></div>
  return <div className="readable-excerpt"><div className="excerpt-preview"><Prose value={`${text.slice(0, length)}…`} /></div><details data-disclosure-key={disclosureKey}><summary className="text-link excerpt-toggle" onClick={event => { event.preventDefault(); const details = event.currentTarget.parentElement; const container = details.closest('.provenance-part, .record-history li, .source-reading section') || details.parentElement; toggleInPlace({ currentTarget: container }, () => { details.open = !details.open }) }}><span className="excerpt-expand">{label}</span><span className="excerpt-collapse">收起全文</span></summary><Prose value={text} /></details></div>
}
export function References({ values }) {
  const rows = (Array.isArray(values) ? values : []).map(value => referenceInfo(value, references)).filter(Boolean).filter((row, index, all) => all.findIndex(other => other.title === row.title && other.url === row.url) === index)
  if (!rows.length) return null
  return <div className="reading-references"><h4>参考出处</h4><ul>{rows.map((row, i) => <li key={i}>{row.url ? <a href={row.url} target="_blank" rel="noreferrer">{row.title} ↗</a> : row.title}{row.source && <span>{row.source}</span>}</li>)}</ul></div>
}
export function DefinitionNote({ definition }) {
  const id = useId(), trigger = useRef(null), popup = useRef(null)
  const [open, setOpen] = useState(false), [position, setPosition] = useState(null)
  const close = (restore = true) => { setOpen(false); if (restore && trigger.current?.isConnected) trigger.current.focus({ preventScroll: true }) }
  useLayoutEffect(() => {
    if (!open) return
    const anchor = trigger.current
    const update = () => {
      if (!anchor?.isConnected || !anchor.getClientRects().length || anchor.closest('[hidden],[inert],[aria-hidden="true"],[data-closing]')) { close(false); return }
      const rect = anchor.getBoundingClientRect()
      if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) { close(false); return }
      const next = floatingPosition(rect, { width: window.innerWidth, height: window.innerHeight }, (popup.current?.scrollHeight || 198) + 2)
      setPosition(previous => previous && Object.keys(next).every(key => next[key] === previous[key]) ? previous : next)
    }
    update()
    const frame = requestAnimationFrame(() => { update(); popup.current?.focus({ preventScroll: true }) })
    const outside = event => { if (!anchor?.contains(event.target) && !popup.current?.contains(event.target)) close(false) }
    const keydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return }
      if (event.key === 'Tab' && popup.current?.contains(event.target)) {
        const items = [...popup.current.querySelectorAll('button,a[href]')].filter(el => el.getClientRects().length)
        const first = items[0], last = items.at(-1)
        if (event.shiftKey && (event.target === popup.current || event.target === first)) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && event.target === last) { event.preventDefault(); first?.focus() }
      }
    }
    const other = event => { if (event.detail !== id) close(false) }
    const observer = new MutationObserver(update)
    for (let node = anchor?.parentElement; node; node = node.parentElement) observer.observe(node, { attributes: true, attributeFilter: ['hidden', 'inert', 'aria-hidden', 'data-closing', 'style'] })
    const size = new ResizeObserver(update)
    if (popup.current) size.observe(popup.current)
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('keydown', keydown, true)
    document.addEventListener('ui:definition-open', other)
    window.addEventListener('scroll', update, true); window.addEventListener('resize', update)
    return () => {
      cancelAnimationFrame(frame); observer.disconnect(); size.disconnect()
      document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', keydown, true)
      document.removeEventListener('ui:definition-open', other)
      window.removeEventListener('scroll', update, true); window.removeEventListener('resize', update)
    }
  }, [open, id])
  if (!definition || (!readableText(definition.description) && !definition.standard_unit)) return null
  return <span className="definition-note"><button ref={trigger} className="definition-trigger" aria-label="查看性质定义" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => { if (open) close(); else { document.dispatchEvent(new CustomEvent('ui:definition-open', { detail: id })); setPosition(null); setOpen(true) } }}>ⓘ</button>{open && createPortal(<section ref={popup} id={id} role="dialog" aria-label="性质定义" tabIndex={-1} className="definition-popover" style={{ ...position, visibility: position ? 'visible' : 'hidden' }}><header><strong>性质定义</strong><button aria-label="关闭性质定义" onClick={() => close()}>×</button></header><Prose value={definition.description} />{definition.standard_unit && <p className="definition-unit">标准单位：{definition.standard_unit}</p>}</section>, document.body)}</span>
}
