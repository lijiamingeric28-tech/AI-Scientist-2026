import { useEffect } from 'react'

/* 滚轮（纵向 deltaY）→ 横向滚动：当容器横向溢出时接管滚轮，否则不拦截（纵向滚动照常）。
 * 不能直接给元素加 React onWheel —— React 将其委托到根且 passive: true，
 * preventDefault 无效（控制台报警告）；因此用原生 addEventListener(..., { passive: false })。
 */
export function useWheelHorizontal(ref) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onWheel = (e) => {
      // deltaX 为主（触控板已横滚）或容器无横向溢出 → 不干预
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
      if (el.scrollWidth <= el.clientWidth + 1) return
      el.scrollLeft += e.deltaY
      e.preventDefault()
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [ref])
}
