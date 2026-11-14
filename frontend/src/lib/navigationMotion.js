export const NAVIGATION_EASE = 'cubic-bezier(.22,1,.36,1)'

export function navigationDirection(order, previous, next) {
  const from = order.indexOf(previous), to = order.indexOf(next)
  return from < 0 || to < 0 || to === from ? 1 : Math.sign(to - from)
}

// One owner for animations and their completion callbacks. Interrupted runs cannot
// hide a newer pane, including when a task changes during navigation.
export function createNavigationMotion({ schedule = setTimeout, unschedule = clearTimeout } = {}) {
  let generation = 0, timers = [], animations = []
  const cancel = () => {
    generation++
    timers.forEach(unschedule); timers = []
    animations.forEach(animation => animation?.cancel()); animations = []
  }
  const run = ({ enter, exit, direction = 1, reduced = false, onExit = () => {}, onFinish = () => {} }) => {
    cancel()
    const token = generation
    if (reduced || !enter?.animate) { onExit(); onFinish(); return }
    const finish = (callback, delay) => timers.push(schedule(() => { if (token === generation) callback() }, delay))
    animations.push(enter.animate([
      { opacity: .25, transform: `translateX(${direction * 28}px)` },
      { opacity: 1, transform: 'translateX(0)' },
    ], { duration: 320, easing: NAVIGATION_EASE }))
    if (exit?.animate) animations.push(exit.animate([
      { opacity: 1, transform: 'translateX(0)' },
      { opacity: 0, transform: `translateX(${-direction * 14}px)` },
    ], { duration: 160, easing: NAVIGATION_EASE, fill: 'forwards' }))
    finish(onExit, 160)
    finish(() => { cancel(); onFinish() }, 320)
  }
  return { run, cancel }
}
