// Presentation-only close lifecycle. Cancellation invalidates even queued timers.
export function createDismissTransition({ onChange, onClose, schedule = setTimeout, clear = clearTimeout }) {
  let pending = false, timer, generation = 0
  const cancel = () => { generation++; clear(timer); timer = undefined; pending = false; onChange(false) }
  const finish = () => { if (!pending) return; cancel(); onClose() }
  return {
    request(duration, reduced = false) {
      if (pending) return
      pending = true
      if (reduced) { finish(); return }
      onChange(true)
      const current = ++generation
      timer = schedule(() => { if (generation === current) finish() }, duration + 50)
    },
    finish,
    cancel,
  }
}
