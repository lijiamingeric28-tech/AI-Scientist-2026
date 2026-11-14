import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '@/components/icons'
import './researchAnswer.css'
import './query-composer.css'

export function composerPopoverPosition(anchor, viewport, height=240) {
  const width=Math.min(420,Math.max(0,viewport.width-24))
  const panelHeight=Math.min(height,Math.max(0,viewport.height-24))
  const below=viewport.height-anchor.bottom-10
  const top=below>=panelHeight||below>=anchor.top-10?anchor.bottom+10:anchor.top-panelHeight-10
  return {left:Math.max(12,Math.min(anchor.left,viewport.width-width-12)),top:Math.max(12,Math.min(top,viewport.height-panelHeight-12)),width,maxHeight:Math.max(0,viewport.height-24)}
}

export default function QueryComposer({ textarea, value, onChange, onSubmit, mode, canSwitch, onSwitch, onStop,
  busy, disabled, selectionCount, onClearSelection, preferenceControls, preferenceSummary, placeholder }) {
  const [menu,setMenu]=useState(false),[position,setPosition]=useState(null)
  const options=useRef(null),panel=useRef(null),menuId=useId()
  const followup=mode==='followup',hasOptions=Boolean(canSwitch||preferenceControls)
  const label=followup?'追问当前结果':'新建科研查询'
  const active=!disabled&&!busy&&Boolean(value.trim())
  useLayoutEffect(()=>{
    const input=textarea.current
    if(!input)return
    input.style.height='auto'
    input.style.height=Math.min(input.scrollHeight,126)+'px'
  },[textarea,value,mode])
  useEffect(()=>{setMenu(false)},[mode])
  useLayoutEffect(()=>{
    if(!menu)return
    const place=()=>{
      if(!options.current||!panel.current)return
      setPosition(composerPopoverPosition(options.current.getBoundingClientRect(),{width:window.innerWidth,height:window.innerHeight},panel.current.getBoundingClientRect().height))
    }
    place()
    window.addEventListener('resize',place)
    window.addEventListener('scroll',place,true)
    return()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true)}
  },[menu,preferenceControls,followup])
  useEffect(()=>{
    if(!menu)return
    panel.current?.querySelector('button,input,select')?.focus({preventScroll:true})
    const outside=event=>{if(!options.current?.contains(event.target)&&!panel.current?.contains(event.target))setMenu(false)}
    const escape=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();setMenu(false);options.current?.focus({preventScroll:true})}}
    document.addEventListener('pointerdown',outside,true)
    document.addEventListener('keydown',escape,true)
    return()=>{document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',escape,true)}
  },[menu])
  const close=()=>{setMenu(false);options.current?.focus({preventScroll:true})}
  return <form className="research-composer" aria-label={label} onSubmit={event=>{event.preventDefault();if(active)onSubmit()}}>
    {selectionCount>0&&followup&&<div className="research-composer-context"><span>{selectionCount} 项选中内容</span><button type="button" className="research-action" onClick={onClearSelection} aria-label="清除追问对象"><Icon.Close width={15} height={15}/></button></div>}
    <div className="research-composer-shell">
      <div className="research-composer-row">
        <button ref={options} className="research-composer-options" type="button" aria-label="检索与对话选项" title={followup?'对话选项':preferenceSummary||'检索与对话选项'} aria-haspopup="dialog" aria-expanded={menu} aria-controls={menu?menuId:undefined} disabled={!hasOptions} onClick={()=>setMenu(open=>!open)}><Icon.Sparkle className="research-composer-star" aria-hidden="true" style={{transform:`rotate(${menu?90:0}deg)`}}/></button>
        <textarea ref={textarea} rows={1} aria-label={label} value={value} placeholder={placeholder||(followup?'追问当前查询结果…':'输入天体和想了解的物理性质…')} onChange={event=>onChange(event.target.value)} disabled={disabled} maxLength={followup?12000:undefined} onKeyDown={event=>{
          if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing&&event.keyCode!==229){event.preventDefault();if(active)onSubmit()}
        }}/>
        {followup&&busy?<button className="research-send" type="button" onClick={onStop} aria-label="停止生成" title="停止生成"><Icon.Stop width={15} height={15} fill="currentColor"/></button>:<button className="research-send" type="submit" disabled={!active} aria-label={followup?'发送追问':'开始查询'} title={followup?'发送追问':'开始查询'}><Icon.Send width={20} height={20}/></button>}
      </div>
    </div>
    {menu&&hasOptions&&createPortal(<div id={menuId} ref={panel} className="research-composer-popover" role="dialog" aria-label="检索与对话选项" style={position||{visibility:'hidden'}} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget)&&event.relatedTarget!==options.current)setMenu(false)}}>
      <header><div><strong>{followup?'对话选项':'科研查询选项'}</strong>{!followup&&preferenceSummary&&<span>{preferenceSummary}</span>}</div><button type="button" className="research-popover-close" onClick={close} aria-label="关闭查询选项"><Icon.Close width={15} height={15}/></button></header>
      {canSwitch&&<div className="research-composer-modes" aria-label="对话模式">{[['followup','追问当前结果'],['new','新建科研查询']].map(([key,name])=><button type="button" key={key} aria-pressed={mode===key} onClick={()=>{setMenu(false);onSwitch(key)}}>{name}</button>)}</div>}
      {!followup&&preferenceControls?<div className="research-composer-settings">{preferenceControls}</div>:followup?<p className="research-composer-menu-hint">追问使用本任务已固定的数据与知识依据。检索篇数与排序可在“新建科研查询”中调整。</p>:null}
    </div>,document.body)}
  </form>
}
