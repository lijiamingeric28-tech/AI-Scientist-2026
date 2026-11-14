import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { backToTopPosition } from '@/lib/backToTopPosition'
import { Icon } from '@/components/icons'
import { Button } from './button'
import './back-to-top.css'

const containers = '.data-workbench, .chat-gutter, .help-page, .settings-content, .workbench-export-body, .export-center-body'

export default function BackToTop({ active = true, scroller, floating = false, draggable = false, onBeforeScroll }) {
  const marker = useRef(null)
  const target = useRef(null)
  const [visible, setVisible] = useState(false)
  const button=useRef(null),drag=useRef(null),suppressClick=useRef(false)
  const [position,setPosition]=useState(null),[dragging,setDragging]=useState(false)
  const place=point=>{
    const el=target.current,b=button.current
    if(!el||!b)return point
    return backToTopPosition(el.getBoundingClientRect(),{width:window.innerWidth,height:window.innerHeight},b.getBoundingClientRect(),point)
  }
  useLayoutEffect(()=>{
    if(!draggable||!active||!visible)return
    const update=()=>setPosition(current=>place(current))
    update()
    const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(update)
    if(target.current)observer?.observe(target.current)
    window.addEventListener('resize',update)
    return()=>{observer?.disconnect();window.removeEventListener('resize',update)}
  },[draggable,active,visible])

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

  const control=active&&visible&&<Button ref={button} type="button" variant="outline" size="sm"
    aria-label="返回顶部" title={draggable?'返回顶部；拖动可调整位置，Alt + 方向键也可移动':undefined}
    onClick={event=>{if(event.detail>0&&suppressClick.current){suppressClick.current=false;event.preventDefault();return}suppressClick.current=false;goToTop()}}
    onPointerDown={draggable?event=>{
      if(event.button!==0)return
      const r=event.currentTarget.getBoundingClientRect()
      suppressClick.current=false
      drag.current={id:event.pointerId,startX:event.clientX,startY:event.clientY,x:r.x,y:r.y,moved:false}
      event.currentTarget.setPointerCapture(event.pointerId)
    }:undefined}
    onPointerMove={draggable?event=>{
      const start=drag.current;if(!start||start.id!==event.pointerId)return
      const dx=event.clientX-start.startX,dy=event.clientY-start.startY
      if(!start.moved&&Math.hypot(dx,dy)<6)return
      start.moved=true;setDragging(true);event.preventDefault()
      setPosition(place({x:start.x+dx,y:start.y+dy}))
    }:undefined}
    onPointerUp={draggable?event=>{
      const start=drag.current;if(!start||start.id!==event.pointerId)return
      suppressClick.current=start.moved;drag.current=null;setDragging(false)
      if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId)
    }:undefined}
    onPointerCancel={draggable?()=>{drag.current=null;setDragging(false)}:undefined}
    onLostPointerCapture={draggable?()=>{drag.current=null;setDragging(false)}:undefined}
    onKeyDown={draggable?event=>{
      const delta={ArrowLeft:[-16,0],ArrowRight:[16,0],ArrowUp:[0,-16],ArrowDown:[0,16]}[event.key]
      if(!event.altKey||!delta)return
      event.preventDefault();const r=event.currentTarget.getBoundingClientRect()
      setPosition(place({x:r.x+delta[0],y:r.y+delta[1]}))
    }:undefined}>
      <Icon.ChevronDown aria-hidden="true" />返回顶部
    </Button>
  return <div ref={marker} className={draggable?'scroll-top-anchor':`scroll-top-control${floating ? ' in-drawer' : ''}`}>
    {draggable?control&&createPortal(<div className="scroll-top-control movable" data-dragging={dragging||undefined}
      style={position?{left:position.x,top:position.y,visibility:'visible'}:{visibility:'hidden'}}>{control}</div>,document.body):control}
  </div>
}
