import { useEffect, useLayoutEffect, useRef, useState } from 'react'
export function useRememberedState(memory, key, initial, sessionKey) {
  const [value, setValue] = useState(() => {
    if (Object.hasOwn(memory, key)) return memory[key] ?? initial
    if (sessionKey) {
      try {
        const saved = sessionStorage.getItem(sessionKey)
        if (saved !== null) return JSON.parse(saved)
      } catch { /* Browsing still works without session storage. */ }
    }
    return initial
  })
  useEffect(() => {
    memory[key] = value
    if (sessionKey) {
      try { sessionStorage.setItem(sessionKey, JSON.stringify(value)) } catch { /* Optional persistence. */ }
    }
  }, [value, memory, key, sessionKey])
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
