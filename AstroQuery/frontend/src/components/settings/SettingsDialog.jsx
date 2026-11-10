import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import RetrievalPreferences from './RetrievalPreferences'
import ThemePaletteSettings from './ThemePaletteSettings'
import { papersValue } from '@/lib/retrievalPreferences'
import { loadReplaySpeed, saveReplaySpeed } from '@/lib/playbackPreferences'
import * as api from '@/services/api'
import LibraryStatus from './LibraryStatus'

const PREFERENCE_KEYS = ['ads_sort', 'literature_papers_per_property']
const FIELDS = [
  {key:'ads_sort',label:'ADS 论文排序',group:'使用偏好'},
  {key:'literature_papers_per_property',label:'每项性质的论文目标',group:'使用偏好'},
  { key: 'dashscope_api_key', label: 'DashScope API Key', secret: true, group: '模型连接', note: '用于任务理解、提取及质量处理。空值保持原密钥。' },
  { key: 'dashscope_base_url', label: 'DashScope Base URL', group: '模型连接', note: '填写 OpenAI 兼容地址，确保与 API Key 的服务地域一致。' },
  { key: 'ads_api_token', label: 'ADS API Token', secret: true, group: '论文检索', note: 'NASA ADS 论文检索凭据。空值保持原 Token。' },
  { key: 'unpaywall_email', label: 'Unpaywall Email', group: '论文检索', note: '开放获取查询使用的联系邮箱。' },
]
const MODELS = { text: '文字检索与性质选择', vision: '正文读取与原文质检', normalization: '清洗与标准化', property: '天体名称识别', insight: '科研洞察', dashscope_model: '任务理解', p1_model: '性质标准化', dashscope_vlm_model: 'VLM 提取', dashscope_bbox_model: '原文定位', dashscope_quality_model: '质量处理', default_research_domain: '研究领域' }
export default function SettingsDialog({ open, onClose, onboarding = false, onConfigChange, theme, onToggleTheme }) {
  const [cfg, setCfg] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false)
  const [values, setValues] = useState({}), [baseline, setBaseline] = useState({}), [revealed, setRevealed] = useState({})
  const [saving, setSaving] = useState(false), savingRef = useRef(false)
  const [discardOpen, setDiscardOpen] = useState(false), [tab, setTab] = useState('preferences'), [speed, setSpeed] = useState(loadReplaySpeed)
  const { toast } = useToast()
  const changed = FIELDS.filter(field => (values[field.key] || '').trim() !== (baseline[field.key] || ''))
  const dismissal = useDismissTransition(() => { setValues({}); setRevealed({}); setDiscardOpen(false); onClose() }, { active: open })
  const contentRef = useRef(null), navRef = useRef(null)
  const panes = useSlidingPanes(contentRef, tab, ['connections', 'preferences', 'theme', 'system'], { active: open })
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
  const accept = (next, preserve = []) => {
    const initial = { dashscope_api_key: '', ads_api_token: '', ...next.editable_values, ads_sort: next.editable_values?.ads_sort || next.effective_values?.ads_sort || 'score desc', literature_papers_per_property: next.editable_values?.literature_papers_per_property || next.effective_values?.literature_papers_per_property || '20' }
    setCfg(next); setBaseline(initial); setValues(previous => ({ ...initial, ...Object.fromEntries(preserve.map(key => [key, previous[key]])) })); onConfigChange?.(next)
  }
  const load = async () => {
    setLoading(true); setError('')
    try { accept(await api.getConfig()) } catch (err) { setError(`服务连接失败：${err.message}`) }
    finally { setLoading(false) }
  }
  useEffect(() => {
    if (!open) return
    setTab(onboarding ? 'connections' : 'preferences'); setValues({}); setBaseline({}); setCfg(null); setRevealed({}); setDiscardOpen(false)
    let alive = true
    setLoading(true); setError('')
    api.getConfig().then(next => { if (alive) { accept(next); setTab(next.setup_complete ? 'preferences' : 'connections') } }).catch(err => alive && setError(`服务连接失败：${err.message}`)).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [open])
  const importCsv = async event => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const { parseConnectionCsv } = await import('@/lib/connectionCsv')
      const imported = parseConnectionCsv(await file.text())
      setValues(previous=>({...previous,...imported})); setError('')
    } catch (error) { setError(error.message) }
    event.target.value = ''
  }
  const save = async (checkCurrent = false) => {
    if (savingRef.current || (!changed.length && !checkCurrent)) return
    const allowed = checkCurrent || tab === 'connections' ? changed.filter(field => !PREFERENCE_KEYS.includes(field.key)) : changed.filter(field => PREFERENCE_KEYS.includes(field.key))
    if (allowed.some(field => field.key === 'literature_papers_per_property') && papersValue(values.literature_papers_per_property) === null) { setError('每项性质的论文目标须为 1–40 的整数。'); return }
    const preserve = changed.filter(field => !allowed.includes(field)).map(field => field.key)
    const body = Object.fromEntries(allowed.map(field => [field.key, (values[field.key] || '').trim()]).filter(([, value]) => value))
    if (!checkCurrent && !Object.keys(body).length) { setError('空值表示保持原配置，当前没有可保存的修改。'); return }
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
      if (checkCurrent || body.dashscope_api_key || body.dashscope_base_url) await api.testAndApplyConfig(body)
      else await api.putConfig(body)
      written = true
      // Clear sensitive drafts after a confirmed write, before reading status.
      setValues(prev => ({ ...prev, ...Object.fromEntries(allowed.filter(field=>field.secret).map(field=>[field.key,''])) })); setRevealed({})
      const next = await api.getConfig(); accept(next, preserve)
      toast(checkCurrent || body.dashscope_api_key || body.dashscope_base_url ? '连接已通过检查并生效' : '设置已保存', 'success')
    } catch (err) { setError(`${written ? '写入成功，但读取确认失败' : '保存失败'}：${err.message}。${written ? '请重新读取确认保存状态。' : '草稿已保留。'}`) }
    finally { savingRef.current = false; setSaving(false) }
  }
  if (!open) return null
  const activeChanges = changed.filter(field => tab === 'preferences' ? PREFERENCE_KEYS.includes(field.key) : tab === 'connections' ? !PREFERENCE_KEYS.includes(field.key) : false)
  return <div className="settings-overlay" data-closing={dismissal.closing || undefined} onClick={close}>
    <section
      ref={dialogRef}
      data-closing={dismissal.closing || undefined}
      onAnimationEnd={dismissal.onAnimationEnd}
      onKeyDownCapture={dismissal.onKeyDownCapture}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
      className="settings-dialog preferences-dialog animate-modal-in"
      onClick={event => event.stopPropagation()}
    >
      <header className="settings-header"><div><h2 id="settings-title">{onboarding ? '连接科研服务，开始你的查询' : '设置'}</h2><p>{onboarding ? '可先浏览演示样例，稍后再完成连接。' : ''}</p></div><Button variant="ghost" size="icon" aria-label="关闭设置" onClick={close} disabled={saving}><Icon.Close /></Button></header>
      <div className="settings-body">
        <nav ref={navRef} className="settings-nav" aria-label="设置分类">{[['preferences', '使用偏好'], ['theme', '外观与配色'], ['connections', '服务连接'], ['system', '模型与科学库']].map(([key, label]) => <button key={key} className={tab === key ? 'selected' : undefined} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>{label}</button>)}</nav>
        <div className="settings-content">
          {loading && <p role="status">正在读取服务配置…</p>}
          {error && <div className="resource-error" role="alert">{error}<Button variant="outline" size="sm" onClick={load} disabled={saving || loading}>重新读取</Button></div>}
          <div ref={contentRef} className="settings-panes slide-panes" data-sliding={panes.moving || undefined}>
          <div {...panes.paneProps('connections')}>{cfg && <>
            <div className="settings-connection-status">{cfg.connection?.state === 'connected' ? '百炼连接已通过检查' : cfg.setup_complete ? '已配置科研连接' : '请填写科研服务连接'}</div>
            <div className="settings-import-actions"><label className="text-link">导入百炼 CSV<input type="file" accept=".csv,text/csv" onChange={importCsv} disabled={saving} className="sr-only"/></label><Button variant="outline" onClick={()=>save(true)} disabled={saving}>测试当前连接</Button></div>
            {['模型连接', '论文检索'].map(group => <section key={group} className="settings-group"><h3>{group}</h3>{FIELDS.filter(field => field.group === group).map(field => {
              const configured = cfg.configured?.[field.key.toUpperCase()]
              const edited = changed.some(item => item.key === field.key) && Boolean(values[field.key]?.trim())
              const overridden = cfg.env_overrides?.includes(field.key)
              return <div key={field.key} className="settings-field">
                <label htmlFor={`config-${field.key}`}>{field.label}</label>
                <div className="settings-input-row"><input id={`config-${field.key}`} autoComplete="off" spellCheck={false} type={field.secret && !revealed[field.key] ? 'password' : 'text'} value={values[field.key] || ''} disabled={saving || overridden} placeholder={configured && field.secret ? '已配置，留空保持原值' : field.key === 'dashscope_base_url' ? 'https://…/compatible-mode/v1' : field.key === 'unpaywall_email' ? 'researcher@example.com' : '输入凭据'} onChange={event => setValues(prev => ({ ...prev, [field.key]: event.target.value }))} />{field.secret && values[field.key] && <Button variant="ghost" size="sm" onClick={() => setRevealed(prev => ({ ...prev, [field.key]: !prev[field.key] }))}>{revealed[field.key] ? '隐藏' : '查看'}</Button>}</div>
                {overridden && <p>此项由启动环境提供，请在启动配置中修改。</p>}
              </div>
            })}</section>)}

          </>}</div>
          <div {...panes.paneProps('preferences')}>
            <section className="settings-group"><h3>文献检索</h3>
              <RetrievalPreferences id="settings" value={{papers_per_property:values.literature_papers_per_property ?? '20',ads_sort:values.ads_sort || 'score desc'}} disabled={saving || loading} overridden={cfg?.env_overrides || []} onChange={v=>setValues(previous=>({...previous,literature_papers_per_property:String(v.papers_per_property),ads_sort:v.ads_sort}))}/>
              <p>每项性质分别取得可读正文；同一篇论文可以用于多个性质。</p>
              {cfg?.env_overrides?.some(key=>PREFERENCE_KEYS.includes(key)) && <p>部分偏好由启动配置提供。</p>}
            </section>
            <section className="settings-group"><h3>显示与回放</h3>
              <div className="preference-setting"><span>界面主题</span><div className="theme-choice" aria-label="界面主题">{[['light','浅色'],['dark','深色']].map(([key,label])=><button key={key} type="button" aria-pressed={theme===key} onClick={()=>{if(theme!==key)onToggleTheme()}}>{label}</button>)}</div></div>
              <div className="preference-setting"><label htmlFor="replay-speed">默认回放速度</label><select id="replay-speed" value={String(speed)} onChange={e=>{setSpeed(Number(e.target.value));saveReplaySpeed(Number(e.target.value))}}>{[...new Set([0.25,0.5,1,2,5,10,20,50,100,Number(speed)].filter(n=>Number.isFinite(n)&&n>=0.25&&n<=100))].sort((a,b)=>a-b).map(n=><option key={n} value={n}>{n}×</option>)}</select></div>
              <div className="preference-setting"><label htmlFor="custom-replay-speed">自定义倍率</label><input id="custom-replay-speed" type="number" min="0.25" max="100" step="0.25" value={speed} onChange={e=>{setSpeed(e.target.value);const n=Number(e.target.value);if(n>=0.25&&n<=100)saveReplaySpeed(n)}} onBlur={()=>setSpeed(loadReplaySpeed())}/></div>
            </section>
          </div>
          <div {...panes.paneProps('theme')}>
            <ThemePaletteSettings theme={theme} onToggleTheme={onToggleTheme} onToast={(msg, type) => toast(msg, type)} />
          </div>
          <div {...panes.paneProps('system')}>{cfg && <div className="settings-group"><h3>当前生效模型</h3>{Object.entries(cfg.models || {}).map(([key, value]) => <div key={key} className="preference-row"><span>{MODELS[key] || key}</span><span className="model-value">{value || '未提供'}</span></div>)}<h3>系统信息</h3><div className="preference-row"><span>软件版本</span><span>{cfg.version || '未提供'}</span></div></div>}<LibraryStatus active={open && tab === 'system'}/></div>
          </div>
        </div>
      </div>
      {discardOpen && <div ref={discardRef} className="discard-notice" role="alert"><span>有未保存的设置修改，是否放弃？</span><Button variant="outline" size="sm" onClick={() => setDiscardOpen(false)}>继续编辑</Button><Button variant="destructive" size="sm" onClick={dismissal.close}>放弃修改</Button></div>}
      <footer className="settings-footer"><Button variant="outline" onClick={close} disabled={saving}>{onboarding ? '稍后设置' : '关闭'}</Button>{activeChanges.length > 0 && <Button variant="accent" onClick={()=>save()} disabled={saving || loading || !cfg || (tab==='preferences' && papersValue(values.literature_papers_per_property)===null)}>{saving ? '正在保存…' : tab==='preferences' ? '保存使用偏好' : '保存连接'}</Button>}</footer>
    </section>
  </div>
}
