// Development-only harness, served by the isolated QA server, never imported by App.
import React, { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useSlidingPanes } from '../src/hooks/useSlidingPanes'
import { useClickFeedback } from '../src/hooks/useClickFeedback'
import '../src/styles.css'

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
const paint = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
const calls = []
const originalAnimate = Element.prototype.animate
Element.prototype.animate = function(frames, options) { calls.push({ pane: this.dataset.slidePane, frames, options }); return originalAnimate.call(this, frames, options) }

function Harness() {
  const [selected, setSelected] = useState('records'), [task, setTask] = useState('first'), [resource, setResource] = useState(0)
  const [results, setResults] = useState([]), [running, setRunning] = useState(false)
  const [feedback, setFeedback] = useState([])
  const ref = useRef(null)
  const panes = useSlidingPanes(ref, selected, ['records','evidence','analysis'], { identity: task })
  useClickFeedback()
  const probeClick = async event => {
    const button = event.currentTarget, rect = button.getBoundingClientRect(), ink = button.querySelector('.click-feedback-ink')
    const expectedX = event.detail ? event.clientX - rect.left : rect.width / 2
    const actualX = ink ? parseFloat(ink.style.left) + parseFloat(ink.style.width) / 2 : NaN
    setFeedback([{ name: event.detail ? '鼠标扩散跟随点击位置' : '键盘扩散位于控件中心', pass: !!ink && Math.abs(actualX - expectedX) < 1 }])
    await sleep(500)
    setFeedback(previous => [...previous, { name: '扩散结束清理装饰节点', pass: !button.querySelector('.click-feedback-overlay') }])
  }
  const run = async () => {
    setRunning(true); const checks = []
    const check = (name, pass, actual) => { checks.push({ name, pass: !!pass, actual }); setResults([...checks]) }
    setSelected('records'); setTask('first'); setResource(0); await paint(); await sleep(350)
    const initial = ref.current.querySelector('[data-slide-pane="records"]')
    initial.scrollTop = 90
    setSelected('analysis'); await paint()
    const exiting = ref.current.querySelector('[data-slide-exit]')
    check('原节点退出、不可交互', exiting === initial && exiting.inert, exiting?.dataset.slidePane)
    check('进入使用28px横向位移', calls.at(-2)?.frames[0].transform === 'translateX(28px)', calls.at(-2)?.frames[0].transform)
    const count = calls.length
    setResource(1); await paint()
    check('晚到资源不重启动画', calls.length === count, calls.length)
    setSelected('evidence'); await paint(); setSelected('records'); await paint(); await sleep(370)
    check('连续切换只留下最后视图', ref.current.querySelectorAll('[data-slide-pane]:not([hidden])').length === 1 && !initial.hidden, selected)
    check('退出节点与动画已清理', !ref.current.querySelector('[data-slide-exit]') && initial.getAnimations().length === 0)
    check('原节点和非零阅读位置保留', ref.current.querySelector('[data-slide-pane="records"]') === initial && initial.scrollTop === 90, initial.scrollTop)
    setSelected('analysis'); await paint(); setTask('second'); await paint(); await sleep(350)
    check('切换任务撤销旧退出回调', !ref.current.querySelector('[data-slide-exit]') && ref.current.querySelector('[data-slide-pane="analysis"]').hidden === false)
    const originalMatch = window.matchMedia.bind(window)
    try {
      window.matchMedia = query => query === '(prefers-reduced-motion: reduce)' ? { matches: true } : originalMatch(query)
      const before = calls.length
      setSelected('evidence'); await paint()
      check('减少动态效果直接切换', calls.length === before && !ref.current.querySelector('[data-slide-exit]'))
    } finally { window.matchMedia = originalMatch }
    setRunning(false)
  }
  return <main style={{ padding: 24, maxWidth: 800 }}><h1>动画专项检查</h1><p>使用实际展示 Hook；减少动态效果采用测试媒体桩，不修改系统偏好。</p><button className="ui-button" onClick={run} disabled={running}>运行交互专项检查</button><button className="ui-button" onClick={probeClick} style={{ marginLeft: 24, padding: '10px 20px', border: '1px solid #6f9d87', borderRadius: 6 }}>测试点击扩散</button><div ref={ref} className="slide-panes" data-sliding={panes.moving || undefined} style={{ height: 130, margin: '20px 0', border: '1px solid #b5caba' }}>{['records','evidence','analysis'].map(key => <section key={key} {...panes.paneProps(key)} style={{ ...panes.paneProps(key).style, height: 130, overflow: 'auto' }}><div style={{ height: 450, padding: 16 }}>{key} · 资源版本 {resource}</div></section>)}</div><ol aria-label="专项结果">{results.map(result => <li key={result.name} data-pass={result.pass}>{result.pass ? '通过' : '失败'} · {result.name}{result.actual != null ? ` · ${String(result.actual)}` : ''}</li>)}</ol><output>{!running && results.length ? results.every(result => result.pass) ? '全部通过' : '存在失败' : '等待检查'}</output><ol aria-label="点击结果">{feedback.map(result => <li data-feedback-pass={result.pass} key={result.name}>{result.pass ? '通过' : '失败'} · {result.name}</li>)}</ol></main>
}
createRoot(document.getElementById('root')).render(<Harness />)
