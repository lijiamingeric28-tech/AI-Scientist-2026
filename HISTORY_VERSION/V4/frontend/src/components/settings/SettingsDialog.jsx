import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import { useSlidingUnderline } from '@/hooks/useSlidingUnderline'
import * as api from '@/services/api'

const FIELDS = [
  { key: 'dashscope_api_key', label: 'DashScope API Key', secret: true, group: '模型连接', note: '用于任务理解、提取及质量处理。空值保持原密钥。' },
  { key: 'dashscope_base_url', label: 'DashScope Base URL', group: '模型连接', note: '填写 OpenAI 兼容地址，确保与 API Key 的服务地域一致。' },
  { key: 'ads_api_token', label: 'ADS API Token', secret: true, group: '论文检索', note: 'NASA ADS 论文检索凭据。空值保持原 Token。' },
  { key: 'unpaywall_email', label: 'Unpaywall Email', group: '论文检索', note: '开放获取查询使用的联系邮箱。' },
]
const MODELS = { dashscope_model: '任务理解', p1_model: '性质标准化', dashscope_vlm_model: 'VLM 提取', dashscope_bbox_model: '原文定位', dashscope_quality_model: '质量处理', default_research_domain: '研究领域' }
export const REPLAY_SPEED_KEY = 'astro_replay_speed'
export function loadReplaySpeed() {
  try { const n = Number(localStorage.getItem(REPLAY_SPEED_KEY)); return Number.isFinite(n) && n >= 1 && n <= 100 ? n : 10 } catch { return 10 }
}
export function saveReplaySpeed(value) {
  try { localStorage.setItem(REPLAY_SPEED_KEY, String(Math.max(1, Math.min(100, Math.round(value))))) } catch { /* preferences only */ }
}

export default function SettingsDialog({ open, onClose, onboarding = false, onConfigChange, theme, onToggleTheme }) {
  const [cfg, setCfg] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false)
  const [values, setValues] = useState({}), [baseline, setBaseline] = useState({}), [revealed, setRevealed] = useState({})
  const [saving, setSaving] = useState(false), savingRef = useRef(false)
  const [discardOpen, setDiscardOpen] = useState(false), [tab, setTab] = useState('connections'), [speed, setSpeed] = useState(loadReplaySpeed)
  const { toast } = useToast()
  const changed = FIELDS.filter(field => (values[field.key] || '').trim() !== (baseline[field.key] || ''))
  const dismissal = useDismissTransition(() => { setValues({}); setRevealed({}); setDiscardOpen(false); onClose() }, { active: open })
  const contentRef = useRef(null), navRef = useRef(null)
  const panes = useSlidingPanes(contentRef, tab, ['connections', 'preferences', 'system'], { active: open })
  useSlidingUnderline(navRef, `${open}:${tab}`)
  const close = () => {
    if (savingRef.current) return
    if (changed.length) { setDiscardOpen(true); return }
    dismissal.close()
  }
  const discardRef = useRef(null), discardOrigin = useRef(null)
  const dialogRef = useDialogFocus(open, () => { if (discardOpen) setDiscardOpen(false); else close() })
  useEffect(() => {
    if (discardOpen) {
      discardOrigin.current = document.activeElement
      discardRef.current?.querySelector('button')?.focus({ preventScroll: true })
    } else if (open && discardOrigin.current?.isConnected) {
      discardOrigin.current.focus({ preventScroll: true })
      discardOrigin.current = null
    }
  }, [discardOpen, open])
  const accept = next => {
    const initial = { dashscope_api_key: '', ads_api_token: '', ...next.editable_values }
    setCfg(next); setBaseline(initial); setValues(initial); onConfigChange?.(next)
  }
  const load = async () => {
    setLoading(true); setError('')
    try { accept(await api.getConfig()) } catch (err) { setError(`服务连接失败：${err.message}`) }
    finally { setLoading(false) }
  }
  useEffect(() => {
    if (!open) return
    setTab('connections'); setValues({}); setBaseline({}); setCfg(null); setRevealed({}); setDiscardOpen(false)
    let alive = true
    setLoading(true); setError('')
    api.getConfig().then(next => { if (alive) accept(next) }).catch(err => alive && setError(`服务连接失败：${err.message}`)).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [open])
  const save = async () => {
    if (savingRef.current || !changed.length) return
    const body = Object.fromEntries(changed.map(field => [field.key, (values[field.key] || '').trim()]).filter(([, value]) => value))
    if (!Object.keys(body).length) { setError('空值表示保持原配置，当前没有可保存的修改。'); return }
    if (body.dashscope_base_url) {
      try {
        const url = new URL(body.dashscope_base_url)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error()
      } catch { setError('Base URL 需要有效的 http(s) 地址，不能包含账号、密钥、查询参数或片段。'); return }
    }
    if (body.unpaywall_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.unpaywall_email)) { setError('请填写有效邮箱。'); return }
    if (Object.values(body).some(value => /[\r\n]/.test(value) || value.length > 512)) { setError('配置必须为单行，且不超过 512 个字符。'); return }
    savingRef.current = true; setSaving(true); setError('')
    let written = false
    try {
      await api.putConfig(body); written = true
      // Clear sensitive drafts after a confirmed write, before reading status.
      setValues(prev => ({ ...prev, dashscope_api_key: '', ads_api_token: '' })); setRevealed({})
      const next = await api.getConfig(); accept(next)
      toast(next.restart_required ? '已保存，请重启服务后发起新的实操查询' : '已保存配置', 'success')
    } catch (err) { setError(`${written ? '写入成功，但读取确认失败' : '保存失败'}：${err.message}。${written ? '请重新读取确认保存状态。' : '草稿已保留。'}`) }
    finally { savingRef.current = false; setSaving(false) }
  }
  if (!open) return null
  const count = FIELDS.filter(field => cfg?.configured?.[field.key.toUpperCase()]).length
  return <div className="settings-overlay" data-closing={dismissal.closing || undefined} onClick={close}>
    <section ref={dialogRef} data-closing={dismissal.closing || undefined} onAnimationEnd={dismissal.onAnimationEnd} onKeyDownCapture={dismissal.onKeyDownCapture} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="settings-title" className="settings-dialog animate-modal-in" onClick={event => event.stopPropagation()}>
      <header className="settings-header"><div><h2 id="settings-title">{onboarding ? '连接科研服务，开始你的查询' : '设置'}</h2><p>{onboarding ? '可先浏览演示样例，稍后再完成连接。' : '管理科研连接、界面偏好和系统信息。'}</p></div><Button variant="ghost" size="icon" aria-label="关闭设置" onClick={close} disabled={saving}><Icon.Close /></Button></header>
      <div className="settings-body">
        <nav ref={navRef} className="settings-nav" aria-label="设置分类">{[['connections', '连接与密钥'], ['preferences', '界面与回放'], ['system', '模型与系统']].map(([key, label]) => <button key={key} className={`filter-chip${tab === key ? ' active' : ''}`} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>{label}</button>)}</nav>
        <div className="settings-content">
          {loading && <p role="status">正在读取服务配置…</p>}
          {error && <div className="resource-error" role="alert">{error}<Button variant="outline" size="sm" onClick={load} disabled={saving || loading}>重新读取</Button></div>}
          <div ref={contentRef} className="settings-panes slide-panes" data-sliding={panes.moving || undefined}>
          <div {...panes.paneProps('connections')}>{cfg && <>
            <div className="notice">已保存 {count} / 4 项连接 · {cfg.restart_required ? '配置有更新，重启服务后生效' : cfg.setup_complete ? '已加载当前配置' : '科研连接尚未齐全'}<br /><small>保存状态不代表凭据已通过联网验证。密钥仅提交至本地服务，不回显。</small></div>
            {['模型连接', '论文检索'].map(group => <section key={group} className="settings-group"><h3>{group}</h3>{FIELDS.filter(field => field.group === group).map(field => {
              const configured = cfg.configured?.[field.key.toUpperCase()]
              const edited = changed.some(item => item.key === field.key) && Boolean(values[field.key]?.trim())
              const overridden = cfg.env_overrides?.[field.key.toUpperCase()]
              return <div key={field.key} className="settings-field">
                <label htmlFor={`config-${field.key}`}>{field.label}<span className={edited ? 'pending-chip' : configured ? 'saved-chip' : 'missing-chip'}>{edited ? '待保存' : configured ? '已配置' : '未填写'}</span><small>必填</small></label>
                <div className="settings-input-row"><input id={`config-${field.key}`} autoComplete="off" spellCheck={false} type={field.secret && !revealed[field.key] ? 'password' : 'text'} value={values[field.key] || ''} disabled={saving || overridden} placeholder={configured && field.secret ? '已配置，留空保持原值' : field.key === 'dashscope_base_url' ? 'https://…/compatible-mode/v1' : field.key === 'unpaywall_email' ? 'researcher@example.com' : '输入凭据'} onChange={event => setValues(prev => ({ ...prev, [field.key]: event.target.value }))} />{field.secret && values[field.key] && <Button variant="ghost" size="sm" onClick={() => setRevealed(prev => ({ ...prev, [field.key]: !prev[field.key] }))}>{revealed[field.key] ? '隐藏' : '查看'}</Button>}</div>
                <p>{overridden ? '由进程环境变量提供；修改 .env 不会覆盖此值。请修改启动环境并重启。' : field.note}</p>
              </div>
            })}</section>)}
            <div className="notice">配置写入服务端 .env。允许部分保存；四项齐全且重启加载后可发起新实操任务。已有任务继续运行。</div>
          </>}</div>
          <div {...panes.paneProps('preferences')} className="settings-group"><h3>界面偏好</h3><div className="preference-row"><span>当前主题：{theme === 'dark' ? '深色' : '浅色'}</span><Button variant="outline" onClick={onToggleTheme}>切换主题</Button></div><h3>演示回放</h3><label htmlFor="replay-speed">新回放速度 · {speed}x</label><input id="replay-speed" type="range" min="1" max="100" value={speed} onChange={event => { const value = Number(event.target.value); setSpeed(value); saveReplaySpeed(value) }} /><p className="hint">偏好即时保存。已有回放速度不变；历史无时间戳事件使用固定节奏。</p></div>
          <div {...panes.paneProps('system')}>{cfg && <div className="settings-group"><h3>当前生效模型</h3>{Object.entries(cfg.models || {}).map(([key, value]) => <div key={key} className="preference-row"><span>{MODELS[key] || key}</span><span className="model-value">{value || '未提供'}</span></div>)}<h3>系统信息</h3><div className="preference-row"><span>数据格式版本</span><span>{cfg.version || '未提供'}</span></div><div className="preference-row output-location"><span>输出目录</span><span>{cfg.output_dir || '未提供'}</span></div><p className="hint">模型信息只读；修改服务配置后重启生效。</p></div>}</div>
          </div>
        </div>
      </div>
      {discardOpen && <div ref={discardRef} className="discard-notice" role="alert"><span>有未保存的连接修改，是否放弃？</span><Button variant="outline" size="sm" onClick={() => setDiscardOpen(false)}>继续编辑</Button><Button variant="destructive" size="sm" onClick={dismissal.close}>放弃修改</Button></div>}
      <footer className="settings-footer"><span className="hint">保存连接后重启服务生效</span><Button variant="outline" onClick={close} disabled={saving}>{onboarding ? '稍后设置' : '关闭'}</Button><Button variant="accent" onClick={save} disabled={saving || loading || !cfg || !changed.some(field => values[field.key]?.trim())}>{saving ? '保存中…' : '保存连接'}</Button></footer>
    </section>
  </div>
}
