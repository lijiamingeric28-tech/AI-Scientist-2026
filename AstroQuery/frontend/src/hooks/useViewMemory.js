import { useEffect, useLayoutEffect, useRef, useState } from 'react'
export function useRememberedState(memory, key, initial) {
  const [value, setValue] = useState(() => memory[key] ?? initial)
  useEffect(() => { memory[key] = value }, [value, memory, key])
  return [value, setValue]
}
export function useScrollMemory(memory, ready, active = true) {
  const ref = useRef(null), restored = useRef(false)
  useLayoutEffect(() => {
    if (!ready || !active || restored.current || !ref.current) return
    ref.current.scrollTop = memory.scrollTop || 0; restored.current = true
  }, [ready, active])
  const onScroll = event => { if (restored.current && active) memory.scrollTop = event.currentTarget.scrollTop }
  return { ref, onScroll }
}
