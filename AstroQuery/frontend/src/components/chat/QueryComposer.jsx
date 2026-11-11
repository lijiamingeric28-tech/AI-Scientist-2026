import { useLayoutEffect, useState } from 'react'
import { Icon } from '@/components/icons'
import './researchAnswer.css'

export default function QueryComposer({ textarea, value, onChange, onSubmit, mode, canSwitch, onSwitch, onStop,
  busy, disabled, selectionCount, onClearSelection, preferenceControls, placeholder }) {
  const [menu, setMenu] = useState(false)
  useLayoutEffect(() => {
    const input = textarea.current
    if (!input) return
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, 126) + 'px'
  }, [textarea, value, mode])

  const followup = mode === 'followup'
  const label = followup ? '追问当前结果' : '新建科研查询'
  const active = !disabled && !busy && Boolean(value.trim())
  return <form className="research-composer" aria-label={label} onSubmit={e => {
    e.preventDefault()
    if (active) onSubmit()
  }}>
    {selectionCount > 0 && followup && <div className="research-composer-context">
      <span>{selectionCount} 项选中内容</span>
      <button type="button" className="research-action" onClick={onClearSelection} aria-label="清除追问对象"><Icon.Close width={15} height={15} /></button>
    </div>}
    <div className="research-composer-row">
      {canSwitch && <div className="research-plus" onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) setMenu(false) }}
        onKeyDown={e => { if (e.key === 'Escape') { setMenu(false); e.currentTarget.querySelector('button')?.focus() } }}>
        <button className="research-plus-toggle" type="button" aria-label="查询选项" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon.Plus width={19} height={19} /></button>
        {menu && <div className="research-plus-menu">
          <button type="button" onClick={() => { setMenu(false); onSwitch(followup ? 'new' : 'followup') }}>
            {followup ? '新建科研查询' : '继续追问当前结果'}
          </button>
        </div>}
      </div>}
      <textarea ref={textarea} rows={1} aria-label={label} value={value} placeholder={placeholder || (followup ? '追问当前查询结果…' : '输入天体和想了解的物理性质…')}
        onChange={e => onChange(e.target.value)} disabled={disabled} maxLength={followup ? 12000 : undefined}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
            e.preventDefault()
            if (active) onSubmit()
          }
        }} />
      {followup && busy ? <button className="research-send" type="button" onClick={onStop} aria-label="停止生成" title="停止生成"><Icon.Stop width={15} height={15} fill="currentColor" /></button> :
        <button className="research-send" type="submit" disabled={!active} aria-label={followup ? '发送追问' : '开始查询'}
          title={followup ? '发送追问' : '开始查询'}><Icon.Send width={20} height={20} /></button>}
    </div>
    {!followup && preferenceControls && <div className="research-composer-preferences">{preferenceControls}</div>}
  </form>
}
