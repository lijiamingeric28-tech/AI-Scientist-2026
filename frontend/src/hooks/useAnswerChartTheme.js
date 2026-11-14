import { useLayoutEffect, useState } from 'react'
import { readAnswerChartTheme } from '@/lib/answerChartTheme'

export function useAnswerChartTheme() {
  const [theme,setTheme]=useState(null)
  useLayoutEffect(()=>{
    const probe=document.createElement('span')
    probe.className='research-chart-theme-probe'
    document.body.appendChild(probe)
    const read=()=>setTheme(readAnswerChartTheme(getComputedStyle(probe)))
    read()
    const observer=new MutationObserver(read)
    observer.observe(document.documentElement,{attributes:true,attributeFilter:['style','class','data-theme','data-contrast']})
    return ()=>{observer.disconnect();probe.remove()}
  },[])
  return theme
}
