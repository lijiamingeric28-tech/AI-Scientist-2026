import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import BackToTop from '@/components/ui/BackToTop'
import { Icon } from '@/components/icons'
import { useToast } from '@/components/ui/toast'
import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useDismissTransition } from '@/hooks/useDismissTransition'
import { useSlidingPanes } from '@/hooks/useSlidingPanes'
import RetrievalPreferences from './RetrievalPreferences'
import ThemePaletteSettings from './ThemePaletteSettings'
import LibraryStatus from './LibraryStatus'
import SettingsKnowledgeStudio from './SettingsKnowledgeStudio'
import SettingsRegistry from './SettingsRegistry'
import SettingsRegistryStudio from './SettingsRegistryStudio'
import { papersValue } from '@/lib/retrievalPreferences'
import { loadReplaySpeed, saveReplaySpeed } from '@/lib/playbackPreferences'
import * as api from '@/services/api'

const PREFERENCE_KEYS = ['ads_sort', 'literature_papers_per_property']
const REPLAY_SPEED_PRESETS = [0.5, 1, 2, 5, 10]
const FIELDS = [
  { key: 'ads_sort', label: 'ADS 论文排序', group: '使用偏好' },
  { key: 'literature_papers_per_property', label: '每项性质的论文目标', group: '使用偏好' },
  {
    key: 'dashscope_api_key',
    label: 'DashScope API Key',
    secret: true,
    group: '模型连接',
    note: '用于任务理解、文献提取及质量处理；留空保持原密钥',
  },
  {
    key: 'dashscope_base_url',
    label: 'DashScope Base URL',
    mono: true,
    group: '模型连接',
    note: 'OpenAI 兼容网关地址，确保与 API Key 的服务地域一致',
  },
  {
    key: 'ads_api_token',
    label: 'ADS API Token',
    secret: true,
    group: '论文检索',
    note: 'NASA ADS 天文文献检索凭据；留空保持原 Token',
  },
  {
    key: 'unpaywall_email',
    label: 'Unpaywall Email',
    mono: true,
    group: '论文检索',
    note: '开放获取 PDF 查询使用的科研联系邮箱',
  },
]

const MODELS = {
  text: '文字检索与性质选择',
  vision: '正文读取与原文质检',
  normalization: '清洗与标准化',
  property: '天体名称识别',
  insight: '历史洞察',
  material_summary: '资料总结',
  copilot: '科研助手 (Copilot)',
  dashscope_model: '任务理解',
  p1_model: '性质标准化',
  dashscope_vlm_model: 'VLM 提取',
  dashscope_bbox_model: '原文定位',
  dashscope_quality_model: '质量处理',
  default_research_domain: '研究领域',
}

const NAV_GROUPS = [
  {
    title: '科研与体验',
    items: [
      ['preferences', '检索与回放', Icon.Sliders],
      ['theme', '外观与配色', Icon.Sun],
    ],
  },
  {
    title: '服务与知识',
    items: [
      ['connections', '服务连接', Icon.Link],
      ['knowledge', '知识库与图谱', Icon.Atom],
      ['registry', '天体与性质规范', Icon.Sliders],
    ],
  },
  {
    title: '运行信息',
    items: [['system', '模型与系统', Icon.Cpu]],
  },
]

const TAB_ORDER = ['preferences', 'theme', 'connections', 'knowledge', 'registry', 'system']

export default function SettingsDialog({
  open,
  onClose,
  onboarding = false,
  initialTab = null,
  initialStudioMode = null,
  knowledgeContext = null,
  onConfigChange,
  theme,
  onToggleTheme,
}) {
  const [cfg, setCfg] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [values, setValues] = useState({})
  const [baseline, setBaseline] = useState({})
  const [revealed, setRevealed] = useState({})
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const [discardOpen, setDiscardOpen] = useState(false)
  const [tab, setTab] = useState(initialTab || 'preferences')
  const [studioMode, setStudioMode] = useState(initialStudioMode || null)
  const [knowledgeEntry, setKnowledgeEntry] = useState(null)
  const [speed, setSpeed] = useState(loadReplaySpeed)
  const { toast } = useToast()

  const changed = FIELDS.filter(field => (values[field.key] || '').trim() !== (baseline[field.key] || ''))
  const dismissal = useDismissTransition(
    () => {
      setValues({})
      setRevealed({})
      setDiscardOpen(false)
      setStudioMode(null)
      onClose()
    },
    { active: open },
  )

  const contentRef = useRef(null)
  const navRef = useRef(null)
  const panes = useSlidingPanes(contentRef, tab, TAB_ORDER, { active: open && !studioMode })

  const close = () => {
    if (savingRef.current) return
    if (changed.length) {
      if (studioMode) setStudioMode(null)
      setDiscardOpen(true)
      return
    }
    dismissal.close()
  }

  const discardRef = useRef(null)
  const discardOrigin = useRef(null)
  const dialogRef = useDialogFocus(open && !studioMode, () => {
    if (discardOpen) setDiscardOpen(false)
    else close()
  })

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
    const initial = {
      dashscope_api_key: '',
      ads_api_token: '',
      ...next.editable_values,
      ads_sort: next.editable_values?.ads_sort || next.effective_values?.ads_sort || 'score desc',
      literature_papers_per_property:
        next.editable_values?.literature_papers_per_property ||
        next.effective_values?.literature_papers_per_property ||
        '20',
    }
    setCfg(next)
    setBaseline(initial)
    setValues(previous => ({ ...initial, ...Object.fromEntries(preserve.map(key => [key, previous[key]])) }))
    onConfigChange?.(next)
  }

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      accept(await api.getConfig())
    } catch (err) {
      setError(`服务连接失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    setTab(initialTab || (onboarding ? 'connections' : 'preferences'))
    setStudioMode(initialStudioMode || null)
    setValues({})
    setBaseline({})
    setCfg(null)
    setRevealed({})
    setDiscardOpen(false)
    let alive = true
    setLoading(true)
    setError('')
    api
      .getConfig()
      .then(next => {
        if (alive) {
          accept(next)
          if (!initialTab && !initialStudioMode) {
            setTab(next.setup_complete ? 'preferences' : 'connections')
          }
        }
      })
      .catch(err => alive && setError(`服务连接失败：${err.message}`))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [open, onboarding, initialTab, initialStudioMode])

  const importCsv = async event => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const { parseConnectionCsv } = await import('@/lib/connectionCsv')
      const imported = parseConnectionCsv(await file.text())
      setValues(previous => ({ ...previous, ...imported }))
      setError('')
    } catch (err) {
      setError(err.message)
    }
    event.target.value = ''
  }

  const save = async (checkCurrent = false) => {
    if (savingRef.current || (!changed.length && !checkCurrent)) return
    const allowed =
      checkCurrent || tab === 'connections'
        ? changed.filter(field => !PREFERENCE_KEYS.includes(field.key))
        : changed.filter(field => PREFERENCE_KEYS.includes(field.key))
    if (
      allowed.some(field => field.key === 'literature_papers_per_property') &&
      papersValue(values.literature_papers_per_property) === null
    ) {
      setError('每项性质的论文目标须为 1–40 的整数。')
      return
    }
    const preserve = changed.filter(field => !allowed.includes(field)).map(field => field.key)
    const body = Object.fromEntries(
      allowed.map(field => [field.key, (values[field.key] || '').trim()]).filter(([, value]) => value),
    )
    if (!checkCurrent && !Object.keys(body).length) {
      setError('空值表示保持原配置，当前没有可保存的修改。')
      return
    }
    if (body.dashscope_base_url) {
      try {
        const url = new URL(body.dashscope_base_url)
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
          throw new Error()
        }
      } catch {
        setError('Base URL 需要有效的 http(s) 地址，不能包含账号、密钥、查询参数或片段。')
        return
      }
    }
    if (body.unpaywall_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.unpaywall_email)) {
      setError('请填写有效邮箱。')
      return
    }
    if (Object.values(body).some(value => /[\r\n]/.test(value) || value.length > 512)) {
      setError('配置必须为单行，且不超过 512 个字符。')
      return
    }
    savingRef.current = true
    setSaving(true)
    setError('')
    let written = false
    try {
      if (checkCurrent || body.dashscope_api_key || body.dashscope_base_url) await api.testAndApplyConfig(body)
      else await api.putConfig(body)
      written = true
      setValues(prev => ({ ...prev, ...Object.fromEntries(allowed.filter(field => field.secret).map(field => [field.key, ''])) }))
      setRevealed({})
      const next = await api.getConfig()
      accept(next, preserve)
      toast(checkCurrent || body.dashscope_api_key || body.dashscope_base_url ? '连接已通过检查并生效' : '设置已保存', 'success')
    } catch (err) {
      setError(
        `${written ? '写入成功，但读取确认失败' : '保存失败'}：${err.message}。${
          written ? '请重新读取确认保存状态。' : '草稿已保留。'
        }`,
      )
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  if (!open) return null

  if (studioMode === 'registry') {
    return <SettingsRegistryStudio open={open} dismissal={dismissal} onBackToSettings={() => { setStudioMode(null); setTab('registry') }} onClose={close} onKnowledge={entryId => { setKnowledgeEntry(entryId); setTab('knowledge'); setStudioMode('graph') }} />
  }

  if (studioMode) {
    return (
      <SettingsKnowledgeStudio
        open={open}
        dismissal={dismissal}
        initialMode={studioMode}
        knowledgeContext={knowledgeContext}
        initialEntryId={knowledgeEntry}
        onBackToSettings={() => {
          setStudioMode(null)
          setTab('knowledge')
        }}
        onClose={close}
      />
    )
  }

  const activeChanges = changed.filter(field =>
    tab === 'preferences'
      ? PREFERENCE_KEYS.includes(field.key)
      : tab === 'connections'
        ? !PREFERENCE_KEYS.includes(field.key)
        : false,
  )

  const connectionStateLabel =
    cfg?.connection?.state === 'connected'
      ? '百炼连接已通过检查'
      : cfg?.setup_complete
        ? '已配置科研连接'
        : '请填写科研服务连接'
  const connectionIsReady = cfg?.connection?.state === 'connected' || Boolean(cfg?.setup_complete)
  const numericSpeed = Number(speed)

  const footerHint =
    tab === 'theme'
      ? '配色改动可实时预览，点击“保存配色配置”持久化生效'
      : tab === 'knowledge'
        ? '点击“打开配置工作台 →”可展开大尺寸图谱与理论库配置视图'
        : tab === 'system'
          ? '模型分配与运行版本为只读状态总览'
          : ''

  return (
    <div className="settings-overlay" data-closing={dismissal.closing || undefined} onClick={close}>
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
        <header className="settings-header">
          <div>
            <h2 id="settings-title">{onboarding ? '连接科研服务，开始你的查询' : '设置'}</h2>
            {onboarding && <p>可先浏览演示样例，稍后再完成连接。</p>}
          </div>
          <Button variant="ghost" size="icon" aria-label="关闭设置" onClick={close} disabled={saving}>
            <Icon.Close />
          </Button>
        </header>

        <div className="settings-body">
          <nav ref={navRef} className="settings-nav" aria-label="设置分类">
            {NAV_GROUPS.map(group => (
              <div key={group.title} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <div className="settings-nav-group-label">{group.title}</div>
                {group.items.map(([key, label, Glyph]) => (
                  <button
                    key={key}
                    type="button"
                    className={tab === key ? 'selected' : undefined}
                    aria-current={tab === key ? 'page' : undefined}
                    onClick={() => setTab(key)}
                  >
                    {Glyph && <Glyph />}
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            ))}
          </nav>

          <div className="settings-content">
            {loading && <p role="status">正在读取服务配置…</p>}
            {error && (
              <div className="resource-error" role="alert">
                {error}
                <Button variant="outline" size="sm" onClick={load} disabled={saving || loading}>
                  重新读取
                </Button>
              </div>
            )}

            <div ref={contentRef} className="settings-panes slide-panes" data-sliding={panes.moving || undefined}>
              {/* 1. 检索与回放 */}
              <div {...panes.paneProps('preferences')}>
                <div className="settings-panel-container">
                  <div className="settings-panel-intro">
                    <h3 className="settings-panel-title">检索与回放 (Preferences &amp; Playback)</h3>
                    <p className="settings-panel-desc">
                      配置新发起科研任务的默认文献检索规模、ADS 排序规则以及历史任务回放倍速。（色彩主题切换统一归入“外观与配色”）
                    </p>
                  </div>

                  <section className="settings-config-section">
                    <div className="settings-config-section-header">
                      <span className="settings-config-section-title">文献检索策略 (LITERATURE RETRIEVAL)</span>
                      <span className="settings-config-section-badge">作用于新建查询</span>
                    </div>
                    <RetrievalPreferences
                      id="settings"
                      layout="settings"
                      value={{
                        papers_per_property: values.literature_papers_per_property ?? '20',
                        ads_sort: values.ads_sort || 'score desc',
                      }}
                      disabled={saving || loading}
                      overridden={cfg?.env_overrides || []}
                      onChange={v =>
                        setValues(previous => ({
                          ...previous,
                          literature_papers_per_property: String(v.papers_per_property),
                          ads_sort: v.ads_sort,
                        }))
                      }
                    />
                  </section>

                  <section className="settings-config-section">
                    <div className="settings-config-section-header">
                      <span className="settings-config-section-title">任务回放体验 (TASK PLAYBACK)</span>
                    </div>
                    <div className="settings-config-rows-group">
                      <div className="settings-config-row">
                        <div className="settings-config-row-label">
                          <strong>默认回放倍速 (Replay Speed)</strong>
                          <span>选择演示样例与历史查询回放时的默认时间压缩倍率（0.25–100×）</span>
                        </div>
                        <div className="settings-config-row-control">
                          <div className="settings-segmented-group" role="group" aria-label="默认回放倍速预设">
                            {REPLAY_SPEED_PRESETS.map(preset => (
                              <button
                                key={preset}
                                type="button"
                                className={`settings-segmented-btn ${numericSpeed === preset ? 'is-active' : ''}`}
                                aria-pressed={numericSpeed === preset}
                                onClick={() => {
                                  setSpeed(preset)
                                  saveReplaySpeed(preset)
                                }}
                              >
                                <span>{preset}×</span>
                              </button>
                            ))}
                          </div>
                          <div className="settings-pill-input-group is-numeric">
                            <input
                              id="custom-replay-speed"
                              type="number"
                              min="0.25"
                              max="100"
                              step="0.25"
                              className="settings-pill-input"
                              aria-label="自定义回放倍速"
                              value={speed}
                              onChange={e => {
                                setSpeed(e.target.value)
                                const n = Number(e.target.value)
                                if (n >= 0.25 && n <= 100) saveReplaySpeed(n)
                              }}
                              onBlur={() => setSpeed(loadReplaySpeed())}
                            />
                          </div>
                          <span className="settings-unit-suffix">×</span>
                        </div>
                      </div>
                    </div>
                  </section>
                </div>
              </div>

              {/* 2. 外观与配色 */}
              <div {...panes.paneProps('theme')}>
                <ThemePaletteSettings theme={theme} onToggleTheme={onToggleTheme} onToast={(msg, type) => toast(msg, type)} />
              </div>

              {/* 3. 服务连接 */}
              <div {...panes.paneProps('connections')}>
                {cfg && (
                  <div className="settings-panel-container">
                    <div className="settings-panel-intro">
                      <h3 className="settings-panel-title">服务连接 (Connections &amp; Auth)</h3>
                      <p className="settings-panel-desc">
                        配置大语言模型兼容网关及天文文献、开放获取数据源凭据；所有凭据仅保存在本机数据目录。
                      </p>
                    </div>

                    <section className="settings-config-section">
                      <div className="settings-config-section-header">
                        <span className="settings-config-section-title">连接状态与快捷工具 (STATUS &amp; TOOLS)</span>
                        <span className={`settings-config-section-badge${connectionIsReady ? '' : ' is-warn'}`}>
                          {connectionStateLabel}
                        </span>
                      </div>
                      <div className="settings-config-rows-group">
                        <div className="settings-config-row">
                          <div className="settings-config-row-label">
                            <strong>快捷凭据导入与连通性测试</strong>
                            <span>支持从百炼控制台导出的 CSV 凭据自动填充，并即时校验连接可用性</span>
                          </div>
                          <div className="settings-config-row-control">
                            <label className="settings-action-inline">
                              <Icon.Download style={{ width: 13, height: 13 }} />
                              <span>导入百炼 CSV</span>
                              <input
                                type="file"
                                accept=".csv,text/csv"
                                onChange={importCsv}
                                disabled={saving}
                                className="sr-only"
                              />
                            </label>
                            <button
                              type="button"
                              className="settings-action-inline"
                              onClick={() => save(true)}
                              disabled={saving}
                            >
                              <span>测试当前连接</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    </section>

                    {[
                      ['模型连接', '大语言模型网关 (MODEL GATEWAY)'],
                      ['论文检索', '文献与开放获取源 (LITERATURE & OA)'],
                    ].map(([group, sectionTitle]) => (
                      <section key={group} className="settings-config-section">
                        <div className="settings-config-section-header">
                          <span className="settings-config-section-title">{sectionTitle}</span>
                        </div>
                        <div className="settings-config-rows-group">
                          {FIELDS.filter(field => field.group === group).map(field => {
                            const configured = cfg.configured?.[field.key.toUpperCase()]
                            const overridden = cfg.env_overrides?.includes(field.key)
                            const placeholder =
                              configured && field.secret
                                ? '已配置，留空保持原值'
                                : field.key === 'dashscope_base_url'
                                  ? 'https://…/compatible-mode/v1'
                                  : field.key === 'unpaywall_email'
                                    ? 'researcher@example.com'
                                    : '输入凭据'
                            return (
                              <div key={field.key} className="settings-config-row">
                                <div className="settings-config-row-label">
                                  <strong>{field.label}</strong>
                                  <span>{field.note}</span>
                                  {overridden && (
                                    <span style={{ color: 'var(--seed-accent)' }}>
                                      此项由启动环境提供，请在启动配置中修改。
                                    </span>
                                  )}
                                </div>
                                <div className="settings-config-row-control">
                                  <div className={`settings-pill-input-group${saving || overridden ? ' is-disabled' : ''}`}>
                                    <input
                                      id={`config-${field.key}`}
                                      autoComplete="off"
                                      spellCheck={false}
                                      type={field.secret && !revealed[field.key] ? 'password' : 'text'}
                                      className={`settings-pill-input${field.mono ? ' is-mono' : ''}`}
                                      value={values[field.key] || ''}
                                      disabled={saving || overridden}
                                      placeholder={placeholder}
                                      aria-label={field.label}
                                      onChange={event =>
                                        setValues(prev => ({ ...prev, [field.key]: event.target.value }))
                                      }
                                    />
                                    {field.secret && configured && !values[field.key] && (
                                      <span className="settings-inline-tag">已配置</span>
                                    )}
                                    {field.secret && values[field.key] && (
                                      <button
                                        type="button"
                                        className="settings-icon-toggle"
                                        aria-label={revealed[field.key] ? `隐藏 ${field.label}` : `查看 ${field.label}`}
                                        onClick={() =>
                                          setRevealed(prev => ({ ...prev, [field.key]: !prev[field.key] }))
                                        }
                                      >
                                        {revealed[field.key] ? (
                                          <Icon.EyeOff style={{ width: 14, height: 14 }} />
                                        ) : (
                                          <Icon.Eye style={{ width: 14, height: 14 }} />
                                        )}
                                      </button>
                                    )}
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </section>
                    ))}
                  </div>
                )}
              </div>

              {/* 4. 知识库与图谱 */}
              <div {...panes.paneProps('knowledge')}>
                <LibraryStatus
                  active={open && tab === 'knowledge' && !studioMode}
                  onLaunchStudio={mode => setStudioMode(mode || 'graph')}
                />
              </div>

              <div {...panes.paneProps('registry')}>
                <SettingsRegistry active={open && tab === 'registry' && !studioMode} onLaunchStudio={() => setStudioMode('registry')} />
              </div>

              {/* 5. 模型与系统 */}
              <div {...panes.paneProps('system')}>
                {cfg && (
                  <div className="settings-panel-container">
                    <div className="settings-panel-intro">
                      <h3 className="settings-panel-title">模型与系统 (Models &amp; System)</h3>
                      <p className="settings-panel-desc">
                        查看智能体各核心检索、抽取、标准化与质检阶段当前实际生效的模型分配及本机服务版本信息。
                      </p>
                    </div>

                    <section className="settings-config-section">
                      <div className="settings-config-section-header">
                        <span className="settings-config-section-title">当前生效模型矩阵 (ACTIVE MODELS)</span>
                        <span className="settings-config-section-badge">只读运行态</span>
                      </div>
                      <div className="settings-config-rows-group">
                        {Object.entries(cfg.models || {}).map(([key, value]) => (
                          <div key={key} className="settings-config-row">
                            <div className="settings-config-row-label">
                              <strong>{MODELS[key] || key}</strong>
                              <span>阶段标识符：{key}</span>
                            </div>
                            <div className="settings-config-row-control">
                              <span className="settings-model-chip" title={value || '未提供'}>
                                {value || '未提供'}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>

                    <section className="settings-config-section">
                      <div className="settings-config-section-header">
                        <span className="settings-config-section-title">系统与运行信息 (SYSTEM INFO)</span>
                      </div>
                      <div className="settings-config-rows-group">
                        <div className="settings-config-row">
                          <div className="settings-config-row-label">
                            <strong>软件版本 (Version)</strong>
                            <span>AstroQuery 后端与科学编译器发布版本号</span>
                          </div>
                          <div className="settings-config-row-control">
                            <span className="settings-model-chip">{cfg.version || '未提供'}</span>
                          </div>
                        </div>
                        <div className="settings-config-row">
                          <div className="settings-config-row-label">
                            <strong>服务配置状态 (Configuration State)</strong>
                            <span>科研任务执行所需的模型与文献接口初始化状态</span>
                          </div>
                          <div className="settings-config-row-control">
                            <span className={`settings-status-pill ${cfg.setup_complete ? 'is-ok' : 'is-warn'}`}>
                              {cfg.setup_complete ? '已完成基础连接' : '待完善连接配置'}
                            </span>
                          </div>
                        </div>
                      </div>
                    </section>
                  </div>
                )}
              </div>
            </div>
          </div>
          <BackToTop />
        </div>

        {discardOpen && (
          <div ref={discardRef} className="discard-notice" role="alert">
            <span>有未保存的设置修改，是否放弃？</span>
            <Button variant="outline" size="sm" onClick={() => setDiscardOpen(false)}>
              继续编辑
            </Button>
            <Button variant="destructive" size="sm" onClick={dismissal.close}>
              放弃修改
            </Button>
          </div>
        )}

        <footer className="settings-footer">
          {footerHint && <span className="settings-footer-hint">{footerHint}</span>}
          <div className="settings-footer-actions">
            <Button variant="outline" onClick={close} disabled={saving}>
              {onboarding ? '稍后设置' : '关闭'}
            </Button>
            {activeChanges.length > 0 && (
              <Button
                variant="accent"
                onClick={() => save()}
                disabled={
                  saving ||
                  loading ||
                  !cfg ||
                  (tab === 'preferences' && papersValue(values.literature_papers_per_property) === null)
                }
              >
                {saving ? '正在保存…' : tab === 'preferences' ? '保存使用偏好' : '保存连接'}
              </Button>
            )}
          </div>
        </footer>
      </section>
    </div>
  )
}
