import {useId,useMemo,useRef,useState} from 'react'
import {filterRegistryFamilies} from '@/lib/registryFamilies'

export default function RegistryFamilySelect({families=[],value='',onChange,disabled=false,required=false,emptyLabel='全部分类',showCounts=false,className=''}) {
  const id=useId(),[keyword,setKeyword]=useState(''),previousSelection=useRef(null)
  const selected=families.find(family=>family.id===value)
  if(selected)previousSelection.current=selected
  if(!value)previousSelection.current=null
  const retained=selected||(previousSelection.current?.id===value?previousSelection.current:null)
  const matches=useMemo(()=>filterRegistryFamilies(families,keyword),[families,keyword])
  const pinned=value&&!matches.some(family=>family.id===value)
  const optionLabel=family=>`${family.label||family.id}${showCounts?` (${family.count??0})`:''}`
  return <div className={`rwb-family-picker ${className}`}>
    <label htmlFor={`${id}-select`}>性质分类</label>
    <input id={`${id}-search`} type="search" aria-label="搜索性质分类" autoComplete="off" placeholder="搜索分类名称或标识…"
      value={keyword} disabled={disabled} aria-describedby={`${id}-hint`} onChange={event=>setKeyword(event.target.value)}
      onKeyDown={event=>{if(event.key==='Enter')event.preventDefault()}} />
    <select id={`${id}-select`} name="family_id" value={value} required={required} disabled={disabled} onChange={event=>onChange(event.target.value)}>
      <option value="">{emptyLabel}</option>
      {pinned&&<option value={value}>{retained?optionLabel(retained):value}{selected?'（当前已选）':'（当前版本未提供）'}</option>}
      {matches.map(family=><option key={family.id} value={family.id}>{optionLabel(family)}</option>)}
    </select>
    <small id={`${id}-hint`} className="rwb-family-caption" role="status">
      {keyword.trim()?matches.length?`匹配 ${matches.length} / ${families.length} 个分类`:'没有匹配分类，请调整搜索词':`${families.length} 个分类 · 支持名称或标识搜索`}
      {pinned&&retained&&'；当前选择已保留'}
    </small>
  </div>
}
