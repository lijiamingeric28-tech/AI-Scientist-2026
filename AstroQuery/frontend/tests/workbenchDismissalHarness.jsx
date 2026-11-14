// Development-only integration checks using the real settings/workbench components.
// Only read APIs are used; no draft, knowledge, task or configuration is saved.
import React, { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import SettingsDialog from '../src/components/settings/SettingsDialog'
import { ToastProvider } from '../src/components/ui/toast'
import '../src/styles.css'
import '../src/frontend-v1.css'
import '../src/research-results.css'
import '../src/components/settings/settings.css'

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
async function waitFor(read, timeout = 6000) {
  const start = performance.now()
  while (performance.now() - start < timeout) {
    const value = read()
    if (value) return value
    await sleep(16)
  }
  throw new Error('等待工作台状态超时')
}
const studio = () => document.querySelector('.settings-studio-dialog')
const closeButton = () => studio()?.querySelector('[aria-label="关闭规范工作台"], [aria-label="关闭设置工作台"]')

function Harness() {
  const [launch, setLaunch] = useState(null), [results, setResults] = useState([]), [running, setRunning] = useState(false)
  const sequence = useRef(0), closes = useRef(0)
  const check = (name, pass, evidence) => setResults(previous => [...previous, { name, pass: !!pass, evidence }])
  const open = async mode => {
    closes.current = 0
    setLaunch({ key: ++sequence.current, mode })
    await waitFor(closeButton)
    await sleep(280) // Let the entrance finish before testing the exit.
  }
  const runExit = async (mode, action, { reduced = false, noAnimation = false } = {}) => {
    await open(mode)
    const originalMatch = window.matchMedia.bind(window)
    const dialog = studio(), overlay = dialog.closest('.settings-overlay'), frames = []
    if (reduced) window.matchMedia = query => query === '(prefers-reduced-motion: reduce)' ? { matches: true } : originalMatch(query)
    if (noAnimation) { dialog.style.animation = 'none'; overlay.style.animation = 'none' }
    const start = performance.now()
    let frame
    const record = () => {
      const el = studio()
      frames.push({ ms: Math.round(performance.now() - start), mounted: !!el,
        closing: !!el?.hasAttribute('data-closing'),
        opacity: el ? Number(getComputedStyle(el.closest('.settings-overlay')).opacity) : 0,
        animation: el ? getComputedStyle(el).animationName : null,
        preferences: !!document.querySelector('.preferences-dialog') })
      if (performance.now() - start < 520) frame = requestAnimationFrame(record)
    }
    record()
    try {
      if (action === 'escape') dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      else if (action === 'backdrop') overlay.click()
      else { const button = closeButton(); button.click(); if (action === 'repeat') button.click() }
      await sleep(560)
      let faded = false, reappeared = false
      for (const sample of frames) {
        if (sample.mounted && sample.opacity < 0.2) faded = true
        if (faded && sample.mounted && sample.opacity > 0.8) reappeared = true
      }
      const name = `${mode === 'registry' ? '规范' : '知识'} · ${action}${reduced ? ' · 减少动态' : ''}${noAnimation ? ' · 无动画回退' : ''}`
      check(name, closes.current === 1 && !studio() && !reappeared && !frames.some(sample => sample.preferences)
        && (reduced || noAnimation || frames.some(sample => sample.animation === 'modal-out')),
      { closeCalls: closes.current, reappeared, frames })
    } finally {
      cancelAnimationFrame(frame)
      window.matchMedia = originalMatch
      setLaunch(null)
      await sleep(32)
    }
  }
  const run = async () => {
    setResults([]); setRunning(true)
    try {
      for (const mode of ['registry', 'graph']) {
        for (const action of ['button', 'backdrop', 'escape', 'repeat']) await runExit(mode, action)
        await runExit(mode, 'button', { reduced: true })
        await runExit(mode, 'button', { noAnimation: true })
        await open(mode)
        studio().querySelector('button').click()
        await waitFor(() => document.querySelector('.preferences-dialog'))
        await sleep(250)
        check(`${mode} · 返回设置保留设置页`, !studio() && closes.current === 0 && !!document.querySelector('.preferences-dialog'))
        setLaunch(null); await sleep(32)
        await open(mode)
        closeButton().click()
        setLaunch({ key: ++sequence.current, mode })
        await waitFor(closeButton); await sleep(500)
        check(`${mode} · 重开撤销旧关闭回调`, !!studio() && closes.current === 0)
        setLaunch(null); await sleep(32)
      }
    } catch (error) { check('回归执行', false, error.message) }
    finally { setLaunch(null); setRunning(false) }
  }
  return <ToastProvider><main style={{ padding: 24, color: 'var(--text-primary)' }}>
    <h1>工作台关闭回归</h1><p>实际组件、实际样式；逐帧检查淡出后重新出现、重复关闭、Esc、遮罩、返回设置、重开和减少动态效果。</p>
    <button type="button" className="ui-button" onClick={run} disabled={running}>运行关闭回归</button>
    <ol aria-label="关闭回归结果">{results.map(result => <li key={result.name} data-pass={result.pass}>{result.pass ? '通过' : '失败'} · {result.name}<details><summary>逐帧证据</summary><pre>{JSON.stringify(result.evidence, null, 2)}</pre></details></li>)}</ol>
    <output aria-label="关闭回归状态">{running ? '检查中' : results.length ? results.every(result => result.pass) ? `全部通过 · ${results.length} 项` : '存在失败' : '等待检查'}</output>
    {launch && <SettingsDialog key={launch.key} open initialTab={launch.mode === 'registry' ? 'registry' : 'knowledge'} initialStudioMode={launch.mode}
      onClose={() => { closes.current++; setLaunch(null) }} theme="light" onToggleTheme={() => {}} />}
  </main></ToastProvider>
}
createRoot(document.getElementById('root')).render(<React.StrictMode><Harness /></React.StrictMode>)
